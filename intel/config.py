"""Configuración por variables de entorno. Ningún secreto vive en el repositorio."""
import os
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent


def _env(nombre: str, defecto: str = "") -> str:
    valor = (os.environ.get(nombre) or "").strip()
    if not valor or valor.startswith("${{"):  # referencia de Railway sin resolver
        return defecto
    return valor


def _int(nombre: str, defecto: int) -> int:
    try:
        return int(_env(nombre, str(defecto)))
    except ValueError:
        return defecto


DIR_CONFIG = Path(_env("INTEL_CONFIG_DIR", str(RAIZ / "config")))

DATABASE_URL = _env("DATABASE_URL")

# Claves externas. Sin ANTHROPIC_API_KEY el radar recoge y archiva, pero no puntúa ni redacta.
ANTHROPIC_API_KEY = _env("ANTHROPIC_API_KEY")
EXA_API_KEY = _env("EXA_API_KEY")

MODELO_PUNTUACION = _env("MODELO_PUNTUACION", "claude-haiku-4-5-20251001")
MODELO_ANALISIS = _env("MODELO_ANALISIS", "claude-sonnet-5-5")
MODELO_REDACCION = _env("MODELO_REDACCION", "claude-sonnet-5-5")

# Programación del motor
RADAR_CADA_HORAS = _int("RADAR_CADA_HORAS", 6)
CANDIDATOS_DIA = _int("CANDIDATOS_DIA", 3)  # lunes=0 ... jueves=3
CANDIDATOS_HORA_UTC = _int("CANDIDATOS_HORA_UTC", 12)  # 12:00 UTC = 06:00 en Tegucigalpa

# Recolección
DIAS_VENTANA = _int("DIAS_VENTANA", 10)  # se ignoran entradas más antiguas
MAX_ITEMS_POR_FUENTE = _int("MAX_ITEMS_POR_FUENTE", 30)
MAX_TEXTOS_POR_PASADA = _int("MAX_TEXTOS_POR_PASADA", 500)
MAX_PUNTUAR_POR_PASADA = _int("MAX_PUNTUAR_POR_PASADA", 600)
HILOS = _int("HILOS", 8)

# Niveles de navegador de Scrapling. El nivel sigiloso solo se usa en fuentes marcadas sigilo: true.
NAVEGADOR = _env("NAVEGADOR", "1") == "1"
MAX_NAVEGADOR_POR_PASADA = _int("MAX_NAVEGADOR_POR_PASADA", 30)

# Dossier
DOSSIER_MAX_FUENTES = _int("DOSSIER_MAX_FUENTES", 20)
DOSSIER_CARACTERES_POR_FUENTE = _int("DOSSIER_CARACTERES_POR_FUENTE", 7000)

# Panel
PANEL_PASSWORD = _env("PANEL_PASSWORD")
PORT = _int("PORT", 8000)

AGENTE_FEEDS = "Mozilla/5.0 (compatible; InteligenciaAutomatizada/1.0; lector de feeds)"
