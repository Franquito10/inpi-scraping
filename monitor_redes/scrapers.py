"""Backends de scraping.

- ApifyBackend: usa actores de Apify (servicio de scraping con proxies residenciales y
  manejo de login). Es la forma confiable de leer Facebook, Instagram, X y TikTok hoy:
  esas redes bloquean el acceso anonimo desde scripts.
- DemoBackend: genera publicaciones ficticias de personas ficticias para probar el
  sistema sin token (nunca usa nombres reales).

Todos devuelven publicaciones normalizadas:
  {plataforma, post_id, usuario, url, texto, fecha (datetime UTC), tipo, likes,
   comentarios, compartidos, vistas, hashtags, menciones, media_url, raw}
"""

import re
import time
import random
import logging
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

import requests

log = logging.getLogger("redes.scraper")

API_APIFY = "https://api.apify.com/v2"
HASHTAG_RE = re.compile(r"#(\w+)", re.UNICODE)
MENCION_RE = re.compile(r"@([\w.]+)", re.UNICODE)


# ---------------------------------------------------------------- utilidades
def _get(item: dict, *rutas, defecto=None):
    """Primer valor no vacio entre varias rutas ('a.b.c')."""
    for ruta in rutas:
        valor = item
        for parte in ruta.split("."):
            if isinstance(valor, dict):
                valor = valor.get(parte)
            elif isinstance(valor, list) and parte.isdigit() and int(parte) < len(valor):
                valor = valor[int(parte)]
            else:
                valor = None
                break
        if valor not in (None, "", [], {}):
            return valor
    return defecto


def _int(v) -> int:
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return 0


def parse_fecha(v) -> datetime | None:
    if v in (None, ""):
        return None
    if isinstance(v, (int, float)):
        ts = float(v)
        if ts > 1e12:  # milisegundos
            ts /= 1000
        return datetime.fromtimestamp(ts, timezone.utc)
    s = str(v).strip()
    if s.isdigit():
        return parse_fecha(int(s))
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        try:
            dt = parsedate_to_datetime(s)  # "Wed Nov 26 12:00:00 +0000 2026"
        except (TypeError, ValueError):
            try:
                dt = datetime.strptime(s, "%a %b %d %H:%M:%S %z %Y")
            except ValueError:
                return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _tags(lista, clave: str | None = None) -> list[str]:
    out = []
    for t in lista or []:
        if isinstance(t, dict):
            t = t.get(clave or "name") or t.get("text") or t.get("screen_name") or t.get("username")
        if t:
            out.append(str(t).lstrip("#@"))
    return out


def extraer_tags(texto: str) -> tuple[list[str], list[str]]:
    return HASHTAG_RE.findall(texto or ""), MENCION_RE.findall(texto or "")


def _pub(plataforma, item, **campos) -> dict:
    texto = campos.get("texto") or ""
    hs, ms = extraer_tags(texto)
    campos.setdefault("hashtags", hs)
    campos.setdefault("menciones", ms)
    if not campos["hashtags"]:
        campos["hashtags"] = hs
    if not campos["menciones"]:
        campos["menciones"] = ms
    base = {"plataforma": plataforma, "tipo": "post", "likes": 0, "comentarios": 0,
            "compartidos": 0, "vistas": 0, "media_url": None, "raw": item}
    base.update(campos)
    base["post_id"] = str(base["post_id"])
    base["texto"] = texto.strip()
    return base


# ---------------------------------------------------------------- normalizadores
def norm_instagram(item: dict) -> dict | None:
    pid = _get(item, "id", "shortCode", "shortcode")
    if not pid or item.get("error"):
        return None
    tipo = {"Video": "reel", "Sidecar": "carrusel", "Image": "foto"}.get(item.get("type"), "post")
    return _pub("instagram", item,
                post_id=pid,
                usuario=_get(item, "ownerUsername", "owner.username", defecto=""),
                url=_get(item, "url", defecto=f"https://www.instagram.com/p/{item.get('shortCode', '')}/"),
                texto=_get(item, "caption", defecto=""),
                fecha=parse_fecha(_get(item, "timestamp", "takenAtTimestamp")),
                tipo=tipo,
                likes=_int(_get(item, "likesCount")),
                comentarios=_int(_get(item, "commentsCount")),
                vistas=_int(_get(item, "videoViewCount", "videoPlayCount")),
                hashtags=_tags(item.get("hashtags")),
                menciones=_tags(item.get("mentions")),
                media_url=_get(item, "displayUrl"),
                entrada=_get(item, "inputUrl", defecto=""))


