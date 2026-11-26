"""Tests del monitor de redes (sin red: Apify y Telegram simulados).

Correr:  python -m pytest tests/test_monitor_redes.py -q
"""

import copy
from datetime import datetime, timezone, timedelta

import pytest

from monitor_redes.config import cargar_settings, usuario_desde_url, slug
from monitor_redes.db import DB
from monitor_redes import scrapers
from monitor_redes.scrapers import norm_instagram, norm_facebook, norm_x, norm_tiktok, parse_fecha, ApifyBackend
from monitor_redes.analisis import clasificar, resumen_reglas
from monitor_redes.recolector import recolectar
from monitor_redes.dashboard import generar_dashboard
from monitor_redes.bot import Bot, partir

AHORA = datetime.now(timezone.utc)
ISO = (AHORA - timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%S.000Z")

PERSONAS = [
    {"nombre": "Ana Prueba", "cargo": "Concejal", "slug": "ana-prueba", "cuentas": {
        "instagram": {"url": "https://www.instagram.com/ana.prueba/", "usuario": "ana.prueba"},
        "x": {"url": "https://x.com/AnaPrueba", "usuario": "AnaPrueba"},
        "facebook": {"url": "https://www.facebook.com/profile.php?id=1000123", "usuario": "1000123"},
        "tiktok": {"url": "https://www.tiktok.com/@anaprueba", "usuario": "anaprueba"}}},
    {"nombre": "Beto Ejemplo", "cargo": "Legislador", "slug": "beto-ejemplo", "cuentas": {
        "instagram": {"url": "https://www.instagram.com/betoej", "usuario": "betoej"},
        "x": {"url": "https://x.com/betoej", "usuario": "betoej"}}},
]

# Muestras con la forma de salida de cada actor de Apify
IG = {"inputUrl": "https://www.instagram.com/ana.prueba/", "id": "311", "type": "Video", "shortCode": "Cabc",
      "caption": "Hoy recorrimos Villa Carmela con los vecinos por la inseguridad #Tucuman @betoej",
      "hashtags": ["Tucuman"], "mentions": ["betoej"], "url": "https://www.instagram.com/p/Cabc/",
      "commentsCount": 4, "likesCount": 120, "timestamp": ISO, "ownerUsername": "ana.prueba", "videoViewCount": 900}
FB = {"facebookUrl": "https://www.facebook.com/profile.php?id=1000123", "postId": "fb9", "url": "https://facebook.com/x/posts/fb9",
      "time": ISO, "text": "Presentamos un proyecto de ordenanza sobre transporte en el Concejo", "likes": 10, "comments": 2, "shares": 1}
TW = {"type": "tweet", "id": "1789", "url": "https://x.com/betoej/status/1789", "text": "Entrevista en radio sobre Milei y la economia",
      "retweetCount": 3, "replyCount": 1, "likeCount": 50, "quoteCount": 0, "viewCount": 2000,
      "createdAt": (AHORA - timedelta(hours=1)).strftime("%a %b %d %H:%M:%S +0000 %Y"),
      "author": {"userName": "BetoEj"}, "entities": {"hashtags": [], "user_mentions": []}}
TT = {"id": "7001", "text": "Feliz cumpleaños a mi hija", "createTimeISO": ISO, "webVideoUrl": "https://tiktok.com/@anaprueba/video/7001",
      "diggCount": 77, "shareCount": 2, "playCount": 3000, "commentCount": 5, "hashtags": [], "authorMeta": {"name": "anaprueba"}}


@pytest.fixture
def cfg(tmp_path):
    c = copy.deepcopy(cargar_settings())
    c["rutas"]["db"] = str(tmp_path / "t.db")
    c["rutas"]["dashboard"] = str(tmp_path / "d.html")
    c["analisis"]["ia"]["habilitada"] = False
    return c


@pytest.fixture
def db(cfg):
    d = DB(cfg["rutas"]["db"])
    d.sincronizar_personas(PERSONAS)
    return d


class FakeApify:
    """Imita la API HTTP de Apify devolviendo items fijos por actor."""
    nombre = "apify"

    def __init__(self, items_por_actor):
        self.items = items_por_actor
        self.headers = {}
        self.entradas = {}
        self._ultimo = None

    class R:
        def __init__(self, data, code=200):
            self._d, self.status_code, self.text = data, code, ""

        def json(self):
            return self._d

        def raise_for_status(self):
            pass

    def post(self, url, json=None, timeout=None):
        actor = url.split("/acts/")[1].split("/")[0].replace("~", "/")
        self.entradas[actor] = json
        self._ultimo = actor
        return self.R({"data": {"id": "run1", "defaultDatasetId": actor.replace("/", "~"), "status": "SUCCEEDED"}})

    def get(self, url, params=None, timeout=None):
        actor = url.split("/datasets/")[1].split("/")[0].replace("~", "/")
        return self.R(self.items.get(actor, []) if (params or {}).get("offset", 0) == 0 else [])


def test_usuario_desde_url():
    assert usuario_desde_url("instagram", "https://www.instagram.com/walter_berarducci/") == "walter_berarducci"
    assert usuario_desde_url("tiktok", "https://www.tiktok.com/@pepeseleme") == "pepeseleme"
    assert usuario_desde_url("facebook", "https://www.facebook.com/profile.php?id=100008752720265") == "100008752720265"
    assert slug("Micaela Viña") == "micaela-vina"


def test_parse_fecha_formatos():
    assert parse_fecha("2026-11-26T10:00:00.000Z").hour == 10
    assert parse_fecha(1764151200).year == 2025
    assert parse_fecha("Wed Nov 26 12:00:00 +0000 2026").day == 26
    assert parse_fecha(None) is None


def test_normalizadores():
    ig = norm_instagram(IG)
    assert ig["tipo"] == "reel" and ig["likes"] == 120 and ig["vistas"] == 900 and "Tucuman" in ig["hashtags"]
    fb = norm_facebook(FB)
    assert fb["post_id"] == "fb9" and fb["compartidos"] == 1 and fb["fecha"].tzinfo
    tw = norm_x(TW)
    assert tw["usuario"] == "BetoEj" and tw["tipo"] == "tweet" and tw["vistas"] == 2000
    tt = norm_tiktok(TT)
    assert tt["usuario"] == "anaprueba" and tt["vistas"] == 3000
    assert norm_x({"noResults": True}) is None
    assert norm_instagram({"error": "not_found", "url": "x"}) is None


def test_clasificar():
    c = clasificar("Hoy recorrimos Villa Carmela con los vecinos por la inseguridad", [])
    assert "Seguridad" in c["temas"] and "Recorrida / territorio" in c["actividades"] and "Villa Carmela" in c["lugares"]
    c = clasificar("Gracias a todos!", ["LaLibertadAvanza"])
    assert "Política partidaria" in c["temas"]
    # palabras cortas no matchean dentro de otras ("acto" en "impacto")
    assert "Acto / evento" not in clasificar("El impacto fue grande", [])["actividades"]


def test_recolectar_asigna_y_deduplica(cfg, db, monkeypatch):
    sesion = FakeApify({
        "apify/instagram-scraper": [IG, {"error": "no_items"}],
        "apify/facebook-posts-scraper": [FB],
        "apidojo/tweet-scraper": [TW, {"noResults": True}],
        "clockworks/tiktok-scraper": [TT],
    })
    backend = ApifyBackend("tok", cfg["scraping"]["actores"], sesion=sesion)
    monkeypatch.setattr(scrapers.time, "sleep", lambda s: None)
    res = recolectar(cfg, db, backend=backend)
    assert len(res["nuevas"]) == 4 and not res["errores"]
    por_red = {p["plataforma"]: p for p in db.publicaciones()}
    assert por_red["x"]["nombre"] == "Beto Ejemplo"          # usuario con otra capitalizacion
    assert por_red["facebook"]["nombre"] == "Ana Prueba"      # perfil profile.php?id=
    assert "Labor legislativa" in por_red["facebook"]["temas"]
    assert sesion.entradas["apidojo/tweet-scraper"]["twitterHandles"] == ["AnaPrueba", "betoej"]
    # segunda corrida: nada nuevo, metricas actualizadas
    IG2 = dict(IG, likesCount=500)
    sesion.items["apify/instagram-scraper"] = [IG2]
    res2 = recolectar(cfg, db, backend=backend)
    assert len(res2["nuevas"]) == 0
    assert {p["plataforma"]: p for p in db.publicaciones()}["instagram"]["likes"] == 500


def test_error_de_una_red_no_frena_las_demas(cfg, db):
    class Roto:
        nombre = "x"

        def scrapear(self, red, cuentas, dias, maximo):
            if red == "x":
                raise RuntimeError("rate limit")
            return [norm_instagram(IG)] if red == "instagram" else []
    res = recolectar(cfg, db, backend=Roto())
    assert len(res["nuevas"]) == 1 and "rate limit" in res["errores"][0]
    assert db.personas()[0]["cuentas"]["x"]["ultimo_error"]


def test_dashboard_se_genera(cfg, db):
    recolectar(cfg, db, backend=scrapers.DemoBackend(semilla=1))
    ruta = generar_dashboard(cfg, db)
    html = ruta.read_text(encoding="utf-8")
    assert "Ana Prueba" in html and '"publicaciones"' in html
    assert "</script><script>" not in html.split('id="datos"')[1].split("</script>")[0]


class FakeTelegram:
    def __init__(self):
        self.enviados = []

    def llamar(self, metodo, archivos=None, _http=40, **p):
        self.enviados.append((metodo, p))
        return {"username": "test"} if metodo == "getMe" else True


def test_bot_comandos_y_avisos(cfg, db):
    tg = FakeTelegram()
    bot = Bot(cfg, db, api=tg, backend=scrapers.DemoBackend(semilla=3), chats_autorizados={111})
    assert "no está autorizado" in bot.manejar(999, "/hoy")
    assert "Listo" in bot.manejar(111, "/start", "Yo")
    bot.ciclo_scraping()                       # primera carga: un solo aviso
    assert any("Carga inicial" in p["text"] for m, p in tg.enviados if m == "sendMessage")
    assert "Ana Prueba" in bot.manejar(111, "/persona ana")
    assert "Beto Ejemplo" in bot.manejar(111, "/persona betto")   # tolera errores de tipeo
    assert "Resumen" in bot.manejar(111, "/semana")
    assert "Ranking" in bot.manejar(111, "/ranking 30")
    assert "Temas" in bot.manejar(111, "/temas")
    assert "Alerta" not in bot.manejar(111, "/alerta inseguridad")
    assert "inseguridad" in bot.manejar(111, "/alertas")
    # llega una publicacion nueva que dispara la alerta
    tg.enviados.clear()
    pub = dict(norm_instagram(dict(IG, id="nuevo1")), persona_id=db.personas()[0]["id"],
               fecha=ISO, temas=[], actividades=[], lugares=[])
    pub.pop("usuario"); pub.pop("entrada")
    db.guardar_publicacion(pub)
    assert bot.avisar_novedades() == 1
    textos = [p["text"] for m, p in tg.enviados if m == "sendMessage"]
    assert any("1 publicaciones nuevas" in t for t in textos)
    assert any("Alerta «inseguridad»" in t for t in textos)
    assert bot.avisar_novedades() == 0


def test_partir_mensajes_largos():
    partes = partir("\n".join(["x" * 100] * 100))
    assert all(len(p) <= 3900 for p in partes) and sum(len(p) for p in partes) >= 100 * 100


def test_resumen_reglas_sin_publicaciones():
    assert "no publicó" in resumen_reglas("Ana", [])
