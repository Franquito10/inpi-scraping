"""Bot de Telegram: avisa que publican y que hacen las personas monitoreadas.

- Scrapea cada N horas y manda las publicaciones nuevas a los chats autorizados.
- Manda un resumen diario a la hora configurada.
- Responde comandos (/hoy, /persona, /buscar, ...). Ver AYUDA.

Solo atiende a los chats listados en TELEGRAM_CHAT_IDS. Usa la Bot API por HTTP
(long polling), sin dependencias extra.
"""

import os
import html
import json
import time
import logging
import difflib
import threading
from collections import defaultdict, Counter
from datetime import datetime, timezone

import requests

from .config import NOMBRE_RED, normalizar, tz
from .db import DB, hace
from .analisis import Resumidor, estadisticas, interacciones, rango_dias, resumen_reglas, _corto
from .recolector import recolectar
from .dashboard import generar_dashboard

log = logging.getLogger("redes.bot")

ICONO = {"facebook": "📘", "x": "✖️", "instagram": "📸", "tiktok": "🎵"}
LIMITE = 3900

AYUDA = """<b>Monitor de redes</b> — qué publican y qué hacen.

<b>Consultas</b>
/hoy — resumen de lo publicado hoy
/semana — resumen de los últimos 7 días
/persona <i>nombre</i> [días] — qué publicó y qué hizo (ej: /persona seleme 3)
/ultimas [n] — las últimas n publicaciones
/buscar <i>texto</i> — buscar en las publicaciones
/temas [días] — de qué se está hablando
/ranking [días] — quién publica más y quién tiene más interacción
/personas — lista de personas monitoreadas

<b>Avisos</b>
/alerta <i>palabra</i> — avisarme cuando alguien la mencione
/alertas — ver mis palabras · /quitar <i>palabra</i>
/silenciar — pausar avisos automáticos · /activar — reanudarlos

<b>Sistema</b>
/actualizar — scrapear ahora
/estado — último scraping y errores
/dashboard — recibir el dashboard (HTML)"""


def esc(t) -> str:
    return html.escape(str(t or ""), quote=False)


def partir(texto: str, limite: int = LIMITE) -> list[str]:
    """Parte un mensaje largo respetando lineas (Telegram corta en 4096)."""
    partes, actual = [], ""
    for linea in texto.split("\n"):
        while len(linea) > limite:
            if actual:
                partes.append(actual)
                actual = ""
            partes.append(linea[:limite])
            linea = linea[limite:]
        if len(actual) + len(linea) + 1 > limite:
            partes.append(actual)
            actual = ""
        actual = f"{actual}\n{linea}" if actual else linea
    if actual:
        partes.append(actual)
    return partes


class TelegramAPI:
    def __init__(self, token: str):
        if not token:
            raise ValueError("Falta TELEGRAM_BOT_TOKEN (crealo con @BotFather)")
        self.base = f"https://api.telegram.org/bot{token}/"
        self.http = requests.Session()

    def llamar(self, metodo: str, archivos=None, _http: int = 40, **params):
        params = {k: v for k, v in params.items() if v is not None}
        r = self.http.post(self.base + metodo, data=params if archivos else None,
                           json=None if archivos else params, files=archivos, timeout=_http)
        datos = r.json()
        if not datos.get("ok"):
            raise RuntimeError(f"Telegram {metodo}: {datos.get('description')}")
        return datos["result"]


