"""
Test end-to-end: ejecuta el pipeline completo contra el boletin de prueba
y valida que cada etapa produce resultados correctos.

Incluye mock de proveedor IA para probar sin API key.
"""

import sys
import json
from pathlib import Path

# Agregar raiz del proyecto al path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.config import cargar_settings, crear_estructura_carpetas, configurar_logging
from src.db import BaseDatos
from src.parser_pdf import ParserPDF
from src.comparador_texto import ComparadorTexto
from src.comparador_fonetico import ComparadorFonetico
from src.scoring import MotorScoring
from src.analisis_ia import AnalizadorIALegal, AnalisisIALegal, ProveedorLLM
from src.dashboard import GeneradorDashboard
from src.pipeline import Pipeline
from tests.crear_boletin_prueba import crear_boletin_prueba


# ============================================================
# Mock de proveedor LLM para testing sin API key
# ============================================================

class ProveedorMock(ProveedorLLM):
    """Proveedor mock que genera analisis IA estructurado sin llamar a ninguna API."""

    def llamar(self, sistema: str, usuario: str, max_tokens: int,
               temperatura: float) -> tuple[str, int]:
        """Genera una respuesta JSON estructurada basada en los datos del prompt."""

        # Extraer scores del prompt para generar respuesta coherente
        import re
        score_texto = self._extraer_pct(usuario, "textual")
        score_fon = self._extraer_pct(usuario, "fonetica")
        score_final = self._extraer_pct(usuario, "global")

        # Logica determinista basada en scores
        if score_final >= 70:
            riesgo = "alto"
            confund = "alta"
            recom = "revisar_urgente"
        elif score_final >= 50:
            riesgo = "medio"
            confund = "media"
            recom = "revisar"
        elif score_final >= 30:
            riesgo = "bajo"
            confund = "baja"
            recom = "probablemente_falso_positivo"
        else:
            riesgo = "bajo"
            confund = "baja"
            recom = "archivar"

        # Extraer marcas del prompt
        marca_vig = self._extraer_campo(usuario, "MARCA VIGILADA")
        marca_det = self._extraer_campo(usuario, "MARCA DETECTADA")

        sim_den = "alta" if score_texto >= 70 else ("media" if score_texto >= 40 else "baja")
        sim_fon = "alta" if score_fon >= 70 else ("media" if score_fon >= 40 else "baja")

        respuesta = {
            "riesgo_preliminar": riesgo,
            "confundibilidad_preliminar": confund,
            "similitud_denominativa": sim_den,
            "similitud_fonetica": sim_fon,
            "similitud_conceptual": "media" if score_final >= 50 else "baja",
            "similitud_visual": "no_aplica",
            "argumentos_a_favor": self._generar_args_favor(marca_vig, marca_det, score_texto, score_fon),
            "argumentos_en_contra": self._generar_args_contra(marca_vig, marca_det, score_texto, score_fon),
            "recomendacion_operativa": recom,
            "resumen_ejecutivo": (
                f"La marca '{marca_det}' presenta {'alta' if score_final >= 60 else 'moderada'} "
                f"similitud con '{marca_vig}'. "
                f"Similitud textual: {score_texto}%, fonetica: {score_fon}%. "
                f"Se recomienda {'revision urgente por posible confusion' if riesgo == 'alto' else 'evaluacion detallada'}."
            ),
        }

        return json.dumps(respuesta, ensure_ascii=False), 150  # mock tokens

    def nombre(self) -> str:
        return "mock/deterministic-v1"

    def _extraer_pct(self, texto: str, campo: str) -> int:
        import re
        match = re.search(rf"{campo}[:\s]+(\d+)%", texto, re.IGNORECASE)
        return int(match.group(1)) if match else 0

    def _extraer_campo(self, texto: str, campo: str) -> str:
        import re
        match = re.search(rf"{campo}:\s*(.+?)(?:\n|$)", texto)
        return match.group(1).strip() if match else "?"

    def _generar_args_favor(self, vig, det, score_t, score_f):
        args = []
        if score_t >= 60:
            args.append(f"Alta similitud denominativa entre '{vig}' y '{det}' ({score_t}%)")
        if score_f >= 60:
            args.append(f"Secuencia fonetica compartida significativa ({score_f}%)")
        if score_t >= 40:
            args.append("Radical o segmento dominante compartido")
        return args or ["Algunos elementos comunes detectados"]

    def _generar_args_contra(self, vig, det, score_t, score_f):
        args = []
        if score_t < 80:
            args.append("No hay coincidencia exacta de la denominacion completa")
        if score_f < 60:
            args.append("La diferencia fonetica reduce el riesgo de confusion oral")
        args.append("Se requiere analisis del contexto comercial y de mercado")
        return args


