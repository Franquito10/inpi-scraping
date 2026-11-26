# Monitor de Redes

Monitorea lo que publican en **Facebook, X, Instagram y TikTok** las 18 personas de la
planilla `Redes c rech.xlsx` (legisladores, concejales SMT, diputados y militantes LLA, etc.):

1. **Scraping** de las publicaciones de las 58 cuentas → base SQLite.
2. **Análisis**: temas (seguridad, economía, labor legislativa, críticas/oposición…), **qué hacen**
   (recorridas, reuniones, sesiones, entrevistas, actos, reclamos…), lugares de Tucumán mencionados,
   hashtags, horarios, interacciones, y un resumen por persona (con Claude si hay API key).
3. **Dashboard** HTML (un solo archivo, funciona offline, modo claro/oscuro, celular).
4. **Bot de Telegram** que avisa las publicaciones nuevas, manda un resumen diario y responde consultas.

```
planilla.xlsx ─► personas.yaml ─► scraping (Apify) ─► SQLite ─► análisis ─┬─► dashboard.html
                                       ▲ cada 3 h                         └─► bot de Telegram
```

## Por qué Apify

Facebook, Instagram, X y TikTok bloquean el acceso anónimo desde scripts (piden login, cortan por IP
o cambian el HTML seguido). [Apify](https://apify.com) mantiene scrapers para cada red con proxies, y
se paga por resultado. Hay crédito gratuito mensual para probar. Los actores que se usan están en
`config.yaml` y se pueden cambiar por otros equivalentes.

Para gastar poco, cada corrida trae solo los **últimos 2 días** (`dias_atras`). La primera vez se hace
una carga de 30 días. Revisá el consumo en la consola de Apify los primeros días y ajustá
`intervalo_horas` / `max_por_cuenta` si hace falta.

## Instalación

Requiere Python 3.10+.

```bash
pip install -r monitor_redes/requirements.txt
```

Copiá `monitor_redes/.env.ejemplo` a `monitor_redes/.env` y completá:

| Variable | De dónde sale |
|---|---|
| `APIFY_TOKEN` | apify.com → Settings → API & Integrations |
| `TELEGRAM_BOT_TOKEN` | En Telegram hablale a **@BotFather** → `/newbot` |
| `TELEGRAM_CHAT_IDS` | Iniciá el bot y mandale `/start`: te responde tu chat ID. Varios separados por coma (sirve un grupo) |
| `ANTHROPIC_API_KEY` | Opcional. console.anthropic.com. Sin esto los resúmenes se arman por reglas |

## Uso

Todo se corre desde la raíz del repo:

```bash
# 1. Cargar la planilla (ya está hecho: monitor_redes/personas.yaml). Repetir si cambia el Excel
python -m monitor_redes importar "Redes c rech.xlsx"

# 2. Carga inicial: últimos 30 días de todas las cuentas (+ genera el dashboard)
python -m monitor_redes scrapear --dias 30

# 3. Ver el dashboard
python -m monitor_redes dashboard --abrir

# 4. Dejar corriendo el bot: scrapea cada 3 h, avisa lo nuevo y resume a las 21:00
python -m monitor_redes bot
```

Otros comandos:

```bash
python -m monitor_redes scrapear --red instagram --persona "Pepe Seleme"
python -m monitor_redes estado          # cuentas, último scraping, errores por cuenta
python -m monitor_redes reclasificar    # si editás los diccionarios de analisis.py
python -m monitor_redes demo --abrir    # prueba todo con personas y datos FICTICIOS, sin tokens
```

En Windows podés hacer doble clic en `monitor_redes/iniciar_bot.bat`. Para que el bot corra 24/7
tiene que quedar prendido en una PC o en un servidor chico (un VPS de los más baratos alcanza).

## Bot de Telegram

| Comando | Qué hace |
|---|---|
| `/hoy` · `/semana` | Resumen: cuántas publicaciones, temas, qué hicieron, lugares, y un párrafo por persona |
| `/persona seleme 3` | Qué publicó y qué hizo esa persona en los últimos 3 días + sus últimas publicaciones (tolera errores de tipeo; también podés mandar solo el nombre) |
| `/ultimas 10` | Últimas publicaciones de todos |
| `/buscar jaldo` | Busca en los textos |
| `/temas` · `/ranking 30` | De qué se habla / quién publica más y quién tiene más interacción |
| `/alerta inseguridad` | Te avisa cuando alguien publique esa palabra (`/alertas`, `/quitar`) |
| `/silenciar` · `/activar` | Pausa o reanuda los avisos automáticos |
| `/actualizar` · `/estado` | Scrapear ya / ver último scraping y cuentas con error |
| `/dashboard` | Te manda el dashboard como archivo HTML para abrir en el celular |

Avisos automáticos: después de cada scraping llegan las publicaciones nuevas agrupadas por persona.
La primera carga no se envía completa, para no inundar el chat. A la hora de `resumen_diario_hora`
llega el resumen del día. Solo responde a los chats de `TELEGRAM_CHAT_IDS`.

## Dashboard

`datos/redes/dashboard.html` se regenera después de cada scraping. Filtros por período, persona,
cargo, red, tema, actividad y texto. Incluye:

- KPIs: publicaciones, personas activas, publicaciones por día, interacciones y reproducciones.
- Quién publica más, por red.
- Publicaciones por día.
- De qué hablan y qué hacen.
- Mapa de calor de día y hora.
- Lugares y hashtags.
- Resumen por persona, con estado de cada cuenta (⚠ si falló el scraping).
- El feed completo, con link a cada publicación.

## Ajustes

- **Personas/cuentas**: editá `monitor_redes/personas.yaml` o reimportá el Excel.
- **Temas, actividades y lugares**: diccionarios al principio de `monitor_redes/analisis.py`.
  Después de editarlos, corré `reclasificar`.
- **Frecuencia, hora del resumen, modelo de IA y actores de Apify**: `monitor_redes/config.yaml`.

## Tests

```bash
python -m pytest tests/test_monitor_redes.py -q
```

Simulan Apify y Telegram: prueban los normalizadores de cada red, la asignación de publicaciones a
personas, la deduplicación, la clasificación, el dashboard y los comandos y avisos del bot.

## Limitaciones

- Solo se lee contenido **público**. Perfiles privados o cuentas suspendidas aparecen con error
  en `/estado`.
- Las historias de Instagram/Facebook (24 h) no se capturan.
- La clasificación por diccionario es orientativa. El resumen con IA es más fino, pero solo resume
  lo que está escrito en las publicaciones.
- Los formatos de salida de los actores de Apify pueden cambiar. Los normalizadores de
  `scrapers.py` aceptan varios nombres de campo, pero si una red deja de traer datos, mirá
  `/estado` y el log (`-v`).