class Bot:
    def __init__(self, cfg: dict, db: DB, api=None, backend=None, chats_autorizados=None):
        self.cfg, self.db = cfg, db
        self.api = api or TelegramAPI(os.environ.get("TELEGRAM_BOT_TOKEN", ""))
        self.backend = backend
        self.zona = tz(cfg)
        self.bcfg = cfg.get("bot") or {}
        if chats_autorizados is None:
            chats_autorizados = {int(x) for x in os.environ.get("TELEGRAM_CHAT_IDS", "").replace(";", ",").split(",")
                                 if x.strip().lstrip("-").isdigit()}
        self.autorizados = set(chats_autorizados)
        self.resumidor = Resumidor(cfg)
        self.lock_scrap = threading.Lock()
        self.despertar = threading.Event()
        self.parar = threading.Event()

    # ------------------------------------------------------------ envio
    def enviar(self, chat_id: int, texto: str) -> None:
        for parte in partir(texto):
            try:
                self.api.llamar("sendMessage", chat_id=chat_id, text=parte, parse_mode="HTML",
                                disable_web_page_preview=True)
            except Exception as e:
                log.error("No pude enviar a %s: %s", chat_id, e)

    def difundir(self, texto: str) -> None:
        for s in self.db.suscriptores():
            if s["chat_id"] in self.autorizados:
                self.enviar(s["chat_id"], texto)

    # ------------------------------------------------------------ formato
    def _hora(self, iso: str) -> str:
        return datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone(self.zona).strftime("%d/%m %H:%M")

    def fmt_pub(self, p: dict, con_nombre: bool = True, largo: int = 280) -> str:
        cab = f"{ICONO.get(p['plataforma'], '•')} "
        if con_nombre:
            cab += f"<b>{esc(p['nombre'])}</b> · "
        cab += f"{NOMBRE_RED[p['plataforma']]} · {self._hora(p['fecha'])}"
        texto = esc(_corto(p["texto"], largo)) or "<i>(sin texto)</i>"
        pie = []
        if p["temas"]:
            pie.append("🏷 " + ", ".join(p["temas"][:3]))
        if p["actividades"]:
            pie.append("📍 " + ", ".join(p["actividades"][:2]))
        inter = interacciones(p)
        if inter:
            pie.append(f"❤️ {inter}")
        if p.get("url"):
            pie.append(f'<a href="{esc(p["url"])}">ver</a>')
        return f"{cab}\n{texto}" + (f"\n<i>{' · '.join(pie)}</i>" if pie else "")

    def buscar_persona(self, consulta: str) -> tuple[dict | None, list[dict]]:
        personas = self.db.personas()
        q = normalizar(consulta).strip()
        exactas = [p for p in personas if q in normalizar(p["nombre"]) or q == p["slug"]]
        if len(exactas) == 1:
            return exactas[0], []
        if exactas:
            return None, exactas
        nombres = {normalizar(p["nombre"]): p for p in personas}
        palabras = {normalizar(w): p for p in personas for w in p["nombre"].split()}
        cerca = difflib.get_close_matches(q, list(nombres) + list(palabras), n=3, cutoff=0.6)
        candidatos = list({id(x): x for x in (nombres.get(c) or palabras.get(c) for c in cerca)}.values())
        if len(candidatos) == 1:
            return candidatos[0], []
        return None, candidatos

    # ------------------------------------------------------------ reportes
    def reporte_periodo(self, dias: int) -> str:
        inicio, etiqueta = rango_dias(dias, self.zona)
        pubs = self.db.publicaciones(desde=inicio)
        if not pubs:
            return f"Sin publicaciones {etiqueta}."
        st = estadisticas(pubs)
        lineas = [f"<b>📊 Resumen {etiqueta}</b>",
                  f"{st['total']} publicaciones de {len(st['personas'])} personas · "
                  + ", ".join(f"{NOMBRE_RED[r]} {n}" for r, n in st["redes"].most_common())]
        if st["temas"]:
            lineas.append("🏷 <b>Temas:</b> " + ", ".join(f"{t} ({n})" for t, n in st["temas"].most_common(5)))
        if st["actividades"]:
            lineas.append("📍 <b>Qué hicieron:</b> " + ", ".join(f"{a} ({n})" for a, n in st["actividades"].most_common(5)))
        if st["lugares"]:
            lineas.append("🗺 <b>Lugares:</b> " + ", ".join(f"{l} ({n})" for l, n in st["lugares"].most_common(5)))
        lineas.append("")
        por_persona = defaultdict(list)
        for p in pubs:
            por_persona[p["persona_id"]].append(p)
        orden = sorted(por_persona.values(), key=len, reverse=True)
        for lista in orden:
            nombre, cargo = lista[0]["nombre"], lista[0]["cargo"]
            # el resumen diario usa IA (si hay); los periodos largos van por reglas para ser rapidos
            texto = (self.resumidor.resumir(nombre, cargo, lista, etiqueta)[0] if dias <= 1
                     else resumen_reglas(nombre, lista))
            lineas.append(f"👤 <b>{esc(nombre)}</b> <i>({esc(cargo)})</i>\n{esc(texto)}\n")
        callados = [p["nombre"] for p in self.db.personas() if p["id"] not in por_persona]
        if callados:
            lineas.append("🔇 <i>Sin publicaciones: " + esc(", ".join(callados)) + "</i>")
        return "\n".join(lineas)

    def reporte_persona(self, persona: dict, dias: int = 7) -> str:
        inicio, etiqueta = rango_dias(dias, self.zona)
        pubs = self.db.publicaciones(desde=inicio, persona_id=persona["id"])
        resumen, modelo = self.resumidor.resumir(persona["nombre"], persona["cargo"], pubs, etiqueta)
        redes = " · ".join(f'<a href="{esc(c["url"])}">{NOMBRE_RED[r]}</a>' for r, c in persona["cuentas"].items())
        lineas = [f"👤 <b>{esc(persona['nombre'])}</b> — {esc(persona['cargo'])}", redes, "",
                  f"<b>{etiqueta.capitalize()}</b>" + (" <i>(resumen IA)</i>" if modelo != "reglas" else ""),
                  esc(resumen)]
        if pubs:
            lineas += ["", "<b>Últimas publicaciones</b>"]
            lineas += [self.fmt_pub(p, con_nombre=False, largo=220) + "\n" for p in pubs[:6]]
        else:
            ultima = self.db.publicaciones(persona_id=persona["id"], limite=1)
            if ultima:
                lineas.append(f"\nÚltima publicación registrada: {self._hora(ultima[0]['fecha'])}")
        return "\n".join(lineas)

    def reporte_ranking(self, dias: int) -> str:
        inicio, etiqueta = rango_dias(dias, self.zona)
        pubs = self.db.publicaciones(desde=inicio)
        if not pubs:
            return f"Sin publicaciones {etiqueta}."
        st = estadisticas(pubs)
        por_cant = sorted(st["personas"].items(), key=lambda x: -x[1]["total"])
        por_int = sorted(st["personas"].items(), key=lambda x: -x[1]["interacciones"])
        l = [f"<b>🏆 Ranking {etiqueta}</b>", "", "<b>Más publicaciones</b>"]
        l += [f"{i}. {esc(n)} — {d['total']} ({', '.join(f'{NOMBRE_RED[r]} {c}' for r, c in d['redes'].most_common())})"
              for i, (n, d) in enumerate(por_cant[:10], 1)]
        l += ["", "<b>Más interacciones</b>"]
        l += [f"{i}. {esc(n)} — {d['interacciones']:,}".replace(",", ".") for i, (n, d) in enumerate(por_int[:10], 1)]
        top = sorted(pubs, key=interacciones, reverse=True)[:3]
        l += ["", "<b>Publicaciones con más repercusión</b>"] + [self.fmt_pub(p, largo=160) + "\n" for p in top]
        return "\n".join(l)

    def reporte_temas(self, dias: int) -> str:
        inicio, etiqueta = rango_dias(dias, self.zona)
        pubs = self.db.publicaciones(desde=inicio)
        if not pubs:
            return f"Sin publicaciones {etiqueta}."
        st = estadisticas(pubs)
        l = [f"<b>🏷 Temas {etiqueta}</b>"]
        for tema, n in st["temas"].most_common(10):
            quienes = Counter(p["nombre"] for p in pubs if tema in p["temas"])
            l.append(f"• <b>{esc(tema)}</b> ({n}): " + esc(", ".join(q for q, _ in quienes.most_common(4))))
        if st["hashtags"]:
            l.append("\n#️⃣ " + " ".join(f"#{esc(h)}" for h, _ in st["hashtags"].most_common(12)))
        return "\n".join(l)

    def reporte_estado(self) -> str:
        c = self.db.ultima_corrida()
        l = ["<b>⚙️ Estado</b>"]
        if c:
            l.append(f"Último scraping: {self._hora(c['fin'])} · {c['nuevas']} nuevas · backend {c['backend']}")
            for e in json.loads(c["errores"] or "[]"):
                l.append(f"⚠️ {esc(e)}")
        else:
            l.append("Todavía no se corrió el scraping.")
        malas = [(p["nombre"], r, cu["ultimo_error"]) for p in self.db.personas()
                 for r, cu in p["cuentas"].items() if cu["ultimo_error"]]
        if malas:
            l.append("\n<b>Cuentas con error</b>")
            l += [f"• {esc(n)} ({NOMBRE_RED[r]}): {esc(_corto(e, 120))}" for n, r, e in malas[:20]]
        l.append(f"\nCada {self.bcfg.get('intervalo_horas', 3)} h · resumen diario {self.bcfg.get('resumen_diario_hora', '21:00')}")
        l.append("IA: " + ("activa" if self.resumidor.usa_ia else "no (resúmenes por reglas)"))
        return "\n".join(l)

    # ------------------------------------------------------------ comandos
    def manejar(self, chat_id: int, texto: str, nombre: str = "") -> str | None:
        """Procesa un mensaje y devuelve la respuesta (HTML) o None."""
        texto = (texto or "").strip()
        if chat_id not in self.autorizados:
            return (f"⛔ Este chat no está autorizado.\nTu chat ID es <code>{chat_id}</code>: agregalo a "
                    f"TELEGRAM_CHAT_IDS en monitor_redes/.env y reiniciá el bot.")
        if not texto.startswith("/"):
            persona, _ = self.buscar_persona(texto)
            return self.reporte_persona(persona) if persona else "Escribí /ayuda para ver los comandos."
        cmd, _, arg = texto.partition(" ")
        cmd = cmd.split("@")[0].lower()
        arg = arg.strip()

        def num(defecto, maximo=365):
            for token in arg.split()[::-1]:
                if token.isdigit():
                    return max(1, min(int(token), maximo))
            return defecto

        if cmd == "/start":
            self.db.suscribir(chat_id, nombre)
            return "✅ Listo, vas a recibir los avisos.\n\n" + AYUDA
        if cmd in ("/ayuda", "/help"):
            return AYUDA
        if cmd == "/hoy":
            return self.reporte_periodo(1)
        if cmd == "/semana":
            return self.reporte_periodo(7)
        if cmd == "/persona":
            if not arg:
                return "Uso: /persona <i>nombre</i> [días]. Ej: /persona huesen 3"
            dias = num(7)
            consulta = " ".join(t for t in arg.split() if not t.isdigit())
            persona, opciones = self.buscar_persona(consulta)
            if persona:
                return self.reporte_persona(persona, dias)
            if opciones:
                return "¿Cuál?\n" + "\n".join(f"• {esc(p['nombre'])} ({esc(p['cargo'])})" for p in opciones)
            return f"No encontré a «{esc(consulta)}». Mirá /personas."
        if cmd == "/ultimas":
            pubs = self.db.publicaciones(limite=num(10, 30))
            return "\n\n".join(self.fmt_pub(p) for p in pubs) or "Todavía no hay publicaciones."
        if cmd == "/buscar":
            if not arg:
                return "Uso: /buscar <i>texto</i>"
            pubs = self.db.buscar(arg, 15)
            if not pubs:
                return f"Nada con «{esc(arg)}»."
            return f"🔎 <b>{len(pubs)} resultados para «{esc(arg)}»</b>\n\n" + "\n\n".join(self.fmt_pub(p) for p in pubs)
        if cmd == "/temas":
            return self.reporte_temas(num(7))
        if cmd == "/ranking":
            return self.reporte_ranking(num(7))
        if cmd == "/personas":
            return "<b>Personas monitoreadas</b>\n" + "\n".join(
                f"• {esc(p['nombre'])} — {esc(p['cargo'])} " + "".join(ICONO[r] for r in p["cuentas"])
                for p in self.db.personas())
        if cmd == "/alerta":
            if not arg:
                return "Uso: /alerta <i>palabra</i> (ej: /alerta jaldo)"
            self.db.agregar_alerta(chat_id, normalizar(arg))
            return f"🔔 Te aviso cuando alguien publique «{esc(arg)}»."
        if cmd == "/alertas":
            pal = self.db.alertas(chat_id)
            return ("🔔 Tus alertas: " + ", ".join(esc(p) for p in pal)) if pal else "No tenés alertas. Usá /alerta <i>palabra</i>."
        if cmd == "/quitar":
            self.db.quitar_alerta(chat_id, normalizar(arg))
            return f"Listo, ya no aviso por «{esc(arg)}»."
        if cmd == "/silenciar":
            self.db.set_avisos(chat_id, False)
            return "🔕 Avisos pausados. /activar para reanudar."
        if cmd == "/activar":
            self.db.suscribir(chat_id, nombre)
            self.db.set_avisos(chat_id, True)
            return "🔔 Avisos activados."
        if cmd == "/estado":
            return self.reporte_estado()
        if cmd == "/actualizar":
            if self.lock_scrap.locked():
                return "⏳ Ya hay un scraping en curso."
            self.despertar.set()
            return "⏳ Scrapeando ahora. Te aviso las novedades cuando termine (puede tardar varios minutos)."
        if cmd == "/dashboard":
            self.enviar_dashboard(chat_id)
            return None
        return "No conozco ese comando. /ayuda"

    def enviar_dashboard(self, chat_id: int) -> None:
        ruta = generar_dashboard(self.cfg, self.db, resumidor=self.resumidor)
        with open(ruta, "rb") as f:
            try:
                self.api.llamar("sendDocument", archivos={"document": ("dashboard.html", f, "text/html")},
                                chat_id=chat_id, caption="Dashboard actualizado: abrilo en el navegador.", _http=120)
            except Exception as e:
                self.enviar(chat_id, f"No pude mandar el dashboard: {esc(e)}")

    # ------------------------------------------------------------ avisos
    def avisar_novedades(self) -> int:
        pendientes = self.db.no_notificadas()
        if not pendientes:
            return 0
        if self.db.get_estado("primer_aviso") is None:
            # primera carga: no inundar con todo el historico
            self.db.marcar_todo_notificado()
            self.db.set_estado("primer_aviso", datetime.now(timezone.utc).isoformat())
            self.difundir(f"📥 Carga inicial lista: {len(pendientes)} publicaciones guardadas. "
                          f"Desde ahora te aviso solo lo nuevo. Probá /semana.")
            return 0
        maximo = self.bcfg.get("max_publicaciones_por_aviso", 15)
        recientes = sorted(pendientes, key=lambda p: p["fecha"], reverse=True)
        cuerpo = [f"🆕 <b>{len(pendientes)} publicaciones nuevas</b>"]
        por_persona = defaultdict(list)
        for p in recientes[:maximo]:
            por_persona[p["nombre"]].append(p)
        for nombre, lista in por_persona.items():
            cuerpo.append("")
            cuerpo += [self.fmt_pub(p) for p in lista]
        if len(pendientes) > maximo:
            cuerpo.append(f"\n… y {len(pendientes) - maximo} más. /ultimas 30 o /dashboard")
        mensaje = "\n".join(cuerpo)
        for s in self.db.suscriptores():
            if s["chat_id"] not in self.autorizados:
                continue
            self.enviar(s["chat_id"], mensaje)
            palabras = self.db.alertas(s["chat_id"])
            for pal in palabras:
                hits = [p for p in pendientes if pal in normalizar(p["texto"] + " " + " ".join(p["hashtags"]))]
                if hits:
                    self.enviar(s["chat_id"], f"🔔 <b>Alerta «{esc(pal)}»</b>\n\n" + "\n\n".join(self.fmt_pub(p) for p in hits[:10]))
        self.db.marcar_notificadas([p["id"] for p in pendientes])
        return len(pendientes)

    def ciclo_scraping(self) -> None:
        if not self.lock_scrap.acquire(blocking=False):
            return
        try:
            res = recolectar(self.cfg, self.db, backend=self.backend)
            self.avisar_novedades()
            if res["errores"]:
                self.difundir("⚠️ Errores en el scraping:\n" + "\n".join(esc(e) for e in res["errores"]))
            try:
                generar_dashboard(self.cfg, self.db, resumidor=self.resumidor)
            except Exception as e:
                log.error("Dashboard: %s", e)
        except Exception as e:
            log.exception("Ciclo de scraping fallo")
            self.difundir(f"⚠️ Falló el scraping: {esc(e)}")
        finally:
            self.lock_scrap.release()

    def tal_vez_resumen_diario(self) -> None:
        hora = self.bcfg.get("resumen_diario_hora")
        if not hora:
            return
        ahora = datetime.now(self.zona)
        hoy = ahora.strftime("%Y-%m-%d")
        if ahora.strftime("%H:%M") >= hora and self.db.get_estado("resumen_diario") != hoy:
            self.db.set_estado("resumen_diario", hoy)
            self.difundir(self.reporte_periodo(1))

    def _planificador(self) -> None:
        intervalo = float(self.bcfg.get("intervalo_horas", 3)) * 3600
        proxima = time.monotonic()  # primera corrida al arrancar
        while not self.parar.is_set():
            if time.monotonic() >= proxima or self.despertar.is_set():
                self.despertar.clear()
                self.ciclo_scraping()
                proxima = time.monotonic() + intervalo
            self.tal_vez_resumen_diario()
            self.despertar.wait(timeout=30)

    # ------------------------------------------------------------ loop
    def correr(self) -> None:
        yo = self.api.llamar("getMe")
        log.info("Bot @%s iniciado. Chats autorizados: %s", yo.get("username"), sorted(self.autorizados) or "ninguno")
        if not self.autorizados:
            log.warning("TELEGRAM_CHAT_IDS vacío: mandale /start al bot para conocer tu chat ID")
        for cid in self.autorizados:
            self.db.suscribir(cid, "")
        self.api.llamar("setMyCommands", commands=[
            {"command": c, "description": d} for c, d in [
                ("hoy", "Resumen de hoy"), ("semana", "Resumen 7 días"), ("persona", "Qué hizo alguien"),
                ("ultimas", "Últimas publicaciones"), ("buscar", "Buscar texto"), ("temas", "Temas"),
                ("ranking", "Ranking"), ("personas", "Lista"), ("alerta", "Alerta por palabra"),
                ("actualizar", "Scrapear ahora"), ("estado", "Estado"), ("dashboard", "Dashboard"),
                ("ayuda", "Ayuda")]])
        threading.Thread(target=self._planificador, daemon=True, name="planificador").start()
        offset = None
        while not self.parar.is_set():
            try:
                updates = self.api.llamar("getUpdates", _http=70, offset=offset, timeout=50,
                                          allowed_updates=["message"])
            except Exception as e:
                log.warning("getUpdates: %s", e)
                time.sleep(5)
                continue
            for u in updates:
                offset = u["update_id"] + 1
                msg = u.get("message") or {}
                chat = msg.get("chat") or {}
                if not msg.get("text") or "id" not in chat:
                    continue
                quien = chat.get("first_name") or chat.get("title") or ""
                try:
                    resp = self.manejar(chat["id"], msg["text"], quien)
                except Exception as e:
                    log.exception("Error manejando %r", msg.get("text"))
                    resp = f"⚠️ Error: {esc(e)}"
                if resp:
                    self.enviar(chat["id"], resp)