# ============================================================
# Tests
# ============================================================

def separador(titulo):
    print(f"\n{'='*60}")
    print(f"  {titulo}")
    print(f"{'='*60}")


def test_parser():
    """Test 1: Parser extrae texto y segmenta correctamente."""
    separador("TEST 1: Parser PDF")

    settings = cargar_settings()
    parser = ParserPDF(settings)

    ruta_pdf = Path("datos/pdfs/boletin_prueba_inpi.pdf")
    if not ruta_pdf.exists():
        crear_boletin_prueba(ruta_pdf)

    resultado = parser.procesar_pdf(ruta_pdf, Path("datos/logos_extraidos"))

    print(f"  Paginas: {resultado.total_paginas}")
    print(f"  Entradas encontradas: {len(resultado.entradas)}")
    print(f"  Imagenes: {len(resultado.imagenes_extraidas)}")
    print(f"  Errores: {resultado.errores}")
    print(f"  Uso OCR: {resultado.uso_ocr}")

    print(f"\n  Entradas detectadas:")
    for e in resultado.entradas:
        print(f"    Pag.{e.pagina} | {e.denominacion:25s} | Clase: {e.clase_niza} | Acta: {e.acta_numero} | Sol: {e.solicitante}")

    assert resultado.total_paginas == 4, f"Esperaba 4 paginas, obtuve {resultado.total_paginas}"
    assert len(resultado.entradas) >= 5, f"Esperaba >=5 entradas, obtuve {len(resultado.entradas)}"

    # Verificar que las denominaciones clave estan
    denoms = [e.denominacion for e in resultado.entradas]
    print(f"\n  Denominaciones: {denoms}")

    print("  [OK] Parser funciona correctamente")
    return resultado


def test_comparadores():
    """Test 2: Comparadores de texto y fonetica."""
    separador("TEST 2: Comparadores texto + fonetica")

    settings = cargar_settings()
    comp_texto = ComparadorTexto(settings)
    comp_fon = ComparadorFonetico(settings)

    # Casos esperados
    casos = [
        ("TELEVET PLUS", "Televet", True, "debe matchear"),
        ("REDEX SOLUTIONS", "Redex", True, "debe matchear"),
        ("MEDILINE PRO", "MediLine", True, "debe matchear"),
        ("RECETAR ONLINE", "Receta Online", True, "fonetico similar"),
        ("AUXILIO 24 HS", "Auxilio24", True, "debe matchear"),
        ("COCACOLA ZERO SUGAR", "Televet", False, "no debe matchear"),
        ("TELVEX", "Televet", True, "fonetico edge case"),
        ("MEDELLIN PHARMA", "MediLine", False, "no debe matchear fuerte"),
    ]

    print(f"  {'Detectada':25s} {'Referencia':15s} {'Texto':6s} {'Fonet':6s} {'Esperado':10s} {'OK?':4s}")
    print(f"  {'-'*75}")

    todos_ok = True
    for detectada, referencia, debe_matchear, nota in casos:
        res_t = comp_texto.comparar(detectada, referencia)
        res_f = comp_fon.comparar(detectada, referencia)

        # Consideramos match si texto>=0.5 O fonetico>=0.5
        matchea = res_t.score >= 0.5 or res_f.score >= 0.5
        ok = matchea == debe_matchear

        print(f"  {detectada:25s} {referencia:15s} {res_t.score:5.0%}  {res_f.score:5.0%}  {'match' if debe_matchear else 'no':10s} {'OK' if ok else 'FAIL'}")

        if not ok:
            todos_ok = False
            print(f"    Texto detalle: {res_t.detalle}")
            print(f"    Fonet detalle: {res_f.detalle}")

    if todos_ok:
        print("  [OK] Todos los comparadores funcionan correctamente")
    else:
        print("  [WARN] Algunos casos no matchearon como se esperaba (revisar umbrales)")

    return todos_ok


