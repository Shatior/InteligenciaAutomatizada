"""Punto de entrada: python -m intel <orden>

  panel       servidor web (por defecto en el contenedor)
  motor       programador + cola de trabajos (servicio de fondo)
  radar       una pasada del radar y salir
  candidatos  generar los candidatos de la semana y salir
  migrar      crear o actualizar el esquema y salir
"""
import json
import logging
import sys


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s", stream=sys.stdout)
    for ruidoso in ("httpx", "httpx2", "httpcore", "trafilatura", "scrapling", "anthropic", "htmldate", "courlan"):
        logging.getLogger(ruidoso).setLevel(logging.WARNING)

    orden = sys.argv[1] if len(sys.argv) > 1 else "panel"
    if orden == "panel":
        import uvicorn

        from . import config

        uvicorn.run("intel.web.app:app", host="0.0.0.0", port=config.PORT, proxy_headers=True, forwarded_allow_ips="*")
    elif orden == "motor":
        from . import trabajos

        trabajos.motor()
    elif orden == "radar":
        from . import db, radar

        db.migrar()
        print(json.dumps(radar.pasada(), ensure_ascii=False, indent=2, default=str))
    elif orden == "candidatos":
        from . import candidatos, db

        db.migrar()
        print(json.dumps(candidatos.generar(), ensure_ascii=False, indent=2, default=str))
    elif orden == "migrar":
        from . import db

        db.migrar()
    else:
        print(__doc__)
        sys.exit(2)


if __name__ == "__main__":
    main()
