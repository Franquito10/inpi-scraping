"""
Capa de analisis juridico preliminar asistido por IA.

Etapa POST-scoring del pipeline. Recibe coincidencias ya detectadas
y genera una evaluacion juridica estructurada, persistente y auditable.

Arquitectura:
- Proveedor de LLM desacoplado por interfaz (OpenAI, Anthropic, local)
- Prompt contextualizado con datos tecnicos + feedback humano historico
- Salida JSON estructurada con validacion estricta
- Persistencia en tabla analisis_ia (regenerable por caso)
- Degradacion elegante si no hay LLM configurado

DISCLAIMER: No es dictamen juridico. Es asistencia automatizada.
"""

import os
import json
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Optional

logger = logging.getLogger("inpi.ia_legal")


# ============================================================
# Modelo de datos
# ============================================================

@dataclass
class AnalisisIALegal:
    """Resultado estructurado del analisis IA legal."""
    id_coincidencia: int = 0
    # Evaluacion principal
    riesgo_preliminar: str = ""           # alto | medio | bajo
    confundibilidad_preliminar: str = ""  # alta | media | baja
    # Evaluacion por dimension
    similitud_denominativa: str = ""      # alta | media | baja
    similitud_fonetica: str = ""          # alta | media | baja
    similitud_conceptual: str = ""        # alta | media | baja | no_aplica
    similitud_visual: str = ""            # alta | media | baja | no_aplica
    # Argumentacion
    argumentos_a_favor: list[str] = field(default_factory=list)
    argumentos_en_contra: list[str] = field(default_factory=list)
    # Operativa
    recomendacion_operativa: str = ""     # revisar_urgente | revisar | probablemente_falso_positivo | archivar
    resumen_ejecutivo: str = ""
    # Metadata
    modelo_usado: str = ""
    proveedor: str = ""
    fecha_analisis: str = ""
    version_prompt: str = "2.0"
    tokens_usados: int = 0
    feedback_incorporado: bool = False
    # Estado
    error: str = ""
    disclaimer: str = (
        "Opinion preliminar asistida por IA. No constituye dictamen "
        "juridico definitivo. Requiere revision profesional."
    )

    def es_valido(self) -> bool:
        """Verifica que el analisis tenga los campos minimos."""
        return bool(
            self.riesgo_preliminar
            and self.confundibilidad_preliminar
            and self.recomendacion_operativa
            and self.resumen_ejecutivo
            and not self.error
        )

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "AnalisisIALegal":
        campos_validos = {f.name for f in cls.__dataclass_fields__.values()}
        filtrado = {k: v for k, v in data.items() if k in campos_validos}
        return cls(**filtrado)


# ============================================================
# Interfaz de proveedor LLM
# ============================================================

class ProveedorLLM(ABC):
    """Interfaz abstracta para proveedores de LLM."""

    @abstractmethod
    def llamar(self, sistema: str, usuario: str, max_tokens: int,
               temperatura: float) -> tuple[str, int]:
        """Llama al LLM. Retorna (respuesta_texto, tokens_usados)."""
        ...

    @abstractmethod
    def nombre(self) -> str:
        ...


class ProveedorOpenAI(ProveedorLLM):
    def __init__(self, modelo: str, api_key: str, base_url: str = ""):
        from openai import OpenAI
        kwargs = {"api_key": api_key}
        if base_url:
            kwargs["base_url"] = base_url
        self._cliente = OpenAI(**kwargs)
        self._modelo = modelo

    def llamar(self, sistema: str, usuario: str, max_tokens: int,
               temperatura: float) -> tuple[str, int]:
        resp = self._cliente.chat.completions.create(
            model=self._modelo,
            messages=[
                {"role": "system", "content": sistema},
                {"role": "user", "content": usuario},
            ],
            max_tokens=max_tokens,
            temperature=temperatura,
            response_format={"type": "json_object"},
        )
        tokens = resp.usage.total_tokens if resp.usage else 0
        return resp.choices[0].message.content, tokens

    def nombre(self) -> str:
        return f"openai/{self._modelo}"


