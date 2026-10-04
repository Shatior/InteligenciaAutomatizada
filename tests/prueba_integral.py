"""Prueba integral sin red ni claves: servidor local de fuentes falsas + Postgres + Claude simulado.

Uso:  DATABASE_URL=postgresql://... python tests/prueba_integral.py

Recorre el camino completo (radar → puntuación → candidatos → dossier → pieza → panel)
y falla con un AssertionError si algo no cuadra. Borra y recrea las tablas: no usar
contra la base de producción.
"""
import base64
import os
import shutil
import sys
import tempfile
import threading
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

PUERTO = 8765
BASE = f"http://127.0.0.1:{PUERTO}"
AHORA = datetime.now(timezone.utc)

PARRAFO = (
    "El gobierno anunció un arancel del 25 % sobre las importaciones de acero a partir del 1 de noviembre, "
    "una medida que afecta a 12.400 millones de dólares de comercio bilateral según el ministerio. "
)
ARTICULOS = {
    "1": ("Arancel del 25 % al acero sacude el comercio bilateral", PARRAFO * 6),
    "2": ("El banco central sube la tasa de referencia a 6,5 %", "El banco central elevó la tasa de política monetaria a 6,5 % tras tres meses de inflación al alza. " * 8),
    "3": ("Ataque de ransomware paraliza a tres bancos regionales", "Un grupo de ransomware cifró los sistemas de tres bancos regionales y exige 4 millones de dólares. " * 8),
    "4": ("Un neobanco alcanza los 2 millones de clientes en Centroamérica", "El neobanco superó los 2 millones de clientes en la región tras lanzar pagos instantáneos. " * 8),
    "9": ("Noticia vieja que no debe entrar", "Texto antiguo. " * 80),
}


def _feed(entradas: list[tuple[str, str, datetime, str]]) -> bytes:
    items = "".join(
        f"<item><title>{t}</title><link>{BASE}/art/{i}?utm_source=rss</link>"
        f"<pubDate>{format_datetime(f)}</pubDate><description>{d}</description></item>"
        for i, t, f, d in entradas
    )
    return f'<?xml version="1.0"?><rss version="2.0"><channel><title>Prueba</title>{items}</channel></rss>'.encode()


class Servidor(BaseHTTPRequestHandler):
    def log_message(self, *a):  # silencio
        pass

    def _responder(self, cuerpo: bytes, tipo="text/html; charset=utf-8", estado=200):
        self.send_response(estado)
        self.send_header("Content-Type", tipo)
        self.send_header("Content-Length", str(len(cuerpo)))
        self.end_headers()
        self.wfile.write(cuerpo)

    def do_GET(self):
        ruta = self.path.split("?")[0]
        if ruta == "/feed1.xml":
            return self._responder(_feed([
                ("1", ARTICULOS["1"][0], AHORA - timedelta(hours=3), "Resumen del arancel."),
                ("2", ARTICULOS["2"][0], AHORA - timedelta(hours=5), "Resumen de la tasa."),
                ("9", ARTICULOS["9"][0], AHORA - timedelta(days=40), "Viejo."),
            ]), "application/rss+xml")
        if ruta == "/feed2.xml":
            # Mismo titular que el artículo 1 en otra URL: debe marcarse duplicado.
            return self._responder(_feed([
                ("1b", ARTICULOS["1"][0], AHORA - timedelta(hours=2), "Copia."),
                ("3", ARTICULOS["3"][0], AHORA - timedelta(hours=1), "Resumen del ataque."),
            ]), "application/rss+xml")
        if ruta == "/feed-roto.xml":
            return self._responder(b"no encontrado", estado=404)
        if ruta == "/portada":
            return self._responder(
                '<html><body><a href="/contacto">Contacto</a>'
                '<a href="/economia/neobanco-AB123"><img src="x.png"></a>'
                f'<a href="/economia/neobanco-AB123">{ARTICULOS["4"][0]}</a></body></html>'.encode()
            )
        if ruta.startswith("/art/") or ruta.startswith("/economia/"):
            clave = "4" if ruta.startswith("/economia/") else ruta.split("/")[-1].rstrip("b")
            titulo, texto = ARTICULOS.get(clave, ("Sin título", "x"))
            parrafos = "".join(f"<p>{texto}</p>" for _ in range(2))
            return self._responder(
                f"<html><head><title>{titulo}</title></head><body><article><h1>{titulo}</h1>{parrafos}</article></body></html>".encode()
            )
        self._responder(b"no", estado=404)


