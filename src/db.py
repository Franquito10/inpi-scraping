"""
Persistencia SQLite para tracking de boletines procesados,
coincidencias encontradas, estados de revision humana,
y analisis IA legal.
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

            CREATE TABLE IF NOT EXISTS analisis_ia (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                id_coincidencia INTEGER UNIQUE REFERENCES coincidencias(id),
                riesgo_preliminar TEXT,
                confundibilidad_preliminar TEXT,
                similitud_denominativa TEXT,
                similitud_fonetica TEXT,
                similitud_conceptual TEXT,
                similitud_visual TEXT,
                argumentos_a_favor JSON,
                argumentos_en_contra JSON,
                recomendacion_operativa TEXT,
                resumen_ejecutivo TEXT,
                modelo_usado TEXT,
                proveedor TEXT,
                fecha_analisis TEXT,
                version_prompt TEXT,
                tokens_usados INTEGER DEFAULT 0,
                feedback_incorporado INTEGER DEFAULT 0,
                error TEXT,
                disclaimer TEXT
            );

            CREATE TABLE IF NOT EXISTS ejecuciones (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                fecha_inicio TEXT,
                fecha_fin TEXT,
                boletines_procesados INTEGER DEFAULT 0,
                coincidencias_encontradas INTEGER DEFAULT 0,
                analisis_ia_generados INTEGER DEFAULT 0,
                estado TEXT,
                detalle TEXT
            );

            CREATE INDEX IF NOT EXISTS idx_boletin_inpi ON boletines(id_inpi);
            CREATE INDEX IF NOT EXISTS idx_coincidencia_marca ON coincidencias(marca_vigilada);
            CREATE INDEX IF NOT EXISTS idx_coincidencia_score ON coincidencias(score_final);
            CREATE INDEX IF NOT EXISTS idx_revision_estado ON revisiones(estado);
            CREATE INDEX IF NOT EXISTS idx_analisis_coincidencia ON analisis_ia(id_coincidencia);
            CREATE INDEX IF NOT EXISTS idx_revision_decision ON revisiones(decision);
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
        query = """
            SELECT c.*,
                   r.estado as estado_revision,
                   r.comentario as comentario_revision,
                   r.decision
            FROM coincidencias c
            LEFT JOIN revisiones r ON r.id_coincidencia = c.id
            WHERE 1=1
        """
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
        query += " GROUP BY c.id ORDER BY c.score_final DESC"
        cur = self.conn.execute(query, params)
        return [dict(row) for row in cur.fetchall()]

    def obtener_todas_coincidencias(self) -> list[dict]:
        return self.obtener_coincidencias()

    def obtener_coincidencia(self, id_coincidencia: int) -> Optional[dict]:
        cur = self.conn.execute(
            "SELECT * FROM coincidencias WHERE id = ?", (id_coincidencia,)
        )
        row = cur.fetchone()
        return dict(row) if row else None

    def obtener_coincidencias_sin_analisis_ia(self) -> list[dict]:
        """Coincidencias que no tienen analisis IA o cuyo analisis tiene error."""
        cur = self.conn.execute("""
            SELECT c.*,
                   r.estado as estado_revision,
                   r.comentario as comentario_revision,
                   r.decision
            FROM coincidencias c
            LEFT JOIN revisiones r ON r.id_coincidencia = c.id
            LEFT JOIN analisis_ia a ON a.id_coincidencia = c.id
            WHERE a.id IS NULL OR (a.error IS NOT NULL AND a.error != '')
            GROUP BY c.id
            ORDER BY c.score_final DESC
        """)
        return [dict(row) for row in cur.fetchall()]

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

    # --- Analisis IA ---

    def guardar_analisis_ia(self, analisis) -> int:
        """Guarda o actualiza un analisis IA. Acepta AnalisisIALegal o dict."""
        if hasattr(analisis, "to_dict"):
            data = analisis.to_dict()
        else:
            data = analisis

        # Upsert: si ya existe para esta coincidencia, reemplazar
        self.conn.execute("DELETE FROM analisis_ia WHERE id_coincidencia = ?",
                          (data.get("id_coincidencia", 0),))

        self.conn.execute("""
            INSERT INTO analisis_ia
            (id_coincidencia, riesgo_preliminar, confundibilidad_preliminar,
             similitud_denominativa, similitud_fonetica, similitud_conceptual,
             similitud_visual, argumentos_a_favor, argumentos_en_contra,
             recomendacion_operativa, resumen_ejecutivo, modelo_usado,
             proveedor, fecha_analisis, version_prompt, tokens_usados,
             feedback_incorporado, error, disclaimer)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            data.get("id_coincidencia", 0),
            data.get("riesgo_preliminar", ""),
            data.get("confundibilidad_preliminar", ""),
            data.get("similitud_denominativa", ""),
            data.get("similitud_fonetica", ""),
            data.get("similitud_conceptual", ""),
            data.get("similitud_visual", ""),
            json.dumps(data.get("argumentos_a_favor", [])),
            json.dumps(data.get("argumentos_en_contra", [])),
            data.get("recomendacion_operativa", ""),
            data.get("resumen_ejecutivo", ""),
            data.get("modelo_usado", ""),
            data.get("proveedor", ""),
            data.get("fecha_analisis", datetime.now().isoformat()),
            data.get("version_prompt", "2.0"),
            data.get("tokens_usados", 0),
            1 if data.get("feedback_incorporado") else 0,
            data.get("error", ""),
            data.get("disclaimer", ""),
        ))
        self.conn.commit()
        return self.conn.execute("SELECT last_insert_rowid()").fetchone()[0]

    def obtener_analisis_ia(self, id_coincidencia: int) -> Optional[dict]:
        """Obtiene el analisis IA para una coincidencia."""
        cur = self.conn.execute(
            "SELECT * FROM analisis_ia WHERE id_coincidencia = ?",
            (id_coincidencia,)
        )
        row = cur.fetchone()
        if not row:
            return None
        d = dict(row)
        # Deserializar JSON
        try:
            d["argumentos_a_favor"] = json.loads(d.get("argumentos_a_favor", "[]"))
        except (json.JSONDecodeError, TypeError):
            d["argumentos_a_favor"] = []
        try:
            d["argumentos_en_contra"] = json.loads(d.get("argumentos_en_contra", "[]"))
        except (json.JSONDecodeError, TypeError):
            d["argumentos_en_contra"] = []
        return d

    def obtener_todos_analisis_ia(self) -> list[dict]:
        """Obtiene todos los analisis IA."""
        cur = self.conn.execute(
            "SELECT * FROM analisis_ia ORDER BY fecha_analisis DESC"
        )
        resultados = []
        for row in cur.fetchall():
            d = dict(row)
            try:
                d["argumentos_a_favor"] = json.loads(d.get("argumentos_a_favor", "[]"))
            except (json.JSONDecodeError, TypeError):
                d["argumentos_a_favor"] = []
            try:
                d["argumentos_en_contra"] = json.loads(d.get("argumentos_en_contra", "[]"))
            except (json.JSONDecodeError, TypeError):
                d["argumentos_en_contra"] = []
            resultados.append(d)
        return resultados

    # --- Feedback historico (para learning loop) ---

    def obtener_feedback_para_par(self, marca_vigilada: str,
                                   marca_detectada: str,
                                   limite: int = 10) -> list[dict]:
        """
        Obtiene historial de decisiones humanas para un par de marcas.
        Busca:
        1. Coincidencias exactas del mismo par
        2. Coincidencias donde la marca vigilada es la misma (patrones)
        Incluye: decision, estado, comentario, fecha.
        """
        resultados = []

        # Primero: mismo par exacto
        cur = self.conn.execute("""
            SELECT c.marca_vigilada, c.marca_detectada, c.score_final,
                   r.estado, r.decision, r.comentario, r.fecha_revision,
                   r.revisado_por
            FROM coincidencias c
            JOIN revisiones r ON r.id_coincidencia = c.id
            WHERE c.marca_vigilada = ?
              AND c.marca_detectada = ?
              AND r.estado != 'pendiente'
            ORDER BY r.fecha_revision DESC
            LIMIT ?
        """, (marca_vigilada, marca_detectada, limite))
        resultados.extend([dict(row) for row in cur.fetchall()])

        # Segundo: misma marca vigilada, otros detectados (para patrones)
        if len(resultados) < limite:
            restantes = limite - len(resultados)
            cur = self.conn.execute("""
                SELECT c.marca_vigilada, c.marca_detectada, c.score_final,
                       r.estado, r.decision, r.comentario, r.fecha_revision,
                       r.revisado_por
                FROM coincidencias c
                JOIN revisiones r ON r.id_coincidencia = c.id
                WHERE c.marca_vigilada = ?
                  AND c.marca_detectada != ?
                  AND r.estado != 'pendiente'
                ORDER BY r.fecha_revision DESC
                LIMIT ?
            """, (marca_vigilada, marca_detectada, restantes))
            resultados.extend([dict(row) for row in cur.fetchall()])

        return resultados

    def obtener_falsos_positivos(self, marca_vigilada: str = "",
                                  limite: int = 20) -> list[dict]:
        """Obtiene coincidencias marcadas como falso positivo."""
        query = """
            SELECT c.marca_vigilada, c.marca_detectada, c.score_final,
                   r.comentario, r.fecha_revision
            FROM coincidencias c
            JOIN revisiones r ON r.id_coincidencia = c.id
            WHERE r.decision = 'falso_positivo'
        """
        params = []
        if marca_vigilada:
            query += " AND c.marca_vigilada = ?"
            params.append(marca_vigilada)
        query += " ORDER BY r.fecha_revision DESC LIMIT ?"
        params.append(limite)
        cur = self.conn.execute(query, params)
        return [dict(row) for row in cur.fetchall()]

    def obtener_confirmados(self, marca_vigilada: str = "",
                             limite: int = 20) -> list[dict]:
        """Obtiene coincidencias confirmadas como conflicto real."""
        query = """
            SELECT c.marca_vigilada, c.marca_detectada, c.score_final,
                   r.comentario, r.fecha_revision
            FROM coincidencias c
            JOIN revisiones r ON r.id_coincidencia = c.id
            WHERE r.decision = 'confirmado'
        """
        params = []
        if marca_vigilada:
            query += " AND c.marca_vigilada = ?"
            params.append(marca_vigilada)
        query += " ORDER BY r.fecha_revision DESC LIMIT ?"
        params.append(limite)
        cur = self.conn.execute(query, params)
        return [dict(row) for row in cur.fetchall()]

    # --- Ejecuciones ---

    def registrar_ejecucion(self, boletines: int, coincidencias: int,
                            estado: str, detalle: str = "",
                            analisis_ia: int = 0) -> int:
        cur = self.conn.execute("""
            INSERT INTO ejecuciones
            (fecha_inicio, fecha_fin, boletines_procesados,
             coincidencias_encontradas, analisis_ia_generados, estado, detalle)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (datetime.now().isoformat(), datetime.now().isoformat(),
              boletines, coincidencias, analisis_ia, estado, detalle))
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
        cur = self.conn.execute("SELECT COUNT(*) FROM analisis_ia WHERE error = '' OR error IS NULL")
        stats["analisis_ia_completados"] = cur.fetchone()[0]
        cur = self.conn.execute("SELECT COUNT(*) FROM revisiones WHERE decision = 'falso_positivo'")
        stats["falsos_positivos"] = cur.fetchone()[0]
        cur = self.conn.execute("SELECT COUNT(*) FROM revisiones WHERE decision = 'confirmado'")
        stats["confirmados"] = cur.fetchone()[0]
        cur = self.conn.execute(
            "SELECT marca_vigilada, COUNT(*) as cnt FROM coincidencias GROUP BY marca_vigilada ORDER BY cnt DESC"
        )
        stats["por_marca"] = [dict(row) for row in cur.fetchall()]
        return stats

    def cerrar(self):
        self.conn.close()
