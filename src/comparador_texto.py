"""
Comparacion textual entre denominaciones marcarias.

Evalua:
- Match exacto (normalizado)
- Similitud parcial (ratio, partial_ratio)
- Distancia de edicion (Levenshtein)
- Contencion (una dentro de otra)
"""

import logging
from dataclasses import dataclass

from rapidfuzz import fuzz
import jellyfish

from .utils import normalizar_texto

logger = logging.getLogger("inpi.texto")


@dataclass
class ResultadoTexto:
    """Resultado de comparacion textual."""
    score: float            # 0.0 a 1.0
    tipo_match: str         # exacto, parcial, contencion, levenshtein
    detalle: str            # explicacion
    score_exacto: float
    score_parcial: float
    score_token: float
    distancia_edit: int


class ComparadorTexto:
    def __init__(self, settings: dict):
        cfg = settings.get("texto", {})
        self.umbral_exacto = cfg.get("umbral_exacto", 0.85)
        self.umbral_parcial = cfg.get("umbral_parcial", 0.65)
        self.normalizar_acentos = cfg.get("normalizar_acentos", True)
        self.normalizar_mayusculas = cfg.get("normalizar_mayusculas", True)
        self.palabras_ignorar = set(
            w.upper() for w in cfg.get("ignorar_palabras", [])
        )

    def comparar(self, texto_detectado: str, marca_ref: str,
                 variantes: list[str] = None) -> ResultadoTexto:
        """
        Compara un texto detectado contra una marca de referencia y sus variantes.
        Retorna el mejor score encontrado.
        """
        candidatos = [marca_ref] + (variantes or [])
        mejor = ResultadoTexto(
            score=0, tipo_match="ninguno", detalle="Sin coincidencia",
            score_exacto=0, score_parcial=0, score_token=0, distancia_edit=999
        )

        for candidato in candidatos:
            resultado = self._comparar_par(texto_detectado, candidato)
            if resultado.score > mejor.score:
                mejor = resultado

        return mejor

    def _comparar_par(self, texto: str, referencia: str) -> ResultadoTexto:
        """Compara un par de textos."""
        # Normalizar
        t1 = normalizar_texto(
            texto,
            quitar_acentos=self.normalizar_acentos,
            minusculas=self.normalizar_mayusculas,
        )
        t2 = normalizar_texto(
            referencia,
            quitar_acentos=self.normalizar_acentos,
            minusculas=self.normalizar_mayusculas,
        )

        # Quitar palabras ignoradas
        t1_limpio = self._quitar_palabras_ruido(t1)
        t2_limpio = self._quitar_palabras_ruido(t2)

        if not t1_limpio or not t2_limpio:
            return ResultadoTexto(
                score=0, tipo_match="vacio", detalle="Texto vacio despues de limpieza",
                score_exacto=0, score_parcial=0, score_token=0, distancia_edit=999
            )

        # 1. Match exacto normalizado
        score_exacto = 1.0 if t1_limpio == t2_limpio else 0.0

        # 2. Ratio de similitud (fuzzy)
        score_ratio = fuzz.ratio(t1_limpio, t2_limpio) / 100.0

        # 3. Partial ratio (substring match)
        score_parcial = fuzz.partial_ratio(t1_limpio, t2_limpio) / 100.0

        # 4. Token sort ratio (insensible al orden de palabras)
        score_token = fuzz.token_sort_ratio(t1_limpio, t2_limpio) / 100.0

        # 5. Distancia de edicion
        dist_edit = jellyfish.levenshtein_distance(t1_limpio, t2_limpio)

        # 6. Contencion: una marca dentro de otra
        score_contencion = 0.0
        if t2_limpio in t1_limpio or t1_limpio in t2_limpio:
            contenida = min(len(t1_limpio), len(t2_limpio))
            contenedora = max(len(t1_limpio), len(t2_limpio))
            score_contencion = contenida / contenedora if contenedora > 0 else 0

        # Determinar score final y tipo
        if score_exacto == 1.0:
            return ResultadoTexto(
                score=1.0, tipo_match="exacto",
                detalle=f"Coincidencia exacta: '{referencia}'",
                score_exacto=1.0, score_parcial=score_parcial,
                score_token=score_token, distancia_edit=0
            )

        # Score compuesto ponderado
        score_final = max(
            score_ratio * 0.9,  # Ratio general
            score_parcial * 0.8,  # Parcial (penalizado un poco)
            score_token * 0.85,  # Token sort
            score_contencion * 0.75,  # Contencion
        )

        # Determinar tipo de match dominante
        scores_tipo = {
            "similitud_ratio": score_ratio,
            "parcial": score_parcial,
            "token_sort": score_token,
            "contencion": score_contencion,
        }
        tipo_dominante = max(scores_tipo, key=scores_tipo.get)

        # Construir explicacion
        detalle = self._explicar(
            texto, referencia, score_ratio, score_parcial,
            score_token, dist_edit, score_contencion, tipo_dominante
        )

        return ResultadoTexto(
            score=min(score_final, 1.0),
            tipo_match=tipo_dominante,
            detalle=detalle,
            score_exacto=score_exacto,
            score_parcial=score_parcial,
            score_token=score_token,
            distancia_edit=dist_edit,
        )

    def _quitar_palabras_ruido(self, texto: str) -> str:
        """Quita palabras comunes que no aportan a la comparacion."""
        palabras = texto.upper().split()
        filtradas = [p for p in palabras if p not in self.palabras_ignorar]
        return " ".join(filtradas).lower()

    def _explicar(self, texto: str, referencia: str,
                  ratio: float, parcial: float, token: float,
                  dist_edit: int, contencion: float, tipo: str) -> str:
        """Genera explicacion legible de la comparacion."""
        partes = [f"'{texto}' vs '{referencia}'"]

        if ratio >= self.umbral_exacto:
            partes.append(f"Similitud muy alta ({ratio:.0%})")
        elif ratio >= self.umbral_parcial:
            partes.append(f"Similitud significativa ({ratio:.0%})")

        if parcial > ratio:
            partes.append(f"Coincidencia parcial: {parcial:.0%}")

        if contencion > 0.5:
            partes.append("Una denominacion contiene a la otra")

        partes.append(f"Distancia de edicion: {dist_edit} caracteres")

        return ". ".join(partes)
