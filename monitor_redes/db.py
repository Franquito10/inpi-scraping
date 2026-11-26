"""Persistencia SQLite de personas, publicaciones, corridas y suscriptores del bot."""

import json
import sqlite3
import threading
from pathlib import Path
from datetime import datetime, timedelta, timezone

ESQUEMA = """
CREATE TABLE IF NOT EXISTS personas (
    id INTEGER PRIMARY KEY,
    slug TEXT UNIQUE NOT NULL,
    nombre TEXT NOT NULL,
    cargo TEXT
);
CREATE TABLE IF NOT EXISTS cuentas (
    persona_id INTEGER NOT NULL REFERENCES personas(id),
    plataforma TEXT NOT NULL,
    url TEXT NOT NULL,
    usuario TEXT,
    ultimo_scrapeo TEXT,
    ultimo_error TEXT,
    PRIMARY KEY (persona_id, plataforma)
);
CREATE TABLE IF NOT EXISTS publicaciones (
    id INTEGER PRIMARY KEY,
    plataforma TEXT NOT NULL,
    post_id TEXT NOT NULL,
    persona_id INTEGER NOT NULL REFERENCES personas(id),
    url TEXT,
    texto TEXT,
    fecha TEXT,              -- ISO UTC de publicacion
    tipo TEXT,               -- post | video | reel | foto | tweet | retweet | ...
    likes INTEGER DEFAULT 0,
    comentarios INTEGER DEFAULT 0,
    compartidos INTEGER DEFAULT 0,
    vistas INTEGER DEFAULT 0,
    hashtags TEXT DEFAULT '[]',
    menciones TEXT DEFAULT '[]',
    media_url TEXT,
    temas TEXT DEFAULT '[]',
    actividades TEXT DEFAULT '[]',
    lugares TEXT DEFAULT '[]',
    detectado TEXT NOT NULL, -- cuando lo vimos por primera vez
    notificado INTEGER DEFAULT 0,
    raw TEXT,
    UNIQUE (plataforma, post_id)
);
CREATE INDEX IF NOT EXISTS ix_pub_fecha ON publicaciones(fecha);
CREATE INDEX IF NOT EXISTS ix_pub_persona ON publicaciones(persona_id);
CREATE TABLE IF NOT EXISTS corridas (
    id INTEGER PRIMARY KEY,
    inicio TEXT, fin TEXT, backend TEXT,
    nuevas INTEGER DEFAULT 0, actualizadas INTEGER DEFAULT 0, errores TEXT DEFAULT '[]'
);
CREATE TABLE IF NOT EXISTS resumenes (
    persona_id INTEGER NOT NULL, fecha TEXT NOT NULL, texto TEXT, modelo TEXT, creado TEXT,
    PRIMARY KEY (persona_id, fecha)
);
CREATE TABLE IF NOT EXISTS suscriptores (
    chat_id INTEGER PRIMARY KEY, nombre TEXT, avisos INTEGER DEFAULT 1, alta TEXT
);
CREATE TABLE IF NOT EXISTS palabras_alerta (
    chat_id INTEGER NOT NULL, palabra TEXT NOT NULL, PRIMARY KEY (chat_id, palabra)
);
CREATE TABLE IF NOT EXISTS estado (clave TEXT PRIMARY KEY, valor TEXT);
"""

