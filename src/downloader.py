"""
Descarga de PDFs de boletines del INPI.
Manejo de reintentos, validacion y deduplicacion.
"""

import time
import logging
from pathlib import Path

import requests

from .utils import hash_archivo

logger = logging.getLogger("inpi.downloader")


class Downloader:
    def __init__(self, settings: dict):
        cfg = settings.get("inpi", {})
        self.reintentos = cfg.get("reintentos_descarga", 3)
        self.timeout = cfg.get("timeout_segundos", 30)
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": cfg.get("user_agent", ""),
        })

    def descargar_pdf(self, url: str, destino: Path) -> bool:
        """
        Descarga un PDF a la ruta destino.
        Retorna True si la descarga fue exitosa y el archivo es valido.
        """
        destino.parent.mkdir(parents=True, exist_ok=True)

        for intento in range(self.reintentos):
            try:
                logger.info(f"Descargando {url} (intento {intento + 1})")
                resp = self.session.get(url, timeout=self.timeout, stream=True)
                resp.raise_for_status()

                # Verificar que es un PDF
                content_type = resp.headers.get("Content-Type", "")
                if "pdf" not in content_type.lower() and not url.lower().endswith(".pdf"):
                    # Algunos servidores no ponen content-type correcto
                    # Verificar los primeros bytes
                    contenido = resp.content
                    if not contenido[:5] == b"%PDF-":
                        logger.error(f"El archivo descargado no parece ser PDF: {content_type}")
                        return False
                    with open(destino, "wb") as f:
                        f.write(contenido)
                else:
                    with open(destino, "wb") as f:
                        for chunk in resp.iter_content(chunk_size=8192):
                            f.write(chunk)

                # Validar archivo descargado
                if self._validar_pdf(destino):
                    logger.info(f"Descarga exitosa: {destino.name} ({destino.stat().st_size} bytes)")
                    return True
                else:
                    logger.warning(f"PDF invalido, reintentando...")
                    destino.unlink(missing_ok=True)

            except requests.RequestException as e:
                logger.warning(f"Error de descarga (intento {intento + 1}): {e}")
                if intento < self.reintentos - 1:
                    time.sleep(2 ** (intento + 1))

        logger.error(f"Fallo la descarga despues de {self.reintentos} intentos: {url}")
        return False

    def _validar_pdf(self, ruta: Path) -> bool:
        """Valida que el archivo sea un PDF real y no este corrupto."""
        if not ruta.exists():
            return False
        size = ruta.stat().st_size
        if size < 100:  # PDF minimo razonable
            logger.warning(f"Archivo demasiado pequeno: {size} bytes")
            return False
        # Verificar magic bytes
        with open(ruta, "rb") as f:
            header = f.read(5)
            if header != b"%PDF-":
                logger.warning(f"Magic bytes incorrectos: {header}")
                return False
            # Verificar que tiene EOF marker
            f.seek(-50, 2)  # Ultimos 50 bytes
            tail = f.read()
            if b"%%EOF" not in tail:
                logger.warning("No se encontro marcador %%EOF")
                # No retornar False porque algunos PDFs validos no lo tienen
        return True

    def obtener_hash(self, ruta: Path) -> str:
        """Retorna hash SHA256 del archivo."""
        return hash_archivo(ruta)

    def archivo_ya_existe(self, destino: Path, hash_conocido: str = "") -> bool:
        """Verifica si el archivo ya existe (por ruta o por hash)."""
        if not destino.exists():
            return False
        if hash_conocido:
            return hash_archivo(destino) == hash_conocido
        return True
