"""
Comparacion visual de logos.

Evalua:
- SSIM (Structural Similarity Index)
- ORB features (keypoints matching)
- Template matching basico

Preprocesamiento:
- Redimensionar a tamano uniforme
- Binarizar si es necesario
- Normalizar fondo
"""

import logging
from pathlib import Path
from dataclasses import dataclass
from typing import Optional

import numpy as np
import cv2

logger = logging.getLogger("inpi.visual")


@dataclass
class ResultadoVisual:
    """Resultado de comparacion visual."""
    score: float
    score_ssim: float
    score_orb: float
    score_template: float
    detalle: str


class ComparadorVisual:
    def __init__(self, settings: dict):
        cfg = settings.get("visual", {})
        self.umbral_ssim = cfg.get("umbral_ssim", 0.45)
        self.umbral_orb = cfg.get("umbral_orb", 0.30)
        self.tam = tuple(cfg.get("redimensionar_a", [200, 200]))
        self.binarizar = cfg.get("binarizar", True)

    def comparar(self, imagen_detectada: Path,
                 imagen_referencia: Path) -> ResultadoVisual:
        """Compara dos imagenes de logos."""
        try:
            img1 = self._cargar_y_preprocesar(imagen_detectada)
            img2 = self._cargar_y_preprocesar(imagen_referencia)
        except Exception as e:
            logger.warning(f"Error cargando imagenes: {e}")
            return ResultadoVisual(
                score=0, score_ssim=0, score_orb=0, score_template=0,
                detalle=f"Error cargando imagenes: {e}"
            )

        if img1 is None or img2 is None:
            return ResultadoVisual(
                score=0, score_ssim=0, score_orb=0, score_template=0,
                detalle="No se pudieron cargar las imagenes"
            )

        # 1. SSIM
        score_ssim = self._calcular_ssim(img1, img2)

        # 2. ORB features
        score_orb = self._calcular_orb(img1, img2)

        # 3. Template matching
        score_template = self._calcular_template(img1, img2)

        # Score final: maximo ponderado
        score = max(
            score_ssim * 0.95,
            score_orb * 0.90,
            score_template * 0.80,
        )

        detalle = self._explicar(
            imagen_detectada.name, imagen_referencia.name,
            score_ssim, score_orb, score_template, score
        )

        return ResultadoVisual(
            score=min(score, 1.0),
            score_ssim=score_ssim,
            score_orb=score_orb,
            score_template=score_template,
            detalle=detalle,
        )

    def comparar_contra_referencias(self, imagen: Path,
                                     referencias: list[Path]) -> tuple[ResultadoVisual, Optional[Path]]:
        """Compara una imagen contra todas las referencias.
        Retorna el mejor resultado y la referencia que matcheo."""
        mejor = ResultadoVisual(score=0, score_ssim=0, score_orb=0,
                                score_template=0, detalle="Sin match visual")
        mejor_ref = None

        for ref in referencias:
            if not ref.exists():
                continue
            resultado = self.comparar(imagen, ref)
            if resultado.score > mejor.score:
                mejor = resultado
                mejor_ref = ref

        return mejor, mejor_ref

    def _cargar_y_preprocesar(self, ruta: Path) -> Optional[np.ndarray]:
        """Carga y preprocesa una imagen para comparacion."""
        if not ruta.exists():
            return None

        img = cv2.imread(str(ruta))
        if img is None:
            # Intentar con PIL para formatos que OpenCV no maneja
            try:
                from PIL import Image
                import io
                pil_img = Image.open(str(ruta)).convert("RGB")
                img = np.array(pil_img)
                img = cv2.cvtColor(img, cv2.COLOR_RGB2BGR)
            except Exception:
                return None

        # Convertir a escala de grises
        gris = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

        # Redimensionar
        gris = cv2.resize(gris, self.tam, interpolation=cv2.INTER_AREA)

        if self.binarizar:
            # Binarizacion adaptativa (mejor para logos con distintos fondos)
            gris = cv2.adaptiveThreshold(
                gris, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                cv2.THRESH_BINARY, 11, 2
            )

        return gris

    def _calcular_ssim(self, img1: np.ndarray, img2: np.ndarray) -> float:
        """Calcula SSIM entre dos imagenes."""
        try:
            from skimage.metrics import structural_similarity
            score, _ = structural_similarity(img1, img2, full=True)
            return max(0, score)
        except Exception as e:
            logger.warning(f"Error calculando SSIM: {e}")
            return 0

    def _calcular_orb(self, img1: np.ndarray, img2: np.ndarray) -> float:
        """Compara usando ORB features + BFMatcher."""
        try:
            orb = cv2.ORB_create(nfeatures=500)
            kp1, des1 = orb.detectAndCompute(img1, None)
            kp2, des2 = orb.detectAndCompute(img2, None)

            if des1 is None or des2 is None or len(des1) < 2 or len(des2) < 2:
                return 0

            bf = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=False)
            matches = bf.knnMatch(des1, des2, k=2)

            # Ratio test de Lowe
            buenos = 0
            total = 0
            for match_pair in matches:
                if len(match_pair) == 2:
                    m, n = match_pair
                    total += 1
                    if m.distance < 0.75 * n.distance:
                        buenos += 1

            return buenos / total if total > 0 else 0
        except Exception as e:
            logger.warning(f"Error calculando ORB: {e}")
            return 0

    def _calcular_template(self, img1: np.ndarray, img2: np.ndarray) -> float:
        """Template matching normalizado."""
        try:
            result = cv2.matchTemplate(img1, img2, cv2.TM_CCOEFF_NORMED)
            _, max_val, _, _ = cv2.minMaxLoc(result)
            return max(0, max_val)
        except Exception as e:
            logger.warning(f"Error en template matching: {e}")
            return 0

    def _explicar(self, nombre1, nombre2, ssim, orb, template, final) -> str:
        """Genera explicacion de la comparacion visual."""
        partes = [f"Comparacion visual: {nombre1} vs {nombre2}"]

        if ssim > self.umbral_ssim:
            partes.append(f"Estructura visual similar (SSIM: {ssim:.0%})")
        if orb > self.umbral_orb:
            partes.append(f"Rasgos visuales compartidos (ORB: {orb:.0%})")
        if template > 0.5:
            partes.append(f"Patron visual coincidente ({template:.0%})")

        partes.append(f"Similitud visual global: {final:.0%}")

        return ". ".join(partes)
