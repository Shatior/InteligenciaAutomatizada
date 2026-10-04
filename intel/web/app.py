"""Panel editorial: ver el radar, elegir temas, pedir dossieres y revisar piezas."""
import html
import logging
import secrets
from contextlib import asynccontextmanager
from datetime import date, timedelta
from pathlib import Path
from urllib.parse import urlsplit

import markdown as md
from fastapi import Depends, FastAPI, Form, HTTPException, Request
from fastapi.responses import PlainTextResponse, RedirectResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from markupsafe import Markup

from .. import buscador, candidatos, config, db, fuentes, llm, redaccion, trabajos

log = logging.getLogger("intel.web")
AQUI = Path(__file__).parent
plantillas = Jinja2Templates(directory=str(AQUI / "templates"))
seguridad = HTTPBasic(realm="Inteligencia")


def _md(texto: str | None) -> Markup:
    """Markdown a HTML escapando antes cualquier HTML que venga del texto generado o recolectado."""
    return Markup(md.markdown(html.escape(texto or "", quote=False)))


plantillas.env.filters["md"] = _md
plantillas.env.filters["fecha"] = lambda v: v.strftime("%d/%m/%Y") if v else "s/f"
plantillas.env.filters["hora"] = lambda v: v.strftime("%d/%m %H:%M") if v else "—"


@asynccontextmanager
async def _arranque(app: FastAPI):
    db.migrar()
    fuentes.sincronizar()
    yield


app = FastAPI(title="Inteligencia", docs_url=None, redoc_url=None, openapi_url=None, lifespan=_arranque)
app.mount("/static", StaticFiles(directory=str(AQUI / "static")), name="static")


def acceso(request: Request, cred: HTTPBasicCredentials = Depends(seguridad)) -> str:
    if not config.PANEL_PASSWORD:
        raise HTTPException(503, "Panel cerrado: falta la variable PANEL_PASSWORD.")
    if not secrets.compare_digest(cred.password.encode(), config.PANEL_PASSWORD.encode()):
        raise HTTPException(401, "Contraseña incorrecta", headers={"WWW-Authenticate": 'Basic realm="Inteligencia"'})
    # Los formularios solo se aceptan desde el propio panel.
    if request.method == "POST":
        origen = request.headers.get("origin")
        if origen and urlsplit(origen).netloc != request.headers.get("host"):
            raise HTTPException(403, "Origen no permitido")
    return cred.username or "editor"


def _ver(request: Request, plantilla: str, **datos):
    datos.update(
        ediciones=fuentes.cargar_ediciones(),
        claude=llm.disponible(),
        exa=buscador.disponible(),
    )
    return plantillas.TemplateResponse(request, plantilla, datos)


def _ir(ruta: str) -> RedirectResponse:
    return RedirectResponse(ruta, status_code=303)


@app.get("/salud")
def salud():
    db.q1("SELECT 1 AS ok")
    return {"ok": True}


# ---------------------------------------------------------------- resumen

@app.get("/")
def inicio(request: Request, _: str = Depends(acceso)):
    totales = db.q1(
        """
        SELECT count(*) AS total,
               count(*) FILTER (WHERE recolectado > now() - interval '24 hours') AS dia,
               count(*) FILTER (WHERE recolectado > now() - interval '7 days') AS semana,
               count(*) FILTER (WHERE estado = 'puntuado') AS puntuados,
               count(*) FILTER (WHERE estado IN ('con_texto', 'sin_texto')) AS por_puntuar
        FROM items
        """
    )
    dominios = db.q(
        """
        SELECT dominio, count(*) AS n, round(avg(puntuacion_global)::numeric, 1) AS media
        FROM items WHERE estado = 'puntuado' AND recolectado > now() - interval '7 days'
        GROUP BY dominio ORDER BY n DESC
        """
    )
    salud_fuentes = db.q1(
        """
        SELECT count(*) FILTER (WHERE activa) AS activas,
               count(*) FILTER (WHERE activa AND fallos_consecutivos = 0 AND ultimo_ok IS NOT NULL) AS sanas,
               count(*) FILTER (WHERE activa AND fallos_consecutivos > 0) AS fallando
        FROM fuentes
        """
    )
    ultimos = db.q("SELECT * FROM trabajos ORDER BY id DESC LIMIT 8")
    uso = db.q(
        """
        SELECT modelo, sum(entrada) AS entrada, sum(salida) AS salida, count(*) AS llamadas
        FROM uso_llm WHERE momento > date_trunc('month', now()) GROUP BY modelo ORDER BY modelo
        """
    )
    return _ver(
        request, "inicio.html", totales=totales, dominios=dominios, salud_fuentes=salud_fuentes,
        ultimos=ultimos, uso=uso, radar_activo=trabajos.hay_activo("radar"),
    )


