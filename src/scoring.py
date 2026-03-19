"""
Motor de scoring final.

Combina los scores de texto, fonetica, visual y color
en un score unificado con explicabilidad completa.

Contempla:
- Ponderacion configurable
- Coincidencia de clase Niza
- Tipo de marca (denominativa/mixta/figurativa)
- Prioridad de la marca vigilada
- Nivel de riesgo resultante
"""

import logging
from dataclasses import dataclass, field

from .comparador_texto import ResultadoTexto
from .comparador_fonetico import ResultadoFonetico
from .comparador_visual import ResultadoVisual
from .comparador_color import ResultadoColor

logger = logging.getLogger("inpi.scoring")


@dataclass
class ResultadoFinal:
    """Resultado consolidado de todas las comparaciones."""
    marca_vigilada: str
    marca_detectada: str
    pagina: int
    archivo_pdf: str
    score_final: float
    nivel_riesgo: str  # alto, medio, bajo
    scores: dict       # {texto, fonetico, visual, color}
    tipo_match_principal: str
    explicacion_completa: str
    recomendacion: str
    clase_niza_detectada: list[int]
    clase_niza_coincide: bool
    tipo_marca: str
    prioridad_marca: str
    factores_a_favor: list[str]
    factores_en_contra: list[str]


class MotorScoring:
    def __init__(self, settings: dict):
        cfg = settings.get("scoring", {})
        self.pesos = cfg.get("pesos", {
            "texto": 0.35, "fonetica": 0.25,
            "visual": 0.25, "color": 0.15
        })
        self.umbral_alerta = cfg.get("umbral_alerta", 0.55)
        self.niveles = cfg.get("niveles", {"alto": 0.75, "medio": 0.55, "bajo": 0.40})

    def calcular(self, marca_vigilada: dict, marca_detectada: str,
                 pagina: int, archivo_pdf: str,
                 resultado_texto: ResultadoTexto,
                 resultado_fonetico: ResultadoFonetico,
                 resultado_visual: ResultadoVisual,
                 resultado_color: ResultadoColor,
                 clase_detectada: list[int] = None,
                 tipo_marca: str = "denominativa") -> ResultadoFinal:
        """Calcula el score final combinado."""

        nombre_vigilada = marca_vigilada.get("nombre", "")
        clases_vigiladas = marca_vigilada.get("clases_niza", [])
        prioridad = marca_vigilada.get("prioridad", "normal")

        scores = {
            "texto": resultado_texto.score,
            "fonetico": resultado_fonetico.score,
            "visual": resultado_visual.score,
            "color": resultado_color.score,
        }

        # Redistribuir pesos dinamicamente cuando no hay datos visuales.
        # Si visual y color son 0 (no habia imagenes), su peso se redistribuye
        # proporcionalmente entre texto y fonetica para no penalizar injustamente.
        peso_texto = self.pesos.get("texto", 0.35)
        peso_fonetica = self.pesos.get("fonetica", 0.25)
        peso_visual = self.pesos.get("visual", 0.25)
        peso_color = self.pesos.get("color", 0.15)

        tiene_visual = scores["visual"] > 0 or scores["color"] > 0
        if not tiene_visual:
            # Sin imagenes: redistribuir peso visual+color a texto+fonetica
            peso_extra = peso_visual + peso_color
            total_tf = peso_texto + peso_fonetica
            if total_tf > 0:
                peso_texto += peso_extra * (peso_texto / total_tf)
                peso_fonetica += peso_extra * (peso_fonetica / total_tf)
            peso_visual = 0
            peso_color = 0

        score_base = (
            scores["texto"] * peso_texto +
            scores["fonetico"] * peso_fonetica +
            scores["visual"] * peso_visual +
            scores["color"] * peso_color
        )

        # Bonus/penalizacion por clase Niza
        clase_coincide = False
        if clase_detectada and clases_vigiladas:
            clase_coincide = bool(set(clase_detectada) & set(clases_vigiladas))
            if clase_coincide:
                score_base = min(1.0, score_base * 1.15)  # +15% si misma clase

        # Ajuste por tipo de marca
        if tipo_marca == "mixta" and scores["visual"] > 0.3:
            score_base = min(1.0, score_base * 1.05)  # Mas peso a visual en mixtas
        elif tipo_marca == "figurativa" and scores["visual"] > 0.4:
            score_base = min(1.0, score_base * 1.10)  # Aun mas en figurativas

        # Ajuste por prioridad de marca vigilada
        if prioridad == "alta":
            score_base = min(1.0, score_base * 1.05)

        score_final = round(score_base, 4)

        # Nivel de riesgo
        nivel = self._determinar_nivel(score_final)

        # Tipo de match principal
        tipo_principal = max(scores, key=scores.get)

        # Factores a favor y en contra
        a_favor, en_contra = self._analizar_factores(
            scores, clase_coincide, tipo_marca, resultado_texto,
            resultado_fonetico, resultado_visual
        )

        # Explicacion completa
        explicacion = self._generar_explicacion(
            nombre_vigilada, marca_detectada, scores, score_final,
            nivel, tipo_principal, clase_coincide, tipo_marca,
            resultado_texto, resultado_fonetico
        )

        # Recomendacion
        recomendacion = self._generar_recomendacion(
            score_final, nivel, clase_coincide, tipo_marca, prioridad
        )

        return ResultadoFinal(
            marca_vigilada=nombre_vigilada,
            marca_detectada=marca_detectada,
            pagina=pagina,
            archivo_pdf=archivo_pdf,
            score_final=score_final,
            nivel_riesgo=nivel,
            scores=scores,
            tipo_match_principal=tipo_principal,
            explicacion_completa=explicacion,
            recomendacion=recomendacion,
            clase_niza_detectada=clase_detectada or [],
            clase_niza_coincide=clase_coincide,
            tipo_marca=tipo_marca,
            prioridad_marca=prioridad,
            factores_a_favor=a_favor,
            factores_en_contra=en_contra,
        )

    def supera_umbral(self, resultado: ResultadoFinal) -> bool:
        """Verifica si el resultado supera el umbral de alerta."""
        return resultado.score_final >= self.umbral_alerta

    def _determinar_nivel(self, score: float) -> str:
        if score >= self.niveles.get("alto", 0.75):
            return "alto"
        elif score >= self.niveles.get("medio", 0.55):
            return "medio"
        elif score >= self.niveles.get("bajo", 0.40):
            return "bajo"
        return "minimo"

    def _analizar_factores(self, scores, clase_coincide, tipo_marca,
                           res_texto, res_fonetico, res_visual):
        """Determina factores a favor y en contra del conflicto."""
        a_favor = []
        en_contra = []

        if scores["texto"] >= 0.7:
            a_favor.append(f"Alta similitud denominativa ({scores['texto']:.0%})")
        elif scores["texto"] < 0.3:
            en_contra.append("Baja similitud denominativa")

        if scores["fonetico"] >= 0.7:
            a_favor.append(f"Secuencia sonora compartida ({scores['fonetico']:.0%})")
        elif scores["fonetico"] < 0.3:
            en_contra.append("Sonoridad diferente")

        if scores["visual"] >= 0.5:
            a_favor.append(f"Similitud visual significativa ({scores['visual']:.0%})")

        if scores["color"] >= 0.5:
            a_favor.append("Paleta cromatica cercana")
        elif scores["color"] < 0.2:
            en_contra.append("Colores distintos")

        if clase_coincide:
            a_favor.append("Misma clase Niza (mayor riesgo de confusion)")
        else:
            en_contra.append("Clases Niza diferentes")

        if tipo_marca == "denominativa" and scores["texto"] < 0.5:
            en_contra.append("Marca denominativa con baja similitud textual")

        if res_texto.distancia_edit <= 2:
            a_favor.append(f"Solo {res_texto.distancia_edit} cambio(s) de caracteres")

        return a_favor, en_contra

    def _generar_explicacion(self, vigilada, detectada, scores, final,
                              nivel, tipo_principal, clase_coincide, tipo_marca,
                              res_texto, res_fonetico):
        """Genera una explicacion completa y legible."""
        partes = [
            f"Se detecto '{detectada}' con similitud a la marca vigilada '{vigilada}'.",
            f"Score global: {final:.0%} (nivel {nivel}).",
        ]

        # Detalles por dimension
        detalles = []
        if scores["texto"] > 0.3:
            detalles.append(f"Texto: {scores['texto']:.0%} ({res_texto.tipo_match})")
        if scores["fonetico"] > 0.3:
            detalles.append(f"Fonetica: {scores['fonetico']:.0%} ({res_fonetico.metodo})")
        if scores["visual"] > 0.2:
            detalles.append(f"Visual: {scores['visual']:.0%}")
        if scores["color"] > 0.2:
            detalles.append(f"Color: {scores['color']:.0%}")

        if detalles:
            partes.append("Detalle: " + " | ".join(detalles) + ".")

        if clase_coincide:
            partes.append("Las clases Niza coinciden, lo que incrementa el riesgo de confusion.")

        partes.append(f"Tipo de marca: {tipo_marca}. Match principal por: {tipo_principal}.")

        return " ".join(partes)

    def _generar_recomendacion(self, score, nivel, clase_coincide,
                                tipo_marca, prioridad):
        """Genera recomendacion operativa."""
        if nivel == "alto":
            if clase_coincide:
                return "REVISAR URGENTE. Alta similitud en misma clase. Posible conflicto marcario serio."
            return "REVISAR CON PRIORIDAD. Alta similitud detectada."
        elif nivel == "medio":
            if clase_coincide:
                return "Revision recomendada. Similitud media en clase coincidente."
            return "Revision normal. Similitud media, verificar contexto."
        elif nivel == "bajo":
            return "Revision opcional. Similitud baja, probablemente sin conflicto."
        else:
            return "Archivar salvo criterio comercial especifico."
