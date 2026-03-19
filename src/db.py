"""
Persistencia SQLite para tracking de boletines procesados,
coincidencias encontradas y estados de revision humana.
"""

import sqlite3
import json
from datetime import datetime
from pathlib import Path
from typing import Optional


class BaseDatos:
    def __init__(self, ruta_db: Path):
        self.ruta = ruta_db
        self.ruta.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.ruta))
        self.conn.row_factory = sqlite3.Row
        self._crear_tablas()

    def _crear_tablas(self):
        cursor = self.conn.cursor()
        cursor.executescript("""
            CREATE TABLE IF NOT EXISTS boletines (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                id_inpi TEXT UNIQUE NOT NULL,
                titulo TEXT,
                fecha_publicacion TEXT,
                comentario TEXT,
                url_descarga TEXT,
                archivo_local TEXT,
                fecha_descarga TEXT,
                estado TEXT DEFAULT 'descargado',
                hash_archivo TEXT
            );

            CREATE TABLE IF NOT EXISTS coincidencias (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                id_boletin INTEGER REFERENCES boletines(id),
                marca_vigilada TEXT NOT NULL,
                marca_detectada TEXT,
                pagina INTEGER,
                tipo_match TEXT,
                score_texto REAL DEFAULT 0,
                score_fonetico REAL DEFAULT 0,
                score_visual REAL DEFAULT 0,
                score_color REAL DEFAULT 0,
                score_final REAL DEFAULT 0,
                nivel_riesgo TEXT,
                explicacion TEXT,
                imagen_extraida TEXT,
                clase_niza TEXT,
                tipo_marca TEXT,
                fecha_deteccion TEXT,
                metadata JSON
            );

            CREATE TABLE IF NOT EXISTS revisiones (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                id_coincidencia INTEGER REFERENCES coincidencias(id),
                estado TEXT DEFAULT 'pendiente',
                prioridad TEXT DEFAULT 'normal',
                comentario TEXT,
                decision TEXT,
                revisado_por TEXT,
                fecha_revision TEXT
            );

            CREATE TABLE IF NOT EXISTS ejecuciones (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                fecha_inicio TEXT,
                fecha_fin TEXT,
                boletines_procesados INTEGER DEFAULT 0,
                coincidencias_encontradas INTEGER DEFAULT 0,
                estado TEXT,
                detalle TEXT
            );

            CREATE INDEX IF NOT EXISTS idx_boletin_inpi ON boletines(id_inpi);
            CREATE INDEX IF NOT EXISTS idx_coincidencia_marca ON coincidencias(marca_vigilada);
            CREATE INDEX IF NOT EXISTS idx_coincidencia_score ON coincidencias(score_final);
            CREATE INDEX IF NOT EXISTS idx_revision_estado ON revisiones(estado);
        """)
        self.conn.commit()

    # --- Boletines ---

    def boletin_existe(self, id_inpi: str) -> bool:
        cur = self.conn.execute(
            "SELECT 1 FROM boletines WHERE id_inpi = ?", (id_inpi,)
        )
        return cur.fetchone() is not None

    def registrar_boletin(self, id_inpi: str, titulo: str, fecha_pub: str,
                          comentario: str, url: str, archivo: str,
                          hash_archivo: str = "") -> int:
        cur = self.conn.execute("""
            INSERT OR IGNORE INTO boletines
            (id_inpi, titulo, fecha_publicacion, comentario, url_descarga,
             archivo_local, fecha_descarga, hash_archivo)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (id_inpi, titulo, fecha_pub, comentario, url, archivo,
              datetime.now().isoformat(), hash_archivo))
        self.conn.commit()
        return cur.lastrowid

    def marcar_boletin_procesado(self, id_inpi: str):
        self.conn.execute(
            "UPDATE boletines SET estado = 'procesado' WHERE id_inpi = ?",
            (id_inpi,)
        )
        self.conn.commit()

    def obtener_boletines_pendientes(self) -> list[dict]:
        cur = self.conn.execute(
            "SELECT * FROM boletines WHERE estado = 'descargado' ORDER BY fecha_publicacion"
        )
        return [dict(row) for row in cur.fetchall()]

    def obtener_todos_boletines(self) -> list[dict]:
        cur = self.conn.execute("SELECT * FROM boletines ORDER BY fecha_publicacion DESC")
        return [dict(row) for row in cur.fetchall()]

    # --- Coincidencias ---

    def registrar_coincidencia(self, id_boletin: int, marca_vigilada: str,
                               marca_detectada: str, pagina: int,
                               tipo_match: str, scores: dict,
                               score_final: float, nivel_riesgo: str,
                               explicacion: str, imagen: str = "",
                               clase_niza: str = "", tipo_marca: str = "",
                               metadata: dict = None) -> int:
        cur = self.conn.execute("""
            INSERT INTO coincidencias
            (id_boletin, marca_vigilada, marca_detectada, pagina, tipo_match,
             score_texto, score_fonetico, score_visual, score_color,
             score_final, nivel_riesgo, explicacion, imagen_extraida,
             clase_niza, tipo_marca, fecha_deteccion, metadata)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (id_boletin, marca_vigilada, marca_detectada, pagina, tipo_match,
              scores.get("texto", 0), scores.get("fonetico", 0),
              scores.get("visual", 0), scores.get("color", 0),
              score_final, nivel_riesgo, explicacion, imagen,
              clase_niza, tipo_marca, datetime.now().isoformat(),
              json.dumps(metadata or {})))
        self.conn.commit()

        # Crear entrada de revision automatica
        self.conn.execute("""
            INSERT INTO revisiones (id_coincidencia, estado, prioridad, fecha_revision)
            VALUES (?, 'pendiente', ?, ?)
        """, (cur.lastrowid,
              "alta" if score_final >= 0.75 else ("normal" if score_final >= 0.55 else "baja"),
              datetime.now().isoformat()))
        self.conn.commit()
        return cur.lastrowid

    def obtener_coincidencias(self, id_boletin: Optional[int] = None,
                              marca: Optional[str] = None,
                              min_score: float = 0) -> list[dict]:
        query = "SELECT c.*, r.estado as estado_revision, r.comentario as comentario_revision, r.decision FROM coincidencias c LEFT JOIN revisiones r ON r.id_coincidencia = c.id GROUP BY c.id HAVING 1=1"
        params = []
        if id_boletin:
            query += " AND c.id_boletin = ?"
            params.append(id_boletin)
        if marca:
            query += " AND c.marca_vigilada = ?"
            params.append(marca)
        if min_score > 0:
            query += " AND c.score_final >= ?"
            params.append(min_score)
        query += " ORDER BY c.score_final DESC"
        cur = self.conn.execute(query, params)
        return [dict(row) for row in cur.fetchall()]

    def obtener_todas_coincidencias(self) -> list[dict]:
        return self.obtener_coincidencias()

    # --- Revisiones ---

    def actualizar_revision(self, id_coincidencia: int, estado: str,
                            comentario: str = "", decision: str = "",
                            revisado_por: str = ""):
        self.conn.execute("""
            UPDATE revisiones SET estado = ?, comentario = ?,
            decision = ?, revisado_por = ?, fecha_revision = ?
            WHERE id_coincidencia = ?
        """, (estado, comentario, decision, revisado_por,
              datetime.now().isoformat(), id_coincidencia))
        self.conn.commit()

    # --- Ejecuciones ---

    def registrar_ejecucion(self, boletines: int, coincidencias: int,
                            estado: str, detalle: str = "") -> int:
        cur = self.conn.execute("""
            INSERT INTO ejecuciones
            (fecha_inicio, fecha_fin, boletines_procesados,
             coincidencias_encontradas, estado, detalle)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (datetime.now().isoformat(), datetime.now().isoformat(),
              boletines, coincidencias, estado, detalle))
        self.conn.commit()
        return cur.lastrowid

    def obtener_estadisticas(self) -> dict:
        stats = {}
        cur = self.conn.execute("SELECT COUNT(*) FROM boletines")
        stats["total_boletines"] = cur.fetchone()[0]
        cur = self.conn.execute("SELECT COUNT(*) FROM boletines WHERE estado = 'procesado'")
        stats["boletines_procesados"] = cur.fetchone()[0]
        cur = self.conn.execute("SELECT COUNT(*) FROM coincidencias")
        stats["total_coincidencias"] = cur.fetchone()[0]
        cur = self.conn.execute("SELECT COUNT(*) FROM revisiones WHERE estado = 'pendiente'")
        stats["pendientes_revision"] = cur.fetchone()[0]
        cur = self.conn.execute(
            "SELECT marca_vigilada, COUNT(*) as cnt FROM coincidencias GROUP BY marca_vigilada ORDER BY cnt DESC"
        )
        stats["por_marca"] = [dict(row) for row in cur.fetchall()]
        return stats

    def cerrar(self):
        self.conn.close()
