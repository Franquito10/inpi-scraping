"""
Capa de analisis juridico asistido por IA.

Genera una evaluacion preliminar de riesgo de confusion
marcaria usando un LLM (OpenAI/Anthropic).

DISCLAIMER: No es dictamen juridico. Es asistencia automatizada.
"""

import os
import json
import logging
from dataclasses import dataclass, field
from typing import Optional

from .scoring import ResultadoFinal

logger = logging.getLogger("inpi.ia_legal")

PROMPT_SISTEMA = """Sos un asistente especializado en derecho de marcas argentino.
Tu rol es dar una opinion preliminar automatizada sobre posibles conflictos marcarios.

REGLAS ESTRICTAS:
- NO inventar datos. Solo analizar lo que se te proporciona.
- NO dar certezas juridicas. Usar siempre lenguaje preliminar.
- Responder SIEMPRE en formato JSON estructurado.
- Evaluar similitud denominativa, fonetica, conceptual y visual segun los datos.
- Considerar el sistema de clasificacion de Niza.
- Ser preciso y conciso.
- Si no hay suficiente evidencia, decirlo.

Tu respuesta debe ser un JSON con esta estructura exacta:
{
  "similitud_denominativa": "alta|media|baja",
  "similitud_fonetica": "alta|media|baja",
  "similitud_conceptual": "alta|media|baja|no_aplica",
  "riesgo_confusion": "alto|medio|bajo",
  "argumentos_a_favor": ["..."],
  "argumentos_en_contra": ["..."],
  "recomendacion": "revisar_urgente|revision_humana|probablemente_falso_positivo|archivar",
  "resumen": "..."
}"""

PROMPT_ANALISIS = """Analiza el siguiente caso de posible conflicto marcario:

MARCA VIGILADA: {marca_vigilada}
MARCA DETECTADA: {marca_detectada}
TIPO DE MARCA DETECTADA: {tipo_marca}

SCORES TECNICOS:
- Similitud textual: {score_texto:.0%}
- Similitud fonetica: {score_fonetico:.0%}
- Similitud visual: {score_visual:.0%}
- Similitud cromatica: {score_color:.0%}
- Score global: {score_final:.0%}

CLASE NIZA VIGILADA: {clases_vigiladas}
CLASE NIZA DETECTADA: {clases_detectadas}
COINCIDENCIA DE CLASE: {clase_coincide}

CONTEXTO ADICIONAL:
- Tipo de match principal: {tipo_match}
- Distancia de edicion: {distancia_edit}
- Pagina del boletin: {pagina}
- Archivo: {archivo}

Da tu evaluacion preliminar en formato JSON."""


@dataclass
class AnalisisIA:
    """Resultado del analisis IA legal."""
    similitud_denominativa: str = ""
    similitud_fonetica: str = ""
    similitud_conceptual: str = ""
    riesgo_confusion: str = ""
    argumentos_a_favor: list[str] = field(default_factory=list)
    argumentos_en_contra: list[str] = field(default_factory=list)
    recomendacion: str = ""
    resumen: str = ""
    error: str = ""
    disclaimer: str = "Esta es una opinion asistida por IA. No constituye dictamen juridico definitivo."


