"""
Comparacion fonetica para denominaciones marcarias.

Implementa un algoritmo fonetico adaptado al espanol rioplatense
y a nombres de fantasia / marcas inventadas.

Reglas principales:
- H muda
- B/V equivalentes
- C/S/Z equivalentes (seseo)
- LL/Y equivalentes (yeismo)
- G/J antes de E,I equivalentes
- QU -> K
- GU antes de E,I -> G
- Ñ -> NI
- W -> U/GU segun contexto
- Dobles consonantes -> simples
- PH -> F
- TH -> T
"""

import re
import logging
from dataclasses import dataclass

import jellyfish

from .utils import normalizar_texto

logger = logging.getLogger("inpi.fonetico")


@dataclass
class ResultadoFonetico:
    """Resultado de comparacion fonetica."""
    score: float
    codigo_detectado: str
    codigo_referencia: str
    detalle: str
    metodo: str


class ComparadorFonetico:
    def __init__(self, settings: dict):
        cfg = settings.get("fonetica", {})
        self.umbral = cfg.get("umbral", 0.60)
        self.algoritmo = cfg.get("algoritmo", "hibrido")
        self.penalizar_longitud = cfg.get("penalizar_longitud_diferente", True)
        self.max_dif_longitud = cfg.get("max_diferencia_longitud", 3)

    def comparar(self, texto_detectado: str, marca_ref: str,
                 variantes: list[str] = None) -> ResultadoFonetico:
        """Compara foneticamente contra marca y variantes."""
        candidatos = [marca_ref] + (variantes or [])
        mejor = ResultadoFonetico(
            score=0, codigo_detectado="", codigo_referencia="",
            detalle="Sin similitud fonetica", metodo=""
        )

        for candidato in candidatos:
            resultado = self._comparar_par(texto_detectado, candidato)
            if resultado.score > mejor.score:
                mejor = resultado

        return mejor

    def _comparar_par(self, texto: str, referencia: str) -> ResultadoFonetico:
        """Compara un par de textos foneticamente."""
        t1 = normalizar_texto(texto, quitar_acentos=True, minusculas=True)
        t2 = normalizar_texto(referencia, quitar_acentos=True, minusculas=True)

        if not t1 or not t2:
            return ResultadoFonetico(
                score=0, codigo_detectado="", codigo_referencia="",
                detalle="Texto vacio", metodo=""
            )

        if self.algoritmo == "hibrido":
            return self._comparar_hibrido(t1, t2, texto, referencia)
        elif self.algoritmo == "soundex_es":
            return self._comparar_soundex_es(t1, t2, texto, referencia)
        else:
            return self._comparar_metaphone_es(t1, t2, texto, referencia)

    def _comparar_hibrido(self, t1: str, t2: str,
                           orig1: str, orig2: str) -> ResultadoFonetico:
        """
        Metodo hibrido: combina codigo fonetico espanol + Levenshtein fonetico.
        Mas robusto para marcas inventadas.
        """
        # 1. Codigos foneticos espanol
        cod1 = self._codigo_fonetico_es(t1)
        cod2 = self._codigo_fonetico_es(t2)

        # Score por igualdad de codigo fonetico
        if cod1 == cod2 and cod1:
            score_codigo = 1.0
        elif cod1 and cod2:
            # Levenshtein entre codigos
            dist = jellyfish.levenshtein_distance(cod1, cod2)
            max_len = max(len(cod1), len(cod2))
            score_codigo = 1.0 - (dist / max_len) if max_len > 0 else 0
        else:
            score_codigo = 0

        # 2. Levenshtein fonetico (sobre representacion fonetica)
        fon1 = self._representacion_fonetica(t1)
        fon2 = self._representacion_fonetica(t2)
        dist_fon = jellyfish.levenshtein_distance(fon1, fon2)
        max_fon = max(len(fon1), len(fon2))
        score_levenshtein = 1.0 - (dist_fon / max_fon) if max_fon > 0 else 0

        # 3. Comparacion de silabas
        score_silabas = self._comparar_silabas(t1, t2)

        # Score final: maximo de los tres metodos
        score = max(score_codigo * 0.95, score_levenshtein * 0.90, score_silabas * 0.85)

        # Penalizacion por diferencia de longitud
        if self.penalizar_longitud:
            dif = abs(len(t1) - len(t2))
            if dif > self.max_dif_longitud:
                penalizacion = 0.1 * (dif - self.max_dif_longitud)
                score = max(0, score - penalizacion)

        # Determinar metodo dominante
        metodos = {
            "codigo_fonetico": score_codigo,
            "levenshtein_fonetico": score_levenshtein,
            "silabas": score_silabas,
        }
        metodo = max(metodos, key=metodos.get)

        detalle = self._explicar_fonetico(
            orig1, orig2, cod1, cod2, fon1, fon2,
            score_codigo, score_levenshtein, score_silabas, score
        )

        return ResultadoFonetico(
            score=min(score, 1.0),
            codigo_detectado=cod1,
            codigo_referencia=cod2,
            detalle=detalle,
            metodo=metodo,
        )

    def _codigo_fonetico_es(self, texto: str) -> str:
        """
        Genera codigo fonetico adaptado al espanol rioplatense.
        Similar a Soundex pero con reglas del castellano.
        """
        if not texto:
            return ""

        t = texto.lower().strip()

        # Paso 1: Reemplazos de digrafos y equivalencias
        reemplazos_digrafos = [
            ("ph", "f"),
            ("th", "t"),
            ("sh", "s"),
            ("ch", "X"),    # Marcador temporal para CH
            ("ll", "Y"),    # Yeismo
            ("rr", "R"),
            ("qu", "k"),
            ("gu(?=[ei])", "g"),
            ("gü(?=[ei])", "gu"),
            ("ce", "se"),
            ("ci", "si"),
            ("ge", "je"),
            ("gi", "ji"),
        ]

        for patron, reemplazo in reemplazos_digrafos:
            t = re.sub(patron, reemplazo, t)

        # Paso 2: Reemplazos de letras individuales
        reemplazos = {
            "h": "",       # H muda
            "v": "b",      # B/V
            "z": "s",      # Seseo
            "x": "ks",
            "w": "u",
            "ñ": "ni",
            "k": "k",
            "c": "k",      # C antes de A, O, U -> K
            "q": "k",
            "y": "Y",      # Yeismo (igual que LL)
        }

        resultado = []
        for char in t:
            resultado.append(reemplazos.get(char, char))

        codigo = "".join(resultado)

        # Paso 3: Eliminar vocales intermedias (mantener primera)
        if len(codigo) > 1:
            primera = codigo[0]
            resto = re.sub(r"[aeiou]", "", codigo[1:])
            codigo = primera + resto

        # Paso 4: Eliminar consonantes duplicadas
        codigo = re.sub(r"(.)\1+", r"\1", codigo)

        return codigo.upper()[:8]  # Truncar a 8 caracteres

    def _representacion_fonetica(self, texto: str) -> str:
        """
        Genera representacion fonetica simplificada.
        Menos agresiva que el codigo, preserva mas estructura.
        """
        t = texto.lower()

        reemplazos = [
            (r"ph", "f"), (r"th", "t"), (r"sh", "s"),
            (r"ch", "ch"), (r"ll", "y"), (r"rr", "r"),
            (r"qu", "k"), (r"gu(?=[ei])", "g"),
            (r"ce", "se"), (r"ci", "si"),
            (r"ge", "je"), (r"gi", "ji"),
            (r"h", ""), (r"v", "b"), (r"z", "s"),
            (r"ñ", "ni"), (r"k", "c"), (r"w", "u"),
        ]

        for patron, reemplazo in reemplazos:
            t = re.sub(patron, reemplazo, t)

        # Eliminar dobles
        t = re.sub(r"(.)\1", r"\1", t)

        return t

    def _comparar_silabas(self, t1: str, t2: str) -> float:
        """Compara la estructura silabica de dos palabras."""
        sil1 = self._silabificar(t1)
        sil2 = self._silabificar(t2)

        if not sil1 or not sil2:
            return 0

        # Comparar silaba por silaba
        matches = 0
        total = max(len(sil1), len(sil2))

        for i in range(min(len(sil1), len(sil2))):
            s1 = self._representacion_fonetica(sil1[i])
            s2 = self._representacion_fonetica(sil2[i])
            if s1 == s2:
                matches += 1
            elif jellyfish.levenshtein_distance(s1, s2) <= 1:
                matches += 0.5

        return matches / total if total > 0 else 0

    def _silabificar(self, texto: str) -> list[str]:
        """Silabificacion basica del espanol."""
        # Simplificacion: dividir en grupos consonante-vocal
        vocales = set("aeiouáéíóú")
        silabas = []
        silaba_actual = ""

        for i, char in enumerate(texto):
            silaba_actual += char
            if char in vocales:
                # Si la siguiente es consonante seguida de vocal, cortar
                if i + 2 < len(texto):
                    if texto[i + 1] not in vocales and texto[i + 2] in vocales:
                        silabas.append(silaba_actual)
                        silaba_actual = ""
                elif i + 1 == len(texto):
                    silabas.append(silaba_actual)
                    silaba_actual = ""

        if silaba_actual:
            if silabas:
                silabas[-1] += silaba_actual
            else:
                silabas.append(silaba_actual)

        return silabas

    def _comparar_soundex_es(self, t1: str, t2: str,
                              orig1: str, orig2: str) -> ResultadoFonetico:
        """Comparacion solo con Soundex espanol."""
        cod1 = self._codigo_fonetico_es(t1)
        cod2 = self._codigo_fonetico_es(t2)

        if cod1 == cod2 and cod1:
            score = 1.0
        else:
            dist = jellyfish.levenshtein_distance(cod1, cod2)
            max_len = max(len(cod1), len(cod2))
            score = 1.0 - (dist / max_len) if max_len > 0 else 0

        return ResultadoFonetico(
            score=score, codigo_detectado=cod1, codigo_referencia=cod2,
            detalle=f"Soundex ES: {cod1} vs {cod2} (score {score:.2f})",
            metodo="soundex_es"
        )

    def _comparar_metaphone_es(self, t1: str, t2: str,
                                orig1: str, orig2: str) -> ResultadoFonetico:
        """Comparacion con representacion fonetica completa."""
        fon1 = self._representacion_fonetica(t1)
        fon2 = self._representacion_fonetica(t2)
        dist = jellyfish.levenshtein_distance(fon1, fon2)
        max_len = max(len(fon1), len(fon2))
        score = 1.0 - (dist / max_len) if max_len > 0 else 0

        return ResultadoFonetico(
            score=score, codigo_detectado=fon1, codigo_referencia=fon2,
            detalle=f"Metaphone ES: {fon1} vs {fon2} (score {score:.2f})",
            metodo="metaphone_es"
        )

    def _explicar_fonetico(self, orig1, orig2, cod1, cod2, fon1, fon2,
                            sc_cod, sc_lev, sc_sil, score_final) -> str:
        """Genera explicacion de la comparacion fonetica."""
        partes = [f"'{orig1}' suena similar a '{orig2}'"]

        if cod1 == cod2:
            partes.append("Mismo codigo fonetico espanol")
        elif sc_cod > 0.7:
            partes.append(f"Codigos foneticos cercanos: {cod1} / {cod2}")

        if sc_lev > 0.7:
            partes.append(f"Representacion fonetica similar: {fon1} / {fon2}")

        if sc_sil > 0.6:
            partes.append("Estructura silabica compatible")

        partes.append(f"Confianza fonetica: {score_final:.0%}")

        return ". ".join(partes)
