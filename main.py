"""
INPI Monitor - Punto de entrada principal.

Uso:
  python main.py                        # Pipeline completo (miercoles actual)
  python main.py --fecha 19/03/2026     # Pipeline para fecha especifica
  python main.py --pendientes           # Solo procesar boletines ya descargados
  python main.py --pdf ruta.pdf         # Procesar un PDF manualmente
  python main.py --dashboard            # Solo regenerar dashboard
  python main.py --analisis-ia          # Ejecutar analisis IA sobre coincidencias pendientes
  python main.py --regenerar-ia 42      # Regenerar analisis IA para coincidencia #42
  python main.py --setup                # Verificar instalacion y dependencias
"""

import sys
import argparse
from pathlib import Path
from datetime import datetime


def main():
    parser = argparse.ArgumentParser(
        description="INPI Monitor - Sistema de vigilancia marcaria",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--fecha", type=str, default=None,
                        help="Fecha de boletines (DD/MM/YYYY)")
    parser.add_argument("--pendientes", action="store_true",
                        help="Solo procesar boletines ya descargados")
    parser.add_argument("--pdf", type=str, default=None,
                        help="Ruta a un PDF para procesar manualmente")
    parser.add_argument("--dashboard", action="store_true",
                        help="Solo regenerar el dashboard HTML")
    parser.add_argument("--analisis-ia", action="store_true",
                        help="Ejecutar analisis IA legal sobre coincidencias pendientes")
    parser.add_argument("--regenerar-ia", type=int, default=None, metavar="ID",
                        help="Regenerar analisis IA para una coincidencia especifica")
    parser.add_argument("--setup", action="store_true",
                        help="Verificar instalacion y dependencias")
    parser.add_argument("--verbose", "-v", action="store_true",
                        help="Activar logging detallado")

    args = parser.parse_args()

    if args.setup:
        verificar_setup()
        return

    from src.config import cargar_settings, configurar_logging
    from src.pipeline import Pipeline

    settings = cargar_settings()
    if args.verbose:
        settings.setdefault("logging", {})["nivel"] = "DEBUG"

    logger = configurar_logging(settings)
    logger.info("INPI Monitor v1.0 iniciando...")

    pipeline = Pipeline(settings)

    try:
        if args.dashboard:
            ruta = pipeline.regenerar_dashboard()
            print(f"\nDashboard regenerado: {ruta}")

        elif args.analisis_ia:
            resultado = pipeline.ejecutar_analisis_ia()
            if "error" in resultado:
                print(f"\nERROR: {resultado['error']}")
            else:
                print(f"\nAnalisis IA completado: {resultado['analisis_generados']} generados")
                ruta = pipeline.regenerar_dashboard()
                print(f"Dashboard actualizado: {ruta}")

        elif args.regenerar_ia is not None:
            resultado = pipeline.ejecutar_analisis_ia(id_coincidencia=args.regenerar_ia)
            if resultado.get("error"):
                print(f"\nERROR: {resultado['error']}")
            else:
                print(f"\nAnalisis IA regenerado para coincidencia #{args.regenerar_ia}")
                print(f"  Riesgo: {resultado.get('riesgo', '?')}")
                print(f"  Recomendacion: {resultado.get('recomendacion', '?')}")

        elif args.pdf:
            ruta_pdf = Path(args.pdf)
            if not ruta_pdf.exists():
                print(f"ERROR: Archivo no encontrado: {ruta_pdf}")
                sys.exit(1)
            resultado = pipeline.procesar_pdf_manual(ruta_pdf)
            print(f"\nProcesamiento manual completado:")
            print(f"  Entradas encontradas: {resultado['entradas']}")
            print(f"  Coincidencias: {resultado['coincidencias']}")
            print(f"  Analisis IA: {resultado['analisis_ia']}")

        else:
            fecha = None
            if args.fecha:
                try:
                    fecha = datetime.strptime(args.fecha, "%d/%m/%Y")
                except ValueError:
                    print("ERROR: Formato de fecha invalido. Usar DD/MM/YYYY")
                    sys.exit(1)

            resultado = pipeline.ejecutar_completo(
                fecha=fecha,
                solo_pendientes=args.pendientes,
            )

            print("\n" + "=" * 50)
            print("RESULTADO DE EJECUCION")
            print("=" * 50)
            print(f"  Boletines descargados:   {resultado['boletines_descargados']}")
            print(f"  Entradas procesadas:     {resultado['entradas_procesadas']}")
            print(f"  Coincidencias detectadas:{resultado['coincidencias_encontradas']}")
            print(f"  Analisis IA generados:   {resultado['analisis_ia_generados']}")
            if resultado.get("dashboard"):
                print(f"  Dashboard:               {resultado['dashboard']}")
            if resultado.get("errores"):
                print(f"  Errores:                 {len(resultado['errores'])}")
                for err in resultado["errores"]:
                    print(f"    - {err}")

    except KeyboardInterrupt:
        print("\nEjecucion interrumpida.")
    except Exception as e:
        logger.error(f"Error fatal: {e}", exc_info=True)
        print(f"\nERROR: {e}")
        sys.exit(1)
    finally:
        pipeline.cerrar()


def verificar_setup():
    """Verifica que todas las dependencias esten instaladas."""
    print("INPI Monitor - Verificacion de instalacion")
    print("=" * 50)

    dependencias = {
        "requests": "Scraping HTTP",
        "bs4": "Parsing HTML",
        "lxml": "Parser HTML rapido",
        "pdfplumber": "Extraccion texto PDF",
        "fitz": "Extraccion imagenes PDF (PyMuPDF)",
        "PIL": "Procesamiento imagenes (Pillow)",
        "jellyfish": "Comparacion fonetica",
        "rapidfuzz": "Fuzzy matching texto",
        "cv2": "Vision por computadora (OpenCV)",
        "skimage": "Metricas de imagen (scikit-image)",
        "sklearn": "Machine learning (scikit-learn)",
        "numpy": "Computacion numerica",
        "jinja2": "Templates HTML",
        "yaml": "Configuracion YAML",
    }

    opcionales = {
        "pytesseract": "OCR (requiere Tesseract instalado)",
        "selenium": "Navegador automatizado (fallback)",
        "openai": "IA Legal - OpenAI/Local",
        "anthropic": "IA Legal - Anthropic",
    }

    errores = 0
    for modulo, descripcion in dependencias.items():
        try:
            __import__(modulo)
            print(f"  [OK] {modulo:15s} - {descripcion}")
        except ImportError:
            print(f"  [X]  {modulo:15s} - {descripcion} (NO INSTALADO)")
            errores += 1

    print("\nOpcionales:")
    for modulo, descripcion in opcionales.items():
        try:
            __import__(modulo)
            print(f"  [OK] {modulo:15s} - {descripcion}")
        except ImportError:
            print(f"  [--] {modulo:15s} - {descripcion} (no instalado)")

    print("\nEstructura de archivos:")
    from pathlib import Path
    archivos = [
        "config/settings.yaml",
        "config/marcas_vigiladas.yaml",
        "src/pipeline.py",
        "src/analisis_ia.py",
        "src/dashboard.py",
        "src/db.py",
    ]
    for arch in archivos:
        ruta = Path(arch)
        estado = "OK" if ruta.exists() else "FALTA"
        print(f"  [{estado}] {arch}")

    print(f"\n{'LISTO para ejecutar' if errores == 0 else f'{errores} dependencia(s) faltante(s). Ejecutar: pip install -r requirements.txt'}")


if __name__ == "__main__":
    main()
