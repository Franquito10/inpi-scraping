"""Corrida de scraping: recorre plataformas, asigna cada publicacion a su persona,
la clasifica y la guarda. Devuelve las publicaciones nuevas."""

import os
import logging
from datetime import datetime, timezone, timedelta

from .config import PLATAFORMAS, NOMBRE_RED, normalizar
from .db import DB
from .analisis import clasificar
from .scrapers import ApifyBackend, DemoBackend, ErrorScraping

log = logging.getLogger("redes.recolector")


def crear_backend(cfg: dict):
    sc = cfg.get("scraping") or {}
    nombre = sc.get("backend", "apify")
    if nombre == "demo":
        return DemoBackend()
    return ApifyBackend(os.environ.get("APIFY_TOKEN", ""), sc.get("actores") or {},
                        sc.get("timeout_minutos", 15))


def _claves(texto: str) -> set[str]:
    t = normalizar(texto or "").strip().rstrip("/")
    if not t:
        return set()
    out = {t}
    for pref in ("https://", "http://", "www.", "m.", "mobile."):
        if t.startswith(pref):
            t = t[len(pref):]
    out.add(t)
    # usuario final de la URL
    ult = t.split("?")[0].rstrip("/").split("/")[-1].lstrip("@")
    if ult:
        out.add(ult)
    if "id=" in t:
        out.add(t.split("id=")[1].split("&")[0])
    return out


def _indice(cuentas: list[dict]) -> dict[str, dict]:
    idx = {}
    for c in cuentas:
        for k in _claves(c["usuario"]) | _claves(c["url"]):
            idx[k] = c
    return idx


def _asignar(pub: dict, idx: dict, cuentas: list[dict]) -> dict | None:
    for campo in ("usuario", "entrada"):
        for k in _claves(str(pub.get(campo) or "")):
            if k in idx:
                return idx[k]
    if len(cuentas) == 1:
        return cuentas[0]
    return None


def recolectar(cfg: dict, db: DB, backend=None, plataformas=None, solo_persona: str | None = None) -> dict:
    sc = cfg.get("scraping") or {}
    backend = backend or crear_backend(cfg)
    dias, maximo = sc.get("dias_atras", 7), sc.get("max_por_cuenta", 30)
    plataformas = plataformas or sc.get("plataformas") or list(PLATAFORMAS)
    inicio = datetime.now(timezone.utc)
    corte = inicio - timedelta(days=dias + 1)
    nuevas, actualizadas, errores = [], 0, []

    personas = db.personas()
    if solo_persona:
        personas = [p for p in personas if p["slug"] == solo_persona]

    for red in plataformas:
        cuentas = [dict(p["cuentas"][red], persona_id=p["id"], nombre=p["nombre"])
                   for p in personas if red in p["cuentas"]]
        if not cuentas:
            continue
        log.info("%s: %d cuentas", NOMBRE_RED[red], len(cuentas))
        try:
            pubs = backend.scrapear(red, cuentas, dias, maximo)
        except (ErrorScraping, Exception) as e:  # una red caida no frena las otras
            log.error("%s fallo: %s", NOMBRE_RED[red], e)
            errores.append(f"{NOMBRE_RED[red]}: {e}")
            for c in cuentas:
                db.marcar_cuenta(c["persona_id"], red, str(e)[:300])
            continue

        idx = _indice(cuentas)
        vistas = set()
        sin_asignar = 0
        for pub in pubs:
            cuenta = _asignar(pub, idx, cuentas)
            if not cuenta:
                sin_asignar += 1
                continue
            if pub.get("fecha") and pub["fecha"] < corte:
                continue
            vistas.add(cuenta["persona_id"])
            cl = clasificar(pub["texto"], pub.get("hashtags"))
            fila = dict(pub, **cl, persona_id=cuenta["persona_id"])
            fila["fecha"] = (pub["fecha"] or inicio).strftime("%Y-%m-%dT%H:%M:%SZ")
            fila.pop("usuario", None)
            fila.pop("entrada", None)
            if db.guardar_publicacion(fila):
                nuevas.append(fila)
            else:
                actualizadas += 1
        if sin_asignar:
            log.warning("%s: %d publicaciones sin persona asignada", NOMBRE_RED[red], sin_asignar)
        for c in cuentas:
            db.marcar_cuenta(c["persona_id"], red, None)

    fin = datetime.now(timezone.utc)
    db.registrar_corrida(inicio, fin, getattr(backend, "nombre", "?"), len(nuevas), actualizadas, errores)
    log.info("Corrida terminada: %d nuevas, %d actualizadas, %d errores", len(nuevas), actualizadas, len(errores))
    return {"nuevas": nuevas, "actualizadas": actualizadas, "errores": errores}


def reclasificar(db: DB) -> int:
    """Vuelve a clasificar todo (util si se editan los diccionarios de analisis.py)."""
    n = 0
    for p in db.publicaciones():
        cl = clasificar(p["texto"] or "", p["hashtags"])
        db.actualizar_clasificacion(p["id"], cl["temas"], cl["actividades"], cl["lugares"])
        n += 1
    return n
