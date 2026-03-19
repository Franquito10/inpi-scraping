"""
Genera un PDF de prueba que simula un boletin real del INPI
con entradas marcarias de distintos tipos para validar el pipeline completo.

Entradas incluidas:
- TELEVET PLUS (similar a Televet - debe matchear)
- REDEX SOLUTIONS (similar a Redex - debe matchear)
- MEDILINE PRO (similar a MediLine - debe matchear)
- RECETAR ONLINE (similar a Receta Online - fonetico)
- AUXILIO 24 HS (similar a Auxilio24 - debe matchear)
- COCACOLA (no deberia matchear con nada)
- TELVEX (fonetico similar a Televet - edge case)
- MEDELLIN PHARMA (no deberia matchear)
"""

import sys
from pathlib import Path

# Usar fitz (PyMuPDF) para crear el PDF
import fitz


def crear_boletin_prueba(ruta_salida: Path):
    """Crea un PDF que simula un boletin de MARCAS NUEVAS del INPI."""

    doc = fitz.open()

    # --- Pagina 1: Caratula ---
    pag = doc.new_page(width=595, height=842)  # A4
    pag.insert_text(
        (150, 80),
        "BOLETIN DE MARCAS",
        fontsize=24,
        fontname="helv",
    )
    pag.insert_text(
        (180, 120),
        "MARCAS NUEVAS",
        fontsize=18,
        fontname="helv",
    )
    pag.insert_text(
        (120, 160),
        "Instituto Nacional de la Propiedad Industrial",
        fontsize=12,
    )
    pag.insert_text(
        (200, 200),
        "Fecha: 19/03/2026",
        fontsize=12,
    )
    pag.insert_text(
        (160, 240),
        "Sector: Marcas - Tipo_Item: 3",
        fontsize=10,
    )

    # --- Pagina 2: Entradas marcarias ---
    pag2 = doc.new_page(width=595, height=842)
    y = 60
    entradas_pag2 = [
        {
            "acta": "3847291",
            "denominacion": "TELEVET PLUS",
            "clase": "44",
            "tipo": "Denominativa",
            "solicitante": "Veterinaria del Sur SRL",
            "domicilio": "Av. Corrientes 1234, CABA",
        },
        {
            "acta": "3847292",
            "denominacion": "REDEX SOLUTIONS",
            "clase": "42",
            "tipo": "Denominativa",
            "solicitante": "Tech Solutions SA",
            "domicilio": "Belgrano 567, Cordoba",
        },
        {
            "acta": "3847293",
            "denominacion": "MEDILINE PRO",
            "clase": "5",
            "tipo": "Mixta",
            "solicitante": "Laboratorios MDP SA",
            "domicilio": "Tucuman 890, Rosario",
        },
    ]

    for entrada in entradas_pag2:
        bloque = (
            f"Acta Nro. {entrada['acta']}\n"
            f"{entrada['denominacion']}\n"
            f"Clase: {entrada['clase']}\n"
            f"Tipo: {entrada['tipo']}\n"
            f"Solicitante: {entrada['solicitante']}\n"
            f"Domicilio: {entrada['domicilio']}\n"
        )
        pag2.insert_text((60, y), bloque, fontsize=11, fontname="helv")
        y += 130
        # Separador
        pag2.draw_line((60, y - 10), (535, y - 10))
        y += 10

    # --- Pagina 3: Mas entradas ---
    pag3 = doc.new_page(width=595, height=842)
    y = 60
    entradas_pag3 = [
        {
            "acta": "3847294",
            "denominacion": "RECETAR ONLINE",
            "clase": "44",
            "tipo": "Denominativa",
            "solicitante": "Digital Health SAS",
            "domicilio": "Maipu 456, CABA",
        },
        {
            "acta": "3847295",
            "denominacion": "AUXILIO 24 HS",
            "clase": "39",
            "tipo": "Mixta",
            "solicitante": "Asistencia Total SA",
            "domicilio": "San Martin 789, Mendoza",
        },
        {
            "acta": "3847296",
            "denominacion": "COCACOLA ZERO SUGAR",
            "clase": "32",
            "tipo": "Mixta",
            "solicitante": "The Coca-Cola Company",
            "domicilio": "Atlanta, USA",
        },
    ]

    for entrada in entradas_pag3:
        bloque = (
            f"Acta Nro. {entrada['acta']}\n"
            f"{entrada['denominacion']}\n"
            f"Clase: {entrada['clase']}\n"
            f"Tipo: {entrada['tipo']}\n"
            f"Solicitante: {entrada['solicitante']}\n"
            f"Domicilio: {entrada['domicilio']}\n"
        )
        pag3.insert_text((60, y), bloque, fontsize=11, fontname="helv")
        y += 130
        pag3.draw_line((60, y - 10), (535, y - 10))
        y += 10

    # --- Pagina 4: Edge cases ---
    pag4 = doc.new_page(width=595, height=842)
    y = 60
    entradas_pag4 = [
        {
            "acta": "3847297",
            "denominacion": "TELVEX",
            "clase": "9",
            "tipo": "Denominativa",
            "solicitante": "Electronica Telvex SRL",
            "domicilio": "Rivadavia 111, CABA",
        },
        {
            "acta": "3847298",
            "denominacion": "MEDELLIN PHARMA",
            "clase": "5",
            "tipo": "Denominativa",
            "solicitante": "Pharma Colombia SA",
            "domicilio": "Medellin, Colombia",
        },
    ]

    for entrada in entradas_pag4:
        bloque = (
            f"Acta Nro. {entrada['acta']}\n"
            f"{entrada['denominacion']}\n"
            f"Clase: {entrada['clase']}\n"
            f"Tipo: {entrada['tipo']}\n"
            f"Solicitante: {entrada['solicitante']}\n"
            f"Domicilio: {entrada['domicilio']}\n"
        )
        pag4.insert_text((60, y), bloque, fontsize=11, fontname="helv")
        y += 130
        pag4.draw_line((60, y - 10), (535, y - 10))
        y += 10

    doc.save(str(ruta_salida))
    doc.close()
    print(f"PDF de prueba creado: {ruta_salida} ({ruta_salida.stat().st_size} bytes)")
    return ruta_salida


if __name__ == "__main__":
    ruta = Path("datos/pdfs/boletin_prueba_inpi.pdf")
    ruta.parent.mkdir(parents=True, exist_ok=True)
    crear_boletin_prueba(ruta)