@app.post("/radar/ejecutar")
def radar_ejecutar(_: str = Depends(acceso)):
    if not trabajos.hay_activo("radar"):
        trabajos.encolar("radar")
    return _ir("/")


# ---------------------------------------------------------------- radar

@app.get("/radar")
def radar_lista(
    request: Request, _: str = Depends(acceso), dominio: str = "", orden: str = "global",
    dias: int = 7, q: str = "", estado: str = "puntuado",
):
    condiciones, params = ["i.recolectado > now() - make_interval(days => %s)"], [max(1, min(dias, 90))]
    if estado == "puntuado":
        condiciones.append("i.estado = 'puntuado' AND i.dominio <> 'ninguno'")
    elif estado == "sin_puntuar":
        condiciones.append("i.estado IN ('con_texto', 'sin_texto', 'nuevo')")
    if dominio:
        condiciones.append("i.dominio = %s")
        params.append(dominio)
    if q.strip():
        condiciones.append("i.tsv @@ websearch_to_tsquery('simple', %s)")
        params.append(q.strip())
    columna = {"regional": "i.puntuacion_regional", "reciente": "i.recolectado"}.get(orden, "i.puntuacion_global")
    items = db.q(
        f"""
        SELECT i.*, f.nombre AS fuente, f.fiabilidad
        FROM items i JOIN fuentes f ON f.id = i.fuente_id
        WHERE {' AND '.join(condiciones)}
        ORDER BY {columna} DESC NULLS LAST, i.recolectado DESC
        LIMIT 150
        """,
        params,
    )
    return _ver(request, "radar.html", items=items, dominio=dominio, orden=orden, dias=dias, q=q, estado=estado)


# ---------------------------------------------------------------- candidatos

@app.get("/candidatos")
def candidatos_lista(request: Request, _: str = Depends(acceso), semana: str = ""):
    try:
        lunes = date.fromisoformat(semana) if semana else candidatos.lunes()
    except ValueError:
        lunes = candidatos.lunes()
    filas = db.q(
        """
        SELECT c.*, (SELECT id FROM dossieres d WHERE d.candidato_id = c.id ORDER BY id DESC LIMIT 1) AS dossier_id
        FROM candidatos c WHERE c.semana = %s AND c.estado <> 'descartado'
        ORDER BY c.edicion, c.puntuacion DESC NULLS LAST
        """,
        (lunes,),
    )
    por_edicion: dict[str, list] = {}
    for f in filas:
        por_edicion.setdefault(f["edicion"], []).append(f)
    ids = sorted({i for f in filas for i in f["item_ids"]})
    items = {
        it["id"]: it for it in db.q(
            "SELECT i.id, i.titulo, i.url, f.nombre AS fuente FROM items i JOIN fuentes f ON f.id = i.fuente_id "
            "WHERE i.id = ANY(%s)", (ids,)
        )
    } if ids else {}
    return _ver(
        request, "candidatos.html", por_edicion=por_edicion, items=items, lunes=lunes,
        anterior=lunes - timedelta(days=7), siguiente=lunes + timedelta(days=7),
        generando=trabajos.hay_activo("candidatos"),
    )


