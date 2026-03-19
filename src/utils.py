"""
Utilidades compartidas: normalizacion de texto, hashing, helpers.
"""

import re
import hashlib
import unicodedata
from pathlib import Path


def normalizar_texto(texto: str, quitar_acentos: bool = True,
                     minusculas: bool = True,
                     quitar_simbolos: bool = True) -> str:
    """Normaliza texto para comparacion: acentos, case, simbolos."""
    if not texto:
        return ""
    t = texto.strip()
    if minusculas:
        t = t.lower()
    if quitar_acentos:
        t = unicodedata.normalize("NFD", t)
        t = "".join(c for c in t if unicodedata.category(c) != "Mn")
    if quitar_simbolos:
        t = re.sub(r"[^\w\s]", " ", t)
    # Colapsar espacios multiples
    t = re.sub(r"\s+", " ", t).strip()
    return t


def limpiar_texto_ocr(texto: str) -> str:
    """Limpia artefactos comunes de OCR."""
    if not texto:
        return ""
    # Reemplazos comunes de OCR
    reemplazos = {
        "|": "l",
        "0": "O",  # solo en contexto de letras, no numeros
        "1": "l",
    }
    # Solo aplicar si el contexto sugiere texto (no numeros)
    t = texto
    # Quitar caracteres de control
    t = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", t)
    # Quitar lineas vacias excesivas
    t = re.sub(r"\n{3,}", "\n\n", t)
    return t.strip()


def hash_archivo(ruta: Path) -> str:
    """Calcula SHA256 de un archivo."""
    sha = hashlib.sha256()
    with open(ruta, "rb") as f:
        for bloque in iter(lambda: f.read(8192), b""):
            sha.update(bloque)
    return sha.hexdigest()


def extraer_clase_niza(texto: str) -> list[int]:
    """Extrae numeros de clase Niza de un texto."""
    # Patrones comunes: "Clase 5", "Cl. 5", "clase: 5", "C.5"
    patrones = [
        r"[Cc]lase[:\s]*(\d{1,2})",
        r"[Cc]l\.?\s*(\d{1,2})",
        r"[Cc]\.?\s*(\d{1,2})",
    ]
    clases = set()
    for patron in patrones:
        for match in re.finditer(patron, texto):
            num = int(match.group(1))
            if 1 <= num <= 45:  # Clases Niza van de 1 a 45
                clases.add(num)
    return sorted(clases)


def extraer_denominacion(texto: str) -> str:
    """Intenta extraer la denominacion/nombre de marca de un bloque de texto."""
    lineas = texto.strip().split("\n")
    if not lineas:
        return ""
    # La denominacion suele estar en las primeras lineas, en mayusculas
    for linea in lineas[:5]:
        linea = linea.strip()
        if len(linea) >= 2 and linea == linea.upper() and not linea.isdigit():
            # Filtrar lineas que son solo numeros o muy cortas
            limpia = re.sub(r"[^\w\s]", "", linea).strip()
            if limpia and len(limpia) >= 2:
                return limpia
    # Fallback: primera linea no vacia
    for linea in lineas:
        if linea.strip():
            return linea.strip()[:100]
    return ""


def detectar_tipo_marca(texto: str, tiene_imagen: bool) -> str:
    """Detecta si la marca es denominativa, mixta o figurativa."""
    tiene_texto = bool(texto and len(texto.strip()) > 2)
    if tiene_texto and tiene_imagen:
        return "mixta"
    elif tiene_imagen and not tiene_texto:
        return "figurativa"
    else:
        return "denominativa"


def formato_porcentaje(valor: float) -> str:
    """Formatea un float 0-1 como porcentaje."""
    return f"{valor * 100:.1f}%"


def truncar(texto: str, max_len: int = 100) -> str:
    """Trunca texto con ellipsis."""
    if len(texto) <= max_len:
        return texto
    return texto[:max_len - 3] + "..."