def _simular_claude():
    """Sustituye la llamada a Claude por respuestas deterministas según la etapa."""
    from intel import db, llm

    def falso(etapa, modelo, sistema, usuario, esquema, max_tokens=4096):
        import re

        if etapa == "puntuacion":
            ids = [int(x) for x in re.findall(r'<item id="(\d+)"', usuario)]
            return {"items": [
                {"id": i, "dominio": "geopolitica", "linea": "eeuu_region", "regiones": ["centroamerica"],
                 "paises": ["Honduras"], "entidades": ["Ministerio"], "magnitud": 4, "novedad": 4, "datos": 4,
                 "relevancia_ca": 5, "cruce": False, "tecnico": False, "resumen": "Resumen de prueba con 25 %."}
                for i in ids
            ]}
        if etapa == "candidatos":
            ids = [int(x) for x in re.findall(r'<item id="(\d+)"', usuario)]
            return {"candidatos": [
                {"titulo": "El arancel al acero y sus límites", "etiqueta": "Norteamérica",
                 "hecho": "Arancel del 25 % desde el 1 de noviembre.", "por_que": "Afecta al comercio regional.",
                 "tesis": ["La interdependencia limita la coerción.", "El arancel es una señal, no una política."],
                 "item_ids": ids[:3], "puntuacion": 8.5},
                {"titulo": "Candidato inventado", "etiqueta": "x", "hecho": "x", "por_que": "x",
                 "tesis": ["a", "b"], "item_ids": [999999], "puntuacion": 9},
            ]}
        if etapa == "dossier_plan":
            return {"consultas": [{"texto": "arancel acero", "reciente": True}] * 4,
                    "palabras_archivo": ["arancel", "acero", "banco"]}
        if etapa == "dossier_extraccion":
            bloques = re.findall(r'<fuente n="(\d+)"[^>]*>\n(.*?)\n</fuente>', usuario, flags=re.S)
            n = next(int(num) for num, texto in bloques if "arancel del 25" in texto)
            salida = {
                "hechos": [
                    {"tipo": "hecho", "dato": "El gobierno anunció un arancel del 25 % al acero.", "cifra": "25 %",
                     "fecha": "1 de noviembre", "fuente": 1,
                     "cita": "anunció un arancel del 25 % sobre las importaciones de acero a partir del 1 de noviembre"},
                    {"tipo": "contexto", "dato": "El comercio afectado suma 12.400 millones de dólares.",
                     "cifra": "12.400 millones", "fecha": "", "fuente": 1,
                     "cita": "afecta a 12.400 millones de dólares de comercio bilateral según el ministerio"},
                    {"tipo": "hecho", "dato": "Dato con cita inventada.", "cifra": "99", "fecha": "", "fuente": 1,
                     "cita": "esta frase no aparece en ninguna fuente del dossier de prueba"},
                ],
                "voces": [{"quien": "Ministerio", "afiliacion": "Gobierno", "postura": "Defiende la medida.",
                           "fuente": 1, "cita": "una medida que afecta a 12.400 millones de dólares"}],
                "contraargumentos": [{"argumento": "La dependencia es mutua.", "fuente": 0}],
                "lagunas": ["No se conoce la respuesta del socio comercial."],
                "tesis": ["La interdependencia limita la coerción.", "Otra tesis."],
            }
            for x in salida["hechos"] + salida["voces"]:
                x["fuente"] = n
            return salida
        if etapa == "redaccion":
            cuerpo = "\n\n".join(
                ["El **Gobierno** anunció un arancel del 25 % al acero que afecta a 12.400 millones de dólares. " * 12] * 4
                + ["Una cifra sin respaldo: 777 millones."]
            )
            return {"etiqueta": "Norteamérica", "titulo": "El arancel que se muerde la cola",
                    "entradilla": "Un arancel del 25 % desde el 1 de noviembre.", "cuerpo": cuerpo, "datos_usados": [1, 2, 3]}
        if etapa == "auditoria":
            return {"problemas": [{"afirmacion": "777 millones", "problema": "No está en el dossier.", "gravedad": "alta"}]}
        raise AssertionError(f"Etapa inesperada: {etapa}")

    llm.estructurado = falso
    llm.disponible = lambda: True
    return db


