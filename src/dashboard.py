"""
Generador de dashboard HTML profesional.
Usa Jinja2 para templates.
Genera un archivo HTML standalone (sin dependencias externas).
Incluye pestana de Analisis IA Legal.
"""

import logging
from pathlib import Path
from datetime import datetime
from collections import Counter

from jinja2 import Template

from .config import obtener_ruta

logger = logging.getLogger("inpi.dashboard")


class GeneradorDashboard:
    def __init__(self, settings: dict):
        cfg = settings.get("dashboard", {})
        self.titulo = cfg.get("titulo", "INPI Monitor")
        self.max_coincidencias = cfg.get("max_coincidencias_resumen", 50)
        self.agrupar_por = cfg.get("agrupar_por", "marca")
        self.archivo_salida = obtener_ruta(settings, "reportes") / "dashboard.html"

    def generar(self, coincidencias: list[dict], estadisticas: dict,
                boletines: list[dict]) -> Path:
        """Genera el dashboard HTML completo."""
        self.archivo_salida.parent.mkdir(parents=True, exist_ok=True)

        # Preparar datos
        resumen = self._calcular_resumen(coincidencias)
        agrupadas = self._agrupar(coincidencias)
        fecha = datetime.now().strftime("%d/%m/%Y %H:%M")

        # Separar coincidencias con analisis IA
        con_ia = [c for c in coincidencias if c.get("analisis_ia") and not c["analisis_ia"].get("error")]
        resumen_ia = self._calcular_resumen_ia(con_ia)

        # Renderizar
        html = TEMPLATE_DASHBOARD.render(
            titulo=self.titulo,
            fecha_generacion=fecha,
            resumen=resumen,
            resumen_ia=resumen_ia,
            estadisticas=estadisticas,
            coincidencias=coincidencias[:self.max_coincidencias],
            agrupadas=agrupadas,
            con_ia=con_ia,
            boletines=boletines,
            total_coincidencias=len(coincidencias),
        )

        with open(self.archivo_salida, "w", encoding="utf-8") as f:
            f.write(html)

        logger.info(f"Dashboard generado: {self.archivo_salida}")
        return self.archivo_salida

    def _calcular_resumen(self, coincidencias: list[dict]) -> dict:
        if not coincidencias:
            return {
                "total": 0, "alto": 0, "medio": 0, "bajo": 0,
                "marcas_afectadas": [], "tipos_match": {},
                "palabras_frecuentes": [],
            }

        niveles = Counter(c.get("nivel_riesgo", "bajo") for c in coincidencias)
        marcas = Counter(c.get("marca_vigilada", "") for c in coincidencias)
        tipos = Counter(c.get("tipo_match", "") for c in coincidencias)

        palabras = []
        for c in coincidencias:
            det = c.get("marca_detectada", "")
            if det:
                palabras.extend(det.upper().split())
        palabras_freq = Counter(palabras).most_common(10)

        return {
            "total": len(coincidencias),
            "alto": niveles.get("alto", 0),
            "medio": niveles.get("medio", 0),
            "bajo": niveles.get("bajo", 0),
            "marcas_afectadas": marcas.most_common(10),
            "tipos_match": dict(tipos),
            "palabras_frecuentes": palabras_freq,
        }

    def _calcular_resumen_ia(self, con_ia: list[dict]) -> dict:
        """Resumen de analisis IA."""
        if not con_ia:
            return {"total": 0, "por_recomendacion": {}, "por_riesgo": {}}

        recomendaciones = Counter()
        riesgos = Counter()
        for c in con_ia:
            ia = c.get("analisis_ia", {})
            recomendaciones[ia.get("recomendacion_operativa", "?")] += 1
            riesgos[ia.get("riesgo_preliminar", "?")] += 1

        return {
            "total": len(con_ia),
            "por_recomendacion": dict(recomendaciones),
            "por_riesgo": dict(riesgos),
        }

    def _agrupar(self, coincidencias: list[dict]) -> dict:
        grupos = {}
        for c in coincidencias:
            clave = c.get("marca_vigilada", "Otra") if self.agrupar_por == "marca" else c.get("tipo_match", "Otro")
            if clave not in grupos:
                grupos[clave] = []
            grupos[clave].append(c)
        for clave in grupos:
            grupos[clave].sort(key=lambda x: x.get("score_final", 0), reverse=True)
        return grupos