@app.post("/candidatos/generar")
def candidatos_generar(_: str = Depends(acceso), edicion: str = Form("")):
    if not trabajos.hay_activo("candidatos"):
        trabajos.encolar("candidatos", {"edicion": edicion or None})
    return _ir("/candidatos")


@app.post("/candidatos/{cid}/descartar")
def candidato_descartar(cid: int, _: str = Depends(acceso)):
    db.ex("UPDATE candidatos SET estado = 'descartado' WHERE id = %s", (cid,))
    return _ir("/candidatos")


@app.post("/candidatos/{cid}/dossier")
def candidato_dossier(cid: int, _: str = Depends(acceso), enfoque: str = Form("")):
    c = db.q1("SELECT * FROM candidatos WHERE id = %s", (cid,))
    if not c:
        raise HTTPException(404)
    d = db.q1(
        "INSERT INTO dossieres (candidato_id, edicion, tema, enfoque) VALUES (%s, %s, %s, %s) RETURNING id",
        (cid, c["edicion"], f"{c['titulo']}. {c['hecho']}", enfoque.strip() or c["por_que"]),
    )
    db.ex("UPDATE candidatos SET estado = 'elegido' WHERE id = %s", (cid,))
    trabajos.encolar("dossier", {"dossier_id": d["id"]})
    return _ir(f"/dossier/{d['id']}")


# ---------------------------------------------------------------- dossieres

@app.get("/dossieres")
def dossieres_lista(request: Request, _: str = Depends(acceso)):
    filas = db.q(
        """
        SELECT d.id, d.edicion, d.tema, d.estado, d.creado, jsonb_array_length(d.hechos) AS hechos,
               (SELECT count(*) FROM dossier_fuentes f WHERE f.dossier_id = d.id) AS fuentes,
               (SELECT count(*) FROM piezas p WHERE p.dossier_id = d.id) AS piezas
        FROM dossieres d ORDER BY d.id DESC LIMIT 100
        """
    )
    return _ver(request, "dossieres.html", filas=filas)


@app.post("/dossieres/nuevo")
def dossier_nuevo(_: str = Depends(acceso), tema: str = Form(...), edicion: str = Form(...), enfoque: str = Form("")):
    if edicion not in fuentes.cargar_ediciones() or len(tema.strip()) < 10:
        raise HTTPException(400, "Tema demasiado corto o edición desconocida")
    d = db.q1(
        "INSERT INTO dossieres (edicion, tema, enfoque) VALUES (%s, %s, %s) RETURNING id",
        (edicion, tema.strip()[:1000], enfoque.strip()[:1000] or None),
    )
    trabajos.encolar("dossier", {"dossier_id": d["id"]})
    return _ir(f"/dossier/{d['id']}")


@app.get("/dossier/{did}")
def dossier_ver(request: Request, did: int, _: str = Depends(acceso)):
    d = db.q1("SELECT * FROM dossieres WHERE id = %s", (did,))
    if not d:
        raise HTTPException(404)
    fs = db.q(
        "SELECT n, url, titulo, medio, publicado, origen, fiabilidad, length(texto) AS caracteres "
        "FROM dossier_fuentes WHERE dossier_id = %s ORDER BY n", (did,)
    )
    piezas = db.q("SELECT id, edicion, titulo, estado, tesis, creado FROM piezas WHERE dossier_id = %s ORDER BY id DESC", (did,))
    todos = d["hechos"] + d["contexto"]
    return _ver(
        request, "dossier.html", d=d, fs=fs, piezas=piezas,
        verificados=sum(1 for h in todos if h.get("verificado")), total=len(todos),
        esperando=d["estado"] in ("pendiente", "en_curso"),
    )


