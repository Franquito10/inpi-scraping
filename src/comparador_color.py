"""
Comparacion cromatica entre logos.

Evalua:
- Histogramas de color (HSV)
- Colores dominantes (K-means)
- Distancia entre paletas

Se usa como senal complementaria, no como criterio principal.
"""

import logging
from pathlib import Path
from dataclasses import dataclass
from typing import Optional

import numpy as np
import cv2

logger = logging.getLogger("inpi.color")


@dataclass
class ResultadoColor:
    """Resultado de comparacion cromatica."""
    score: float
    score_histograma: float
    score_dominantes: float
    colores_detectados: list  # [(R,G,B), ...]
    colores_referencia: list
    detalle: str


class ComparadorColor:
    def __init__(self, settings: dict):
        cfg = settings.get("color", {})
        self.umbral_hist = cfg.get("umbral_histograma", 0.40)
        self.n_dominantes = cfg.get("n_colores_dominantes", 5)
        self.umbral_dom = cfg.get("umbral_color_dominante", 0.35)
        self.tam = (150, 150)

    def comparar(self, imagen_detectada: Path,
                 imagen_referencia: Path) -> ResultadoColor:
        """Compara dos imagenes por color."""
        try:
            img1 = self._cargar(imagen_detectada)
            img2 = self._cargar(imagen_referencia)
        except Exception as e:
            logger.warning(f"Error cargando imagenes para color: {e}")
            return ResultadoColor(
                score=0, score_histograma=0, score_dominantes=0,
                colores_detectados=[], colores_referencia=[],
                detalle=f"Error: {e}"
            )

        if img1 is None or img2 is None:
            return ResultadoColor(
                score=0, score_histograma=0, score_dominantes=0,
                colores_detectados=[], colores_referencia=[],
                detalle="No se pudieron cargar las imagenes"
            )

        # 1. Comparacion de histogramas HSV
        score_hist = self._comparar_histogramas(img1, img2)

        # 2. Comparacion de colores dominantes
        dom1 = self._colores_dominantes(img1)
        dom2 = self._colores_dominantes(img2)
        score_dom = self._comparar_dominantes(dom1, dom2)

        # Score final
        score = score_hist * 0.5 + score_dom * 0.5

        detalle = self._explicar(score_hist, score_dom, dom1, dom2, score)

        return ResultadoColor(
            score=min(score, 1.0),
            score_histograma=score_hist,
            score_dominantes=score_dom,
            colores_detectados=dom1,
            colores_referencia=dom2,
            detalle=detalle,
        )

    def comparar_contra_referencias(self, imagen: Path,
                                     referencias: list[Path]) -> tuple[ResultadoColor, Optional[Path]]:
        """Compara contra todas las referencias."""
        mejor = ResultadoColor(score=0, score_histograma=0, score_dominantes=0,
                               colores_detectados=[], colores_referencia=[],
                               detalle="Sin match de color")
        mejor_ref = None

        for ref in referencias:
            if not ref.exists():
                continue
            resultado = self.comparar(imagen, ref)
            if resultado.score > mejor.score:
                mejor = resultado
                mejor_ref = ref

        return mejor, mejor_ref

    def _cargar(self, ruta: Path) -> Optional[np.ndarray]:
        """Carga imagen en BGR."""
        if not ruta.exists():
            return None
        img = cv2.imread(str(ruta))
        if img is None:
            try:
                from PIL import Image
                pil_img = Image.open(str(ruta)).convert("RGB")
                img = np.array(pil_img)
                img = cv2.cvtColor(img, cv2.COLOR_RGB2BGR)
            except Exception:
                return None
        return cv2.resize(img, self.tam)

    def _comparar_histogramas(self, img1: np.ndarray, img2: np.ndarray) -> float:
        """Compara histogramas HSV."""
        hsv1 = cv2.cvtColor(img1, cv2.COLOR_BGR2HSV)
        hsv2 = cv2.cvtColor(img2, cv2.COLOR_BGR2HSV)

        # Calcular histogramas para H y S (V es menos informativo)
        hist_params = {
            "channels": [0, 1],
            "histSize": [50, 60],
            "ranges": [0, 180, 0, 256],
        }

        h1 = cv2.calcHist([hsv1], hist_params["channels"], None,
                          hist_params["histSize"], hist_params["ranges"])
        h2 = cv2.calcHist([hsv2], hist_params["channels"], None,
                          hist_params["histSize"], hist_params["ranges"])

        cv2.normalize(h1, h1, 0, 1, cv2.NORM_MINMAX)
        cv2.normalize(h2, h2, 0, 1, cv2.NORM_MINMAX)

        # Correlacion de histogramas
        score = cv2.compareHist(h1, h2, cv2.HISTCMP_CORREL)
        return max(0, score)

    def _colores_dominantes(self, img: np.ndarray) -> list[tuple]:
        """Extrae colores dominantes con K-means."""
        try:
            from sklearn.cluster import KMeans

            # Reshape a lista de pixeles
            pixeles = img.reshape(-1, 3).astype(np.float32)

            # Filtrar pixeles muy oscuros o muy claros (fondo)
            mask = np.all(pixeles > 20, axis=1) & np.all(pixeles < 240, axis=1)
            pixeles_filtrados = pixeles[mask]

            if len(pixeles_filtrados) < self.n_dominantes:
                pixeles_filtrados = pixeles

            n_clusters = min(self.n_dominantes, len(pixeles_filtrados))
            if n_clusters < 1:
                return []

            kmeans = KMeans(n_clusters=n_clusters, n_init=10, random_state=42)
            kmeans.fit(pixeles_filtrados)

            # Ordenar por frecuencia
            labels, counts = np.unique(kmeans.labels_, return_counts=True)
            orden = np.argsort(-counts)

            colores = []
            for idx in orden:
                bgr = kmeans.cluster_centers_[labels[idx]].astype(int)
                rgb = (int(bgr[2]), int(bgr[1]), int(bgr[0]))
                colores.append(rgb)

            return colores
        except Exception as e:
            logger.warning(f"Error extrayendo colores dominantes: {e}")
            return []

    def _comparar_dominantes(self, dom1: list[tuple], dom2: list[tuple]) -> float:
        """Compara paletas de colores dominantes."""
        if not dom1 or not dom2:
            return 0

        # Para cada color dominante de img1, encontrar el mas cercano en img2
        distancias = []
        for c1 in dom1:
            min_dist = float("inf")
            for c2 in dom2:
                dist = self._distancia_color(c1, c2)
                min_dist = min(min_dist, dist)
            distancias.append(min_dist)

        # Normalizar: distancia maxima posible en RGB es ~441 (sqrt(3*255^2))
        max_dist = 441.0
        promedio = np.mean(distancias)
        score = 1.0 - (promedio / max_dist)
        return max(0, score)

    def _distancia_color(self, c1: tuple, c2: tuple) -> float:
        """Distancia euclidiana entre dos colores RGB."""
        return np.sqrt(sum((a - b) ** 2 for a, b in zip(c1, c2)))

    def _explicar(self, hist, dom, dom1, dom2, final) -> str:
        """Explica la comparacion cromatica."""
        partes = []

        if hist > self.umbral_hist:
            partes.append(f"Distribucion de color similar (histograma: {hist:.0%})")
        if dom > self.umbral_dom:
            partes.append(f"Paleta de colores dominantes cercana ({dom:.0%})")

        if dom1:
            colores_str = ", ".join(f"RGB{c}" for c in dom1[:3])
            partes.append(f"Colores detectados: {colores_str}")

        partes.append(f"Similitud cromatica: {final:.0%}")
        return ". ".join(partes) if partes else "Sin similitud cromatica significativa"