def norm_facebook(item: dict) -> dict | None:
    pid = _get(item, "postId", "id", "post_id")
    if not pid or item.get("error"):
        return None
    tipo = "video" if _get(item, "isVideo") or "/videos/" in str(item.get("url", "")) else "post"
    return _pub("facebook", item,
                post_id=pid,
                usuario=_get(item, "user.id", "pageName", "user.name", defecto=""),
                url=_get(item, "url", "topLevelUrl", "facebookUrl", defecto=""),
                texto=_get(item, "text", "message", "postText", defecto=""),
                fecha=parse_fecha(_get(item, "time", "timestamp", "date")),
                tipo=tipo,
                likes=_int(_get(item, "likes", "reactionsCount", "topReactionsCount")),
                comentarios=_int(_get(item, "comments", "commentsCount")),
                compartidos=_int(_get(item, "shares", "sharesCount")),
                vistas=_int(_get(item, "viewsCount", "videoViewCount")),
                media_url=_get(item, "media.0.thumbnail", "media.0.photo_image.uri", "thumbnail"),
                entrada=_get(item, "inputUrl", "facebookUrl", "pageUrl", defecto=""))


def norm_x(item: dict) -> dict | None:
    pid = _get(item, "id", "id_str", "tweetId")
    if not pid or item.get("noResults") or item.get("error"):
        return None
    if item.get("isRetweet") or _get(item, "retweeted_tweet", "retweetedTweet"):
        tipo = "retweet"
    elif item.get("isReply"):
        tipo = "respuesta"
    elif item.get("isQuote"):
        tipo = "cita"
    else:
        tipo = "tweet"
    usuario = _get(item, "author.userName", "author.screen_name", "user.screen_name", defecto="")
    return _pub("x", item,
                post_id=pid,
                usuario=usuario,
                url=_get(item, "url", "twitterUrl", defecto=f"https://x.com/{usuario}/status/{pid}"),
                texto=_get(item, "fullText", "text", "full_text", defecto=""),
                fecha=parse_fecha(_get(item, "createdAt", "created_at")),
                tipo=tipo,
                likes=_int(_get(item, "likeCount", "favorite_count")),
                comentarios=_int(_get(item, "replyCount", "reply_count")),
                compartidos=_int(_get(item, "retweetCount", "retweet_count")) + _int(_get(item, "quoteCount")),
                vistas=_int(_get(item, "viewCount", "views")),
                hashtags=_tags(_get(item, "entities.hashtags"), "text"),
                menciones=_tags(_get(item, "entities.user_mentions"), "screen_name"),
                media_url=_get(item, "extendedEntities.media.0.media_url_https", "media.0.media_url_https"),
                entrada="")


def norm_tiktok(item: dict) -> dict | None:
    pid = _get(item, "id")
    if not pid or item.get("error"):
        return None
    return _pub("tiktok", item,
                post_id=pid,
                usuario=_get(item, "authorMeta.name", "author.uniqueId", "input", defecto=""),
                url=_get(item, "webVideoUrl", "url", defecto=""),
                texto=_get(item, "text", "desc", defecto=""),
                fecha=parse_fecha(_get(item, "createTimeISO", "createTime")),
                tipo="video",
                likes=_int(_get(item, "diggCount", "stats.diggCount")),
                comentarios=_int(_get(item, "commentCount", "stats.commentCount")),
                compartidos=_int(_get(item, "shareCount", "stats.shareCount")),
                vistas=_int(_get(item, "playCount", "stats.playCount")),
                hashtags=_tags(item.get("hashtags"), "name"),
                menciones=_tags(item.get("mentions")),
                media_url=_get(item, "videoMeta.coverUrl", "covers.default"),
                entrada=_get(item, "input", defecto=""))


