"""
Scraper del portal de boletines del INPI Argentina.
Detecta boletines nuevos de marcas y extrae URLs de descarga.

URLs reales descubiertas:
- Listado: https://portaltramites.inpi.gob.ar/Boletines?Tipo_Item=3
- PDFs:    https://portaltramites.inpi.gob.ar/Uploads/Boletines/{NUMERO}_3_.pdf
  donde _3_ = Marcas

Estrategia de descubrimiento:
1. Intentar parsear el listado HTML (requests + BS4)
2. Fallback: probar numeros secuenciales desde el ultimo conocido
3. Fallback: Selenium si el portal requiere JS
"""

import re
import time
import logging
from datetime import datetime, timedelta
from typing import Optional
from dataclasses import dataclass

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger("inpi.scraper")

# URL base real del portal INPI
URL_BASE = "https://portaltramites.inpi.gob.ar"
URL_BOLETINES = f"{URL_BASE}/Boletines"
URL_BOLETINES_MARCAS = f"{URL_BOLETINES}?Tipo_Item=3"
URL_PDF_TEMPLATE = f"{URL_BASE}/Uploads/Boletines/{{numero}}_3_.pdf"


@dataclass
class BoletinInfo:
    """Representa un boletin detectado en el portal."""
    id_inpi: str
    numero: int
    titulo: str
    fecha_publicacion: str
    comentario: str
    url_descarga: str
    sector: str = "Marcas"