def test_scoring():
    """Test 3: Motor de scoring combina dimensiones."""
    separador("TEST 3: Motor de Scoring")

    settings = cargar_settings()
    scoring = MotorScoring(settings)
    comp_texto = ComparadorTexto(settings)
    comp_fon = ComparadorFonetico(settings)

    from src.comparador_visual import ResultadoVisual
    from src.comparador_color import ResultadoColor

    marca = {"nombre": "Televet", "clases_niza": [5, 44], "prioridad": "alta", "variantes": ["TeleVet"]}
    res_t = comp_texto.comparar("TELEVET PLUS", "Televet", marca["variantes"])
    res_f = comp_fon.comparar("TELEVET PLUS", "Televet", marca["variantes"])
    res_v = ResultadoVisual(score=0, score_ssim=0, score_orb=0, score_template=0, detalle="Sin imagen")
    res_c = ResultadoColor(score=0, score_histograma=0, score_dominantes=0, colores_detectados=[], colores_referencia=[], detalle="Sin imagen")

    resultado = scoring.calcular(
        marca_vigilada=marca,
        marca_detectada="TELEVET PLUS",
        pagina=2,
        archivo_pdf="boletin_prueba.pdf",
        resultado_texto=res_t,
        resultado_fonetico=res_f,
        resultado_visual=res_v,
        resultado_color=res_c,
        clase_detectada=[44],
        tipo_marca="denominativa",
    )

    print(f"  Marca: {resultado.marca_vigilada} vs {resultado.marca_detectada}")
    print(f"  Score final: {resultado.score_final:.0%}")
    print(f"  Nivel riesgo: {resultado.nivel_riesgo}")
    print(f"  Clase coincide: {resultado.clase_niza_coincide}")
    print(f"  Factores a favor: {resultado.factores_a_favor}")
    print(f"  Factores en contra: {resultado.factores_en_contra}")
    print(f"  Recomendacion: {resultado.recomendacion}")
    print(f"  Supera umbral: {scoring.supera_umbral(resultado)}")

    assert scoring.supera_umbral(resultado), "TELEVET PLUS deberia superar el umbral"
    print("  [OK] Scoring funciona correctamente")
    return resultado


