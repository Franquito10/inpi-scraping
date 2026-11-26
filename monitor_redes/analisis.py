"""Analisis de publicaciones: temas, que hacen (actividades), lugares, metricas y resumenes.

La clasificacion es por diccionario (rapida, gratis, explicable). Los diccionarios estan
pensados para politica de Tucuman y se pueden ampliar aca abajo.
Opcionalmente, Claude redacta un resumen diario por persona ("que publico y que hizo").
"""

import os
import re
import logging
from collections import Counter, defaultdict
from datetime import datetime, timedelta

from .config import normalizar, NOMBRE_RED

log = logging.getLogger("redes.analisis")

TEMAS = {
    "Seguridad": ["seguridad", "inseguridad", "policia", "delito", "robo", "narco", "droga",
                  "motochorro", "comisaria", "violencia", "crimen"],
    "Economía y empleo": ["economia", "inflacion", "empleo", "desempleo", "trabajo", "salario", "sueldo",
                          "precios", "impuesto", "pyme", "comercio", "comerciante", "produccion",
                          "inversion", "dolar", "industria", "azucar", "limon"],
    "Educación": ["escuela", "educacion", "docente", "alumno", "universidad", "unt", "estudiante",
                  "aula", "colegio", "maestr"],
    "Salud": ["salud", "hospital", "caps", "medico", "vacuna", "dengue", "sanitari", "enfermer", "pami"],
    "Obras e infraestructura": ["obra", "pavimento", "bache", "asfalto", "cloaca", "agua potable",
                                "luminaria", "iluminacion", "ruta", "puente", "desague", "vivienda"],
    "Servicios urbanos": ["basura", "residuos", "limpieza", "transporte", "colectivo", "transito",
                          "semaforo", "espacio verde", "plaza", "boleto"],
    "Labor legislativa": ["proyecto", "sesion", "ley", "ordenanza", "legislatura", "concejo",
                          "comision", "aprobamos", "aprobado", "votacion", "pedido de informe",
                          "resolucion", "banca", "minuta"],
    "Política partidaria": ["libertad avanza", "lla", "militancia", "militante", "afiliacion",
                            "campana", "elecciones", "eleccion", "candidat", "lista", "fiscales", "boleta"],
    "Gobierno nacional": ["milei", "gobierno nacional", "nacion", "casa rosada", "presidente",
                          "bullrich", "caputo", "karina", "javier"],
    "Críticas / oposición": ["kirchner", "kirchnerismo", "peronismo", "jaldo", "chahla", "manzur",
                             "casta", "corrupcion", "curro", "privilegio", "repudio", "verguenza"],
    "Social y comunidad": ["barrio", "vecino", "comedor", "merendero", "fundacion", "solidari",
                           "donacion", "ayuda", "ong", "jubilad"],
    "Deporte y cultura": ["futbol", "atletico", "san martin", "deporte", "cultura", "festival",
                          "musica", "peña folklórica", "rugby", "teatro"],
    "Personal / familia": ["familia", "cumpleanos", "amigos", "vacaciones", "mi hijo", "mi hija",
                           "mama", "papa", "esposa", "esposo", "amor"],
    "Efemérides / religión": ["dios", "virgen", "misa", "feliz dia", "aniversario", "patria",
                              "independencia", "9 de julio", "25 de mayo", "navidad", "pascua"],
}

ACTIVIDADES = {
    "Recorrida / territorio": ["recorr", "visitamos", "visite", "caminata", "timbreo", "puerta a puerta",
                               "territorio", "estuvimos en", "junto a los vecinos"],
    "Reunión": ["reunion", "nos reunimos", "me reuni", "encuentro con", "mesa de trabajo"],
    "Trabajo legislativo": ["sesion", "presente un", "presentamos", "proyecto de", "comision",
                            "votamos", "aprobamos", "pedido de informe", "ordenanza"],
    "Medios / entrevista": ["entrevista", "radio", "programa", "canal", "streaming", "en vivo",
                            "conferencia de prensa", "nota en", "diario", "tv"],
    "Acto / evento": ["acto", "evento", "inauguracion", "inauguramos", "congreso", "jornada",
                      "charla", "presentacion", "acompanamos", "participamos"],
    "Reclamo / gestión": ["reclamo", "reclamamos", "gestion", "gestionamos", "solicitamos",
                          "exigimos", "denuncia", "denunciamos"],
    "Opinión / posicionamiento": ["basta", "repudio", "inaceptable", "opino", "creo que",
                                  "no vamos a permitir", "es hora de", "vergonzoso"],
    "Campaña / militancia": ["militancia", "afiliacion", "sumate", "fiscales", "voluntari",
                             "campana", "vamos con"],
    "Vida personal": ["cumpleanos", "familia", "vacaciones", "amigos", "mi hija", "mi hijo"],
}