class AnalizadorIA:
    def __init__(self, settings: dict):
        cfg = settings.get("ia_legal", {})
        self.habilitado = cfg.get("habilitado", False)
        self.proveedor = cfg.get("proveedor", "openai")
        self.modelo = cfg.get("modelo", "gpt-4o-mini")
        self.api_key_env = cfg.get("api_key_env", "OPENAI_API_KEY")
        self.max_tokens = cfg.get("max_tokens", 1000)
        self.temperatura = cfg.get("temperatura", 0.2)
        self._cliente = None

    def _inicializar_cliente(self):
        """Inicializa el cliente de IA."""
        api_key = os.environ.get(self.api_key_env)
        if not api_key:
            raise ValueError(
                f"API key no encontrada. Configurar variable de entorno: {self.api_key_env}"
            )

        if self.proveedor == "openai":
            try:
                from openai import OpenAI
                self._cliente = OpenAI(api_key=api_key)
            except ImportError:
                raise ImportError("Instalar openai: pip install openai")
        elif self.proveedor == "anthropic":
            try:
                import anthropic
                self._cliente = anthropic.Anthropic(api_key=api_key)
            except ImportError:
                raise ImportError("Instalar anthropic: pip install anthropic")

    def analizar(self, resultado: ResultadoFinal,
                 marca_config: dict) -> AnalisisIA:
        """Analiza un resultado con IA."""
        if not self.habilitado:
            return AnalisisIA(error="Analisis IA no habilitado en configuracion")

        try:
            if not self._cliente:
                self._inicializar_cliente()

            prompt = PROMPT_ANALISIS.format(
                marca_vigilada=resultado.marca_vigilada,
                marca_detectada=resultado.marca_detectada,
                tipo_marca=resultado.tipo_marca,
                score_texto=resultado.scores.get("texto", 0),
                score_fonetico=resultado.scores.get("fonetico", 0),
                score_visual=resultado.scores.get("visual", 0),
                score_color=resultado.scores.get("color", 0),
                score_final=resultado.score_final,
                clases_vigiladas=marca_config.get("clases_niza", []),
                clases_detectadas=resultado.clase_niza_detectada,
                clase_coincide="Si" if resultado.clase_niza_coincide else "No",
                tipo_match=resultado.tipo_match_principal,
                distancia_edit="N/A",
                pagina=resultado.pagina,
                archivo=resultado.archivo_pdf,
            )

            respuesta = self._llamar_ia(prompt)
            return self._parsear_respuesta(respuesta)

        except Exception as e:
            logger.error(f"Error en analisis IA: {e}")
            return AnalisisIA(error=str(e))

    def _llamar_ia(self, prompt: str) -> str:
        """Realiza la llamada al modelo de IA."""
        if self.proveedor == "openai":
            resp = self._cliente.chat.completions.create(
                model=self.modelo,
                messages=[
                    {"role": "system", "content": PROMPT_SISTEMA},
                    {"role": "user", "content": prompt},
                ],
                max_tokens=self.max_tokens,
                temperature=self.temperatura,
            )
            return resp.choices[0].message.content

        elif self.proveedor == "anthropic":
            resp = self._cliente.messages.create(
                model=self.modelo,
                system=PROMPT_SISTEMA,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=self.max_tokens,
                temperature=self.temperatura,
            )
            return resp.content[0].text

        return ""

    def _parsear_respuesta(self, respuesta: str) -> AnalisisIA:
        """Parsea la respuesta JSON del modelo."""
        try:
            # Limpiar posibles marcadores de codigo
            texto = respuesta.strip()
            if texto.startswith("```"):
                texto = texto.split("\n", 1)[1]
            if texto.endswith("```"):
                texto = texto.rsplit("```", 1)[0]
            texto = texto.strip()

            data = json.loads(texto)
            return AnalisisIA(
                similitud_denominativa=data.get("similitud_denominativa", ""),
                similitud_fonetica=data.get("similitud_fonetica", ""),
                similitud_conceptual=data.get("similitud_conceptual", ""),
                riesgo_confusion=data.get("riesgo_confusion", ""),
                argumentos_a_favor=data.get("argumentos_a_favor", []),
                argumentos_en_contra=data.get("argumentos_en_contra", []),
                recomendacion=data.get("recomendacion", ""),
                resumen=data.get("resumen", ""),
            )
        except (json.JSONDecodeError, KeyError) as e:
            logger.warning(f"Error parseando respuesta IA: {e}")
            return AnalisisIA(
                resumen=respuesta[:500],
                error=f"Respuesta no estructurada: {e}"
            )