NORMALIZADORES = {"instagram": norm_instagram, "facebook": norm_facebook,
                  "x": norm_x, "tiktok": norm_tiktok}


# ---------------------------------------------------------------- Apify
class ErrorScraping(Exception):
    pass


class ApifyBackend:
    nombre = "apify"

    def __init__(self, token: str, actores: dict, timeout_min: int = 15, sesion=None):
        if not token:
            raise ErrorScraping("Falta APIFY_TOKEN (ver monitor_redes/.env.ejemplo)")
        self.token = token
        self.actores = actores
        self.timeout = timeout_min * 60
        self.http = sesion or requests.Session()
        self.http.headers["Authorization"] = f"Bearer {token}"

    def _entrada(self, plataforma: str, cuentas: list[dict], dias: int, maximo: int) -> dict:
        urls = [c["url"] for c in cuentas]
        usuarios = [c["usuario"] for c in cuentas]
        desde = (datetime.now(timezone.utc) - timedelta(days=dias)).strftime("%Y-%m-%d")
        if plataforma == "instagram":
            return {"directUrls": urls, "resultsType": "posts", "resultsLimit": maximo,
                    "onlyPostsNewerThan": desde, "addParentData": False}
        if plataforma == "facebook":
            return {"startUrls": [{"url": u} for u in urls], "resultsLimit": maximo,
                    "onlyPostsNewerThan": desde}
        if plataforma == "x":
            return {"twitterHandles": usuarios, "maxItems": maximo * len(usuarios),
                    "sort": "Latest", "start": desde, "includeSearchTerms": False}
        if plataforma == "tiktok":
            return {"profiles": usuarios, "resultsPerPage": maximo, "oldestPostDateUnified": desde,
                    "profileScrapeSections": ["videos"], "shouldDownloadVideos": False,
                    "shouldDownloadCovers": False, "shouldDownloadSubtitles": False}
        raise ValueError(plataforma)

    def _correr_actor(self, actor: str, entrada: dict) -> list[dict]:
        actor_id = actor.replace("/", "~")
        r = self.http.post(f"{API_APIFY}/acts/{actor_id}/runs", json=entrada, timeout=60)
        if r.status_code >= 400:
            raise ErrorScraping(f"Apify {actor}: HTTP {r.status_code} {r.text[:300]}")
        run = r.json()["data"]
        run_id, dataset = run["id"], run["defaultDatasetId"]
        limite = time.monotonic() + self.timeout
        estado = run.get("status")
        while estado in ("READY", "RUNNING"):
            if time.monotonic() > limite:
                self.http.post(f"{API_APIFY}/actor-runs/{run_id}/abort", timeout=30)
                raise ErrorScraping(f"Apify {actor}: timeout")
            time.sleep(10)
            estado = self.http.get(f"{API_APIFY}/actor-runs/{run_id}", timeout=30).json()["data"]["status"]
        if estado != "SUCCEEDED":
            log.warning("Apify %s termino con estado %s; se usan los items parciales", actor, estado)
        items, offset = [], 0
        while True:
            r = self.http.get(f"{API_APIFY}/datasets/{dataset}/items",
                              params={"clean": "true", "format": "json", "offset": offset, "limit": 1000},
                              timeout=60)
            r.raise_for_status()
            lote = r.json()
            items.extend(lote)
            if len(lote) < 1000:
                break
            offset += 1000
        return items

    def scrapear(self, plataforma: str, cuentas: list[dict], dias: int, maximo: int) -> list[dict]:
        items = self._correr_actor(self.actores[plataforma], self._entrada(plataforma, cuentas, dias, maximo))
        norm = NORMALIZADORES[plataforma]
        return [p for p in (norm(i) for i in items) if p]


