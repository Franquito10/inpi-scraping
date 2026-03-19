"""
Extraccion de texto e imagenes desde PDFs de boletines INPI.

Estrategia:
1. Extraer texto con PyMuPDF/fitz (primario, rapido, sin deps extra)
2. Fallback con pdfplumber si fitz no extrae texto
3. Si una pagina no tiene texto, aplicar OCR con Tesseract
4. Extraer imagenes embebidas con PyMuPDF
5. Segmentar por entradas marcarias (cada publicacion individual)
"""

import re
import logging
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional

import fitz  # PyMuPDF

logger = logging.getLogger("inpi.parser")


@dataclass
class EntradaMarcaria:
    """Representa una publicacion individual dentro del boletin."""
    pagina: int
    texto_completo: str
    denominacion: str
    clase_niza: list[int] = field(default_factory=list)
    tipo_marca: str = ""  # denominativa, mixta, figurativa
    solicitante: str = ""
    acta_numero: str = ""
    imagenes: list[Path] = field(default_factory=list)
    texto_limpio: str = ""


@dataclass
class ResultadoParseo:
    """Resultado completo del parseo de un PDF."""
    archivo: str
    total_paginas: int
    entradas: list[EntradaMarcaria]
    texto_por_pagina: dict  # {pagina: texto}
    imagenes_extraidas: list[Path]
    errores: list[str]
    uso_ocr: bool = False