@app.post("/dossier/{did}/reintentar")
def dossier_reintentar(did: int, _: str = Depends(acceso)):
    db.ex("UPDATE dossieres SET estado = 'pendiente', error = NULL WHERE id = %s", (did,))
    trabajos.encolar("dossier", {"dossier_id": did})
    return _ir(f"/dossier/{did}")


@app.post("/dossier/{did}/pieza")
def dossier_pieza(
    did: int, _: str = Depends(acceso), tesis: str = Form(""), tesis_propia: str = Form(""), edicion: str = Form(""),
):
    d = db.q1("SELECT * FROM dossieres WHERE id = %s", (did,))
    if not d or d["estado"] != "listo":
        raise HTTPException(400, "El dossier no está listo")
    elegida = tesis_propia.strip() or tesis.strip()
    if not elegida:
        raise HTTPException(400, "Hay que elegir o escribir una tesis")
    ed = edicion if edicion in fuentes.cargar_ediciones() else d["edicion"]
    p = db.q1(
        "INSERT INTO piezas (dossier_id, edicion, tesis) VALUES (%s, %s, %s) RETURNING id", (did, ed, elegida[:1000])
    )
    trabajos.encolar("pieza", {"pieza_id": p["id"]})
    return _ir(f"/pieza/{p['id']}")


# ---------------------------------------------------------------- piezas

@app.get("/piezas")
def piezas_lista(request: Request, _: str = Depends(acceso)):
    filas = db.q(
        "SELECT id, dossier_id, edicion, etiqueta, titulo, tesis, estado, palabras, creado, actualizado "
        "FROM piezas ORDER BY id DESC LIMIT 100"
    )
    return _ver(request, "piezas.html", filas=filas)


@app.get("/pieza/{pid}")
def pieza_ver(request: Request, pid: int, _: str = Depends(acceso)):
    p = db.q1("SELECT * FROM piezas WHERE id = %s", (pid,))
    if not p:
        raise HTTPException(404)
    return _ver(request, "pieza.html", p=p, v=p["verificacion"] or {}, esperando=p["estado"] == "pendiente")


@app.post("/pieza/{pid}/guardar")
def pieza_guardar(
    pid: int, _: str = Depends(acceso), etiqueta: str = Form(""), titulo: str = Form(""),
    entradilla: str = Form(""), cuerpo: str = Form(""), accion: str = Form("guardar"),
):
    estado = "aprobada" if accion == "aprobar" else "editada"
    db.ex(
        "UPDATE piezas SET etiqueta = %s, titulo = %s, entradilla = %s, cuerpo = %s, estado = %s, actualizado = now() "
        "WHERE id = %s",
        (etiqueta.strip()[:80], titulo.strip()[:300], entradilla.strip(), cuerpo.replace("\r\n", "\n").strip(), estado, pid),
    )
    if accion == "reverificar":
        trabajos.encolar("reverificar", {"pieza_id": pid})
    return _ir(f"/pieza/{pid}")


@app.get("/pieza/{pid}/descargar")
def pieza_md(pid: int, _: str = Depends(acceso)):
    p = db.q1("SELECT * FROM piezas WHERE id = %s", (pid,))
    if not p:
        raise HTTPException(404)
    return PlainTextResponse(
        redaccion.a_markdown(p), media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="pieza-{pid}.md"'},
    )


# ---------------------------------------------------------------- fuentes y trabajos

@app.get("/fuentes")
def fuentes_lista(request: Request, _: str = Depends(acceso)):
    filas = db.q(
        "SELECT * FROM fuentes ORDER BY activa DESC, (fallos_consecutivos > 0) DESC, dominio, region, nombre"
    )
    return _ver(request, "fuentes.html", filas=filas)


@app.get("/trabajos")
def trabajos_lista(request: Request, _: str = Depends(acceso)):
    filas = db.q("SELECT * FROM trabajos ORDER BY id DESC LIMIT 60")
    return _ver(request, "trabajos.html", filas=filas)
