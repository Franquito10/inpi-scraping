"""Carga de configuracion, variables de entorno y lista de personas."""

import os
import re
import logging
import unicodedata
from pathlib import Path
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import yaml

RAIZ = Path(__file__).resolve().parent.parent
PAQUETE = Path(__file__).resolve().parent
PLATAFORMAS = ("facebook", "x", "instagram", "tiktok")
NOMBRE_RED = {"facebook": "Facebook", "x": "X", "instagram": "Instagram", "tiktok": "TikTok"}

log = logging.getLogger("redes")


def cargar_env(ruta: Path = PAQUETE / ".env") -> None:
    """Carga un archivo .env simple (CLAVE=valor) sin pisar variables ya definidas."""
    if not ruta.exists():
        return
    for linea in ruta.read_text(encoding="utf-8").splitlines():
        linea = linea.strip()
        if not linea or linea.startswith("#") or "=" not in linea:
            continue
        clave, valor = linea.split("=", 1)
        os.environ.setdefault(clave.strip(), valor.strip().strip('"').strip("'"))


def cargar_settings(ruta: Path | None = None) -> dict:
    ruta = ruta or PAQUETE / "config.yaml"
    with open(ruta, encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}
    cargar_env()
    return cfg


def ruta_de(cfg: dict, clave: str) -> Path:
    p = Path(cfg["rutas"][clave])
    return p if p.is_absolute() else RAIZ / p


def tz(cfg: dict) -> ZoneInfo:
    return ZoneInfo(cfg.get("zona_horaria", "America/Argentina/Tucuman"))


def ahora_utc() -> datetime:
    return datetime.now(timezone.utc)


def normalizar(texto: str) -> str:
    """minusculas y sin acentos (para busquedas y clasificacion)."""
    t = unicodedata.normalize("NFKD", texto or "")
    return "".join(c for c in t if not unicodedata.combining(c)).lower()


def slug(texto: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", normalizar(texto)).strip("-")


def usuario_desde_url(plataforma: str, url: str) -> str:
    """Extrae el nombre de usuario (o id) de la URL de un perfil."""
    url = (url or "").strip()
    if not url:
        return ""
    m = re.search(r"[?&]id=(\d+)", url)
    if m:
        return m.group(1)
    ruta = re.sub(r"^https?://[^/]+/", "", url).split("?")[0].strip("/")
    usuario = ruta.split("/")[0] if ruta else ""
    return usuario.lstrip("@")


def cargar_personas(cfg: dict) -> list[dict]:
    ruta = ruta_de(cfg, "personas")
    if not ruta.exists():
        raise FileNotFoundError(
            f"No existe {ruta}. Importa el Excel primero: python -m monitor_redes importar archivo.xlsx")
    with open(ruta, encoding="utf-8") as f:
        datos = yaml.safe_load(f) or {}
    personas = []
    for p in datos.get("personas", []):
        cuentas = {}
        for red in PLATAFORMAS:
            url = (p.get("redes") or {}).get(red)
            if url:
                cuentas[red] = {"url": url, "usuario": usuario_desde_url(red, url)}
        personas.append({
            "nombre": p["nombre"].strip(),
            "cargo": (p.get("cargo") or "").strip(),
            "slug": slug(p["nombre"]),
            "cuentas": cuentas,
        })
    return personas
