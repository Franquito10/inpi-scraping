"""Importa la planilla de personas/redes (xlsx) a personas.yaml.

Formato esperado (como 'Redes c rech.xlsx'):
  fila 1: PERSONA | CARGO | REDES
  fila 2:         |       | FB | TW | IG | TIK TOK
  filas siguientes: una persona por fila con las URLs.
Las columnas se detectan por encabezado y, si falta, por el dominio de la URL.
"""

from pathlib import Path

import yaml
import openpyxl

ENCABEZADOS = {
    "fb": "facebook", "facebook": "facebook",
    "tw": "x", "twitter": "x", "x": "x",
    "ig": "instagram", "instagram": "instagram",
    "tik tok": "tiktok", "tiktok": "tiktok",
}
DOMINIOS = {"facebook.com": "facebook", "fb.com": "facebook", "x.com": "x", "twitter.com": "x",
            "instagram.com": "instagram", "tiktok.com": "tiktok"}


def _red_por_url(url: str) -> str | None:
    for dom, red in DOMINIOS.items():
        if dom in url:
            return red
    return None


def leer_excel(ruta: Path) -> list[dict]:
    wb = openpyxl.load_workbook(ruta, read_only=True, data_only=True)
    ws = wb.worksheets[0]
    filas = [[("" if c is None else str(c).strip()) for c in fila]
             for fila in ws.iter_rows(values_only=True)]
    filas = [f for f in filas if any(f)]

    col_nombre, col_cargo, col_red = 0, 1, {}
    for fila in filas[:3]:
        for i, celda in enumerate(fila):
            k = celda.lower()
            if k == "persona" or k == "nombre":
                col_nombre = i
            elif k == "cargo":
                col_cargo = i
            elif k in ENCABEZADOS:
                col_red[i] = ENCABEZADOS[k]

    personas = []
    for fila in filas:
        nombre = fila[col_nombre] if col_nombre < len(fila) else ""
        if not nombre or nombre.lower() in ("persona", "nombre"):
            continue
        redes = {}
        for i, celda in enumerate(fila):
            if not celda.startswith("http"):
                continue
            red = _red_por_url(celda) or col_red.get(i)
            if red and red not in redes:
                redes[red] = celda
        personas.append({
            "nombre": nombre,
            "cargo": fila[col_cargo] if col_cargo < len(fila) else "",
            "redes": redes,
        })
    return personas


def importar(ruta_excel: Path, ruta_salida: Path) -> list[dict]:
    personas = leer_excel(ruta_excel)
    ruta_salida.parent.mkdir(parents=True, exist_ok=True)
    with open(ruta_salida, "w", encoding="utf-8") as f:
        f.write("# Generado desde la planilla. Se puede editar a mano (agregar/quitar personas o redes).\n")
        yaml.safe_dump({"personas": personas}, f, allow_unicode=True, sort_keys=False, width=200)
    return personas