def main() -> None:
    if not os.environ.get("DATABASE_URL"):
        sys.exit("Falta DATABASE_URL")

    # Registro de prueba en un directorio temporal
    tmp = Path(tempfile.mkdtemp())
    for nombre in ("ediciones.yaml", "guia_pieza.md"):
        shutil.copy(RAIZ / "config" / nombre, tmp / nombre)
    (tmp / "fuentes.yaml").write_text(
        f"""fuentes:
  - {{id: uno, nombre: Feed Uno, url: "{BASE}/feed1.xml", dominio: geopolitica, fiabilidad: B}}
  - {{id: dos, nombre: Feed Dos, url: "{BASE}/feed2.xml", dominio: ciber, fiabilidad: B}}
  - {{id: roto, nombre: Feed Roto, url: "{BASE}/feed-roto.xml", dominio: macro, fiabilidad: C}}
  - {{id: portada, nombre: Portada HTML, url: "{BASE}/portada", metodo: html, patron: "^/economia/.+-[A-Z]{{2}}\\\\d+", dominio: transformacion, region: centroamerica, fiabilidad: C}}
""",
        encoding="utf-8",
    )
    os.environ.update(INTEL_CONFIG_DIR=str(tmp), NAVEGADOR="0", PANEL_PASSWORD="clave-de-prueba")
    os.environ.pop("ANTHROPIC_API_KEY", None)
    os.environ.pop("EXA_API_KEY", None)

    servidor = ThreadingHTTPServer(("127.0.0.1", PUERTO), Servidor)
    threading.Thread(target=servidor.serve_forever, daemon=True).start()

    from intel import candidatos, db, dossier, radar, redaccion, trabajos

    db.pool()
    db.ex("DROP TABLE IF EXISTS uso_llm, trabajos, piezas, dossier_fuentes, dossieres, candidatos, items, fuentes CASCADE")
    db.migrar()
    db.migrar()  # idempotente

    # 1. Radar sin clave: recoge y archiva, no puntúa
    r = radar.pasada()
    print("radar:", r)
    assert r["fuentes"] == 4 and len(r["fuentes_fallidas"]) == 1 and r["fuentes_fallidas"][0]["id"] == "roto", r
    estados = {x["estado"]: x["n"] for x in db.q("SELECT estado, count(*) AS n FROM items GROUP BY estado")}
    print("estados:", estados)
    assert estados == {"con_texto": 4, "duplicado": 1}, estados  # el viejo no entra; el repetido se marca
    assert r["puntuacion"]["motivo"] == "sin_clave"
    portada = db.q1("SELECT titulo, texto_metodo FROM items WHERE fuente_id = 'portada'")
    assert portada["titulo"].startswith("Un neobanco") and portada["texto_metodo"] == "http", portada
    assert db.q1("SELECT fallos_consecutivos AS n FROM fuentes WHERE id = 'roto'")["n"] == 1

    # 2. Segunda pasada: nada nuevo
    r2 = radar.pasada()
    assert r2["nuevos"] == 0, r2

    # 3. Con Claude simulado: puntuación, candidatos, dossier, pieza
    _simular_claude()
    from intel import puntuar

    p = puntuar.puntuar_pendientes()
    assert p["puntuados"] == 4, p
    fila = db.q1("SELECT puntuacion_global, puntuacion_regional FROM items WHERE estado = 'puntuado' LIMIT 1")
    assert fila["puntuacion_global"] == 8.0 and fila["puntuacion_regional"] == 9.0, fila

    c = candidatos.generar()
    print("candidatos:", c)
    assert c["ediciones"]["global"] == 0, c  # menos de cinco items: no se proponen temas
    db.ex("UPDATE items SET estado = 'puntuado', dominio = 'geopolitica', puntuacion_global = 8, puntuacion_regional = 8.6 WHERE estado = 'duplicado'")
    c = candidatos.generar("global")
    assert c["ediciones"] == {"global": 1}, c  # el candidato sin items reales se descarta
    cand = db.q1("SELECT * FROM candidatos LIMIT 1")

    d = db.q1(
        "INSERT INTO dossieres (candidato_id, edicion, tema) VALUES (%s, 'regional', %s) RETURNING id",
        (cand["id"], cand["titulo"]),
    )
    res = dossier.construir(d["id"])
    print("dossier:", res)
    assert res["datos"] == 3 and res["verificados"] == 2, res  # la cita inventada no se verifica
    dd = db.q1("SELECT * FROM dossieres WHERE id = %s", (d["id"],))
    assert dd["estado"] == "listo" and len(dd["tesis"]) == 3, dd["tesis"]

    pz = db.q1(
        "INSERT INTO piezas (dossier_id, edicion, tesis) VALUES (%s, 'regional', 'La interdependencia limita la coerción.') RETURNING id",
        (d["id"],),
    )
    res = redaccion.redactar(pz["id"])
    v = db.q1("SELECT verificacion FROM piezas WHERE id = %s", (pz["id"],))["verificacion"]
    print("verificación:", {k: (len(x) if isinstance(x, list) else x) for k, x in v.items()})
    assert [x["cifra"] for x in v["cifras_sin_respaldo"]] == ["777"], v["cifras_sin_respaldo"]
    assert [x["id"] for x in v["datos_no_verificados"]] == [3], v["datos_no_verificados"]
    assert v["auditoria"][0]["gravedad"] == "alta"

    # 4. Cola de trabajos y programación
    trabajos._programar()
    assert trabajos.hay_activo("radar")
    t = trabajos._reclamar(trabajos.LENTOS)
    assert t["tipo"] == "radar" and trabajos._reclamar(["radar"]) is None
    trabajos._recuperar_interrumpidos()
    assert db.q1("SELECT estado FROM trabajos WHERE id = %s", (t["id"],))["estado"] == "error"

    # 5. Panel
    from fastapi.testclient import TestClient

    from intel.web.app import app

    with TestClient(app) as cliente:
        assert cliente.get("/salud").json() == {"ok": True}
        assert cliente.get("/").status_code == 401
        mal = {"Authorization": "Basic " + base64.b64encode(b"x:otra").decode()}
        assert cliente.get("/", headers=mal).status_code == 401
        h = {"Authorization": "Basic " + base64.b64encode(b"editor:clave-de-prueba").decode()}
        for ruta in ("/", "/radar", "/radar?q=arancel&orden=regional&estado=todos", "/candidatos", "/dossieres",
                     f"/dossier/{d['id']}", "/piezas", f"/pieza/{pz['id']}", "/fuentes", "/trabajos"):
            resp = cliente.get(ruta, headers=h)
            assert resp.status_code == 200, (ruta, resp.status_code, resp.text[:400])
        assert "777" in cliente.get(f"/pieza/{pz['id']}", headers=h).text
        assert cliente.get(f"/pieza/{pz['id']}/descargar", headers=h).text.startswith("**Norteamérica**")
        resp = cliente.post("/dossieres/nuevo", headers=h, data={"tema": "Un tema libre de prueba", "edicion": "ciber"}, follow_redirects=False)
        assert resp.status_code == 303 and resp.headers["location"].startswith("/dossier/")
        resp = cliente.post("/radar/ejecutar", headers={**h, "Origin": "https://malo.example"}, follow_redirects=False)
        assert resp.status_code == 403
        resp = cliente.post(
            f"/pieza/{pz['id']}/guardar", headers=h, follow_redirects=False,
            data={"etiqueta": "E", "titulo": "T <script>", "entradilla": "e", "cuerpo": "**Actor** dijo <b>x</b>", "accion": "aprobar"},
        )
        assert resp.status_code == 303
        pagina = cliente.get(f"/pieza/{pz['id']}", headers=h).text
        assert "<strong>Actor</strong>" in pagina and "<b>x</b>" not in pagina and "T <script>" not in pagina

    servidor.shutdown()
    db.pool().close()
    print("\nTODO CORRECTO")


if __name__ == "__main__":
    main()
