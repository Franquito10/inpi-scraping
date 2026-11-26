"""Genera el dashboard HTML (un solo archivo, sin dependencias externas)."""

import logging
from datetime import datetime, timezone
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from .config import PAQUETE, NOMBRE_RED, tz, ruta_de
from .db import DB, hace
from .analisis import Resumidor, rango_dias

log = logging.getLogger("redes.dashboard")


def datos_dashboard(cfg: dict, db: DB, resumidor: Resumidor | None = None, dias_hist: int = 120) -> dict:
    zona = tz(cfg)
    pubs = db.publicaciones(desde=hace(dias_hist))
    inicio7, _ = rango_dias(7, zona)
    resumidor = resumidor or Resumidor({"analisis": {"ia": {"habilitada": False}}})
    hoy = datetime.now(zona).strftime("%Y-%m-%d")

    personas = []
    for p in db.personas():
        propias = [x for x in pubs if x["persona_id"] == p["id"]]
        semana = [x for x in propias if x["fecha"] >= inicio7.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")]
        clave = f"7d:{hoy}:{len(semana)}"  # se rehace si entran publicaciones nuevas
        guardado = db.resumen(p["id"], clave)
        if guardado:
            resumen, modelo = guardado["texto"], guardado["modelo"]
        else:
            resumen, modelo = resumidor.resumir(p["nombre"], p["cargo"], semana, "últimos 7 días")
            db.guardar_resumen(p["id"], clave, resumen, modelo)
        personas.append({
            "id": p["id"], "nombre": p["nombre"], "cargo": p["cargo"] or "",
            "resumen": resumen, "resumen_ia": modelo != "reglas",
            "cuentas": {red: {"url": c["url"], "usuario": c["usuario"],
                              "ultimo": c["ultimo_scrapeo"], "error": c["ultimo_error"]}
                        for red, c in p["cuentas"].items()},
        })

    corrida = db.ultima_corrida()
    return {
        "generado": datetime.now(zona).strftime("%d/%m/%Y %H:%M"),
        "zona": str(zona),
        "redes": NOMBRE_RED,
        "personas": personas,
        "ultima_corrida": corrida,
        "publicaciones": [{
            "id": x["id"], "persona_id": x["persona_id"], "red": x["plataforma"], "url": x["url"],
            "texto": (x["texto"] or "")[:1500], "fecha": x["fecha"], "tipo": x["tipo"],
            "likes": x["likes"], "comentarios": x["comentarios"], "compartidos": x["compartidos"],
            "vistas": x["vistas"], "hashtags": x["hashtags"], "temas": x["temas"],
            "actividades": x["actividades"], "lugares": x["lugares"],
        } for x in pubs],
    }


def generar_dashboard(cfg: dict, db: DB, salida: Path | None = None, resumidor=None,
                      titulo: str = "Monitor de Redes") -> Path:
    salida = Path(salida or ruta_de(cfg, "dashboard"))
    salida.parent.mkdir(parents=True, exist_ok=True)
    env = Environment(loader=FileSystemLoader(PAQUETE / "plantillas"), autoescape=True)
    html = env.get_template("dashboard.html").render(datos=datos_dashboard(cfg, db, resumidor), titulo=titulo)
    salida.write_text(html, encoding="utf-8")
    log.info("Dashboard generado: %s", salida)
    return salida