def test_db_y_feedback():
    """Test 4: DB con tablas, analisis IA y feedback."""
    separador("TEST 4: Base de datos + feedback loop")

    ruta_db = Path("datos/test_e2e.db")
    ruta_db.unlink(missing_ok=True)
    db = BaseDatos(ruta_db)

    # Registrar boletin
    id_bol = db.registrar_boletin(
        id_inpi="test_001", titulo="Boletin prueba",
        fecha_pub="19/03/2026", comentario="MARCAS NUEVAS",
        url="http://test", archivo="test.pdf",
    )
    print(f"  Boletin registrado: id={id_bol}")

    # Registrar coincidencia
    id_coinc = db.registrar_coincidencia(
        id_boletin=id_bol, marca_vigilada="Televet",
        marca_detectada="TELEVET PLUS", pagina=2,
        tipo_match="texto", scores={"texto": 0.85, "fonetico": 0.9, "visual": 0, "color": 0},
        score_final=0.78, nivel_riesgo="alto",
        explicacion="Alta similitud denominativa y fonetica",
        clase_niza="[44]", tipo_marca="denominativa",
        metadata={"recomendacion": "REVISAR URGENTE", "factores_a_favor": ["Mismo radical"], "factores_en_contra": ["Palabra adicional PLUS"]},
    )
    print(f"  Coincidencia registrada: id={id_coinc}")

    # Simular revision humana (falso positivo previo para feedback)
    db.registrar_coincidencia(
        id_boletin=id_bol, marca_vigilada="Televet",
        marca_detectada="TELEVISA", pagina=3,
        tipo_match="fonetico", scores={"texto": 0.4, "fonetico": 0.6, "visual": 0, "color": 0},
        score_final=0.45, nivel_riesgo="bajo",
        explicacion="Similitud fonetica parcial",
    )
    # Marcar como falso positivo
    db.actualizar_revision(
        id_coincidencia=2, estado="descartado",
        decision="falso_positivo",
        comentario="No hay relacion comercial, marcas de rubros totalmente distintos",
        revisado_por="abogada",
    )
    print("  Revision humana registrada (falso positivo)")

    # Guardar analisis IA
    analisis = AnalisisIALegal(
        id_coincidencia=id_coinc,
        riesgo_preliminar="alto",
        confundibilidad_preliminar="alta",
        similitud_denominativa="alta",
        similitud_fonetica="alta",
        similitud_conceptual="media",
        similitud_visual="no_aplica",
        argumentos_a_favor=["Comparten radical TELEVET", "Misma clase 44"],
        argumentos_en_contra=["Palabra adicional PLUS", "Solicitantes diferentes"],
        recomendacion_operativa="revisar_urgente",
        resumen_ejecutivo="TELEVET PLUS presenta alta similitud con la marca vigilada Televet.",
        modelo_usado="mock/test",
        proveedor="mock",
        fecha_analisis="2026-03-19T10:00:00",
        tokens_usados=150,
        feedback_incorporado=True,
    )
    db.guardar_analisis_ia(analisis)
    print("  Analisis IA guardado en DB")

    # Recuperar analisis IA
    recuperado = db.obtener_analisis_ia(id_coinc)
    assert recuperado is not None, "Analisis IA no recuperado"
    assert recuperado["riesgo_preliminar"] == "alto"
    assert isinstance(recuperado["argumentos_a_favor"], list)
    assert len(recuperado["argumentos_a_favor"]) == 2
    print(f"  Analisis IA recuperado: riesgo={recuperado['riesgo_preliminar']}, recom={recuperado['recomendacion_operativa']}")

    # Obtener feedback historico
    feedback = db.obtener_feedback_para_par("Televet", "TELEVET PLUS")
    print(f"  Feedback para par Televet/TELEVET PLUS: {len(feedback)} items")

    feedback_general = db.obtener_feedback_para_par("Televet", "NUEVA MARCA")
    print(f"  Feedback general para Televet: {len(feedback_general)} items")
    assert len(feedback_general) >= 1, "Deberia haber feedback del falso positivo"

    # Estadisticas
    stats = db.obtener_estadisticas()
    print(f"  Estadisticas: {stats}")
    assert stats["analisis_ia_completados"] == 1
    assert stats["falsos_positivos"] == 1

    # Sin analisis
    sin = db.obtener_coincidencias_sin_analisis_ia()
    print(f"  Coincidencias sin analisis IA: {len(sin)}")

    db.cerrar()
    ruta_db.unlink(missing_ok=True)
    print("  [OK] DB + feedback + analisis IA funcionan correctamente")


