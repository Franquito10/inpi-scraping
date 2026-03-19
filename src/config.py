"""
Carga y validacion de configuracion centralizada.
Lee settings.yaml y marcas_vigiladas.yaml.
"""

import os
import sys
import yaml
import logging
from pathlib import Path
from typing import Any

# Determinar raiz del proyecto
if getattr(sys, 'frozen', False):
    # Ejecutando como .exe empaquetado
    RAIZ_PROYECTO = Path(sys.executable).parent
else:
    RAIZ_PROYECTO = Path(__file__).parent.parent

ARCHIVO_SETTINGS = RAIZ_PROYECTO / "config" / "settings.yaml"
ARCHIVO_MARCAS = RAIZ_PROYECTO / "config" / "marcas_vigiladas.yaml"


def cargar_yaml(ruta: Path) -> dict:
    """Carga un archivo YAML y retorna dict."""
    if not ruta.exists():
        raise FileNotFoundError(f"Archivo de configuracion no encontrado: {ruta}")
    with open(ruta, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def cargar_settings() -> dict:
    """Carga la configuracion general."""
    return cargar_yaml(ARCHIVO_SETTINGS)


def cargar_marcas() -> list[dict]:
    """Carga las marcas vigiladas."""
    data = cargar_yaml(ARCHIVO_MARCAS)
    return data.get("marcas", [])


def obtener_ruta(settings: dict, clave: str) -> Path:
    """Resuelve una ruta relativa desde la config a ruta absoluta."""
    ruta_rel = settings.get("rutas", {}).get(clave, "")
    return RAIZ_PROYECTO / ruta_rel


def crear_estructura_carpetas(settings: dict) -> None:
    """Crea todas las carpetas necesarias si no existen."""
    for clave in ["datos", "pdfs", "logos_referencia", "logos_extraidos", "reportes"]:
        ruta = obtener_ruta(settings, clave)
        ruta.mkdir(parents=True, exist_ok=True)


def configurar_logging(settings: dict) -> logging.Logger:
    """Configura logging global."""
    cfg_log = settings.get("logging", {})
    nivel = getattr(logging, cfg_log.get("nivel", "INFO").upper(), logging.INFO)
    archivo_log = RAIZ_PROYECTO / cfg_log.get("archivo", "datos/inpi.log")
    archivo_log.parent.mkdir(parents=True, exist_ok=True)

    logger = logging.getLogger("inpi")
    logger.setLevel(nivel)

    # Handler archivo
    fh = logging.FileHandler(archivo_log, encoding="utf-8")
    fh.setLevel(nivel)
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    fh.setFormatter(fmt)
    logger.addHandler(fh)

    # Handler consola
    ch = logging.StreamHandler()
    ch.setLevel(nivel)
    ch.setFormatter(fmt)
    logger.addHandler(ch)

    return logger


def validar_settings(settings: dict) -> list[str]:
    """Valida la configuracion y retorna lista de advertencias."""
    advertencias = []
    if not settings.get("inpi", {}).get("url_boletines"):
        advertencias.append("No se configuro URL de boletines INPI")
    if not settings.get("scoring", {}).get("pesos"):
        advertencias.append("No se configuraron pesos de scoring")
    marcas = cargar_marcas()
    if not marcas:
        advertencias.append("No hay marcas vigiladas configuradas")
    return advertencias