TEMPLATE_DASHBOARD = Template(r"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{{ titulo }}</title>
<style>
  :root {
    --azul: #1a56db; --azul-claro: #e8eefb;
    --rojo: #dc2626; --naranja: #ea580c;
    --amarillo: #ca8a04; --verde: #16a34a;
    --violeta: #7c3aed; --violeta-claro: #ede9fe;
    --gris: #6b7280; --gris-claro: #f3f4f6;
    --blanco: #ffffff; --texto: #1f2937; --borde: #e5e7eb;
  }
  * { margin:0; padding:0; box-sizing:border-box; }
  body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; color: var(--texto); background: var(--gris-claro); line-height: 1.5; }
  .container { max-width: 1280px; margin: 0 auto; padding: 20px; }
  header { background: var(--azul); color: white; padding: 24px; margin-bottom: 24px; border-radius: 8px; }
  header h1 { font-size: 24px; margin-bottom: 4px; }
  header .fecha { opacity: 0.8; font-size: 14px; }

  /* Tabs */
  .tabs { display: flex; gap: 0; margin-bottom: 0; border-bottom: 2px solid var(--borde); }
  .tab { padding: 12px 24px; cursor: pointer; font-weight: 600; font-size: 14px; border: 1px solid transparent; border-bottom: none; border-radius: 8px 8px 0 0; background: transparent; color: var(--gris); transition: all 0.2s; }
  .tab:hover { background: var(--gris-claro); }
  .tab.active { background: var(--blanco); color: var(--azul); border-color: var(--borde); margin-bottom: -2px; border-bottom: 2px solid var(--blanco); }
  .tab.ia-tab.active { color: var(--violeta); }
  .tab-content { display: none; }
  .tab-content.active { display: block; padding-top: 24px; }

  .cards { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 16px; margin-bottom: 24px; }
  .card { background: var(--blanco); padding: 20px; border-radius: 8px; border: 1px solid var(--borde); text-align: center; }
  .card .numero { font-size: 36px; font-weight: 700; }
  .card .label { font-size: 13px; color: var(--gris); text-transform: uppercase; letter-spacing: 0.5px; }
  .card.alto .numero { color: var(--rojo); }
  .card.medio .numero { color: var(--naranja); }
  .card.bajo .numero { color: var(--amarillo); }
  .card.total .numero { color: var(--azul); }
  .card.ia .numero { color: var(--violeta); }

  .seccion { background: var(--blanco); border-radius: 8px; border: 1px solid var(--borde); margin-bottom: 24px; overflow: hidden; }
  .seccion h2 { padding: 16px 20px; font-size: 18px; border-bottom: 1px solid var(--borde); background: var(--gris-claro); }
  .seccion h2.ia-header { background: var(--violeta-claro); color: var(--violeta); }
  .seccion-body { padding: 20px; }

  table { width: 100%; border-collapse: collapse; font-size: 14px; }
  th { text-align: left; padding: 10px 12px; background: var(--gris-claro); font-weight: 600; border-bottom: 2px solid var(--borde); }
  td { padding: 10px 12px; border-bottom: 1px solid var(--borde); vertical-align: top; }
  tr:hover { background: #f9fafb; }

  .badge { display: inline-block; padding: 2px 10px; border-radius: 12px; font-size: 12px; font-weight: 600; text-transform: uppercase; }
  .badge-alto { background: #fef2f2; color: var(--rojo); }
  .badge-medio { background: #fff7ed; color: var(--naranja); }
  .badge-bajo { background: #fefce8; color: var(--amarillo); }
  .badge-minimo { background: var(--gris-claro); color: var(--gris); }
  .badge-revisar_urgente { background: #fef2f2; color: var(--rojo); }
  .badge-revisar { background: #fff7ed; color: var(--naranja); }
  .badge-probablemente_falso_positivo { background: #f0fdf4; color: var(--verde); }
  .badge-archivar { background: var(--gris-claro); color: var(--gris); }

  .score-bar { width: 100%; height: 8px; background: var(--gris-claro); border-radius: 4px; overflow: hidden; margin-top: 4px; }
  .score-fill { height: 100%; border-radius: 4px; }
  .score-fill.alto { background: var(--rojo); }
  .score-fill.medio { background: var(--naranja); }
  .score-fill.bajo { background: var(--amarillo); }
  .score-fill.minimo { background: var(--gris); }

  .btn { background: none; border: 1px solid var(--borde); padding: 4px 12px; border-radius: 4px; cursor: pointer; font-size: 12px; color: var(--azul); }
  .btn:hover { background: var(--azul-claro); }
  .btn-ia { color: var(--violeta); }
  .btn-ia:hover { background: var(--violeta-claro); }

  .expandible { display: none; margin-top: 12px; padding: 12px; background: var(--gris-claro); border-radius: 6px; font-size: 13px; }
  .expandible.visible { display: block; }

  /* IA Legal card */
  .ia-card { background: var(--blanco); border: 1px solid var(--borde); border-radius: 8px; padding: 20px; margin-bottom: 16px; border-left: 4px solid var(--violeta); }
  .ia-card h3 { font-size: 16px; margin-bottom: 8px; display: flex; justify-content: space-between; align-items: center; }
  .ia-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; margin: 12px 0; }
  .ia-field { font-size: 13px; }
  .ia-field .ia-label { font-weight: 600; color: var(--gris); font-size: 12px; text-transform: uppercase; letter-spacing: 0.3px; }
  .ia-field .ia-value { margin-top: 2px; }
  .ia-arguments { margin: 12px 0; }
  .ia-arguments h4 { font-size: 13px; font-weight: 600; margin-bottom: 4px; }
  .ia-arg-favor { color: var(--rojo); font-size: 13px; padding: 2px 0; }
  .ia-arg-contra { color: var(--verde); font-size: 13px; padding: 2px 0; }
  .ia-resumen { background: var(--violeta-claro); padding: 12px; border-radius: 6px; margin-top: 12px; font-size: 13px; }
  .ia-meta { font-size: 11px; color: var(--gris); margin-top: 8px; }

  .disclaimer { margin-top: 24px; padding: 16px; background: #fffbeb; border: 1px solid #fde68a; border-radius: 8px; font-size: 13px; color: #92400e; }
  .disclaimer-ia { background: var(--violeta-claro); border-color: #c4b5fd; color: #5b21b6; }

  .grupo-header { padding: 12px 20px; background: var(--azul-claro); font-weight: 600; cursor: pointer; border-bottom: 1px solid var(--borde); display: flex; justify-content: space-between; align-items: center; }
  .grupo-header:hover { background: #dce5f5; }
  .grupo-body { display: none; }
  .grupo-body.visible { display: block; }

  .tags { display: flex; gap: 6px; flex-wrap: wrap; margin-top: 4px; }
  .tag { font-size: 11px; padding: 1px 8px; background: var(--azul-claro); color: var(--azul); border-radius: 10px; }
  .tag-ia { background: var(--violeta-claro); color: var(--violeta); }

  .factores { margin: 8px 0; }
  .factor-favor { color: var(--rojo); }
  .factor-contra { color: var(--verde); }

  footer { text-align: center; padding: 20px; color: var(--gris); font-size: 13px; }

  @media (max-width: 768px) {
    .cards { grid-template-columns: 1fr 1fr; }
    .ia-grid { grid-template-columns: 1fr; }
    table { font-size: 12px; }
    th, td { padding: 8px 6px; }
    .tabs { flex-wrap: wrap; }
    .tab { font-size: 12px; padding: 8px 12px; }
  }
</style>
</head>
<body>
<div class="container">

<header>
  <h1>{{ titulo }}</h1>
  <div class="fecha">Generado: {{ fecha_generacion }} | Boletines: {{ estadisticas.get('boletines_procesados', 0) }} | Coincidencias: {{ total_coincidencias }} | Analisis IA: {{ estadisticas.get('analisis_ia_completados', 0) }}</div>
</header>

<!-- TABS -->
<div class="tabs">
  <div class="tab active" onclick="switchTab('resumen')">Resumen</div>
  <div class="tab" onclick="switchTab('detalle')">Detalle coincidencias</div>
  <div class="tab ia-tab" onclick="switchTab('ia-legal')">Analisis IA Legal</div>
  <div class="tab" onclick="switchTab('boletines')">Boletines</div>
</div>

<!-- TAB: Resumen -->
<div id="tab-resumen" class="tab-content active">
  <div class="cards">
    <div class="card total"><div class="numero">{{ resumen.total }}</div><div class="label">Total coincidencias</div></div>
    <div class="card alto"><div class="numero">{{ resumen.alto }}</div><div class="label">Riesgo alto</div></div>
    <div class="card medio"><div class="numero">{{ resumen.medio }}</div><div class="label">Riesgo medio</div></div>
    <div class="card bajo"><div class="numero">{{ resumen.bajo }}</div><div class="label">Riesgo bajo</div></div>
    <div class="card ia"><div class="numero">{{ resumen_ia.total }}</div><div class="label">Con analisis IA</div></div>
  </div>

  {% if resumen.marcas_afectadas %}
  <div class="seccion">
    <h2>Marcas mas afectadas</h2>
    <div class="seccion-body">
      <table>
        <tr><th>Marca vigilada</th><th>Coincidencias</th></tr>
        {% for marca, cnt in resumen.marcas_afectadas %}
        <tr><td><strong>{{ marca }}</strong></td><td>{{ cnt }}</td></tr>
        {% endfor %}
      </table>
    </div>
  </div>
  {% endif %}

  {% if resumen.palabras_frecuentes %}
  <div class="seccion">
    <h2>Terminos mas repetidos</h2>
    <div class="seccion-body">
      <div class="tags">{% for p, c in resumen.palabras_frecuentes %}<span class="tag">{{ p }} ({{ c }})</span>{% endfor %}</div>
    </div>
  </div>
  {% endif %}

  {% if resumen_ia.total > 0 %}
  <div class="seccion">
    <h2 class="ia-header">Resumen IA Legal</h2>
    <div class="seccion-body">
      <div class="cards">
        {% for rec, cnt in resumen_ia.por_recomendacion.items() %}
        <div class="card"><div class="numero" style="font-size:24px">{{ cnt }}</div><div class="label">{{ rec | replace('_', ' ') }}</div></div>
        {% endfor %}
      </div>
      <p style="margin-top:12px;font-size:13px;color:var(--gris)">
        Falsos positivos historicos: {{ estadisticas.get('falsos_positivos', 0) }} |
        Confirmados: {{ estadisticas.get('confirmados', 0) }}
      </p>
    </div>
  </div>
  {% endif %}
</div>

<!-- TAB: Detalle coincidencias -->
<div id="tab-detalle" class="tab-content">
  <div class="seccion">
    <h2>Detalle de coincidencias</h2>
    {% for grupo, items in agrupadas.items() %}
    <div class="grupo-header" onclick="toggleGrupo(this)">
      <span>{{ grupo }} ({{ items|length }})</span>
      <span class="btn">ver mas</span>
    </div>
    <div class="grupo-body">
      <table>
        <tr><th>Marca detectada</th><th>Score</th><th>Nivel</th><th>Tipo</th><th>PDF / Pag.</th><th></th></tr>
        {% for c in items %}
        <tr>
          <td>
            <strong>{{ c.get('marca_detectada', 'N/A') }}</strong>
            <div class="tags">
              {% if c.get('clase_niza') %}<span class="tag">Clase {{ c.get('clase_niza') }}</span>{% endif %}
              {% if c.get('tipo_marca') %}<span class="tag">{{ c.get('tipo_marca') }}</span>{% endif %}
              {% if c.get('analisis_ia') and not c['analisis_ia'].get('error') %}<span class="tag tag-ia">IA</span>{% endif %}
            </div>
          </td>
          <td>
            {{ "%.0f"|format((c.get('score_final', 0)) * 100) }}%
            <div class="score-bar"><span class="score-fill {{ c.get('nivel_riesgo', 'minimo') }}" style="width:{{ (c.get('score_final', 0)) * 100 }}%"></span></div>
          </td>
          <td><span class="badge badge-{{ c.get('nivel_riesgo', 'minimo') }}">{{ c.get('nivel_riesgo', 'N/A') }}</span></td>
          <td>{{ c.get('tipo_match', 'N/A') }}</td>
          <td>{{ c.get('archivo_pdf', 'N/A') }}<br><small>Pag. {{ c.get('pagina', '?') }}</small></td>
          <td>
            <button class="btn" onclick="toggleExp(this)">detalle</button>
            <div class="expandible">
              <p><strong>Explicacion:</strong> {{ c.get('explicacion', '') }}</p>
              <p><strong>Recomendacion:</strong> {{ c.get('recomendacion', '') }}</p>
              {% if c.get('factores_a_favor') %}
              <div class="factores"><strong>A favor:</strong><ul>{% for f in c.get('factores_a_favor', []) %}<li class="factor-favor">{{ f }}</li>{% endfor %}</ul></div>
              {% endif %}
              {% if c.get('factores_en_contra') %}
              <div class="factores"><strong>En contra:</strong><ul>{% for f in c.get('factores_en_contra', []) %}<li class="factor-contra">{{ f }}</li>{% endfor %}</ul></div>
              {% endif %}
              <p><strong>Scores:</strong> Texto: {{ "%.0f"|format((c.get('score_texto', 0)) * 100) }}% | Fonetico: {{ "%.0f"|format((c.get('score_fonetico', 0)) * 100) }}% | Visual: {{ "%.0f"|format((c.get('score_visual', 0)) * 100) }}% | Color: {{ "%.0f"|format((c.get('score_color', 0)) * 100) }}%</p>
              {% if c.get('estado_revision') %}<p><strong>Revision:</strong> {{ c.get('estado_revision') }} {% if c.get('decision') %} ({{ c.get('decision') }}){% endif %} {% if c.get('comentario_revision') %} - {{ c.get('comentario_revision') }}{% endif %}</p>{% endif %}
            </div>
          </td>
        </tr>
        {% endfor %}
      </table>
    </div>
    {% endfor %}
  </div>
</div>

<!-- TAB: Analisis IA Legal -->
<div id="tab-ia-legal" class="tab-content">
  {% if con_ia %}
  <div class="cards" style="margin-bottom:24px">
    <div class="card ia"><div class="numero">{{ con_ia|length }}</div><div class="label">Analisis completados</div></div>
    {% for rec, cnt in resumen_ia.por_recomendacion.items() %}
    <div class="card"><div class="numero" style="font-size:24px">{{ cnt }}</div><div class="label">{{ rec | replace('_', ' ') }}</div></div>
    {% endfor %}
  </div>

  {% for c in con_ia %}
  {% set ia = c.get('analisis_ia', {}) %}
  <div class="ia-card">
    <h3>
      <span>{{ c.get('marca_vigilada', '') }} vs {{ c.get('marca_detectada', '') }}</span>
      <span>
        <span class="badge badge-{{ ia.get('riesgo_preliminar', 'medio') }}">Riesgo: {{ ia.get('riesgo_preliminar', '?') }}</span>
        <span class="badge badge-{{ ia.get('recomendacion_operativa', 'revisar') }}">{{ ia.get('recomendacion_operativa', '?') | replace('_', ' ') }}</span>
      </span>
    </h3>

    <div class="ia-grid">
      <div class="ia-field"><div class="ia-label">Confundibilidad preliminar</div><div class="ia-value"><span class="badge badge-{{ ia.get('confundibilidad_preliminar', 'media') }}">{{ ia.get('confundibilidad_preliminar', '?') }}</span></div></div>
      <div class="ia-field"><div class="ia-label">Score tecnico</div><div class="ia-value">{{ "%.0f"|format((c.get('score_final', 0)) * 100) }}% ({{ c.get('nivel_riesgo', '') }})</div></div>
      <div class="ia-field"><div class="ia-label">Sim. denominativa</div><div class="ia-value">{{ ia.get('similitud_denominativa', '-') }}</div></div>
      <div class="ia-field"><div class="ia-label">Sim. fonetica</div><div class="ia-value">{{ ia.get('similitud_fonetica', '-') }}</div></div>
      <div class="ia-field"><div class="ia-label">Sim. conceptual</div><div class="ia-value">{{ ia.get('similitud_conceptual', '-') }}</div></div>
      <div class="ia-field"><div class="ia-label">Sim. visual</div><div class="ia-value">{{ ia.get('similitud_visual', '-') }}</div></div>
      <div class="ia-field"><div class="ia-label">Tipo marca</div><div class="ia-value">{{ c.get('tipo_marca', '-') }}</div></div>
      <div class="ia-field"><div class="ia-label">Clase / PDF / Pag.</div><div class="ia-value">{{ c.get('clase_niza', '-') }} | Pag. {{ c.get('pagina', '?') }}</div></div>
    </div>

    {% if ia.get('argumentos_a_favor') or ia.get('argumentos_en_contra') %}
    <div class="ia-arguments">
      {% if ia.get('argumentos_a_favor') %}
      <h4 style="color:var(--rojo)">Argumentos a favor del conflicto</h4>
      {% for arg in ia.get('argumentos_a_favor', []) %}<div class="ia-arg-favor">&#8226; {{ arg }}</div>{% endfor %}
      {% endif %}
      {% if ia.get('argumentos_en_contra') %}
      <h4 style="color:var(--verde);margin-top:8px">Argumentos en contra</h4>
      {% for arg in ia.get('argumentos_en_contra', []) %}<div class="ia-arg-contra">&#8226; {{ arg }}</div>{% endfor %}
      {% endif %}
    </div>
    {% endif %}

    {% if ia.get('resumen_ejecutivo') %}
    <div class="ia-resumen"><strong>Resumen ejecutivo:</strong> {{ ia.get('resumen_ejecutivo', '') }}</div>
    {% endif %}

    <div class="ia-meta">
      Modelo: {{ ia.get('modelo_usado', '?') }} | Proveedor: {{ ia.get('proveedor', '?') }} | {{ ia.get('fecha_analisis', '') | truncate(19) }}
      {% if ia.get('feedback_incorporado') %} | <span class="tag tag-ia" style="font-size:10px">Con feedback historico</span>{% endif %}
      | Tokens: {{ ia.get('tokens_usados', 0) }}
    </div>
  </div>
  {% endfor %}

  <div class="disclaimer disclaimer-ia">
    <strong>Aviso legal:</strong> Las opiniones preliminares de esta seccion son generadas por inteligencia artificial
    y no constituyen dictamen juridico. Son una herramienta de asistencia para priorizar la revision profesional.
    Toda decision sobre acciones legales debe ser tomada por un profesional habilitado.
  </div>

  {% else %}
  <div class="seccion">
    <h2 class="ia-header">Analisis IA Legal</h2>
    <div class="seccion-body" style="text-align:center;padding:40px;color:var(--gris)">
      <p style="font-size:16px">No hay analisis IA disponibles.</p>
      <p style="margin-top:8px">Para activar esta funcion, configurar <code>ia_legal.habilitado: true</code> en <code>config/settings.yaml</code> y proporcionar una API key.</p>
      <p style="margin-top:4px">Ejecutar: <code>python main.py --analisis-ia</code></p>
    </div>
  </div>
  {% endif %}
</div>

<!-- TAB: Boletines -->
<div id="tab-boletines" class="tab-content">
  {% if boletines %}
  <div class="seccion">
    <h2>Boletines procesados</h2>
    <div class="seccion-body">
      <table>
        <tr><th>ID</th><th>Titulo</th><th>Fecha</th><th>Estado</th></tr>
        {% for b in boletines %}
        <tr>
          <td>{{ b.get('id_inpi', '') }}</td>
          <td>{{ b.get('titulo', '') }}</td>
          <td>{{ b.get('fecha_publicacion', '') }}</td>
          <td><span class="badge badge-{% if b.get('estado')=='procesado' %}bajo{% else %}medio{% endif %}">{{ b.get('estado', '') }}</span></td>
        </tr>
        {% endfor %}
      </table>
    </div>
  </div>
  {% else %}
  <div class="seccion"><h2>Boletines</h2><div class="seccion-body" style="text-align:center;padding:40px;color:var(--gris)">No hay boletines procesados aun.</div></div>
  {% endif %}
</div>

<div class="disclaimer">
  <strong>Aviso:</strong> Este reporte es generado automaticamente con fines de vigilancia marcaria.
  No constituye dictamen juridico. Las coincidencias detectadas requieren revision profesional.
</div>

<footer>INPI Monitor v1.0 | {{ fecha_generacion }}</footer>
</div>

<script>
function switchTab(name) {
  document.querySelectorAll('.tab-content').forEach(t => t.classList.remove('active'));
  document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
  document.getElementById('tab-' + name).classList.add('active');
  event.target.classList.add('active');
}
function toggleExp(btn) {
  const el = btn.nextElementSibling;
  el.classList.toggle('visible');
  btn.textContent = el.classList.contains('visible') ? 'ocultar' : 'detalle';
}
function toggleGrupo(header) {
  const body = header.nextElementSibling;
  body.classList.toggle('visible');
  const btn = header.querySelector('.btn');
  if (btn) btn.textContent = body.classList.contains('visible') ? 'ocultar' : 'ver mas';
}
document.addEventListener('DOMContentLoaded', function() {
  const primer = document.querySelector('.grupo-body');
  if (primer) primer.classList.add('visible');
});
</script>
</body>
</html>""")