class ParserPDF:
    def __init__(self, settings: dict):
        cfg_ext = settings.get("extraccion", {})
        self.ocr_fallback = cfg_ext.get("ocr_fallback", True)
        self.idioma_ocr = cfg_ext.get("idioma_ocr", "spa")
        self.min_ancho = cfg_ext.get("min_ancho_imagen", 50)
        self.min_alto = cfg_ext.get("min_alto_imagen", 50)
        self.max_imgs_pagina = cfg_ext.get("max_imagenes_por_pagina", 10)

    def procesar_pdf(self, ruta_pdf: Path, dir_imagenes: Path) -> ResultadoParseo:
        """Procesa un PDF completo: texto + imagenes + segmentacion."""
        logger.info(f"Procesando PDF: {ruta_pdf.name}")
        dir_imagenes.mkdir(parents=True, exist_ok=True)

        errores = []
        texto_paginas = {}
        imagenes_total = []
        uso_ocr = False

        # Paso 1: Extraer texto con PyMuPDF (primario)
        try:
            texto_paginas = self._extraer_texto_fitz(ruta_pdf)
        except Exception as e:
            errores.append(f"Error fitz: {e}")
            logger.error(f"Error extrayendo texto con fitz: {e}")

        # Paso 1b: Fallback con pdfplumber si fitz no dio texto
        if not any(t.strip() for t in texto_paginas.values()):
            try:
                texto_paginas = self._extraer_texto_pdfplumber(ruta_pdf)
            except Exception as e:
                logger.warning(f"Fallback pdfplumber tampoco funciono: {e}")

        # Paso 2: OCR en paginas sin texto
        if self.ocr_fallback:
            for pag, texto in texto_paginas.items():
                if not texto or len(texto.strip()) < 20:
                    texto_ocr = self._ocr_pagina(ruta_pdf, pag)
                    if texto_ocr:
                        texto_paginas[pag] = texto_ocr
                        uso_ocr = True

        # Paso 3: Extraer imagenes con PyMuPDF
        try:
            imagenes_total = self._extraer_imagenes(ruta_pdf, dir_imagenes)
        except Exception as e:
            errores.append(f"Error extrayendo imagenes: {e}")
            logger.error(f"Error extrayendo imagenes: {e}")

        # Paso 4: Segmentar en entradas marcarias
        entradas = self._segmentar_entradas(texto_paginas, imagenes_total)

        total_paginas = len(texto_paginas)
        logger.info(
            f"PDF procesado: {total_paginas} paginas, "
            f"{len(entradas)} entradas, {len(imagenes_total)} imagenes"
        )

        return ResultadoParseo(
            archivo=ruta_pdf.name,
            total_paginas=total_paginas,
            entradas=entradas,
            texto_por_pagina=texto_paginas,
            imagenes_extraidas=imagenes_total,
            errores=errores,
            uso_ocr=uso_ocr,
        )

    def _extraer_texto_fitz(self, ruta: Path) -> dict[int, str]:
        """Extrae texto de cada pagina con PyMuPDF (fitz)."""
        textos = {}
        doc = fitz.open(str(ruta))
        for i in range(len(doc)):
            texto = doc[i].get_text("text") or ""
            textos[i + 1] = texto
        doc.close()
        return textos

    def _extraer_texto_pdfplumber(self, ruta: Path) -> dict[int, str]:
        """Fallback: extrae texto con pdfplumber."""
        try:
            import pdfplumber
            textos = {}
            with pdfplumber.open(str(ruta)) as pdf:
                for i, pagina in enumerate(pdf.pages, 1):
                    texto = pagina.extract_text() or ""
                    textos[i] = texto
            return textos
        except ImportError:
            logger.warning("pdfplumber no disponible")
            return {}
        except Exception as e:
            logger.warning(f"Error pdfplumber: {e}")
            return {}

    def _ocr_pagina(self, ruta_pdf: Path, num_pagina: int) -> str:
        """Aplica OCR a una pagina especifica."""
        try:
            import pytesseract
            from PIL import Image
            doc = fitz.open(str(ruta_pdf))
            pagina = doc[num_pagina - 1]
            mat = fitz.Matrix(300 / 72, 300 / 72)
            pix = pagina.get_pixmap(matrix=mat)
            img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
            doc.close()
            texto = pytesseract.image_to_string(img, lang=self.idioma_ocr)
            logger.debug(f"OCR pagina {num_pagina}: {len(texto)} caracteres")
            return texto
        except ImportError:
            logger.debug("pytesseract no disponible, saltando OCR")
            return ""
        except Exception as e:
            logger.warning(f"Error OCR pagina {num_pagina}: {e}")
            return ""

    def _extraer_imagenes(self, ruta_pdf: Path, dir_salida: Path) -> list[Path]:
        """Extrae imagenes embebidas del PDF."""
        imagenes = []
        doc = fitz.open(str(ruta_pdf))
        nombre_base = ruta_pdf.stem

        for num_pag in range(len(doc)):
            pagina = doc[num_pag]
            imgs_pagina = pagina.get_images(full=True)
            count = 0

            for img_idx, img_info in enumerate(imgs_pagina):
                if count >= self.max_imgs_pagina:
                    break
                xref = img_info[0]
                try:
                    img_data = doc.extract_image(xref)
                    if not img_data:
                        continue
                    ancho = img_data.get("width", 0)
                    alto = img_data.get("height", 0)

                    if ancho < self.min_ancho or alto < self.min_alto:
                        continue

                    ext = img_data.get("ext", "png")
                    nombre = f"{nombre_base}_p{num_pag + 1}_img{img_idx}.{ext}"
                    ruta_img = dir_salida / nombre

                    with open(ruta_img, "wb") as f:
                        f.write(img_data["image"])

                    imagenes.append(ruta_img)
                    count += 1
                except Exception as e:
                    logger.warning(f"Error extrayendo imagen xref={xref}: {e}")

        doc.close()
        return imagenes

    def _segmentar_entradas(self, texto_paginas: dict[int, str],
                            imagenes: list[Path]) -> list[EntradaMarcaria]:
        """Segmenta el texto en entradas marcarias individuales."""
        from .utils import extraer_clase_niza, extraer_denominacion, detectar_tipo_marca

        entradas = []

        for pagina, texto in texto_paginas.items():
            if not texto or len(texto.strip()) < 10:
                continue

            imgs_pagina = [
                img for img in imagenes
                if f"_p{pagina}_" in img.name
            ]

            bloques = self._dividir_en_bloques(texto)

            for bloque in bloques:
                if len(bloque.strip()) < 5:
                    continue

                denominacion = extraer_denominacion(bloque)
                clases = extraer_clase_niza(bloque)
                tipo = detectar_tipo_marca(denominacion, bool(imgs_pagina))
                solicitante = self._extraer_solicitante(bloque)
                acta = self._extraer_acta(bloque)

                entrada = EntradaMarcaria(
                    pagina=pagina,
                    texto_completo=bloque,
                    denominacion=denominacion,
                    clase_niza=clases,
                    tipo_marca=tipo,
                    solicitante=solicitante,
                    acta_numero=acta,
                    imagenes=imgs_pagina,
                    texto_limpio=bloque.strip(),
                )
                entradas.append(entrada)

        logger.info(f"Segmentadas {len(entradas)} entradas marcarias")
        return entradas

    def _dividir_en_bloques(self, texto: str) -> list[str]:
        """Divide el texto de una pagina en bloques por patrones INPI."""
        separadores = [
            r"\n\s*[-=_]{10,}\s*\n",
            r"\n\s*\*{5,}\s*\n",
            r"\n(?=Acta\s+N[ro°]+\.?\s*\d+)",
            r"\n(?=SOLICITUD\s+(?:DE\s+)?(?:MARCA|REGISTRO))",
            r"\n(?=N[°º]\s*\d{4,})",
        ]

        patron_compuesto = "|".join(separadores)
        bloques = re.split(patron_compuesto, texto)
        return [b for b in bloques if b and len(b.strip()) > 10]

    def _extraer_solicitante(self, texto: str) -> str:
        """Extrae el nombre del solicitante."""
        patrones = [
            r"[Ss]olicitante[:\s]+(.+?)(?:\n|$)",
            r"[Tt]itular[:\s]+(.+?)(?:\n|$)",
            r"[Pp]ropietario[:\s]+(.+?)(?:\n|$)",
        ]
        for patron in patrones:
            match = re.search(patron, texto)
            if match:
                return match.group(1).strip()
        return ""

    def _extraer_acta(self, texto: str) -> str:
        """Extrae el numero de acta/expediente."""
        patrones = [
            r"[Aa]cta\s+[Nn][ro°]+\.?\s*(\d+)",
            r"[Ee]xp(?:ediente)?\.?\s*[Nn][ro°]+\.?\s*(\d+)",
            r"N[°º]\s*(\d{4,})",
        ]
        for patron in patrones:
            match = re.search(patron, texto)
            if match:
                return match.group(1)
        return ""