LUGARES = [
    "San Miguel de Tucumán", "Yerba Buena", "Tafí Viejo", "Banda del Río Salí", "Alderetes",
    "Las Talitas", "Concepción", "Monteros", "Famaillá", "Aguilares", "Lules", "Simoca",
    "Tafí del Valle", "Trancas", "Burruyacú", "La Cocha", "Juan Bautista Alberdi", "Bella Vista",
    "El Manantial", "San Pablo", "Villa Carmela", "Barrio Norte", "Barrio Sur", "Villa Luján",
    "Villa 9 de Julio", "El Bosque", "La Costanera", "San Cayetano", "Villa Mariano Moreno",
    "Ciudadela", "Villa Amalia", "Legislatura", "Concejo Deliberante", "Casa de Gobierno",
    "Plaza Independencia", "Parque 9 de Julio", "Buenos Aires", "Congreso",
]


def _compilar(dic: dict[str, list[str]]) -> dict[str, re.Pattern]:
    out = {}
    for clave, palabras in dic.items():
        partes = []
        for p in palabras:
            p = normalizar(p)
            fin = r"(?!\w)" if len(p) <= 4 else ""
            partes.append(r"(?<!\w)" + re.escape(p) + fin)
        out[clave] = re.compile("|".join(partes))
    return out


_RX_TEMAS = _compilar(TEMAS)
_RX_ACT = _compilar(ACTIVIDADES)
_RX_LUG = _compilar({l: [l] for l in LUGARES})


def clasificar(texto: str, hashtags: list[str] | None = None) -> dict:
    t = normalizar(texto + " " + " ".join(hashtags or []))
    # los hashtags vienen pegados (#LaLibertadAvanza): los separamos por mayusculas
    t += " " + normalizar(" ".join(re.sub(r"(?<!^)(?=[A-Z])", " ", h) for h in hashtags or []))
    return {
        "temas": [k for k, rx in _RX_TEMAS.items() if rx.search(t)],
        "actividades": [k for k, rx in _RX_ACT.items() if rx.search(t)],
        "lugares": [k for k, rx in _RX_LUG.items() if rx.search(t)],
    }


def interacciones(p: dict) -> int:
    return (p.get("likes") or 0) + (p.get("comentarios") or 0) + (p.get("compartidos") or 0)


# ------------------------------------------------------------------ agregados
def estadisticas(pubs: list[dict]) -> dict:
    por_persona = defaultdict(lambda: {"total": 0, "redes": Counter(), "interacciones": 0,
                                       "temas": Counter(), "actividades": Counter()})
    temas, acts, lugares, hashtags, redes = Counter(), Counter(), Counter(), Counter(), Counter()
    for p in pubs:
        pp = por_persona[p["nombre"]]
        pp["total"] += 1
        pp["redes"][p["plataforma"]] += 1
        pp["interacciones"] += interacciones(p)
        pp["temas"].update(p["temas"])
        pp["actividades"].update(p["actividades"])
        temas.update(p["temas"])
        acts.update(p["actividades"])
        lugares.update(p["lugares"])
        hashtags.update(h.lower() for h in p["hashtags"])
        redes[p["plataforma"]] += 1
    return {"total": len(pubs), "personas": dict(por_persona), "temas": temas,
            "actividades": acts, "lugares": lugares, "hashtags": hashtags, "redes": redes}