# ---------------------------------------------------------------- Demo
PERSONAS_DEMO = [
    {"nombre": "Laura Demo", "cargo": "Legisladora (ficticia)"},
    {"nombre": "Martin Ejemplo", "cargo": "Concejal (ficticio)"},
    {"nombre": "Sofia Prueba", "cargo": "Diputada (ficticia)"},
    {"nombre": "Diego Muestra", "cargo": "Militante (ficticio)"},
    {"nombre": "Carla Ficticia", "cargo": "Influencer (ficticia)"},
]

_FRASES = [
    "Hoy recorrimos el barrio {barrio} junto a los vecinos, escuchando sus reclamos por {reclamo}. #Tucuman",
    "Presentamos un proyecto en la Legislatura para mejorar la {area}. Seguimos trabajando. #TrabajoLegislativo",
    "Reunion de trabajo con comerciantes de {lugar} sobre la situacion economica y el empleo.",
    "Gran sesion hoy en el Concejo: aprobamos la ordenanza de {area}. #ConcejoSMT",
    "Entrevista en radio esta manana hablando de seguridad y del delito en {lugar}.",
    "Nos sumamos a la jornada solidaria en el merendero de {barrio}. Gracias a todos los voluntarios!",
    "Basta de casta y privilegios. Los tucumanos merecen otra politica. #LaLibertadAvanza",
    "Acompanamos la inauguracion de la obra de pavimento en {lugar}.",
    "Feliz cumpleanos a mi hija, la luz de mi vida.",
    "Pedido de informe por los baches y la falta de iluminacion en {barrio}.",
    "Charla en la escuela de {lugar} con estudiantes y docentes sobre educacion y futuro.",
    "Hospital de {lugar}: reclamamos por la falta de medicos y insumos de salud.",
]
_RELLENO = {
    "barrio": ["Villa Carmela", "Barrio Norte", "Villa Lujan", "El Bosque", "Villa 9 de Julio", "Ciudadela"],
    "reclamo": ["la basura", "los baches", "la inseguridad", "el transporte"],
    "area": ["seguridad vial", "salud mental", "transparencia", "educacion tecnica"],
    "lugar": ["Yerba Buena", "Tafi Viejo", "Banda del Rio Sali", "Concepcion", "Las Talitas", "Monteros"],
}


class DemoBackend:
    """Datos ficticios: sirve para probar dashboard y bot sin token."""
    nombre = "demo"

    def __init__(self, semilla: int | None = 42, por_cuenta: int = 6):
        self.rnd = random.Random(semilla)
        self.por_cuenta = por_cuenta

    def scrapear(self, plataforma: str, cuentas: list[dict], dias: int, maximo: int) -> list[dict]:
        r, out = self.rnd, []
        ahora = datetime.now(timezone.utc)
        for c in cuentas:
            for _ in range(r.randint(1, min(maximo, self.por_cuenta))):
                frase = r.choice(_FRASES)
                texto = frase.format(**{k: r.choice(v) for k, v in _RELLENO.items()})
                hora_local = r.choice([8, 9, 10, 11, 12, 13, 17, 18, 19, 20, 21, 22])
                fecha = (ahora - timedelta(days=r.uniform(0, dias))).replace(
                    hour=(hora_local + 3) % 24, minute=r.randint(0, 59))
                if fecha > ahora:
                    fecha -= timedelta(days=1)
                pid = f"demo-{plataforma}-{c['usuario']}-{r.randint(10**8, 10**9)}"
                out.append(_pub(plataforma, {}, post_id=pid, usuario=c["usuario"],
                                url=f"https://example.com/{plataforma}/{pid}", texto=texto, fecha=fecha,
                                tipo={"tiktok": "video", "x": "tweet"}.get(plataforma, r.choice(["post", "foto", "reel"])),
                                likes=r.randint(5, 900), comentarios=r.randint(0, 120),
                                compartidos=r.randint(0, 80),
                                vistas=r.randint(300, 40000) if plataforma in ("tiktok", "instagram") else 0,
                                entrada=c["url"]))
        return out