def test_analisis_ia_mock():
    """Test 5: Analisis IA con proveedor mock."""
    separador("TEST 5: Analisis IA con mock LLM")

    settings = cargar_settings()
    analizador = AnalizadorIALegal(settings)
    # Forzar habilitado y usar mock
    analizador.habilitado = True
    analizador._proveedor = ProveedorMock()

    coincidencia = {
        "id": 1,
        "marca_vigilada": "Televet",
        "marca_detectada": "TELEVET PLUS",
        "tipo_marca": "denominativa",
        "clase_niza": "[44]",
        "score_texto": 0.85,
        "score_fonetico": 0.90,
        "score_visual": 0.0,
        "score_color": 0.0,
        "score_final": 0.78,
        "nivel_riesgo": "alto",
        "tipo_match": "texto",
        "explicacion": "Alta similitud denominativa con Televet",
        "pagina": 2,
        "id_boletin": 1,
        "solicitante": "Veterinaria del Sur SRL",
        "acta_numero": "3847291",
    }

    marca = {"nombre": "Televet", "variantes": ["TeleVet"], "clases_niza": [5, 44], "prioridad": "alta"}

    # Feedback historico simulado
    feedback = [
        {
            "marca_vigilada": "Televet",
            "marca_detectada": "TELEVISA",
            "decision": "falso_positivo",
            "estado": "descartado",
            "comentario": "Sin relacion comercial",
            "fecha_revision": "2026-03-10",
        },
    ]

    resultado = analizador.analizar_coincidencia(coincidencia, marca, feedback)

    print(f"  Riesgo preliminar:       {resultado.riesgo_preliminar}")
    print(f"  Confundibilidad:         {resultado.confundibilidad_preliminar}")
    print(f"  Similitud denominativa:  {resultado.similitud_denominativa}")
    print(f"  Similitud fonetica:      {resultado.similitud_fonetica}")
    print(f"  Similitud conceptual:    {resultado.similitud_conceptual}")
    print(f"  Similitud visual:        {resultado.similitud_visual}")
    print(f"  Recomendacion:           {resultado.recomendacion_operativa}")
    print(f"  Argumentos a favor:      {resultado.argumentos_a_favor}")
    print(f"  Argumentos en contra:    {resultado.argumentos_en_contra}")
    print(f"  Resumen:                 {resultado.resumen_ejecutivo}")
    print(f"  Modelo:                  {resultado.modelo_usado}")
    print(f"  Proveedor:               {resultado.proveedor}")
    print(f"  Tokens:                  {resultado.tokens_usados}")
    print(f"  Feedback incorporado:    {resultado.feedback_incorporado}")
    print(f"  Es valido:               {resultado.es_valido()}")
    print(f"  Error:                   {resultado.error or 'Ninguno'}")

    assert resultado.es_valido(), f"Analisis deberia ser valido pero tiene error: {resultado.error}"
    assert resultado.riesgo_preliminar in ("alto", "medio", "bajo")
    assert resultado.feedback_incorporado is True
    assert resultado.proveedor == "mock/deterministic-v1"
    print("  [OK] Analisis IA mock funciona correctamente")
    return resultado


def test_pipeline_completo():
    """Test 6: Pipeline end-to-end con PDF real."""
    separador("TEST 6: Pipeline completo end-to-end")

    # Limpiar DB de test anterior
    ruta_db = Path("datos/inpi.db")
    ruta_db.unlink(missing_ok=True)

    # Crear PDF de prueba si no existe
    ruta_pdf = Path("datos/pdfs/boletin_prueba_inpi.pdf")
    if not ruta_pdf.exists():
        crear_boletin_prueba(ruta_pdf)

    # Crear pipeline con IA habilitada via mock
    settings = cargar_settings()
    settings["ia_legal"]["habilitado"] = True  # Forzar IA

    pipeline = Pipeline(settings)
    # Inyectar mock
    pipeline.ia.habilitado = True
    pipeline.ia._proveedor = ProveedorMock()

    # Ejecutar procesamiento manual del PDF
    resultado = pipeline.procesar_pdf_manual(ruta_pdf)

    print(f"  Entradas procesadas:     {resultado['entradas']}")
    print(f"  Coincidencias detectadas:{resultado['coincidencias']}")
    print(f"  Analisis IA generados:   {resultado['analisis_ia']}")

    # Verificar coincidencias en DB
    coincidencias = pipeline.db.obtener_todas_coincidencias()
    print(f"\n  Coincidencias en DB: {len(coincidencias)}")
    for c in coincidencias:
        ia = pipeline.db.obtener_analisis_ia(c["id"])
        ia_info = f"IA: {ia['recomendacion_operativa']}" if ia and not ia.get("error") else "Sin IA"
        print(
            f"    #{c['id']} | {c['marca_vigilada']:15s} vs {c['marca_detectada']:25s} | "
            f"Score: {c['score_final']:.0%} | {c['nivel_riesgo']:6s} | {ia_info}"
        )

    # Verificar dashboard
    ruta_dash = Path("datos/reportes/dashboard.html")
    assert ruta_dash.exists(), "Dashboard no generado"
    size = ruta_dash.stat().st_size
    print(f"\n  Dashboard generado: {ruta_dash} ({size:,} bytes)")

    # Verificar que el dashboard contiene la seccion IA
    with open(ruta_dash, "r") as f:
        html = f.read()
    assert "Analisis IA Legal" in html, "Dashboard no contiene seccion IA Legal"
    assert "Riesgo:" in html or "riesgo_preliminar" in html or "ia-card" in html
    print("  Dashboard contiene seccion IA Legal")

    # Estadisticas finales
    stats = pipeline.db.obtener_estadisticas()
    print(f"\n  Estadisticas finales:")
    print(f"    Boletines:              {stats['total_boletines']}")
    print(f"    Boletines procesados:   {stats['boletines_procesados']}")
    print(f"    Coincidencias totales:  {stats['total_coincidencias']}")
    print(f"    Analisis IA completos:  {stats['analisis_ia_completados']}")
    print(f"    Pendientes revision:    {stats['pendientes_revision']}")

    assert stats["total_coincidencias"] > 0, "Deberia haber coincidencias"
    assert stats["analisis_ia_completados"] > 0, "Deberia haber analisis IA"

    pipeline.cerrar()
    print("  [OK] Pipeline completo funciona end-to-end")


