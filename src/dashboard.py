"""
Generador de dashboard HTML profesional.
Usa Jinja2 para templates.
Genera un archivo HTML standalone (sin dependencias externas).
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
                boletines: list[dict], analisis_ia: dict = None) -> Path:
        """Genera el dashboard HTML completo."""
        self.archivo_salida.parent.mkdir(parents=True, exist_ok=True)

        # Preparar datos
        resumen = self._calcular_resumen(coincidencias)
        agrupadas = self._agrupar(coincidencias)
        fecha = datetime.now().strftime("%d/%m/%Y %H:%M")

        # Renderizar
        html = TEMPLATE_DASHBOARD.render(
            titulo=self.titulo,
            fecha_generacion=fecha,
            resumen=resumen,
            estadisticas=estadisticas,
            coincidencias=coincidencias[:self.max_coincidencias],
            agrupadas=agrupadas,
            boletines=boletines,
            analisis_ia=analisis_ia or {},
            total_coincidencias=len(coincidencias),
        )

        with open(self.archivo_salida, "w", encoding="utf-8") as f:
            f.write(html)

        logger.info(f"Dashboard generado: {self.archivo_salida}")
        return self.archivo_salida

    def _calcular_resumen(self, coincidencias: list[dict]) -> dict:
        """Calcula estadisticas de resumen."""
        if not coincidencias:
            return {
                "total": 0, "alto": 0, "medio": 0, "bajo": 0,
                "marcas_afectadas": [], "tipos_match": {},
                "palabras_frecuentes": [],
            }

        niveles = Counter(c.get("nivel_riesgo", "bajo") for c in coincidencias)
        marcas = Counter(c.get("marca_vigilada", "") for c in coincidencias)
        tipos = Counter(c.get("tipo_match_principal", "") for c in coincidencias)

        # Palabras mas frecuentes en marcas detectadas
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

    def _agrupar(self, coincidencias: list[dict]) -> dict:
        """Agrupa coincidencias por marca o criterio."""
        grupos = {}
        for c in coincidencias:
            clave = c.get("marca_vigilada", "Otra") if self.agrupar_por == "marca" else c.get("tipo_match_principal", "Otro")
            if clave not in grupos:
                grupos[clave] = []
            grupos[clave].append(c)
        # Ordenar cada grupo por score
        for clave in grupos:
            grupos[clave].sort(key=lambda x: x.get("score_final", 0), reverse=True)
        return grupos


# Template HTML inline (standalone, sin dependencias externas)
TEMPLATE_DASHBOARD = Template("""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{{ titulo }}</title>
<style>
  :root {
    --azul: #1a56db;
    --azul-claro: #e8eefb;
    --rojo: #dc2626;
    --naranja: #ea580c;
    --amarillo: #ca8a04;
    --verde: #16a34a;
    --gris: #6b7280;
    --gris-claro: #f3f4f6;
    --blanco: #ffffff;
    --texto: #1f2937;
    --borde: #e5e7eb;
  }
  * { margin:0; padding:0; box-sizing:border-box; }
  body {
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
    color: var(--texto);
    background: var(--gris-claro);
    line-height: 1.5;
  }
  .container { max-width: 1200px; margin: 0 auto; padding: 20px; }
  header {
    background: var(--azul);
    color: white;
    padding: 24px;
    margin-bottom: 24px;
    border-radius: 8px;
  }
  header h1 { font-size: 24px; margin-bottom: 4px; }
  header .fecha { opacity: 0.8; font-size: 14px; }

  .cards { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 16px; margin-bottom: 24px; }
  .card {
    background: var(--blanco);
    padding: 20px;
    border-radius: 8px;
    border: 1px solid var(--borde);
    text-align: center;
  }
  .card .numero { font-size: 36px; font-weight: 700; }
  .card .label { font-size: 13px; color: var(--gris); text-transform: uppercase; letter-spacing: 0.5px; }
  .card.alto .numero { color: var(--rojo); }
  .card.medio .numero { color: var(--naranja); }
  .card.bajo .numero { color: var(--amarillo); }
  .card.total .numero { color: var(--azul); }

  .seccion {
    background: var(--blanco);
    border-radius: 8px;
    border: 1px solid var(--borde);
    margin-bottom: 24px;
    overflow: hidden;
  }
  .seccion h2 {
    padding: 16px 20px;
    font-size: 18px;
    border-bottom: 1px solid var(--borde);
    background: var(--gris-claro);
  }
  .seccion-body { padding: 20px; }

  table { width: 100%; border-collapse: collapse; font-size: 14px; }
  th { text-align: left; padding: 10px 12px; background: var(--gris-claro); font-weight: 600; border-bottom: 2px solid var(--borde); }
  td { padding: 10px 12px; border-bottom: 1px solid var(--borde); vertical-align: top; }
  tr:hover { background: #f9fafb; }

  .badge {
    display: inline-block;
    padding: 2px 10px;
    border-radius: 12px;
    font-size: 12px;
    font-weight: 600;
    text-transform: uppercase;
  }
  .badge-alto { background: #fef2f2; color: var(--rojo); }
  .badge-medio { background: #fff7ed; color: var(--naranja); }
  .badge-bajo { background: #fefce8; color: var(--amarillo); }
  .badge-minimo { background: var(--gris-claro); color: var(--gris); }

  .score-bar {
    width: 100%;
    height: 8px;
    background: var(--gris-claro);
    border-radius: 4px;
    overflow: hidden;
    margin-top: 4px;
  }
  .score-fill {
    height: 100%;
    border-radius: 4px;
    transition: width 0.3s;
  }
  .score-fill.alto { background: var(--rojo); }
  .score-fill.medio { background: var(--naranja); }
  .score-fill.bajo { background: var(--amarillo); }
  .score-fill.minimo { background: var(--gris); }

  .detalle-toggle {
    background: none;
    border: 1px solid var(--borde);
    padding: 4px 12px;
    border-radius: 4px;
    cursor: pointer;
    font-size: 12px;
    color: var(--azul);
  }
  .detalle-toggle:hover { background: var(--azul-claro); }
  .detalle-content {
    display: none;
    margin-top: 12px;
    padding: 12px;
    background: var(--gris-claro);
    border-radius: 6px;
    font-size: 13px;
  }
  .detalle-content.visible { display: block; }

  .factores { margin: 8px 0; }
  .factor-favor { color: var(--rojo); }
  .factor-contra { color: var(--verde); }

  .grupo-header {
    padding: 12px 20px;
    background: var(--azul-claro);
    font-weight: 600;
    cursor: pointer;
    border-bottom: 1px solid var(--borde);
    display: flex;
    justify-content: space-between;
    align-items: center;
  }
  .grupo-header:hover { background: #dce5f5; }
  .grupo-body { display: none; }
  .grupo-body.visible { display: block; }

  .tags { display: flex; gap: 6px; flex-wrap: wrap; margin-top: 4px; }
  .tag {
    font-size: 11px;
    padding: 1px 8px;
    background: var(--azul-claro);
    color: var(--azul);
    border-radius: 10px;
  }

  .disclaimer {
    margin-top: 24px;
    padding: 16px;
    background: #fffbeb;
    border: 1px solid #fde68a;
    border-radius: 8px;
    font-size: 13px;
    color: #92400e;
  }

  footer {
    text-align: center;
    padding: 20px;
    color: var(--gris);
    font-size: 13px;
  }

  @media (max-width: 768px) {
    .cards { grid-template-columns: 1fr 1fr; }
    table { font-size: 12px; }
    th, td { padding: 8px 6px; }
  }
</style>
</head>
<body>
<div class="container">

<header>
  <h1>{{ titulo }}</h1>
  <div class="fecha">Generado: {{ fecha_generacion }} | Boletines procesados: {{ estadisticas.get('boletines_procesados', 0) }}</div>
</header>

<!-- Resumen -->
<div class="cards">
  <div class="card total">
    <div class="numero">{{ resumen.total }}</div>
    <div class="label">Total coincidencias</div>
  </div>
  <div class="card alto">
    <div class="numero">{{ resumen.alto }}</div>
    <div class="label">Riesgo alto</div>
  </div>
  <div class="card medio">
    <div class="numero">{{ resumen.medio }}</div>
    <div class="label">Riesgo medio</div>
  </div>
  <div class="card bajo">
    <div class="numero">{{ resumen.bajo }}</div>
    <div class="label">Riesgo bajo</div>
  </div>
</div>

<!-- Marcas mas afectadas -->
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

<!-- Palabras frecuentes -->
{% if resumen.palabras_frecuentes %}
<div class="seccion">
  <h2>Terminos mas repetidos</h2>
  <div class="seccion-body">
    <div class="tags">
      {% for palabra, cnt in resumen.palabras_frecuentes %}
      <span class="tag">{{ palabra }} ({{ cnt }})</span>
      {% endfor %}
    </div>
  </div>
</div>
{% endif %}

<!-- Coincidencias agrupadas -->
<div class="seccion">
  <h2>Detalle de coincidencias</h2>
  {% for grupo, items in agrupadas.items() %}
  <div class="grupo-header" onclick="toggleGrupo(this)">
    <span>{{ grupo }} ({{ items|length }} coincidencias)</span>
    <span class="detalle-toggle">ver mas</span>
  </div>
  <div class="grupo-body">
    <table>
      <tr>
        <th>Marca detectada</th>
        <th>Score</th>
        <th>Nivel</th>
        <th>Tipo</th>
        <th>PDF / Pagina</th>
        <th>Acciones</th>
      </tr>
      {% for c in items %}
      <tr>
        <td>
          <strong>{{ c.get('marca_detectada', 'N/A') }}</strong>
          <div class="tags">
            {% if c.get('clase_niza') %}<span class="tag">Clase {{ c.get('clase_niza') }}</span>{% endif %}
            {% if c.get('tipo_marca') %}<span class="tag">{{ c.get('tipo_marca') }}</span>{% endif %}
          </div>
        </td>
        <td>
          {{ "%.0f"|format((c.get('score_final', 0)) * 100) }}%
          <div class="score-bar">
            <span class="score-fill {{ c.get('nivel_riesgo', 'minimo') }}" style="width:{{ (c.get('score_final', 0)) * 100 }}%"></span>
          </div>
        </td>
        <td><span class="badge badge-{{ c.get('nivel_riesgo', 'minimo') }}">{{ c.get('nivel_riesgo', 'N/A') }}</span></td>
        <td>{{ c.get('tipo_match_principal', 'N/A') }}</td>
        <td>{{ c.get('archivo_pdf', 'N/A') }}<br><small>Pag. {{ c.get('pagina', '?') }}</small></td>
        <td>
          <button class="detalle-toggle" onclick="toggleDetalle(this)">ver detalle</button>
          <div class="detalle-content">
            <p><strong>Explicacion:</strong> {{ c.get('explicacion', '') }}</p>
            <p><strong>Recomendacion:</strong> {{ c.get('recomendacion', '') }}</p>
            {% if c.get('factores_a_favor') %}
            <div class="factores">
              <strong>A favor del conflicto:</strong>
              <ul>{% for f in c.get('factores_a_favor', []) %}<li class="factor-favor">{{ f }}</li>{% endfor %}</ul>
            </div>
            {% endif %}
            {% if c.get('factores_en_contra') %}
            <div class="factores">
              <strong>En contra:</strong>
              <ul>{% for f in c.get('factores_en_contra', []) %}<li class="factor-contra">{{ f }}</li>{% endfor %}</ul>
            </div>
            {% endif %}
            <p><strong>Scores:</strong>
              Texto: {{ "%.0f"|format((c.get('score_texto', 0)) * 100) }}% |
              Fonetico: {{ "%.0f"|format((c.get('score_fonetico', 0)) * 100) }}% |
              Visual: {{ "%.0f"|format((c.get('score_visual', 0)) * 100) }}% |
              Color: {{ "%.0f"|format((c.get('score_color', 0)) * 100) }}%
            </p>
            {% if c.get('estado_revision') %}
            <p><strong>Estado revision:</strong> {{ c.get('estado_revision') }}
              {% if c.get('comentario_revision') %} - {{ c.get('comentario_revision') }}{% endif %}
            </p>
            {% endif %}
          </div>
        </td>
      </tr>
      {% endfor %}
    </table>
  </div>
  {% endfor %}
</div>

<!-- Boletines procesados -->
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
{% endif %}

<div class="disclaimer">
  <strong>Aviso:</strong> Este reporte es generado automaticamente con fines de vigilancia marcaria.
  No constituye dictamen juridico. Las coincidencias detectadas requieren revision profesional
  para determinar si representan conflictos marcarios reales.
</div>

<footer>
  INPI Monitor v1.0 | Generado automaticamente | {{ fecha_generacion }}
</footer>

</div>

<script>
function toggleDetalle(btn) {
  const content = btn.nextElementSibling;
  content.classList.toggle('visible');
  btn.textContent = content.classList.contains('visible') ? 'ocultar' : 'ver detalle';
}
function toggleGrupo(header) {
  const body = header.nextElementSibling;
  body.classList.toggle('visible');
  const btn = header.querySelector('.detalle-toggle');
  if (btn) btn.textContent = body.classList.contains('visible') ? 'ocultar' : 'ver mas';
}
// Abrir primer grupo por defecto
document.addEventListener('DOMContentLoaded', function() {
  const primer = document.querySelector('.grupo-body');
  if (primer) primer.classList.add('visible');
});
</script>
</body>
</html>""")
