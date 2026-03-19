"""
Pipeline principal: orquesta todo el flujo de scraping a dashboard.

Paso 1-2: Detectar y descargar boletines nuevos
Paso 3-6: Parsear, comparar, calcular scoring
Paso 7:   Analisis IA legal (post-scoring, sobre coincidencias guardadas)
Paso 8:   Generar dashboard
"""

import json
import logging
from pathlib import Path
from datetime import datetime

from .config import cargar_settings, cargar_marcas, obtener_ruta, crear_estructura_carpetas
from .db import BaseDatos
from .scraper import ScraperINPI
from .downloader import Downloader
from .parser_pdf import ParserPDF
from .comparador_texto import ComparadorTexto
from .comparador_fonetico import ComparadorFonetico
from .comparador_visual import ComparadorVisual, ResultadoVisual
from .comparador_color import ComparadorColor, ResultadoColor
from .scoring import MotorScoring
from .analisis_ia import AnalizadorIALegal
from .dashboard import GeneradorDashboard
from .utils import hash_archivo

logger = logging.getLogger("inpi.pipeline")


class Pipeline:
    def __init__(self, settings: dict = None):
        self.settings = settings or cargar_settings()
        self.marcas = cargar_marcas()

        # Crear estructura de carpetas
        crear_estructura_carpetas(self.settings)

        # Inicializar componentes
        self.db = BaseDatos(obtener_ruta(self.settings, "db"))
        self.scraper = ScraperINPI(self.settings)
        self.downloader = Downloader(self.settings)
        self.parser = ParserPDF(self.settings)
        self.comp_texto = ComparadorTexto(self.settings)
        self.comp_fonetico = ComparadorFonetico(self.settings)
        self.comp_visual = ComparadorVisual(self.settings)
        self.comp_color = ComparadorColor(self.settings)
        self.scoring = MotorScoring(self.settings)
        self.ia = AnalizadorIALegal(self.settings)
        self.dashboard = GeneradorDashboard(self.settings)

        self.dir_pdfs = obtener_ruta(self.settings, "pdfs")
        self.dir_logos_ref = obtener_ruta(self.settings, "logos_referencia")
        self.dir_logos_ext = obtener_ruta(self.settings, "logos_extraidos")

    def ejecutar_completo(self, fecha=None, solo_pendientes=False) -> dict:
        """Ejecuta el pipeline completo."""
        logger.info("=" * 60)
        logger.info("INICIO DE EJECUCION DEL PIPELINE")
        logger.info("=" * 60)

        resultados = {
            "boletines_descargados": 0,
            "entradas_procesadas": 0,
            "coincidencias_encontradas": 0,
            "analisis_ia_generados": 0,
            "errores": [],
            "dashboard": None,
        }

        try:
            # Paso 1 & 2: Detectar y descargar boletines nuevos
            if not solo_pendientes:
                n_descargados = self._paso_descarga(fecha)
                resultados["boletines_descargados"] = n_descargados

            # Paso 3-6: Procesar boletines pendientes
            n_entradas, n_coincidencias = self._paso_procesamiento()
            resultados["entradas_procesadas"] = n_entradas
            resultados["coincidencias_encontradas"] = n_coincidencias

            # Paso 7: Analisis IA legal (sobre todas las coincidencias sin analisis)
            n_ia = self._paso_analisis_ia()
            resultados["analisis_ia_generados"] = n_ia

            # Paso 8: Dashboard
            ruta_dashboard = self._paso_dashboard()
            resultados["dashboard"] = str(ruta_dashboard)

            # Registrar ejecucion
            self.db.registrar_ejecucion(
                boletines=resultados["boletines_descargados"],
                coincidencias=n_coincidencias,
                estado="ok",
                analisis_ia=n_ia,
            )

        except Exception as e:
            logger.error(f"Error en pipeline: {e}", exc_info=True)
            resultados["errores"].append(str(e))
            self.db.registrar_ejecucion(
                boletines=0, coincidencias=0,
                estado="error", detalle=str(e),
            )

        logger.info(f"Pipeline finalizado: {resultados}")
        return resultados

    def _paso_descarga(self, fecha=None) -> int:
        """Detecta y descarga boletines nuevos."""
        logger.info("--- PASO 1: Detectar boletines nuevos ---")

        if fecha is None:
            fecha = self.scraper.obtener_miercoles_actual()

        boletines = self.scraper.obtener_boletines_disponibles(fecha)
        if not boletines:
            logger.info("No se encontraron boletines en el portal")
            return 0

        # Filtrar ya procesados
        ids_existentes = {
            b["id_inpi"] for b in self.db.obtener_todos_boletines()
        }
        nuevos = self.scraper.filtrar_nuevos(boletines, ids_existentes)

        if not nuevos:
            logger.info("No hay boletines nuevos para descargar")
            return 0

        logger.info(f"--- PASO 2: Descargar {len(nuevos)} boletines ---")
        descargados = 0
        for boletin in nuevos:
            nombre_archivo = f"boletin_{boletin.id_inpi}.pdf"
            destino = self.dir_pdfs / nombre_archivo

            if self.downloader.descargar_pdf(boletin.url_descarga, destino):
                h = self.downloader.obtener_hash(destino)
                self.db.registrar_boletin(
                    id_inpi=boletin.id_inpi,
                    titulo=boletin.titulo,
                    fecha_pub=boletin.fecha_publicacion,
                    comentario=boletin.comentario,
                    url=boletin.url_descarga,
                    archivo=str(destino),
                    hash_archivo=h,
                )
                descargados += 1
            else:
                logger.warning(f"No se pudo descargar boletin {boletin.id_inpi}")

        return descargados

    def _paso_procesamiento(self) -> tuple[int, int]:
        """Procesa boletines pendientes."""
        logger.info("--- PASO 3-6: Procesar boletines pendientes ---")

        pendientes = self.db.obtener_boletines_pendientes()
        if not pendientes:
            logger.info("No hay boletines pendientes de procesamiento")
            return 0, 0

        total_entradas = 0
        total_coincidencias = 0

        for boletin in pendientes:
            ruta_pdf = Path(boletin["archivo_local"])
            if not ruta_pdf.exists():
                logger.warning(f"PDF no encontrado: {ruta_pdf}")
                continue

            logger.info(f"Procesando: {ruta_pdf.name}")

            # Parsear PDF
            resultado_parseo = self.parser.procesar_pdf(ruta_pdf, self.dir_logos_ext)
            total_entradas += len(resultado_parseo.entradas)

            # Comparar cada entrada contra cada marca vigilada
            for entrada in resultado_parseo.entradas:
                for marca in self.marcas:
                    n_coinc = self._comparar_entrada(
                        entrada, marca, boletin, ruta_pdf.name
                    )
                    total_coincidencias += n_coinc

            # Marcar como procesado
            self.db.marcar_boletin_procesado(boletin["id_inpi"])

        logger.info(
            f"Procesamiento completo: {total_entradas} entradas, "
            f"{total_coincidencias} coincidencias"
        )
        return total_entradas, total_coincidencias

    def _comparar_entrada(self, entrada, marca: dict,
                          boletin: dict, nombre_pdf: str) -> int:
        """Compara una entrada marcaria contra una marca vigilada."""
        nombre_marca = marca.get("nombre", "")
        variantes = marca.get("variantes", [])
        logo_ref = marca.get("logo", "")

        # Comparacion textual
        res_texto = self.comp_texto.comparar(
            entrada.denominacion, nombre_marca, variantes
        )

        # Comparacion fonetica
        res_fonetico = self.comp_fonetico.comparar(
            entrada.denominacion, nombre_marca, variantes
        )

        # Comparacion visual (solo si hay imagenes)
        res_visual = ResultadoVisual(
            score=0, score_ssim=0, score_orb=0, score_template=0,
            detalle="Sin imagenes para comparar"
        )
        if entrada.imagenes and logo_ref:
            ruta_logo = self.dir_logos_ref / Path(logo_ref).name
            if not ruta_logo.exists():
                ruta_logo = Path(logo_ref)
            if ruta_logo.exists():
                res_visual, _ = self.comp_visual.comparar_contra_referencias(
                    entrada.imagenes[0], [ruta_logo]
                )

        # Comparacion de color
        res_color = ResultadoColor(
            score=0, score_histograma=0, score_dominantes=0,
            colores_detectados=[], colores_referencia=[],
            detalle="Sin imagenes para comparar color"
        )
        if entrada.imagenes and logo_ref:
            ruta_logo = self.dir_logos_ref / Path(logo_ref).name
            if not ruta_logo.exists():
                ruta_logo = Path(logo_ref)
            if ruta_logo.exists():
                res_color, _ = self.comp_color.comparar_contra_referencias(
                    entrada.imagenes[0], [ruta_logo]
                )

        # Scoring final
        resultado = self.scoring.calcular(
            marca_vigilada=marca,
            marca_detectada=entrada.denominacion,
            pagina=entrada.pagina,
            archivo_pdf=nombre_pdf,
            resultado_texto=res_texto,
            resultado_fonetico=res_fonetico,
            resultado_visual=res_visual,
            resultado_color=res_color,
            clase_detectada=entrada.clase_niza,
            tipo_marca=entrada.tipo_marca,
        )

        # Solo guardar si supera umbral
        if self.scoring.supera_umbral(resultado):
            self.db.registrar_coincidencia(
                id_boletin=boletin["id"],
                marca_vigilada=nombre_marca,
                marca_detectada=entrada.denominacion,
                pagina=entrada.pagina,
                tipo_match=resultado.tipo_match_principal,
                scores=resultado.scores,
                score_final=resultado.score_final,
                nivel_riesgo=resultado.nivel_riesgo,
                explicacion=resultado.explicacion_completa,
                imagen=str(entrada.imagenes[0]) if entrada.imagenes else "",
                clase_niza=str(entrada.clase_niza),
                tipo_marca=resultado.tipo_marca,
                metadata={
                    "recomendacion": resultado.recomendacion,
                    "factores_a_favor": resultado.factores_a_favor,
                    "factores_en_contra": resultado.factores_en_contra,
                    "solicitante": entrada.solicitante,
                    "acta_numero": entrada.acta_numero,
                },
            )
            return 1

        return 0

    def _paso_analisis_ia(self) -> int:
        """Paso 7: Analisis IA legal para coincidencias sin analisis."""
        logger.info("--- PASO 7: Analisis IA legal ---")

        if not self.ia.habilitado:
            logger.info("Analisis IA deshabilitado en configuracion")
            return 0

        # Obtener coincidencias que no tienen analisis IA
        pendientes = self.db.obtener_coincidencias_sin_analisis_ia()
        if not pendientes:
            logger.info("Todas las coincidencias ya tienen analisis IA")
            return 0

        logger.info(f"Analizando {len(pendientes)} coincidencias con IA...")
        resultados = self.ia.analizar_lote(pendientes, self.marcas, self.db)

        n_ok = sum(1 for r in resultados if r.es_valido())
        n_err = sum(1 for r in resultados if r.error)
        logger.info(f"Analisis IA completado: {n_ok} exitosos, {n_err} con error")
        return n_ok

    def _paso_dashboard(self) -> Path:
        """Genera el dashboard HTML."""
        logger.info("--- PASO 8: Generar dashboard ---")

        coincidencias = self.db.obtener_todas_coincidencias()
        estadisticas = self.db.obtener_estadisticas()
        boletines = self.db.obtener_todos_boletines()

        # Enriquecer coincidencias con metadata y analisis IA
        for c in coincidencias:
            # Metadata del scoring
            try:
                meta = json.loads(c.get("metadata", "{}"))
                c["recomendacion"] = meta.get("recomendacion", "")
                c["factores_a_favor"] = meta.get("factores_a_favor", [])
                c["factores_en_contra"] = meta.get("factores_en_contra", [])
                c["solicitante"] = meta.get("solicitante", "")
                c["acta_numero"] = meta.get("acta_numero", "")
            except Exception:
                c["recomendacion"] = ""
                c["factores_a_favor"] = []
                c["factores_en_contra"] = []

            # Analisis IA
            analisis = self.db.obtener_analisis_ia(c["id"])
            c["analisis_ia"] = analisis

        ruta = self.dashboard.generar(coincidencias, estadisticas, boletines)
        return ruta

    def ejecutar_analisis_ia(self, id_coincidencia: int = None) -> dict:
        """
        Ejecuta o regenera analisis IA.
        Si id_coincidencia es None, procesa todas las pendientes.
        Si se pasa un id, regenera ese caso especifico.
        """
        if not self.ia.habilitado:
            return {"error": "Analisis IA no habilitado en configuracion"}

        if id_coincidencia:
            return self._regenerar_ia_individual(id_coincidencia)
        else:
            n = self._paso_analisis_ia()
            self._paso_dashboard()
            return {"analisis_generados": n}

    def _regenerar_ia_individual(self, id_coincidencia: int) -> dict:
        """Regenera el analisis IA para un caso especifico."""
        coincidencia = self.db.obtener_coincidencia(id_coincidencia)
        if not coincidencia:
            return {"error": f"Coincidencia {id_coincidencia} no encontrada"}

        marca_nombre = coincidencia.get("marca_vigilada", "")
        marca_cfg = next(
            (m for m in self.marcas if m["nombre"] == marca_nombre), {}
        )

        resultado = self.ia.regenerar_analisis(
            id_coincidencia, coincidencia, marca_cfg, self.db
        )

        # Regenerar dashboard
        self._paso_dashboard()

        return {
            "id_coincidencia": id_coincidencia,
            "riesgo": resultado.riesgo_preliminar,
            "recomendacion": resultado.recomendacion_operativa,
            "error": resultado.error,
        }

    def procesar_pdf_manual(self, ruta_pdf: Path) -> dict:
        """Procesa un PDF especifico manualmente (sin descarga del portal)."""
        logger.info(f"Procesamiento manual: {ruta_pdf.name}")

        # Registrar como boletin manual
        h = hash_archivo(ruta_pdf)
        id_manual = f"manual_{ruta_pdf.stem}"
        self.db.registrar_boletin(
            id_inpi=id_manual,
            titulo=f"Manual: {ruta_pdf.name}",
            fecha_pub=datetime.now().strftime("%d/%m/%Y"),
            comentario="Carga manual",
            url="",
            archivo=str(ruta_pdf),
            hash_archivo=h,
        )

        # Procesar
        n_entradas, n_coincidencias = self._paso_procesamiento()

        # Analisis IA
        n_ia = self._paso_analisis_ia()

        # Dashboard
        self._paso_dashboard()

        return {
            "entradas": n_entradas,
            "coincidencias": n_coincidencias,
            "analisis_ia": n_ia,
        }

    def regenerar_dashboard(self) -> Path:
        """Regenera el dashboard con datos existentes."""
        return self._paso_dashboard()

    def cerrar(self):
        """Cierra conexiones."""
        self.db.cerrar()