def resumen_reglas(nombre: str, pubs: list[dict]) -> str:
    """Resumen sin IA: cuantas publicaciones, donde, temas, actividades y lugares."""
    if not pubs:
        return f"{nombre} no publicó en el período."
    st = estadisticas(pubs)
    redes = ", ".join(f"{n} en {NOMBRE_RED[r]}" for r, n in st["redes"].most_common())
    partes = [f"{len(pubs)} publicaciones ({redes})."]
    if st["temas"]:
        partes.append("Temas: " + ", ".join(t for t, _ in st["temas"].most_common(4)) + ".")
    if st["actividades"]:
        partes.append("Qué hizo: " + ", ".join(a for a, _ in st["actividades"].most_common(4)) + ".")
    if st["lugares"]:
        partes.append("Lugares: " + ", ".join(l for l, _ in st["lugares"].most_common(4)) + ".")
    top = max(pubs, key=interacciones)
    if interacciones(top) > 0:
        partes.append(f"Lo más visto ({interacciones(top)} interacciones): “{_corto(top['texto'], 120)}”")
    return "\n".join(partes)


def _corto(texto: str, n: int) -> str:
    texto = " ".join((texto or "").split())
    return texto if len(texto) <= n else texto[: n - 1] + "…"


PROMPT_RESUMEN = """Sos analista de monitoreo de redes sociales de política de Tucumán (Argentina).
Abajo están las publicaciones de {nombre} ({cargo}) del período {periodo}.

Escribí un resumen breve en español rioplatense, neutral y factual, con este formato:
- Qué publicó: 1-2 oraciones sobre los temas y mensajes principales.
- Qué hizo: actividades concretas que se desprenden (recorridas, reuniones, sesiones, actos, entrevistas), con lugares y fechas si aparecen.
- A destacar: posicionamientos, críticas o anuncios relevantes (si no hay, omití esta línea).

No inventes nada que no esté en las publicaciones. Máximo 90 palabras.

Publicaciones:
{publicaciones}"""


class Resumidor:
    """Redacta resumenes por persona. Usa Claude si hay API key; si no, reglas."""

    def __init__(self, cfg: dict):
        ia = (cfg.get("analisis") or {}).get("ia") or {}
        self.modelo = ia.get("modelo", "claude-sonnet-5-5")
        self.cliente = None
        if ia.get("habilitada", True) and os.environ.get("ANTHROPIC_API_KEY"):
            try:
                import anthropic
                self.cliente = anthropic.Anthropic()
            except ImportError:
                log.warning("ANTHROPIC_API_KEY definida pero falta 'pip install anthropic'; uso reglas")

    @property
    def usa_ia(self) -> bool:
        return self.cliente is not None

    def resumir(self, nombre: str, cargo: str, pubs: list[dict], periodo: str) -> tuple[str, str]:
        if not pubs or not self.cliente:
            return resumen_reglas(nombre, pubs), "reglas"
        lineas = [f"[{p['fecha'][:16].replace('T', ' ')} · {NOMBRE_RED[p['plataforma']]}] "
                  f"{_corto(p['texto'], 600) or '(sin texto)'}" for p in pubs[:40]]
        try:
            resp = self.cliente.messages.create(
                model=self.modelo, max_tokens=500,
                messages=[{"role": "user", "content": PROMPT_RESUMEN.format(
                    nombre=nombre, cargo=cargo or "-", periodo=periodo, publicaciones="\n".join(lineas))}])
            texto = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text").strip()
            return texto or resumen_reglas(nombre, pubs), self.modelo
        except Exception as e:  # red, cuota, etc: nunca frenar el sistema por la IA
            log.warning("Resumen IA fallo para %s: %s", nombre, e)
            return resumen_reglas(nombre, pubs), "reglas"


def heatmap_dia_hora(pubs: list[dict], zona) -> list[list[int]]:
    """Matriz 7x24 (lunes..domingo x hora local)."""
    m = [[0] * 24 for _ in range(7)]
    for p in pubs:
        if p.get("fecha"):
            dt = datetime.fromisoformat(p["fecha"].replace("Z", "+00:00")).astimezone(zona)
            m[dt.weekday()][dt.hour] += 1
    return m


def rango_dias(dias: int, zona) -> tuple[datetime, str]:
    ahora = datetime.now(zona)
    inicio = (ahora - timedelta(days=dias - 1)).replace(hour=0, minute=0, second=0, microsecond=0)
    etiqueta = "hoy" if dias == 1 else f"últimos {dias} días"
    return inicio, etiqueta