CAMPOS_JSON = ("hashtags", "menciones", "temas", "actividades", "lugares")


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class DB:
    def __init__(self, ruta: Path):
        ruta = Path(ruta)
        ruta.parent.mkdir(parents=True, exist_ok=True)
        self.con = sqlite3.connect(ruta, check_same_thread=False)
        self.con.row_factory = sqlite3.Row
        self.lock = threading.RLock()
        with self.lock:
            self.con.executescript(ESQUEMA)

    # ---------- personas ----------
    def sincronizar_personas(self, personas: list[dict]) -> None:
        with self.lock, self.con:
            for p in personas:
                self.con.execute(
                    "INSERT INTO personas(slug, nombre, cargo) VALUES (?,?,?) "
                    "ON CONFLICT(slug) DO UPDATE SET nombre=excluded.nombre, cargo=excluded.cargo",
                    (p["slug"], p["nombre"], p["cargo"]))
                pid = self.persona_id(p["slug"])
                for red, c in p["cuentas"].items():
                    self.con.execute(
                        "INSERT INTO cuentas(persona_id, plataforma, url, usuario) VALUES (?,?,?,?) "
                        "ON CONFLICT(persona_id, plataforma) DO UPDATE SET url=excluded.url, usuario=excluded.usuario",
                        (pid, red, c["url"], c["usuario"]))

    def persona_id(self, slug: str) -> int | None:
        r = self.con.execute("SELECT id FROM personas WHERE slug=?", (slug,)).fetchone()
        return r["id"] if r else None

    def personas(self) -> list[dict]:
        with self.lock:
            rows = self.con.execute("SELECT * FROM personas ORDER BY nombre").fetchall()
            out = []
            for r in rows:
                d = dict(r)
                d["cuentas"] = {c["plataforma"]: dict(c) for c in self.con.execute(
                    "SELECT * FROM cuentas WHERE persona_id=?", (r["id"],))}
                out.append(d)
            return out

    def marcar_cuenta(self, persona_id: int, plataforma: str, error: str | None) -> None:
        with self.lock, self.con:
            self.con.execute(
                "UPDATE cuentas SET ultimo_scrapeo=?, ultimo_error=? WHERE persona_id=? AND plataforma=?",
                (_iso(datetime.now(timezone.utc)), error, persona_id, plataforma))

    # ---------- publicaciones ----------
    def guardar_publicacion(self, pub: dict) -> bool:
        """Inserta o actualiza metricas. Devuelve True si es nueva."""
        datos = dict(pub)
        for k in CAMPOS_JSON:
            datos[k] = json.dumps(datos.get(k) or [], ensure_ascii=False)
        datos["raw"] = json.dumps(datos.get("raw") or {}, ensure_ascii=False, default=str)[:20000]
        datos.setdefault("detectado", _iso(datetime.now(timezone.utc)))
        with self.lock, self.con:
            existe = self.con.execute(
                "SELECT id FROM publicaciones WHERE plataforma=? AND post_id=?",
                (datos["plataforma"], datos["post_id"])).fetchone()
            if existe:
                self.con.execute(
                    "UPDATE publicaciones SET likes=?, comentarios=?, compartidos=?, vistas=?, "
                    "texto=COALESCE(NULLIF(?, ''), texto) WHERE id=?",
                    (datos.get("likes", 0), datos.get("comentarios", 0), datos.get("compartidos", 0),
                     datos.get("vistas", 0), datos.get("texto", ""), existe["id"]))
                return False
            cols = ["plataforma", "post_id", "persona_id", "url", "texto", "fecha", "tipo", "likes",
                    "comentarios", "compartidos", "vistas", "hashtags", "menciones", "media_url",
                    "temas", "actividades", "lugares", "detectado", "notificado", "raw"]
            datos.setdefault("notificado", 0)
            self.con.execute(
                f"INSERT INTO publicaciones({','.join(cols)}) VALUES ({','.join('?' * len(cols))})",
                [datos.get(c) for c in cols])
            return True

    def actualizar_clasificacion(self, pub_id: int, temas, actividades, lugares) -> None:
        with self.lock, self.con:
            self.con.execute(
                "UPDATE publicaciones SET temas=?, actividades=?, lugares=? WHERE id=?",
                (json.dumps(temas, ensure_ascii=False), json.dumps(actividades, ensure_ascii=False),
                 json.dumps(lugares, ensure_ascii=False), pub_id))

    def _filas(self, sql: str, params=()) -> list[dict]:
        with self.lock:
            out = []
            for r in self.con.execute(sql, params).fetchall():
                d = dict(r)
                for k in CAMPOS_JSON:
                    if k in d:
                        d[k] = json.loads(d[k] or "[]")
                d.pop("raw", None)
                out.append(d)
            return out

    SELECT_PUB = ("SELECT p.*, pe.nombre, pe.cargo, pe.slug FROM publicaciones p "
                  "JOIN personas pe ON pe.id = p.persona_id ")

    def publicaciones(self, desde: datetime | None = None, persona_id: int | None = None,
                      limite: int | None = None) -> list[dict]:
        sql, params, cond = self.SELECT_PUB, [], []
        if desde:
            cond.append("p.fecha >= ?")
            params.append(_iso(desde))
        if persona_id:
            cond.append("p.persona_id = ?")
            params.append(persona_id)
        if cond:
            sql += "WHERE " + " AND ".join(cond)
        sql += " ORDER BY p.fecha DESC"
        if limite:
            sql += f" LIMIT {int(limite)}"
        return self._filas(sql, params)

    def buscar(self, texto: str, limite: int = 15) -> list[dict]:
        return self._filas(self.SELECT_PUB + "WHERE p.texto LIKE ? ORDER BY p.fecha DESC LIMIT ?",
                           (f"%{texto}%", limite))

    def no_notificadas(self) -> list[dict]:
        return self._filas(self.SELECT_PUB + "WHERE p.notificado = 0 ORDER BY p.fecha ASC")

    def marcar_notificadas(self, ids: list[int]) -> None:
        if not ids:
            return
        with self.lock, self.con:
            self.con.executemany("UPDATE publicaciones SET notificado=1 WHERE id=?", [(i,) for i in ids])

    def marcar_todo_notificado(self) -> None:
        with self.lock, self.con:
            self.con.execute("UPDATE publicaciones SET notificado=1")

    # ---------- corridas ----------
    def registrar_corrida(self, inicio, fin, backend, nuevas, actualizadas, errores) -> None:
        with self.lock, self.con:
            self.con.execute(
                "INSERT INTO corridas(inicio, fin, backend, nuevas, actualizadas, errores) VALUES (?,?,?,?,?,?)",
                (_iso(inicio), _iso(fin), backend, nuevas, actualizadas, json.dumps(errores, ensure_ascii=False)))

    def ultima_corrida(self) -> dict | None:
        r = self.con.execute("SELECT * FROM corridas ORDER BY id DESC LIMIT 1").fetchone()
        return dict(r) if r else None

    # ---------- resumenes ----------
    def guardar_resumen(self, persona_id: int, fecha: str, texto: str, modelo: str) -> None:
        with self.lock, self.con:
            self.con.execute(
                "INSERT OR REPLACE INTO resumenes VALUES (?,?,?,?,?)",
                (persona_id, fecha, texto, modelo, _iso(datetime.now(timezone.utc))))

    def resumen(self, persona_id: int, fecha: str) -> dict | None:
        r = self.con.execute("SELECT * FROM resumenes WHERE persona_id=? AND fecha=?",
                             (persona_id, fecha)).fetchone()
        return dict(r) if r else None

    # ---------- bot ----------
    def suscribir(self, chat_id: int, nombre: str) -> None:
        with self.lock, self.con:
            self.con.execute(
                "INSERT INTO suscriptores(chat_id, nombre, avisos, alta) VALUES (?,?,1,?) "
                "ON CONFLICT(chat_id) DO UPDATE SET nombre=excluded.nombre",
                (chat_id, nombre, _iso(datetime.now(timezone.utc))))

    def set_avisos(self, chat_id: int, activos: bool) -> None:
        with self.lock, self.con:
            self.con.execute("UPDATE suscriptores SET avisos=? WHERE chat_id=?", (int(activos), chat_id))

    def suscriptores(self, solo_activos: bool = True) -> list[dict]:
        sql = "SELECT * FROM suscriptores" + (" WHERE avisos=1" if solo_activos else "")
        return [dict(r) for r in self.con.execute(sql).fetchall()]

    def agregar_alerta(self, chat_id: int, palabra: str) -> None:
        with self.lock, self.con:
            self.con.execute("INSERT OR IGNORE INTO palabras_alerta VALUES (?,?)", (chat_id, palabra))

    def quitar_alerta(self, chat_id: int, palabra: str) -> None:
        with self.lock, self.con:
            self.con.execute("DELETE FROM palabras_alerta WHERE chat_id=? AND palabra=?", (chat_id, palabra))

    def alertas(self, chat_id: int) -> list[str]:
        return [r["palabra"] for r in self.con.execute(
            "SELECT palabra FROM palabras_alerta WHERE chat_id=? ORDER BY palabra", (chat_id,))]

    def get_estado(self, clave: str, defecto: str | None = None) -> str | None:
        r = self.con.execute("SELECT valor FROM estado WHERE clave=?", (clave,)).fetchone()
        return r["valor"] if r else defecto

    def set_estado(self, clave: str, valor: str) -> None:
        with self.lock, self.con:
            self.con.execute("INSERT OR REPLACE INTO estado VALUES (?,?)", (clave, valor))


def hace(dias: float) -> datetime:
    return datetime.now(timezone.utc) - timedelta(days=dias)
