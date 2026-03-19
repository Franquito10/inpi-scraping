"""
Scraper del portal de boletines del INPI Argentina.
Detecta boletines nuevos de marcas y extrae URLs de descarga.

Estrategia:
1. Intenta con requests + BeautifulSoup (liviano)
2. Fallback con Selenium si el portal requiere JS
"""

import re
import time
import logging
from datetime import datetime, timedelta
from typing import Optional
from dataclasses import dataclass, field

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger("inpi.scraper")


@dataclass
class BoletinInfo:
    """Representa un boletin detectado en el portal."""
    id_inpi: str
    titulo: str
    fecha_publicacion: str
    comentario: str
    url_descarga: str
    sector: str = "Marcas"


class ScraperINPI:
    def __init__(self, settings: dict):
        cfg = settings.get("inpi", {})
        self.url_base = cfg.get("url_base", "")
        self.url_boletines = cfg.get("url_boletines", "")
        self.tipo_item = cfg.get("tipo_item", 3)
        self.filtro_comentario = cfg.get("filtro_comentario", "MARCAS NUEVAS")
        self.reintentos = cfg.get("reintentos_descarga", 3)
        self.timeout = cfg.get("timeout_segundos", 30)
        self.user_agent = cfg.get("user_agent", "")
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": self.user_agent,
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "es-AR,es;q=0.9",
        })

    def obtener_boletines_disponibles(self, fecha: Optional[datetime] = None) -> list[BoletinInfo]:
        """
        Obtiene la lista de boletines disponibles en el portal.
        Si se pasa fecha, filtra por esa fecha. Si no, trae los mas recientes.
        """
        boletines = []

        # Intentar con requests primero
        try:
            boletines = self._scrape_con_requests(fecha)
            if boletines:
                logger.info(f"Obtenidos {len(boletines)} boletines via requests")
                return boletines
        except Exception as e:
            logger.warning(f"Fallo scraping con requests: {e}")

        # Fallback con Selenium
        try:
            boletines = self._scrape_con_selenium(fecha)
            logger.info(f"Obtenidos {len(boletines)} boletines via Selenium")
        except Exception as e:
            logger.error(f"Fallo scraping con Selenium: {e}")

        return boletines

    def _scrape_con_requests(self, fecha: Optional[datetime]) -> list[BoletinInfo]:
        """Scraping con requests + BeautifulSoup."""
        url = self.url_boletines
        params = {"Tipo_Item": self.tipo_item}
        if fecha:
            params["Fecha"] = fecha.strftime("%d/%m/%Y")

        for intento in range(self.reintentos):
            try:
                resp = self.session.get(url, params=params, timeout=self.timeout)
                resp.raise_for_status()
                return self._parsear_html_boletines(resp.text, fecha)
            except requests.RequestException as e:
                logger.warning(f"Intento {intento + 1}/{self.reintentos} fallo: {e}")
                if intento < self.reintentos - 1:
                    time.sleep(2 ** (intento + 1))
        return []

    def _parsear_html_boletines(self, html: str, fecha_filtro: Optional[datetime]) -> list[BoletinInfo]:
        """
        Parsea el HTML del listado de boletines.
        Adaptar selectores segun la estructura real del portal INPI.
        """
        soup = BeautifulSoup(html, "lxml")
        boletines = []

        # Estrategia 1: Tabla con filas de boletines
        # El portal INPI tipicamente usa una tabla/grilla ASP.NET
        tabla = soup.find("table", {"id": re.compile(r"GridView|grd|tbl", re.I)})
        if tabla:
            filas = tabla.find_all("tr")[1:]  # Saltar header
            for fila in filas:
                boletin = self._parsear_fila_tabla(fila, fecha_filtro)
                if boletin:
                    boletines.append(boletin)
            return boletines

        # Estrategia 2: Divs o lista con links a PDFs
        links_pdf = soup.find_all("a", href=re.compile(r"\.pdf|Download|Descarga", re.I))
        for link in links_pdf:
            boletin = self._parsear_link_pdf(link, fecha_filtro)
            if boletin:
                boletines.append(boletin)

        # Estrategia 3: Buscar en todo el HTML patrones de boletines
        if not boletines:
            boletines = self._parsear_generico(soup, fecha_filtro)

        return boletines

    def _parsear_fila_tabla(self, fila, fecha_filtro: Optional[datetime]) -> Optional[BoletinInfo]:
        """Parsea una fila de tabla de boletines."""
        celdas = fila.find_all("td")
        if len(celdas) < 3:
            return None

        # Extraer datos de las celdas
        textos = [c.get_text(strip=True) for c in celdas]
        link = fila.find("a", href=True)
        if not link:
            return None

        href = link.get("href", "")
        url_descarga = href if href.startswith("http") else f"{self.url_base}/{href.lstrip('/')}"

        # Detectar fecha, titulo y comentario de las celdas
        fecha_str = ""
        titulo = ""
        comentario = ""
        id_inpi = ""

        for texto in textos:
            # Detectar fecha
            match_fecha = re.search(r"\d{1,2}/\d{1,2}/\d{4}", texto)
            if match_fecha:
                fecha_str = match_fecha.group()
            # Detectar si contiene "MARCAS" o similar
            if re.search(r"MARCA", texto, re.I):
                comentario = texto
            # Detectar ID numerico
            match_id = re.search(r"\b(\d{4,})\b", texto)
            if match_id and not id_inpi:
                id_inpi = match_id.group(1)

        if not id_inpi:
            # Generar ID desde URL
            match_url_id = re.search(r"[Ii]d[=_](\d+)", url_descarga)
            id_inpi = match_url_id.group(1) if match_url_id else href[-20:]

        titulo = textos[0] if textos else "Sin titulo"

        # Filtrar por comentario si no coincide
        if self.filtro_comentario and comentario:
            if self.filtro_comentario.upper() not in comentario.upper():
                return None

        # Filtrar por fecha si se especifico
        if fecha_filtro and fecha_str:
            try:
                fecha_pub = datetime.strptime(fecha_str, "%d/%m/%Y")
                if fecha_pub.date() != fecha_filtro.date():
                    return None
            except ValueError:
                pass

        return BoletinInfo(
            id_inpi=id_inpi,
            titulo=titulo,
            fecha_publicacion=fecha_str,
            comentario=comentario,
            url_descarga=url_descarga,
        )

    def _parsear_link_pdf(self, link, fecha_filtro: Optional[datetime]) -> Optional[BoletinInfo]:
        """Parsea un link a PDF encontrado en el HTML."""
        href = link.get("href", "")
        texto = link.get_text(strip=True)
        url = href if href.startswith("http") else f"{self.url_base}/{href.lstrip('/')}"

        # Extraer ID del link
        match_id = re.search(r"[Ii]d[=_](\d+)", href)
        id_inpi = match_id.group(1) if match_id else href[-20:]

        # Buscar fecha y comentario en el contexto circundante
        padre = link.parent
        contexto = padre.get_text(strip=True) if padre else ""

        fecha_str = ""
        match_fecha = re.search(r"\d{1,2}/\d{1,2}/\d{4}", contexto)
        if match_fecha:
            fecha_str = match_fecha.group()

        # Filtrar por "MARCAS NUEVAS"
        if self.filtro_comentario:
            if self.filtro_comentario.upper() not in contexto.upper():
                return None

        return BoletinInfo(
            id_inpi=id_inpi,
            titulo=texto or "Boletin",
            fecha_publicacion=fecha_str,
            comentario=contexto[:200],
            url_descarga=url,
        )

    def _parsear_generico(self, soup, fecha_filtro: Optional[datetime]) -> list[BoletinInfo]:
        """Parseo generico como ultimo recurso."""
        boletines = []
        # Buscar cualquier link que parezca un boletin
        for link in soup.find_all("a", href=True):
            href = link.get("href", "")
            texto = link.get_text(strip=True).upper()
            if "MARCA" in texto or "BOLETIN" in texto or ".pdf" in href.lower():
                url = href if href.startswith("http") else f"{self.url_base}/{href.lstrip('/')}"
                match_id = re.search(r"\d{4,}", href)
                boletines.append(BoletinInfo(
                    id_inpi=match_id.group() if match_id else href[-20:],
                    titulo=link.get_text(strip=True),
                    fecha_publicacion="",
                    comentario=texto,
                    url_descarga=url,
                ))
        return boletines

    def _scrape_con_selenium(self, fecha: Optional[datetime]) -> list[BoletinInfo]:
        """Fallback: scraping con navegador automatizado."""
        try:
            from selenium import webdriver
            from selenium.webdriver.chrome.options import Options
            from selenium.webdriver.chrome.service import Service
            from selenium.webdriver.common.by import By
            from selenium.webdriver.support.ui import WebDriverWait
            from selenium.webdriver.support import expected_conditions as EC
        except ImportError:
            logger.error("Selenium no instalado. Instalar con: pip install selenium")
            return []

        options = Options()
        options.add_argument("--headless")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument(f"--user-agent={self.user_agent}")

        driver = None
        try:
            driver = webdriver.Chrome(options=options)
            driver.set_page_load_timeout(self.timeout)

            url = f"{self.url_boletines}?Tipo_Item={self.tipo_item}"
            driver.get(url)

            # Esperar a que cargue la tabla
            WebDriverWait(driver, 15).until(
                EC.presence_of_element_located((By.TAG_NAME, "table"))
            )
            time.sleep(2)  # Espera adicional por JS

            html = driver.page_source
            return self._parsear_html_boletines(html, fecha)
        except Exception as e:
            logger.error(f"Error en Selenium: {e}")
            return []
        finally:
            if driver:
                driver.quit()

    def filtrar_nuevos(self, boletines: list[BoletinInfo],
                       ids_existentes: set[str]) -> list[BoletinInfo]:
        """Filtra boletines que ya fueron procesados."""
        nuevos = [b for b in boletines if b.id_inpi not in ids_existentes]
        logger.info(f"Boletines nuevos: {len(nuevos)} de {len(boletines)} totales")
        return nuevos

    def obtener_miercoles_actual(self) -> datetime:
        """Retorna la fecha del miercoles mas reciente (hoy si es miercoles)."""
        hoy = datetime.now()
        dias_desde_miercoles = (hoy.weekday() - 2) % 7
        return hoy - timedelta(days=dias_desde_miercoles)
