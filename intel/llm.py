"""Llamadas a Claude con salida estructurada (herramienta forzada) y registro de consumo."""
import logging

from . import config, db

log = logging.getLogger("intel.llm")

_cliente = None


class SinClave(RuntimeError):
    pass


def disponible() -> bool:
    return bool(config.ANTHROPIC_API_KEY)


def _c():
    global _cliente
    if _cliente is None:
        if not disponible():
            raise SinClave("Falta ANTHROPIC_API_KEY: el sistema no puede puntuar, analizar ni redactar.")
        import anthropic

        _cliente = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY, max_retries=4, timeout=300)
    return _cliente


def estructurado(
    etapa: str, modelo: str, sistema: str, usuario: str, esquema: dict, max_tokens: int = 4096
) -> dict:
    """Pide al modelo una respuesta que cumpla `esquema` y la devuelve como diccionario."""
    respuesta = _c().messages.create(
        model=modelo,
        max_tokens=max_tokens,
        system=sistema,
        messages=[{"role": "user", "content": usuario}],
        tools=[{"name": "entregar", "description": "Entrega el resultado estructurado.", "input_schema": esquema}],
        tool_choice={"type": "tool", "name": "entregar"},
    )
    try:
        db.ex(
            "INSERT INTO uso_llm (etapa, modelo, entrada, salida) VALUES (%s, %s, %s, %s)",
            (etapa, modelo, respuesta.usage.input_tokens, respuesta.usage.output_tokens),
        )
    except Exception:  # noqa: BLE001  el registro de consumo nunca debe tumbar una llamada
        log.warning("No se pudo registrar el consumo", exc_info=True)

    if respuesta.stop_reason == "max_tokens":
        raise RuntimeError(f"Respuesta truncada en la etapa «{etapa}» (max_tokens={max_tokens})")
    for bloque in respuesta.content:
        if bloque.type == "tool_use":
            return dict(bloque.input)
    raise RuntimeError(f"El modelo no devolvió resultado estructurado en la etapa «{etapa}»")
