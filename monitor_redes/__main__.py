"""Monitor de Redes - linea de comandos.

Uso (desde la raiz del repo):
  python -m monitor_redes importar "Redes c rech.xlsx"   # carga la planilla -> personas.yaml
  python -m monitor_redes scrapear                       # scrapea todas las redes
  python -m monitor_redes scrapear --red instagram --persona pepe-seleme
  python -m monitor_redes dashboard --abrir              # genera y abre el dashboard
  python -m monitor_redes bot                            # bot de Telegram + scraping periodico
  python -m monitor_redes estado                         # cuentas, ultimo scraping, errores
  python -m monitor_redes demo --abrir                   # prueba todo con datos ficticios
  python -m monitor_redes reclasificar                   # re-aplica temas/actividades
"""

import sys
import copy
import argparse
import logging
import webbrowser
from pathlib import Path

from .config import cargar_settings, cargar_personas, ruta_de, slug, RAIZ, NOMBRE_RED, PLATAFORMAS


def _logging(verbose: bool) -> None:
    logging.basicConfig(level=logging.DEBUG if verbose else logging.INFO,
                        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s", datefmt="%H:%M:%S")
    logging.getLogger("urllib3").setLevel(logging.WARNING)


def _db(cfg):
    from .db import DB
    db = DB(ruta_de(cfg, "db"))
    db.sincronizar_personas(cargar_personas(cfg))
    return db


def cmd_importar(cfg, a):
    from .importar import importar
    salida = ruta_de(cfg, "personas")
    personas = importar(Path(a.excel), salida)
    n = sum(len(p["redes"]) for p in personas)
    print(f"✔ {len(personas)} personas y {n} cuentas importadas a {salida}")
    for p in personas:
        print(f"  - {p['nombre']:<26} {p['cargo']:<20} {', '.join(NOMBRE_RED[r] for r in p['redes'])}")


def cmd_scrapear(cfg, a):
    from .recolector import recolectar
    if a.backend:
        cfg["scraping"]["backend"] = a.backend
    if a.dias:
        cfg["scraping"]["dias_atras"] = a.dias
    db = _db(cfg)
    res = recolectar(cfg, db, plataformas=[a.red] if a.red else None, solo_persona=slug(a.persona) if a.persona else None)
    print(f"✔ {len(res['nuevas'])} publicaciones nuevas, {res['actualizadas']} actualizadas")
    for e in res["errores"]:
        print(f"  ⚠ {e}")
    if not a.sin_dashboard:
        cmd_dashboard(cfg, argparse.Namespace(abrir=False), db)


def cmd_dashboard(cfg, a, db=None):
    from .dashboard import generar_dashboard
    from .analisis import Resumidor
    db = db or _db(cfg)
    ruta = generar_dashboard(cfg, db, resumidor=Resumidor(cfg))
    print(f"✔ Dashboard: {ruta}")
    if a.abrir:
        webbrowser.open(ruta.as_uri())


def cmd_bot(cfg, a):
    from .bot import Bot
    if a.backend:
        cfg["scraping"]["backend"] = a.backend
    Bot(cfg, _db(cfg)).correr()


def cmd_estado(cfg, a):
    db = _db(cfg)
    c = db.ultima_corrida()
    print("Último scraping:", f"{c['fin']} ({c['nuevas']} nuevas, backend {c['backend']})" if c else "nunca")
    for p in db.personas():
        n = len(db.publicaciones(persona_id=p["id"]))
        print(f"\n{p['nombre']} — {p['cargo']} ({n} publicaciones)")
        for r, cu in p["cuentas"].items():
            est = f"ERROR: {cu['ultimo_error']}" if cu["ultimo_error"] else (cu["ultimo_scrapeo"] or "sin scrapear")
            print(f"   {NOMBRE_RED[r]:<10} @{cu['usuario']:<28} {est}")


def cmd_reclasificar(cfg, a):
    from .recolector import reclasificar
    print(f"✔ {reclasificar(_db(cfg))} publicaciones reclasificadas")


def cmd_demo(cfg, a):
    """Base y dashboard aparte, con personas y publicaciones FICTICIAS."""
    from .db import DB
    from .recolector import recolectar
    from .scrapers import DemoBackend, PERSONAS_DEMO
    from .dashboard import generar_dashboard
    cfg = copy.deepcopy(cfg)
    cfg["rutas"]["db"] = "datos/redes/demo.db"
    cfg["rutas"]["dashboard"] = "datos/redes/demo_dashboard.html"
    ruta_db = ruta_de(cfg, "db")
    if ruta_db.exists():
        ruta_db.unlink()
    db = DB(ruta_db)
    personas = [{"nombre": p["nombre"], "cargo": p["cargo"], "slug": slug(p["nombre"]),
                 "cuentas": {r: {"url": f"https://example.com/{r}/{slug(p['nombre'])}", "usuario": slug(p["nombre"])}
                             for r in PLATAFORMAS}} for p in PERSONAS_DEMO]
    db.sincronizar_personas(personas)
    cfg["scraping"]["dias_atras"] = 30
    res = recolectar(cfg, db, backend=DemoBackend(semilla=7, por_cuenta=12))
    ruta = generar_dashboard(cfg, db, titulo="Monitor de Redes · DEMO (datos ficticios)")
    print(f"✔ Demo: {len(res['nuevas'])} publicaciones ficticias · dashboard en {ruta}")
    if a.abrir:
        webbrowser.open(ruta.as_uri())


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python -m monitor_redes", description="Monitor de redes sociales",
                                 formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    ap.add_argument("-v", "--verbose", action="store_true")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("importar", help="importar planilla xlsx de personas/redes")
    s.add_argument("excel")
    s = sub.add_parser("scrapear", help="scrapear publicaciones")
    s.add_argument("--red", choices=PLATAFORMAS)
    s.add_argument("--persona", help="solo esta persona (nombre)")
    s.add_argument("--dias", type=int, help="traer los ultimos N dias (pisa config.yaml)")
    s.add_argument("--backend", choices=["apify", "demo"])
    s.add_argument("--sin-dashboard", action="store_true")
    s = sub.add_parser("dashboard", help="generar dashboard HTML")
    s.add_argument("--abrir", action="store_true")
    s = sub.add_parser("bot", help="correr bot de Telegram (incluye scraping periodico)")
    s.add_argument("--backend", choices=["apify", "demo"])
    sub.add_parser("estado", help="estado de cuentas y scraping")
    sub.add_parser("reclasificar", help="reclasificar publicaciones guardadas")
    s = sub.add_parser("demo", help="probar con datos ficticios")
    s.add_argument("--abrir", action="store_true")

    a = ap.parse_args(argv)
    _logging(a.verbose)
    cfg = cargar_settings()
    from .scrapers import ErrorScraping
    try:
        {"importar": cmd_importar, "scrapear": cmd_scrapear, "dashboard": cmd_dashboard, "bot": cmd_bot,
         "estado": cmd_estado, "reclasificar": cmd_reclasificar, "demo": cmd_demo}[a.cmd](cfg, a)
    except (ErrorScraping, FileNotFoundError, ValueError) as e:
        print(f"✘ {e}")
        return 1
    except KeyboardInterrupt:
        print("\nDetenido.")


if __name__ == "__main__":
    sys.exit(main())