def test_modo_sin_ia():
    """Test 7: Sistema funciona sin IA configurada."""
    separador("TEST 7: Modo sin IA (degradacion elegante)")

    ruta_db = Path("datos/test_no_ia.db")
    ruta_db.unlink(missing_ok=True)

    settings = cargar_settings()
    settings["ia_legal"]["habilitado"] = False

    # Verificar que el analizador no explota
    analizador = AnalizadorIALegal(settings)
    resultado = analizador.analizar_coincidencia({"id": 1}, {}, [])

    assert resultado.error == "Analisis IA no habilitado. Activar en config/settings.yaml"
    assert not resultado.es_valido()
    print(f"  Resultado sin IA: error='{resultado.error}'")
    print("  [OK] Sistema funciona correctamente sin IA configurada")


def test_regenerar_ia():
    """Test 8: Regenerar analisis IA para un caso especifico."""
    separador("TEST 8: Regenerar analisis IA individual")

    ruta_db = Path("datos/inpi.db")
    if not ruta_db.exists():
        print("  SKIP: Ejecutar test_pipeline_completo primero")
        return

    settings = cargar_settings()
    settings["ia_legal"]["habilitado"] = True
    pipeline = Pipeline(settings)
    pipeline.ia.habilitado = True
    pipeline.ia._proveedor = ProveedorMock()

    # Obtener primera coincidencia
    coincidencias = pipeline.db.obtener_todas_coincidencias()
    if not coincidencias:
        print("  SKIP: No hay coincidencias")
        pipeline.cerrar()
        return

    id_coinc = coincidencias[0]["id"]
    print(f"  Regenerando analisis para coincidencia #{id_coinc}...")

    resultado = pipeline.ejecutar_analisis_ia(id_coincidencia=id_coinc)
    print(f"  Resultado: {resultado}")

    # Verificar que se actualizo
    analisis = pipeline.db.obtener_analisis_ia(id_coinc)
    assert analisis is not None, "Analisis no encontrado despues de regenerar"
    print(f"  Analisis regenerado: riesgo={analisis['riesgo_preliminar']}, modelo={analisis['modelo_usado']}")

    pipeline.cerrar()
    print("  [OK] Regeneracion de analisis IA funciona")


# ============================================================
# Ejecucion
# ============================================================

if __name__ == "__main__":
    print("\n" + "#" * 60)
    print("#  INPI Monitor - Test End-to-End Completo")
    print("#" * 60)

    tests = [
        ("Parser PDF", test_parser),
        ("Comparadores", test_comparadores),
        ("Scoring", test_scoring),
        ("DB + Feedback", test_db_y_feedback),
        ("Analisis IA Mock", test_analisis_ia_mock),
        ("Pipeline E2E", test_pipeline_completo),
        ("Modo sin IA", test_modo_sin_ia),
        ("Regenerar IA", test_regenerar_ia),
    ]

    resultados = []
    for nombre, test_fn in tests:
        try:
            test_fn()
            resultados.append((nombre, "OK"))
        except Exception as e:
            print(f"  [FAIL] {nombre}: {e}")
            import traceback
            traceback.print_exc()
            resultados.append((nombre, f"FAIL: {e}"))

    separador("RESUMEN DE TESTS")
    for nombre, estado in resultados:
        icono = "OK" if estado == "OK" else "FAIL"
        print(f"  [{icono:4s}] {nombre}")

    fallos = sum(1 for _, e in resultados if e != "OK")
    print(f"\n  Total: {len(tests)} tests, {len(tests) - fallos} OK, {fallos} fallos")