class ScraperINPI:
    def __init__(self, settings: dict):
        cfg = settings.get("inpi", {})
        self.url_base = cfg.get("url_base", URL_BASE)
        self.url_boletines = cfg.get("url_boletines", URL_BOLETINES_MARCAS)
        self.tipo_item = cfg.get("tipo_item", 3)
        self.filtro_comentario = cfg.get("filtro_comentario", "MARCAS NUEVAS")
        self.reintentos = cfg.get("reintentos_descarga", 3)
        self.timeout = cfg.get("timeout_segundos", 30)
        self.user_agent = cfg.get("user_agent", "")
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": self.user_agent or "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "text/html,application/xhtml+xml,application/pdf",
            "Accept-Language": "es-AR,es;q=0.9",
        })

    def obtener_boletines_disponibles(self, fecha: Optional[datetime] = None) -> list[BoletinInfo]:
        """
        Obtiene la lista de boletines disponibles.
        Estrategia: listado HTML -> secuencial -> Selenium fallback.
        """
        boletines = []

        # Estrategia 1: Parsear listado HTML
        try:
            boletines = self._scrape_listado_html(fecha)
            if boletines:
                logger.info(f"Encontrados {len(boletines)} boletines via listado HTML")
                return boletines
        except Exception as e:
            logger.warning(f"Fallo scraping listado HTML: {e}")

        # Estrategia 2: Descubrimiento secuencial
        try:
            boletines = self._descubrir_secuencial(fecha)
            if boletines:
                logger.info(f"Encontrados {len(boletines)} boletines via secuencial")
                return boletines
        except Exception as e:
            logger.warning(f"Fallo descubrimiento secuencial: {e}")

        # Estrategia 3: Selenium fallback
        try:
            boletines = self._scrape_con_selenium(fecha)
            if boletines:
                logger.info(f"Encontrados {len(boletines)} boletines via Selenium")
        except Exception as e:
            logger.error(f"Fallo Selenium: {e}")

        return boletines

    def _scrape_listado_html(self, fecha: Optional[datetime]) -> list[BoletinInfo]:
        """Parsea el listado de boletines del portal INPI."""
        url = f"{URL_BOLETINES}?Tipo_Item={self.tipo_item}"

        for intento in range(self.reintentos):
            try:
                resp = self.session.get(url, timeout=self.timeout)
                resp.raise_for_status()
                return self._parsear_listado(resp.text, fecha)
            except requests.RequestException as e:
                logger.warning(f"Intento {intento + 1}/{self.reintentos} listado: {e}")
                if intento < self.reintentos - 1:
                    time.sleep(2 ** (intento + 1))
        return []

    def _parsear_listado(self, html: str, fecha_filtro: Optional[datetime]) -> list[BoletinInfo]:
        """Parsea el HTML del listado de boletines INPI."""
        soup = BeautifulSoup(html, "lxml")
        boletines = []

        # Buscar links a PDFs de boletines con patron real
        # Patron: /Uploads/Boletines/{numero}_3_.pdf
        links_pdf = soup.find_all("a", href=re.compile(r"/Uploads/Boletines/\d+_3_\.pdf", re.I))

        for link in links_pdf:
            href = link.get("href", "")
            match = re.search(r"/(\d+)_3_\.pdf", href)
            if not match:
                continue

            numero = int(match.group(1))
            url_completa = href if href.startswith("http") else f"{self.url_base}{href}"

            # Buscar fecha y titulo en contexto
            contexto = self._obtener_contexto(link)
            fecha_str = self._extraer_fecha(contexto)
            titulo = f"Boletin Nro. {numero}"

            boletin = BoletinInfo(
                id_inpi=str(numero),
                numero=numero,
                titulo=titulo,
                fecha_publicacion=fecha_str,
                comentario=contexto[:200],
                url_descarga=url_completa,
            )

            # Filtrar por fecha si se especifico
            if fecha_filtro and fecha_str:
                try:
                    fecha_pub = datetime.strptime(fecha_str, "%d/%m/%Y")
                    if fecha_pub.date() != fecha_filtro.date():
                        continue
                except ValueError:
                    pass

            boletines.append(boletin)

        # Si no encontro links directos, buscar en tablas/grillas ASP.NET
        if not boletines:
            boletines = self._parsear_grilla_aspnet(soup, fecha_filtro)

        return boletines

    def _parsear_grilla_aspnet(self, soup, fecha_filtro: Optional[datetime]) -> list[BoletinInfo]:
        """Parsea grillas ASP.NET tipicas del portal INPI."""
        boletines = []

        # Buscar tablas con IDs tipicos de ASP.NET
        for tabla in soup.find_all("table"):
            filas = tabla.find_all("tr")
            if len(filas) < 2:
                continue

            for fila in filas[1:]:  # Saltar header
                celdas = fila.find_all("td")
                if len(celdas) < 2:
                    continue

                link = fila.find("a", href=True)
                if not link:
                    continue

                href = link.get("href", "")
                texto_fila = " ".join(c.get_text(strip=True) for c in celdas)

                # Detectar numero de boletin
                match_num = re.search(r"\b(\d{4,})\b", texto_fila)
                if not match_num:
                    match_num = re.search(r"/(\d+)_", href)
                if not match_num:
                    continue

                numero = int(match_num.group(1))
                url = href if href.startswith("http") else f"{self.url_base}/{href.lstrip('/')}"
                fecha_str = self._extraer_fecha(texto_fila)

                boletines.append(BoletinInfo(
                    id_inpi=str(numero),
                    numero=numero,
                    titulo=f"Boletin Nro. {numero}",
                    fecha_publicacion=fecha_str,
                    comentario=texto_fila[:200],
                    url_descarga=url,
                ))

        return boletines

    def _descubrir_secuencial(self, fecha: Optional[datetime] = None,
                               ultimo_conocido: int = 6002,
                               rango: int = 20) -> list[BoletinInfo]:
        """
        Descubre boletines probando numeros secuenciales.
        Comienza desde el ultimo numero conocido y prueba hacia adelante.
        """
        boletines = []
        fallos_consecutivos = 0

        for i in range(rango):
            numero = ultimo_conocido + i
            url = URL_PDF_TEMPLATE.format(numero=numero)

            try:
                resp = self.session.head(url, timeout=10, allow_redirects=True)
                if resp.status_code == 200:
                    content_type = resp.headers.get("Content-Type", "")
                    content_length = int(resp.headers.get("Content-Length", 0))

                    if content_length > 1000:  # PDF minimo razonable
                        logger.info(f"Boletin encontrado: {numero} ({content_length} bytes)")
                        boletines.append(BoletinInfo(
                            id_inpi=str(numero),
                            numero=numero,
                            titulo=f"Boletin Nro. {numero}",
                            fecha_publicacion="",
                            comentario="Descubierto por secuencia",
                            url_descarga=url,
                        ))
                        fallos_consecutivos = 0
                    else:
                        fallos_consecutivos += 1
                else:
                    fallos_consecutivos += 1

            except requests.RequestException:
                fallos_consecutivos += 1

            # Si hay 5 fallos consecutivos, parar
            if fallos_consecutivos >= 5:
                break

        return boletines

    def _scrape_con_selenium(self, fecha: Optional[datetime]) -> list[BoletinInfo]:
        """Fallback: scraping con navegador automatizado."""
        try:
            from selenium import webdriver
            from selenium.webdriver.chrome.options import Options
            from selenium.webdriver.common.by import By
            from selenium.webdriver.support.ui import WebDriverWait
            from selenium.webdriver.support import expected_conditions as EC
        except ImportError:
            logger.error("Selenium no instalado")
            return []

        options = Options()
        options.add_argument("--headless")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")

        driver = None
        try:
            driver = webdriver.Chrome(options=options)
            driver.set_page_load_timeout(self.timeout)
            driver.get(f"{URL_BOLETINES}?Tipo_Item={self.tipo_item}")

            WebDriverWait(driver, 15).until(
                EC.presence_of_element_located((By.TAG_NAME, "table"))
            )
            time.sleep(2)

            return self._parsear_listado(driver.page_source, fecha)
        except Exception as e:
            logger.error(f"Error Selenium: {e}")
            return []
        finally:
            if driver:
                driver.quit()

    def construir_url_pdf(self, numero: int) -> str:
        """Construye la URL de descarga de un boletin por su numero."""
        return URL_PDF_TEMPLATE.format(numero=numero)

    def filtrar_nuevos(self, boletines: list[BoletinInfo],
                       ids_existentes: set[str]) -> list[BoletinInfo]:
        """Filtra boletines ya procesados."""
        nuevos = [b for b in boletines if b.id_inpi not in ids_existentes]
        logger.info(f"Boletines nuevos: {len(nuevos)} de {len(boletines)} totales")
        return nuevos

    def obtener_miercoles_actual(self) -> datetime:
        """Retorna la fecha del miercoles mas reciente."""
        hoy = datetime.now()
        dias_desde_miercoles = (hoy.weekday() - 2) % 7
        return hoy - timedelta(days=dias_desde_miercoles)

    def _obtener_contexto(self, element) -> str:
        """Obtiene texto del contexto circundante de un elemento HTML."""
        padre = element.parent
        if padre:
            return padre.get_text(strip=True)[:300]
        return element.get_text(strip=True)

    def _extraer_fecha(self, texto: str) -> str:
        """Extrae fecha del texto."""
        match = re.search(r"\d{1,2}\s+[Dd]e\s+\w+\s+[Dd]e\s+\d{4}", texto)
        if match:
            return match.group()
        match = re.search(r"\d{1,2}/\d{1,2}/\d{4}", texto)
        if match:
            return match.group()
        return ""
