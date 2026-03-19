"""
Script de empaquetado para generar .exe con PyInstaller.

Uso:
  pip install pyinstaller
  python empaquetar.py
"""

import subprocess
import sys
from pathlib import Path


def empaquetar():
    raiz = Path(__file__).parent

    # Verificar PyInstaller
    try:
        import PyInstaller
    except ImportError:
        print("Instalando PyInstaller...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "pyinstaller"])

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--name", "INPIMonitor",
        "--onefile",
        "--console",
        # Incluir archivos de configuracion
        "--add-data", f"{raiz / 'config'};config",
        "--add-data", f"{raiz / 'logos_referencia'};logos_referencia",
        # Imports ocultos que PyInstaller puede no detectar
        "--hidden-import", "pdfplumber",
        "--hidden-import", "fitz",
        "--hidden-import", "PIL",
        "--hidden-import", "cv2",
        "--hidden-import", "sklearn.cluster",
        "--hidden-import", "skimage.metrics",
        "--hidden-import", "jellyfish",
        "--hidden-import", "rapidfuzz",
        "--hidden-import", "lxml",
        "--hidden-import", "yaml",
        "--hidden-import", "jinja2",
        # Icono (si existe)
        # "--icon", str(raiz / "assets" / "icon.ico"),
        str(raiz / "main.py"),
    ]

    print("Empaquetando...")
    print(" ".join(cmd))
    subprocess.check_call(cmd)

    print("\n" + "=" * 50)
    print("Empaquetado completado.")
    print(f"Ejecutable en: {raiz / 'dist' / 'INPIMonitor.exe'}")
    print("=" * 50)
    print("\nPara distribuir, copiar:")
    print("  - dist/INPIMonitor.exe")
    print("  - config/ (carpeta completa)")
    print("  - logos_referencia/ (con los logos)")
    print("\nNota: Si se usa OCR, el usuario necesita Tesseract instalado por separado.")


if __name__ == "__main__":
    empaquetar()