class ProveedorAnthropic(ProveedorLLM):
    def __init__(self, modelo: str, api_key: str):
        import anthropic
        self._cliente = anthropic.Anthropic(api_key=api_key)
        self._modelo = modelo

    def llamar(self, sistema: str, usuario: str, max_tokens: int,
               temperatura: float) -> tuple[str, int]:
        resp = self._cliente.messages.create(
            model=self._modelo,
            system=sistema,
            messages=[{"role": "user", "content": usuario}],
            max_tokens=max_tokens,
            temperature=temperatura,
        )
        tokens = (resp.usage.input_tokens + resp.usage.output_tokens) if resp.usage else 0
        return resp.content[0].text, tokens

    def nombre(self) -> str:
        return f"anthropic/{self._modelo}"


class ProveedorLocal(ProveedorLLM):
    """Proveedor para modelos locales compatibles con API OpenAI (Ollama, LM Studio, etc)."""
    def __init__(self, modelo: str, base_url: str):
        from openai import OpenAI
        self._cliente = OpenAI(api_key="local", base_url=base_url)
        self._modelo = modelo

    def llamar(self, sistema: str, usuario: str, max_tokens: int,
               temperatura: float) -> tuple[str, int]:
        resp = self._cliente.chat.completions.create(
            model=self._modelo,
            messages=[
                {"role": "system", "content": sistema},
                {"role": "user", "content": usuario},
            ],
            max_tokens=max_tokens,
            temperature=temperatura,
        )
        tokens = resp.usage.total_tokens if resp.usage else 0
        return resp.choices[0].message.content, tokens

    def nombre(self) -> str:
        return f"local/{self._modelo}"


# ============================================================
# Prompts
# ============================================================

PROMPT_SISTEMA_V2 = """Sos un asistente especializado en derecho de marcas argentino (Ley 22.362).
Tu rol es emitir una opinion preliminar automatizada sobre posibles conflictos marcarios,
basandote exclusivamente en los datos que se te proporcionan.

REGLAS ESTRICTAS:
1. NO inventar datos, hechos ni antecedentes que no esten en el caso.
2. Usar SIEMPRE lenguaje preliminar: "podria", "sugiere", "preliminarmente".
3. Responder SIEMPRE en JSON valido con la estructura exacta indicada.
4. Evaluar similitud denominativa, fonetica, conceptual y visual segun los scores tecnicos.
5. Considerar la clasificacion de Niza: misma clase = mayor riesgo.
6. Para marcas denominativas, priorizar analisis textual y fonetico.
7. Para marcas mixtas/figurativas, dar mas peso al componente visual.
8. Considerar que marcas de fantasia (inventadas) tienen mayor proteccion.
9. Si hay historial de feedback humano, ajustar tu criterio en consecuencia.
10. Ser conciso y profesional. Maximo 2-3 lineas por argumento.
11. La recomendacion debe ser accionable y clara.
12. Si la evidencia es ambigua o insuficiente, decirlo explicitamente.

FORMATO DE RESPUESTA (JSON estricto):
{
  "riesgo_preliminar": "alto|medio|bajo",
  "confundibilidad_preliminar": "alta|media|baja",
  "similitud_denominativa": "alta|media|baja",
  "similitud_fonetica": "alta|media|baja",
  "similitud_conceptual": "alta|media|baja|no_aplica",
  "similitud_visual": "alta|media|baja|no_aplica",
  "argumentos_a_favor": ["argumento 1", "argumento 2"],
  "argumentos_en_contra": ["argumento 1", "argumento 2"],
  "recomendacion_operativa": "revisar_urgente|revisar|probablemente_falso_positivo|archivar",
  "resumen_ejecutivo": "Resumen de 2-3 oraciones sobre el caso."
}"""


PROMPT_CASO = """CASO DE ANALISIS MARCARIO
========================

MARCA VIGILADA: {marca_vigilada}
  - Variantes registradas: {variantes}
  - Clases Niza vigiladas: {clases_vigiladas}
  - Prioridad: {prioridad}

MARCA DETECTADA: {marca_detectada}
  - Tipo de marca: {tipo_marca}
  - Clase Niza detectada: {clases_detectadas}
  - Solicitante: {solicitante}
  - Acta: {acta}
  - Coincidencia de clase Niza: {clase_coincide}

SCORES TECNICOS (0% a 100%):
  - Similitud textual:    {score_texto}
  - Similitud fonetica:   {score_fonetico}
  - Similitud visual:     {score_visual}
  - Similitud cromatica:  {score_color}
  - Score global:         {score_final}
  - Nivel de riesgo tecnico: {nivel_riesgo}
  - Tipo de match principal: {tipo_match}

EXPLICACION TECNICA:
{explicacion_tecnica}

UBICACION:
  - Boletin: {boletin}
  - Pagina: {pagina}

{seccion_feedback}

Emiti tu evaluacion preliminar en formato JSON."""


SECCION_FEEDBACK = """HISTORIAL DE FEEDBACK HUMANO (para ajustar tu criterio):
{feedback_items}

INSTRUCCIONES SOBRE EL FEEDBACK:
- Si hay falsos positivos previos para este par, se mas conservador.
- Si hay confirmaciones de conflicto previas para patrones similares, se mas estricto.
- Si hay exclusiones manuales, respeta esas decisiones.
- Usa este historial para calibrar tu nivel de alarma."""


ITEM_FEEDBACK = """  - [{fecha}] Par "{marca_vig}" vs "{marca_det}": decision="{decision}", estado="{estado}"
    Comentario: {comentario}"""


# ============================================================
# Motor de analisis
# ============================================================

class AnalizadorIALegal:
    """Motor de analisis juridico asistido por IA."""

    def __init__(self, settings: dict):
        cfg = settings.get("ia_legal", {})
        self.habilitado = cfg.get("habilitado", False)
        self.proveedor_nombre = cfg.get("proveedor", "openai")
        self.modelo = cfg.get("modelo", "gpt-4o-mini")
        self.api_key_env = cfg.get("api_key_env", "OPENAI_API_KEY")
        self.base_url = cfg.get("base_url", "")
        self.max_tokens = cfg.get("max_tokens", 1500)
        self.temperatura = cfg.get("temperatura", 0.2)
        self.max_feedback_items = cfg.get("max_feedback_items", 10)
        self._proveedor: Optional[ProveedorLLM] = None

    def _crear_proveedor(self) -> ProveedorLLM:
        """Crea el proveedor de LLM segun configuracion."""
        api_key = os.environ.get(self.api_key_env, "")

        if self.proveedor_nombre == "openai":
            if not api_key:
                raise ValueError(f"Variable de entorno {self.api_key_env} no configurada")
            return ProveedorOpenAI(self.modelo, api_key, self.base_url)

        elif self.proveedor_nombre == "anthropic":
            if not api_key:
                raise ValueError(f"Variable de entorno {self.api_key_env} no configurada")
            return ProveedorAnthropic(self.modelo, api_key)

        elif self.proveedor_nombre == "local":
            base = self.base_url or "http://localhost:11434/v1"
            return ProveedorLocal(self.modelo, base)

        else:
            raise ValueError(f"Proveedor desconocido: {self.proveedor_nombre}")

    def analizar_coincidencia(self, coincidencia: dict, marca_config: dict,
                               feedback_historico: list[dict] = None) -> AnalisisIALegal:
        """
        Analiza una coincidencia individual.
        Recibe la coincidencia (dict de DB), config de la marca, y feedback previo.
        """
        if not self.habilitado:
            return AnalisisIALegal(
                id_coincidencia=coincidencia.get("id", 0),
                error="Analisis IA no habilitado. Activar en config/settings.yaml"
            )

        try:
            if not self._proveedor:
                self._proveedor = self._crear_proveedor()

            prompt_usuario = self._construir_prompt(
                coincidencia, marca_config, feedback_historico
            )

            texto_resp, tokens = self._proveedor.llamar(
                sistema=PROMPT_SISTEMA_V2,
                usuario=prompt_usuario,
                max_tokens=self.max_tokens,
                temperatura=self.temperatura,
            )

            resultado = self._parsear_respuesta(texto_resp)
            resultado.id_coincidencia = coincidencia.get("id", 0)
            resultado.modelo_usado = self.modelo
            resultado.proveedor = self._proveedor.nombre()
            resultado.fecha_analisis = datetime.now().isoformat()
            resultado.tokens_usados = tokens
            resultado.feedback_incorporado = bool(feedback_historico)

            if not resultado.es_valido():
                logger.warning(
                    f"Analisis IA incompleto para coincidencia {resultado.id_coincidencia}"
                )

            return resultado

        except ImportError as e:
            logger.error(f"Libreria faltante para proveedor IA: {e}")
            return AnalisisIALegal(
                id_coincidencia=coincidencia.get("id", 0),
                error=f"Libreria no instalada: {e}"
            )
        except Exception as e:
            logger.error(f"Error en analisis IA: {e}")
            return AnalisisIALegal(
                id_coincidencia=coincidencia.get("id", 0),
                error=str(e)
            )

    def analizar_lote(self, coincidencias: list[dict], marcas_config: list[dict],
                       db) -> list[AnalisisIALegal]:
        """Analiza un lote de coincidencias. Usado en el pipeline."""
        if not self.habilitado:
            logger.info("Analisis IA deshabilitado, saltando lote")
            return []

        resultados = []
        marcas_por_nombre = {m["nombre"]: m for m in marcas_config}

        for coinc in coincidencias:
            marca_nombre = coinc.get("marca_vigilada", "")
            marca_cfg = marcas_por_nombre.get(marca_nombre, {})

            # Obtener feedback historico para este par
            feedback = db.obtener_feedback_para_par(
                marca_vigilada=marca_nombre,
                marca_detectada=coinc.get("marca_detectada", ""),
                limite=self.max_feedback_items,
            )

            # Verificar si ya tiene analisis (no regenerar si existe)
            existente = db.obtener_analisis_ia(coinc["id"])
            if existente and not existente.get("error"):
                logger.debug(f"Analisis IA ya existe para coincidencia {coinc['id']}, saltando")
                continue

            resultado = self.analizar_coincidencia(coinc, marca_cfg, feedback)
            if resultado.id_coincidencia:
                db.guardar_analisis_ia(resultado)
                resultados.append(resultado)

            logger.info(
                f"Analisis IA #{coinc['id']}: {resultado.recomendacion_operativa} "
                f"(riesgo={resultado.riesgo_preliminar})"
            )

        return resultados

    def regenerar_analisis(self, id_coincidencia: int, coincidencia: dict,
                            marca_config: dict, db) -> AnalisisIALegal:
        """Regenera el analisis IA para una coincidencia especifica."""
        feedback = db.obtener_feedback_para_par(
            marca_vigilada=coincidencia.get("marca_vigilada", ""),
            marca_detectada=coincidencia.get("marca_detectada", ""),
            limite=self.max_feedback_items,
        )

        resultado = self.analizar_coincidencia(coincidencia, marca_config, feedback)
        if resultado.id_coincidencia:
            db.guardar_analisis_ia(resultado)

        return resultado

    def _construir_prompt(self, coincidencia: dict, marca_config: dict,
                           feedback: list[dict] = None) -> str:
        """Construye el prompt contextualizado con datos del caso y feedback."""

        # Seccion de feedback historico
        seccion_fb = ""
        if feedback:
            items = []
            for fb in feedback:
                items.append(ITEM_FEEDBACK.format(
                    fecha=fb.get("fecha_revision", "?"),
                    marca_vig=fb.get("marca_vigilada", "?"),
                    marca_det=fb.get("marca_detectada", "?"),
                    decision=fb.get("decision", "sin decision"),
                    estado=fb.get("estado", "?"),
                    comentario=fb.get("comentario", "sin comentario")[:200],
                ))
            seccion_fb = SECCION_FEEDBACK.format(feedback_items="\n".join(items))

        # Formatear scores como porcentaje
        def pct(val):
            try:
                return f"{float(val) * 100:.0f}%"
            except (TypeError, ValueError):
                return "N/A"

        return PROMPT_CASO.format(
            marca_vigilada=marca_config.get("nombre", coincidencia.get("marca_vigilada", "")),
            variantes=", ".join(marca_config.get("variantes", [])),
            clases_vigiladas=marca_config.get("clases_niza", []),
            prioridad=marca_config.get("prioridad", "normal"),
            marca_detectada=coincidencia.get("marca_detectada", ""),
            tipo_marca=coincidencia.get("tipo_marca", "denominativa"),
            clases_detectadas=coincidencia.get("clase_niza", ""),
            solicitante=coincidencia.get("solicitante", "No disponible"),
            acta=coincidencia.get("acta_numero", "No disponible"),
            clase_coincide="Si" if self._clases_coinciden(
                marca_config.get("clases_niza", []),
                coincidencia.get("clase_niza", "")
            ) else "No",
            score_texto=pct(coincidencia.get("score_texto", 0)),
            score_fonetico=pct(coincidencia.get("score_fonetico", 0)),
            score_visual=pct(coincidencia.get("score_visual", 0)),
            score_color=pct(coincidencia.get("score_color", 0)),
            score_final=pct(coincidencia.get("score_final", 0)),
            nivel_riesgo=coincidencia.get("nivel_riesgo", ""),
            tipo_match=coincidencia.get("tipo_match", ""),
            explicacion_tecnica=coincidencia.get("explicacion", "No disponible"),
            boletin=coincidencia.get("id_boletin", ""),
            pagina=coincidencia.get("pagina", ""),
            seccion_feedback=seccion_fb,
        )

    def _clases_coinciden(self, clases_vigiladas: list, clases_detectadas) -> bool:
        """Verifica si hay interseccion de clases Niza."""
        try:
            if isinstance(clases_detectadas, str):
                import re
                nums = [int(x) for x in re.findall(r'\d+', clases_detectadas)]
            else:
                nums = list(clases_detectadas or [])
            return bool(set(clases_vigiladas) & set(nums))
        except Exception:
            return False

    def _parsear_respuesta(self, texto: str) -> AnalisisIALegal:
        """Parsea y valida la respuesta JSON del LLM."""
        try:
            limpio = texto.strip()
            # Quitar markdown code blocks si vienen
            if limpio.startswith("```"):
                limpio = limpio.split("\n", 1)[1] if "\n" in limpio else limpio[3:]
            if limpio.endswith("```"):
                limpio = limpio.rsplit("```", 1)[0]
            limpio = limpio.strip()

            data = json.loads(limpio)

            # Validar valores permitidos
            valores_riesgo = {"alto", "medio", "bajo"}
            valores_confund = {"alta", "media", "baja"}
            valores_similitud = {"alta", "media", "baja", "no_aplica"}
            valores_recom = {"revisar_urgente", "revisar", "probablemente_falso_positivo", "archivar"}

            riesgo = data.get("riesgo_preliminar", "").lower()
            if riesgo not in valores_riesgo:
                riesgo = "medio"  # default seguro

            confund = data.get("confundibilidad_preliminar", "").lower()
            if confund not in valores_confund:
                confund = "media"

            recom = data.get("recomendacion_operativa", "").lower()
            if recom not in valores_recom:
                recom = "revisar"

            return AnalisisIALegal(
                riesgo_preliminar=riesgo,
                confundibilidad_preliminar=confund,
                similitud_denominativa=self._validar_nivel(data.get("similitud_denominativa"), valores_similitud),
                similitud_fonetica=self._validar_nivel(data.get("similitud_fonetica"), valores_similitud),
                similitud_conceptual=self._validar_nivel(data.get("similitud_conceptual"), valores_similitud),
                similitud_visual=self._validar_nivel(data.get("similitud_visual"), valores_similitud),
                argumentos_a_favor=self._validar_lista(data.get("argumentos_a_favor")),
                argumentos_en_contra=self._validar_lista(data.get("argumentos_en_contra")),
                recomendacion_operativa=recom,
                resumen_ejecutivo=str(data.get("resumen_ejecutivo", ""))[:1000],
            )

        except json.JSONDecodeError as e:
            logger.warning(f"Respuesta IA no es JSON valido: {e}")
            return AnalisisIALegal(
                resumen_ejecutivo=texto[:500] if texto else "",
                error=f"Respuesta no estructurada del LLM: {e}",
            )

    def _validar_nivel(self, valor, permitidos: set) -> str:
        if not valor:
            return ""
        v = str(valor).lower()
        return v if v in permitidos else ""

    def _validar_lista(self, valor) -> list[str]:
        if not valor or not isinstance(valor, list):
            return []
        return [str(x)[:300] for x in valor[:10]]
