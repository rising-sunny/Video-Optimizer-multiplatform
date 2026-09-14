# AI Video Playbook — referencia para IAs agénticas

> **Para la IA que lee esto:** este archivo es tu punto de partida para **generar
> videos desde este repo** sin re-descubrir todo. Es permanente y **actualizable**:
> si aprendés algo nuevo (un entry point cambió, una métrica nueva, una decisión de
> estrategia), **actualizá la sección correspondiente y el Changelog al final**.
> Mantené los hechos verificables; no inventes rutas ni claves.

Última actualización: **2026-08-14**.

---

## 0. TL;DR (lo mínimo para arrancar)

- Este repo genera videos **narrados** (guión IA → TTS → imágenes IA → ensamblaje
  FFmpeg → subtítulos) para el canal **Stunning Revelations** (historia/misterios).
- **Generar un Short:** `\.venv\Scripts\python.exe daily_short_pipeline.py --topic "TEMA" --bgm "ruta.mp3"`
- **Generar un Long-form (documental):** `\.venv\Scripts\python.exe long_form_builder.py "TEMA" --minutes 10`
- **Nunca subas automáticamente.** La subida es un paso aparte y explícito; subí como
  `unlisted` primero para revisar. Ver §5.
- Las mejoras de calidad ya están **bakeadas en el código** (hooks, capítulos,
  metadata long-form correcta). No hay que aplicarlas a mano. Ver §6.
- El **Channel Bible** (`daily_shorts/channel_strategy_profile.json`) controla tono,
  hooks, categorías y la mezcla de temas. Ver §7.

---

## 1. Entorno (cómo correr)

- **Python 3.11 en el venv local** `.venv` (NO el Python global, NO `python_portable`).
  Los lanzadores `RUN.bat` / `INSTALL_DEPS.bat` apuntan a `.venv`.
  - Invocación directa recomendada: `\.venv\Scripts\python.exe <script.py>`
- **FFmpeg/ffprobe** en el PATH (`ffmpeg -version`).
- **Secretos** en `.env` (gitignored). Claves relevantes: `GROQ_API_KEY` (guiones),
  `FAL_KEY` (imágenes flux), `STABILITY_API_KEY`, `GOOGLE_API_KEY` (YouTube Data API,
  lectura de canales), credenciales OAuth en `token.json` (subida/edición YouTube),
  `WHISPER_REMOTE_*` (subtítulos word-level via VPS). Si falta una, el paso degrada
  o falla con log claro. **Nunca** escribas secretos en archivos versionados.
- **Subtítulos word-level (hormozi)** usan Whisper en un VPS via túnel SSH
  (`start_whisper_tunnel.bat`). Si el túnel está caído, cae a timing por segmento
  (menos preciso, NO se rompe).
- Detalle de setup completo: `CONTEXTO_OTRA_PC.md` y `SETUP_OTRA_PC.md`.

---

## 2. Los canales del usuario

El usuario (`estebannavarro.rojo@gmail.com`) tiene **dos canales** bajo el mismo login
(brand accounts; se cambia con el menú de cuenta de YouTube).

### Stunning Revelations — el canal de ESTE pipeline
- ID: `UC66EnGiys6V3gKe-J0XD-_Q` · handle `@stunning-revelations`
- Nicho: historia olvidada, civilizaciones perdidas, misterios oscuros, desastres,
  guerra, conspiraciones suaves. Audiencia angloparlante (US/UK/AU/CA).
- Formato: shorts narrados 45-58s + documentales long-form 8-15 min.
- **Diagnóstico (jul 2026):** muchos suscriptores (~3,470, ya pasó el mínimo de
  monetización) pero **pocas vistas por short** (mediana ~22). Cuello de botella =
  **retención / hook** (swipe rate ~37%). El dinero real viene de **watch hours**
  (long-form), no de shorts. Motor dual: short ganador → documental hermano.

### MathRelaxing — OTRO canal, NO producido por este pipeline
- ID: `UCn8REDiVrUNYYVoPLSkXWqQ` · handle `@mathrelaxing`
- Nicho: visualizaciones matemáticas "oddly satisfying" (atractores, Chladni/cimática,
  fractales, ondas). Contenido = **simulaciones visuales**, no guión narrado — se
  produce con OTRO método, no con `daily_short_pipeline.py`.
- **Diagnóstico (jul 2026):** problema espejo — muchas vistas (mediana ~183/short,
  71% pasan 100) pero **casi sin suscriptores** (~45). Cuello de botella =
  **conversión a suscriptor / construir audiencia**. Familias ganadoras: ondas/cimática,
  atractores (Lorenz/Aizawa/Thomas), fractales. Los videos "1 Hour Deep Focus" están
  muertos (suspender).

> Si te piden generar para MathRelaxing con este repo: aclará que el pipeline actual es
> para contenido **narrado** de Stunning Revelations; el estilo de MathRelaxing es otra
> producción.

---

## 3. Generar un SHORT (narrado)

Entry point: `daily_short_pipeline.py` → función `run_pipeline(...)`.

**CLI:**
```bat
.venv\Scripts\python.exe daily_short_pipeline.py --topic "TEMA" --bgm "C:\ruta\musica.mp3"
```
Flags útiles: `--count N`, `--voice en-US-GuyNeural`, `--image-provider flux_dev`
(calidad, ~$0.025/img) | `flux_schnell` (rápido) | `auto`, `--style Photorealism`,
`--upload` (¡solo si te lo piden!), `--privacy unlisted|public`.

**Programático (agente):**
```python
from daily_short_pipeline import run_pipeline
res = run_pipeline(topic="TEMA", bgm_path=r"C:\ruta.mp3", image_provider="flux_dev")
# res: {video_path, thumbnail_path, metadata, output_dir}. upload=False por defecto.
```
El pipeline: elige/usa tema → guión (Groq, con reglas del Bible) → TTS → imágenes IA →
ensamblaje FFmpeg + subtítulos → metadata (Short) + thumbnail. Deja todo en `output_dir`.
La salida por defecto va a `daily_shorts/<fecha>/` (junction a Drive).

---

## 4. Generar un LONG-FORM (documental)

Entry point reusable: `long_form_builder.py` → función `build_long_form(...)`.
(Generaliza el script one-off `build_derinkuyu_long.py`.)

**CLI:**
```bat
.venv\Scripts\python.exe long_form_builder.py "TEMA" --minutes 10
.venv\Scripts\python.exe long_form_builder.py "TEMA" --minutes 12 --no-assemble   # solo guión+metadata
.venv\Scripts\python.exe long_form_builder.py "TEMA" --source-short "https://youtube.com/shorts/XXXX"
```

**Programático:**
```python
from long_form_builder import build_long_form
r = build_long_form("TEMA", minutes=10)   # nunca sube; deja listo para subir
# r: {output_dir, storyboard_path, video_path, metadata, duration_s, chapters, status}
```
Hace: outline dinámico de capítulos (Groq) → guión por capítulo (tono del Bible + hook
obligatorio con número/fecha en el cap. 1) → prompts visuales → TTS → storyboard
`long_form_16_9` → imágenes + ensamblaje (si `assemble=True`) → **metadata long-form**
(sin `#shorts`, `is_short:False`, **capítulos automáticos** desde `chapter`+`start_time`).

> El camino de **guión+metadata está verificado**. El render completo (imágenes+MP4)
> usa las mismas funciones probadas de Derinkuyu, pero conviene un **render corto de
> prueba** antes de depender de él para publicar.

---

## 5. Subida y seguridad (LEER)

- **Nunca subas automáticamente.** Confirmá con el usuario antes de publicar. La subida
  publica en un canal real y es difícil de revertir.
- **Subí como `unlisted` primero** para revisar, después el usuario pasa a `public`.
- Subida programática:
  ```python
  from daily_short_pipeline import upload_to_youtube
  upload_to_youtube(Path(output_dir), privacy_status="unlisted")
  ```
- `is_short` se detecta **solo** (por metadata o por el video: vertical y ≤180s). Los
  documentales 16:9 ya NO se suben como Shorts. No lo fuerces.
- Editar metadata de un video ya subido = modificar contenido público → **confirmá primero**.

---

## 6. Mejoras ya bakeadas (no re-aplicar a mano)

Cambios en el código (commit del 2026-07-19) — la generación ya sale mejorada:
- **Hook fuerte:** `channel_strategy.validate_hook()` avisa si el hook no abre con
  número/fecha/escala; el prompt (`build_hook_prompt_instructions`) exige un opener con
  número/fecha concretos. (Data: esos hooks retienen mucho más = mejor swipe rate.)
- **Metadata long-form correcta:** `generate_youtube_metadata` detecta long-form y genera
  metadata de documental (título buscable, sin `#shorts`, `is_short:False`) con
  **capítulos automáticos**.
- **Sanitizer:** `_sanitize_description_text` elimina `\n` literales en descripciones (YT/FB/IG).
- **Uploader:** `upload_from_metadata` respeta `is_short` (no lo hardcodea).
- **Mezcla de temas por datos:** `production_weight` en el Bible ahora SÍ pesa la
  selección de temas (`build_category_weight_map`).

---

## 7. El Channel Bible (Stunning Revelations)

Archivo: `daily_shorts/channel_strategy_profile.json` (cargado por `channel_strategy.py`).
Controla: identidad, `shorts_rules` (duración 45-58s), `hook_patterns` (A/B/C/D +
prohibidos), `narrative_structure` (timing 0-58s), `title_formula`, `categories` con
`priority` + `production_weight`, `cover_frame`, `narration_tone`, `long_form_rules`,
`kpis_30d`, `expansion_rule` (short >5× mediana en 48h → documental hermano).

**Mezcla de temas actual (production_weight, basada en datos jul 2026):**
Lost Civilizations 0.30 · Cosmic/Space 0.22 · Historical Mysteries 0.13 ·
War/Military 0.13 · Natural Disasters 0.12 · Soft Conspiracies 0.05 · UFOs 0.05.
(Civ. perdidas y cósmico suben; desastres baja por saturación.)

Para cambiar comportamiento de generación, **editá el Bible**, no el código.

---

## 8. La métrica que decide todo (shorts)

**"Viewed rate" / swipe rate** ("Se quedaron viendo" en YouTube Studio → Contenido →
Shorts → Modo Avanzado, por video). Es el % que NO desliza en los primeros segundos y
decide la distribución. Meta: **≥45%**. No está en la API con el token actual (solo
`youtube.upload` + `youtube.force-ssl`); para leerla por API se necesita el scope
`yt-analytics.readonly` (re-autenticar OAuth). Hoy se mira manual en Studio.

Fórmula ganadora de títulos/hook (validada con datos propios): **gancho numérico + cifra
concreta + sujeto nombrado**, duración corta. Ej: "72 Seconds: The Wow! Signal",
"20,000 Hidden: Derinkuyu's Secret City".

---

## 9. Mapa de archivos clave

| Archivo | Qué hace |
|---|---|
| `daily_short_pipeline.py` | Pipeline de shorts (`run_pipeline`) + metadata + upload helpers |
| `long_form_builder.py` | Entry point reusable de documentales (`build_long_form`) |
| `channel_strategy.py` | Loader/validadores del Bible (hooks, pesos, duración) |
| `daily_shorts/channel_strategy_profile.json` | El Channel Bible (editar para cambiar estrategia) |
| `youtube_uploader.py` | Subida a YouTube (`upload_from_metadata`, `upload_video`) |
| `youtube_channel_analyzer.py` | Métricas + historial de cualquier canal via API |
| `storyboard_generator.py` | Generación de storyboard (guión + escenas) |
| `RUN.bat` | Abre la GUI (`video_optimizer_pyqt6.py`) |
| `build_derinkuyu_long.py` | Ejemplo one-off de documental (referencia; hardcodeado) |

---

## 10. Gotchas

- Usá SIEMPRE `.venv`; el Python global puede estar corrupto en la PC del usuario.
- No importes torch/whisper en local (pesados; Whisper va al VPS).
- Carpetas `projects/`, `daily_shorts/`, `auto_videos/` son **junctions a Google Drive**.
  Para borrar un junction: `[System.IO.Directory]::Delete($path, $false)` (no `rmdir`).
- No commitees secretos (`.env`, `.env.txt` están gitignored; mantenelo así).
- Convención de guardado: cuando el usuario diga "guardá/subí a git" → `git add` de los
  archivos relevantes + `commit` descriptivo + `git push origin main`. No barras
  artefactos de runtime ni los videos pesados de `long_form/*_project/`.

---

## Changelog

- **2026-09-14** — **Limpieza del repo.** 230 → 169 archivos `.py` en la raíz (−11.100 líneas en
  total; 4.640 de ellas quitadas de módulos que siguen vivos). Todo lo borrado está en git
  (commit anterior a este).
  - Fuera: 44 scripts one-off/parches de junio (Tunguska, Dyatlov, Baltic, `patch*.py`,
    `extract_mixins.py`…), 9 "tests" que eran scripts manuales (dos publicaban de verdad en
    Facebook/X), el arranque viejo para Google Drive (`start.py`, `START_VISIBLE.bat`,
    `DEBUG_START.bat`, `make_portable.ps1`), `shorts-saas/`, `vps_x_bot/` + scripts VPS/X
    standalone, `giphy_client.py` (nunca hubo key), `analysis_mixin.py` (se importaba pero
    la GUI no lo heredaba), `ui_workers.py` e `interactive_thumbnail_editor.py` (solo los
    usaba una pestaña de thumbnails que nunca se creaba), dumps y `.ass` de prueba.
  - Dentro de módulos vivos: 131 funciones/métodos/clases con cero referencias (verificado
    contra despacho dinámico `getattr`), 7 bloques inalcanzables tras un `return`, imports
    sin uso. Cascada iterada hasta converger; `pyflakes` no reporta nombres indefinidos
    nuevos; los 125 módulos importan headless; suite de tests igual que antes.
  - **Bug encontrado de paso:** el autoload de proyecto con `project_autoload` (fix del
    2026-09-04) estaba cableado en un método que nadie llamaba; la GUI entraba por
    `_load_last_project_once` (`video_optimizer_pyqt6.py`), que volvía en silencio con un
    puntero roto. Ahora ese método usa `decide_project_to_load` (guarda en
    `test_project_autoload.py`).
  - Estado de runtime (`crash_log.txt`, `gui_config.json`, `last_project_path.txt`) salió
    del índice de git y está en `.gitignore`.
  - Herramientas CLI que se quedan aunque nadie las importe: `check_facebook_access.py`,
    `youtube_analytics_client.py`, `microdoc_analytics.py`, `build_derinkuyu_long.py`.

- **2026-08-27f** — El negative prompt perdía el **60% de sus términos** antes de llegar a
  la API, en silencio. Lo destapó un test que ya estaba en rojo (`len(negative) <= 360`
  contra 895 reales) y que se venía ignorando.
  - **Causa raíz, en un comentario del código:** *"900 chars: ... still under Recraft's
    ~1000-char API ceiling"*. Pero el negative prompt **no tiene 1000 caracteres propios**:
    Recraft no expone parámetro negativo, así que `_compose_prompt_with_negative` lo pega
    al final del prompt (`"Avoid: ..."`) dentro del **mismo** techo. El prompt visual se
    lleva ~700, así que entran ~290. Se presupuestaron 900 contra un espacio ya ocupado.
  - **Medido antes:** de 63 términos llegaban 25, y los 19 primeros eran sinónimos de "sin
    texto" (`subtitles`, `letters`, `timestamp`, `shutterstock`, `getty images`...).
    Se perdían **todos** los anti-anacronismo, **todos** los anti-fantasía y **todos** los
    anti-deformidad. Además cortaba a mitad de término (`"modern"` de `"modern clothing"`).
  - Arreglos: bucket de texto/marca de 25 → 6 términos; anacronismos de 12 → 6 (eran seis
    formas de decir "moderno"); anti-sobrenatural de 20 → 6; tope de 900 → **300** con el
    porqué documentado; y un bucket nuevo de **anatomía esencial** (`extra fingers`,
    `deformed hands`, `bad anatomy`) colocado ARRIBA para que siempre llegue.
  - **Ahora llegan 21-22 de 22 términos**, sin fragmentos.
  - El recorte por término completo hubo que aplicarlo en DOS lados: al construir
    (`image_generation_manager`) y al componer (`recraft_client`). El segundo lo encontró
    un test nuevo que atrapó `'fused'` (de `'fused fingers'`) ya con el primero arreglado.
  - Guardas: `test_recraft_prompt_quality` pasa de 4 a 6 tests. El que fallaba se actualizó
    a la INTENCIÓN (empieza con texto/marca) en vez de a la lista literal vieja.

- **2026-08-27e** — Revisión del estado de la API de Recraft (salieron V4 y V4.1). Probado
  en vivo contra la API, no leído de la doc:
  - **Nada estaba roto:** el payload actual (`style: realistic_image`, `size: 1024x1820`,
    sin `model`) sigue generando imágenes.
  - `recraftv4_1` **rechaza** ese payload: `style` tiene que ser `"any"` y el tamaño en
    notación `"9:16"` (`1024x1820` da `invalid_request_parameter`).
  - **Se queda en V3 por resolución:** en vertical 9:16, V3 entrega **1024x1820** y V4.1
    solo **768x1344**. Contra el render de 1080x1920 eso es reescalar 1.05x contra 1.43x.
    El modelo nuevo es mejor por píxel pero da menos píxeles en el formato que se usa.
  - **`model` ahora va EXPLÍCITO** (`RECRAFT_MODEL = "recraftv3"`). Antes se omitía y
    Recraft elegía su default: funciona hoy, pero cuando muevan ese default a V4.x el
    payload empezaría a fallar con `400 invalid_image_type`. Es exactamente la clase de
    fallo que en este proyecto degrada en silencio.
  - `recraftv4_1_pro` genera a 2K y sí superaría a V3, pero cuesta **6x** ($0.21 vs
    $0.035 por imagen). Sin probar, a la espera de decisión.
  - El selector de estilo de la GUI (`style_combo`, 47 opciones de
    `recraft_style_catalog`) ya llega hasta la llamada; no hacía falta tocarlo.

- **2026-08-27d** — El nombre del canal estaba **cableado en 33 lugares** de 3 archivos
  (`claude_client.py`, `daily_short_pipeline.py`, `auto_video_integration_pyqt6.py`): los
  guiones seguían cerrando con *"subscribe to Stunning Revelations"* aunque el perfil
  apuntara al canal nuevo. Se detectó generando un guion de prueba, no leyendo el código.
  - Nuevo `channel_strategy.get_channel_name()`, leído del Bible. Los tres archivos lo
    usan; `claude_client` y `auto_video_integration` con un shim de import perezoso porque
    se cargan antes que el perfil.
  - El prompt de Shorts ya no tiene la identidad cableada: handle, posicionamiento,
    `out_of_scope` y filtro editorial salen del perfil. Antes decía "@Stunning-Revelations"
    y pedía *"¿Qué sigue sin explicación?"* + *"Termina con sensación de misterio"*, que
    empujaba al guion al misterio aunque el Bible dijera lo contrario.
  - `narrative_structure` reescrita para 80s y carga útil adelante: hook 0-6s, **payload
    6-20s** (donde antes iba "contexto mínimo" y "misterio"), contexto 20-40s,
    consecuencias 40-70s, cierre 70-80s con la consecuencia, no con un misterio abierto.
  - **Cuidado si se repite este tipo de reemplazo masivo:** cambiar `"Stunning Revelations"`
    por `{get_channel_name()}` con búsqueda y reemplazo dejó texto literal en strings que
    no eran f-strings, y **sets de Python** en posiciones de código
    (`or topic or {get_channel_name()}`). Hubo que reparar caso por caso.

- **2026-08-27c** — **Corrección de nicho del canal nuevo.** No es misterios ni cosmos:
  son **hechos históricos impactantes, documentados**. Eso invalida los pesos que se habían
  puesto horas antes (Cosmic Threats 0.32 era la categoría principal y queda fuera).
  - **Recalculado** el rendimiento del canal anterior restringido a las categorías que sí
    aplican (223 videos, percentil dentro del mes):
    Civilizaciones antiguas **0.65** (n=28, mediana 118 views) · Guerra y militar **0.57**
    (n=42, la muestra más grande, mediana 113) · Desastres provocados 0.38 (n=7) ·
    Desastres naturales 0.37 (n=15) · **Ciencia y tecnología histórica 0.34** (n=14).
  - **Dato que contradice lo que veníamos recomendando:** el cluster de programas
    desclasificados (Paperclip, MK Ultra, Stargate, Demon Core) cae en la categoría más
    floja de las aplicables. Se le deja peso 0.08 hasta tener datos propios.
  - Categorías nuevas: Ancient Civilizations & Empires 0.32 · War & Military 0.30 ·
    Turning Points & Political History 0.18 (sin datos propios, peso por criterio
    editorial) · Historical Disasters 0.12 · Science & Technology 0.08.
    **Fuera:** UFOs, paranormal, amenazas cósmicas, misterios sin resolver, conspiraciones.
  - `editorial_principles`: se quitó "¿Qué sigue sin explicación?" — era el principio que
    empujaba al canal hacia el misterio. Series reemplazadas por otras de hecho consumado
    ("Empires That Fell", "The Day Everything Changed", "Cities That Were Abandoned").
  - **Aviso para el futuro:** los percentiles de estas categorías vienen de un canal con
    otra mezcla y otro público. Sirven para arrancar, no como verdad. A los ~15 videos del
    canal nuevo hay que recalcular con sus propios datos.

- **2026-08-27b** — **Canal nuevo: @stunningfactsofhistory** (`UCXQ1_6A-JkBeQsMkiDcunGA`),
  misma cuenta de Google. Borrón y cuenta nueva; el anterior queda vivo pero ya no es
  destino de publicación.
  - **Token:** `token.json` ahora autoriza el canal nuevo. El del anterior quedó en
    `token_stunning-revelations.json` (y `token_*.json` se agregó a `.gitignore`). Un
    `token.json` sirve para UN canal: para volver al viejo, copiar el respaldo encima.
  - `daily_shorts/channel_strategy_profile.json` y `.env` apuntan al canal nuevo.
  - **Pesos por categoría, según lo medido en el canal anterior** (percentil dentro del
    mes de publicación, 223 videos): Cosmic 0.22 → **0.32** (percentil 0.76, la mejor);
    Lost Civilizations 0.30 (0.70); Historical Mysteries 0.13 → 0.18; War 0.13;
    Natural Disasters 0.12 → **0.07** (los listicles con cifras de muertos rindieron 0.37;
    los eventos únicos sí funcionan); **UFOs & Paranormal 0.05 → 0** (percentil 0.28, la
    peor) y **Soft Conspiracies → 0**.
  - **Duración:** objetivo 50s → **80s**, rango 60-95s, `hard_limit` 60 → **180**. El
    límite de 60 estaba desactualizado (Shorts admite 3 min) y el pipeline avisaba en cada
    render. Medido: entre 45 y 90s el percentil es plano, y los de 91-180s rinden igual con
    13x más watch time. `weekly_cap` 5 → 4 (calidad sobre volumen).
  - **Sin migrar:** los 223 videos del canal viejo. El análisis histórico
    (`uploads.json`, percentiles por categoría) sigue siendo válido como aprendizaje, pero
    `youtube_analytics_client.py` ahora reporta el canal nuevo, que arranca en cero.

- **2026-08-27** — La música quedaba inaudible **y el QA decía que estaba bien**. Mi
  estimación erraba por 10 dB y nunca la había contrastado contra el audio renderizado.
  - **Medido sobre narración+música reales:** la música quedaba **25.8 dB** bajo la voz
    durante la narración. El log informaba **15.6 dB** ("banda sana: 10-20").
  - **Las dos mitades de la fórmula estaban mal**, por causas distintas:
    1. *Niveles.* `compute_mix_gains` usaba `AudioSegment.dBFS` (RMS del archivo) para voz
       y música. Pero lo que se percibe es la voz **en sus tramos hablados** contra la
       música **en su nivel típico**: la voz medida así está ~2 dB por encima de su RMS y
       la música ~3.5 dB por debajo del suyo. 5.6 dB de error que dejaban la cama a 11.6 dB
       en vez de los 6 pedidos. Nuevas `speech_level_dbfs()` y `music_level_dbfs()`.
       (Probé LUFS: para este material da lo mismo que dBFS, el sesgo no venía de ahí.)
    2. *Ducking.* La reducción real era **14.2 dB**, no los 9.6 de `(L-T)(1-1/ratio)`.
       Barrido sobre material real para calibrar: thr 0.03/ratio 3 → 14.1 dB;
       0.05/3 → 11.2; **0.08/2.5 → 7.6** (elegido); 0.10/2 → 5.5; 0.15/2 → 3.8.
  - `estimate_ducked_music_under_voice_db()` ya no calcula la compresión: usa
    `MEASURED_DUCK_DEPTH_DB`, una constante medida. Si se tocan los parámetros del
    sidechain hay que **volver a medir**, no recalcular.
  - **Resultado medido: 13.6 dB** bajo la voz (antes 25.8). La música sube ~12 dB.
  - **Por qué los tests no lo detectaron:** `TestMusicAudibilityBudget` comprobaba la
    *estimación*, y la estimación era justo lo que estaba mal. Nuevo
    `TestMixSeparationIsMeasured`: renderiza con FFmpeg y **mide** que la separación caiga
    entre 8 y 22 dB, y que la estimación del QA no se aleje más de 7 dB de lo renderizado.
    Lección: un test sobre un modelo no valida nada si el modelo es el bug.

- **2026-08-26d** — Tres arreglos tras el render de "Supernova de 1054":
  - **El swoosh dejó de sonar — regresión introducida el 26-08.** La inyección del SFX
    buscaba clips llamados `overlay_transition`, que existían cuando el Film Burn se
    *insertaba* como clip aparte. Al pasar a mezclarlo sobre el clip entrante esos clips
    dejaron de existir, el bucle no encontró ninguno e inyectó **cero** — y el mensaje de
    éxito estaba FUERA del bucle, así que el log decía "mezclados exitosamente". Ahora se
    usan los índices de cambio de escena (`escenas_nuevas`), se cuenta lo inyectado y el
    log dice el número. Verificado difiriendo la pista antes/después: energía agregada de
    0.40–0.44 en los 9 cortes contra 0.017 de fondo.
  - **El QA también mentía:** decía `[OK] SFX: lo inyecta la ruta FFmpeg directa` sin
    comprobar que hubiera inyectado algo. Esa rama se eliminó; ahora reporta la cuenta real
    o `[FAIL]`.
  - **El cover frame se movía.** Al pasar los efectos a FFmpeg, el `zoompan` empezó a
    aplicarse también a la placa de texto de 0,7s: el texto se desplazaba y escalaba en
    menos de un segundo. Medido en el MP4: deriva de **14.75** antes, **0.03** ahora.
    `_build_motion_filter` devuelve un filtro estático cuando el clip es el cover.
  - **El cover caía a gradiente oscuro.** Las rutas del storyboard son relativas al
    proyecto (`project_media/segment_001.png`) y `os.path.exists` fallaba desde el cwd, así
    que solo veía los videos arrastrados (ruta absoluta) y se rendía. `generate_cover_frame`
    acepta `media_base_dir` y el ensamblador le pasa `project_base_dir`.
  - Guardas: `TestCoverFrameStaysStill` + `TestCoverFrameResolvesRelativePaths`
    (40 tests en el archivo).

- **2026-08-26c** — Tema en español → guion en inglés, y validación de que el guion hable
  del tema (pedido por el usuario tras el caso "El Núcleo del Demonio").
  - `_localize_topic_for_research()` lleva el tema al idioma del guion **antes** de
    investigar. No es traducción literal: se pide el nombre de uso corriente, el que
    titularía el artículo de enciclopedia. `"El Núcleo del Demonio"` → `Demon Core`;
    `"¿Quiénes fueron los Pueblos del Mar?"` → `Sea Peoples`; `"Incidente del cohete
    noruego de 1995"` → `1995 Norwegian rocket incident`. Con caché, y si falla se usa el
    original (el filtro de relevancia sigue cubriendo). El nombre del proyecto y la GUI
    conservan el tema original.
  - `topic_needs_localization()` evita gastar la llamada al LLM cuando el tema ya está en
    el idioma del guion (detecta acentos, signos invertidos y artículos del español).
  - `script_matches_topic()` valida el guion generado contra el tema, justo al parsear el
    JSON, **antes** de gastar TTS e imágenes.
  - **Calibración (importante si se toca):** la regla es que aparezca al menos un término
    **distintivo** (≥5 letras) del tema, NO un porcentaje de cobertura. Medido sobre 139
    guiones reales del disco: exigir cobertura ≥50% marcaba 13 como deriva y **12 eran
    falsos positivos** (los temas de este canal son titulares largos tipo "The Carrington
    Event: The Day the Sun Almost Ended Civilization"). Con la regla actual: 138 OK, 1
    deriva — y esa es real (un guion de Chicxulub que nunca dice "Chicxulub" ni
    "asteroid"). Que sea distintivo importa: el guion de música latina compartía "core"
    con "Demon core" por casualidad; lo que nunca aparecía era "demon".
  - Si el tema necesitaba traducción y no se logró, la validación **se omite**: comparar
    un tema en español contra un guion en inglés marcaría deriva siempre, y una alerta que
    salta siempre no la mira nadie.
  - Guardas: `TopicLocalizationTests` + `ScriptTopicDriftTests` (27 tests en el archivo).
  - **Limitación conocida:** "Nazi expedition to the Himalayas" resuelve a `Willy Merkl`
    en vez del artículo de la expedición de Schäfer. Pasa el filtro porque el resumen sí
    menciona los términos. La validación de guion lo cubre aguas abajo.

- **2026-08-26b** — El guion salía sobre un tema equivocado. Pedido "El Núcleo del Demonio",
  salió *"The Devil's Core: Latin Music's 2021 Global Surge"*.
  - **Causa:** `_search_wikipedia_title` tomaba el **primer** resultado de búsqueda sin
    verificar nada. Buscar "El Núcleo del Demonio" en la Wikipedia **inglesa** devuelve
    `2021 in Latin music`. Como el guion es EN, se prueba `en` primero y ese resultado
    "funciona", así que nunca se llega a la Wikipedia española — que **sí tiene el artículo
    correcto** (`Núcleo del demonio`). Con DuckDuckGo rate-limited, esos 5 fragmentos
    equivocados fueron toda la investigación y el LLM escribió sobre eso.
  - `_match_is_relevant()` valida que el artículo hable del tema: coincidencia de términos
    en el título, o —para siglas tipo `MH370` vs `Malaysia Airlines Flight 370`— que el
    resumen los mencione. Si no pasa, se descarta y sigue buscando en otros idiomas.
    Verificado: también descarta `Battle of Madagascar` para "Operación Paperclip".
  - **Sin investigación es MEJOR que con investigación equivocada:** el LLM escribe desde
    su propio conocimiento y el tema sale bien igual.
  - Un límite de tasa de Wikipedia devolvía `Expecting value: line 1 column 1`, que no dice
    nada. Ahora se identifica como límite temporal.
  - **Evaluado y descartado:** un chequeo léxico de "el guion habla del tema" da falsos
    positivos, porque el tema se escribe en español y el guion sale en inglés
    ("El Núcleo del Demonio" vs "The Demon Core" no comparten palabras).
  - Guardas: `test_script_quality_guards.WikipediaRelevanceGuardTests` (7 tests).

- **2026-08-26** — Efectos de cámara movidos a un filtergraph de FFmpeg: **~21 min → ~27s**
  de ensamblaje (medido sobre el proyecto Muriq-Tidnim, 9 clips, 1989 cuadros).
  - **Por qué era lento:** `apply_cinematic=True` forzaba la ruta MoviePy, que genera cada
    cuadro en un hilo de Python. Medido durante un render real: `python` 0,60 núcleos y
    `ffmpeg` 0,14 de **20 hilos** — 3,7% de la máquina, con el encoder hambreado esperando
    cuadros. Por eso NVENC/QSV no servía de nada: el encoder nunca fue el cuello.
  - `CameraMovement.build_ffmpeg_motion_filter()` traduce los mismos presets de
    `calculate_positions` a `zoompan`. Ambas rutas usan la misma matemática, así que se ven
    igual. Verificado: paneo medido de **161 px** contra 162 teóricos.
  - **Semántica de `zoompan`** (verificada empíricamente, es fácil de confundir): `zoom`
    multiplica el input igual que nuestra `scale`, y `x`/`y` son la esquina de la ventana
    visible **en coordenadas del input original**, no del input ya zoomeado.
  - **La ruta rápida también tenía el Ken Burns muerto:** su `zoompan` escribía la
    progresión en función de `in`, que con una imagen fija nunca avanza. Medido: dif
    primer-vs-último cuadro de `0.05` (estático) con `in` contra `2.63` con `on`.
  - **Film Burn:** la ruta FFmpeg lo *insertaba* como clips extra, sumando 8 × 0,70s = 5,6s
    y corriendo todo el visual respecto del audio (el QA lo cazó). Ahora se mezcla dentro
    del clip entrante con `blend=all_mode=screen:repeatlast=0`, que corta el blend al
    terminar el overlay y deja pasar el clip intacto. Duración final: 66,33s vs 66,34s.
  - **Fade-out del cierre:** iba antes del `zoompan`; en una imagen fija el input tiene un
    solo cuadro en t=0, así que un fade con `st` de varios segundos nunca disparaba. Movido
    después del zoompan.
  - `apply_cinematic` ya no fuerza MoviePy. Esa ruta queda como respaldo para medios con
    extensiones no soportadas, con sus arreglos del 19-08 intactos.
  - Guardas: `test_audio_mix_sync_guards.py` (36 tests, ~7s) suma que FFmpeg acepte el
    filtergraph de cada movimiento, que todos muevan de verdad, que no dejen bordes negros,
    que la progresión use `on` y no `in`, y que el desplazamiento del paneo coincida con la
    geometría del recorrido.
  - **Decidido dejarlo como está (2026-08-26):** el quemado de subtítulos sigue siendo una
    segunda pasada completa (`-vf subtitles` re-encodea todo, con segunda compresión
    encima). Se evaluó fusionarlo en el filtergraph del export y el usuario prefirió no
    tocarlo. **No proponerlo de nuevo salvo que lo pida.**

- **2026-08-20** — Subida a Facebook (error 190). **Corrige el diagnóstico del 19b:**
  no era "la página cuelga del Business Manager y por eso no se puede derivar el token".
  - **Causa real: `granular_scopes`.** Meta congela en el token a qué páginas alcanza cada
    permiso `pages_*`, según lo que se tildó en el diálogo de autorización de la app. En el
    token actual (app *MathRelaxing*), `pages_manage_posts` / `pages_show_list` /
    `pages_read_engagement` / `pages_manage_ads` apuntan **solo** a The Books Wanderer
    (`1200587819810293`), no a Stunning Revelations (`533073909895353`). Por eso
    `/me/accounts` no la lista y `GET /<page_id>?fields=access_token` devuelve 200 sin token.
  - **Tener rol de administrador en el Business NO alcanza:** el usuario ya tenía Full
    access sobre la página (verificado en la UI) y el token seguía sin cubrirla. Un token
    ya emitido tampoco se actualiza al cambiar roles — hay que reautorizar la app
    incluyendo esa página y emitir un token **nuevo**.
  - Diagnóstico correcto ante un 190: `GET /debug_token` → `granular_scopes` → comparar
    `target_ids` contra `FACEBOOK_PAGE_ID`. El texto del 190 miente: enumera permisos
    faltantes que el token sí tiene.
  - `facebook_uploader._resolve_page_access_token` valida el page token guardado con un
    `GET /me` y, si Facebook lo rechaza, intenta derivar uno del user token (un error de
    red NO invalida el token). Si no hay forma, `_page_token_help` lista las páginas que
    el user token sí administra **y los `granular_scopes`**, y apunta a la reautorización.
  - **Resuelto:** se reautorizó la app incluyendo Stunning Revelations y se emitió un
    token nuevo. Verificado: los `granular_scopes` ahora apuntan a `533073909895353`,
    y los tres tokens (page, user, IG) son válidos y no vencen.
  - **`check_facebook_access.py`** — correr ANTES de publicar. Chequea que el page
    token funcione y sea de la página correcta, los vencimientos, y el alcance de los
    `pages_*`. Sale con código 1 y dice qué arreglar.
  - Guardas: `test_facebook_uploader.py` (12 tests).

- **2026-08-19** — Efectos visuales y nivel de música:
  - **Los efectos cinematográficos / Ken Burns nunca se aplicaban.** El bloque que los
    aplica estaba indentado DENTRO del `except MemoryError` del bucle de clips de
    `video_assembler.assemble_video_from_prompts`: solo corría si cargar la imagen
    fallaba por memoria. El log igual anunciaba "Efectos cinematográficos activados".
    Medido en el MP4: diferencia entre frames de `0.000` (stills congelados).
  - **Y aunque corriera, estaba roto:** moviepy 1.0.3 + Pillow 10 sin cv2 → el resizer es
    el de PIL → `Image.ANTIALIAS` (eliminado en Pillow 10) reventaba cada `clip.resize()`,
    y el `except Exception` del bucle se comía la excepción **descartando el clip entero**.
    Shim en `moviepy_pillow_compat.py`, importado por `video_assembler` y
    `cinematic_effects`. La llamada a efectos ahora tiene su propio try: si falla, se
    pierde el movimiento, no la escena.
  - **Y los movimientos estaban mal implementados:** `generate_moviepy_resize_lambda`
    devolvía solo la escala y descartaba x/y → los `PAN_*` (scale 1.0→1.0) eran no-ops, y
    los zooms devolvían un clip más grande que el lienzo, recortado desde la esquina.
    Nuevo `CameraMovement.apply_movement()`: zoom + paneo reposicionando cuadro a cuadro
    sobre un lienzo fijo, con `PAN_HEADROOM_SCALE` y clamp anti-borde-negro.
  - **Música inaudible:** se atenuaba dos veces (cama de 10 dB + sidechain ratio 8 sobre
    threshold -34 dB ≈ 16 dB más) → ~26 dB bajo la voz. Ahora cama de **6 dB** y ducking
    más suave (threshold 0.03, ratio 3) → ~**15.6 dB** bajo la voz con narración, 6 dB
    entre frases. Para subirla o bajarla: `audio_mix_utils.MUSIC_UNDER_VOICE_DB`.
  - **Guardas:** `test_audio_mix_sync_guards.py` (31 tests, ~3s) cubre filtergraph válido,
    banda de audibilidad de la música, el shim de Pillow, que cada movimiento mueva de
    verdad sin cambiar el lienzo ni dejar bordes negros, y un check AST de que los efectos
    no vuelvan a quedar dentro de un `except`. El log de ensamblaje reporta
    `[OK]/[FAIL]` de efectos aplicados y de la atenuación total de la música.

- **2026-08-18** — Audio y sincronía del short (los tres síntomas salían del mismo tramo
  de `assemble_video_from_storyboard`):
  - **Voz tapada por la música:** el filtro de auto-ducking era inválido (reusaba la
    etiqueta `[v]` en dos entradas → ffmpeg salía con `-22` en *cada* render) y siempre
    caía al fallback `música - 3 dB`. Ahora: `asplit` para la llave del sidechain,
    `amix ... normalize=0`, `alimiter`, voz nivelada a **-16 dBFS** y música **10 dB por
    debajo** antes del ducking. El stderr de ffmpeg ahora se loguea si vuelve a fallar.
  - **Swoosh inaudible:** `_assemble_direct_ffmpeg` es quien lo inyecta, pero con efectos
    cinematográficos el ensamblaje va por MoviePy y esa función no corre; el pre-mezclado
    se salteaba por ser transición overlay (Film Burn) → no sonaba en ningún lado. Ahora
    se mezcla en la ruta MoviePy, nivelado **por pico** (el wav tiene media -27 dBFS) y
    alineado al pico del SFX, no a su inicio (el archivo dura 4.1s y arranca con build-up).
  - **Cover frame:** desplazaba +0.7s los timestamps de todos los segmentos sin desplazar
    la narración → todo el video quedaba corrido. Se agrega ese padding a la pista de voz.
  - **Subtítulos:** Whisper transcribe ahora la voz sola (`subtitle_audio_path`, mismo
    timeline) en vez de la mezcla con música.
  - La inyección de SFX ya no pisa el mp3 de narración del proyecto (antes los swooshes se
    acumulaban en cada re-ensamblaje).
  - **Guardas para que no vuelva a pasar:** las decisiones de la cadena de audio salieron a
    `audio_mix_utils.py` (filtergraph, ganancias, gating del SFX, offset del cover) y tienen
    tests en `test_audio_mix_sync_guards.py` — uno por bug, incluido uno que corre FFmpeg de
    verdad contra el filtergraph. Ademas cada render imprime al final un bloque
    **QA DE AUDIO / SINCRONIA** con `[OK]/[FAIL]` por ducking, SFX, cover frame, duración
    video-vs-audio y % de palabras ancladas a Whisper (también en `result['audio_qa_problems']`).
    Correr las guardas: `.\.venv\Scripts\python.exe test_audio_mix_sync_guards.py`
  - **Limitación conocida:** `_estimate_scene_durations_with_selected_tts` devuelve `None`
    ("bypass to prevent async hang in Windows") desde el commit inicial, así que los tiempos
    por escena salen de un reparto por cantidad de palabras, no de medir el TTS real. Es la
    causa de que los cortes de imagen no caigan exactamente donde cae la voz. El código de
    medición (inalcanzable) y su test se retiraron en la limpieza del 2026-09-14; están en git
    si se retoma.
- **2026-08-14** — Proyectos nuevos quedan aislados: “Nuevo proyecto” borra
  `last_project_path.txt`; un tema distinto o un storyboard de rechazo no se
  guardan encima del JSON anterior (se crea carpeta nueva); un rechazo no se
  persiste ni se restaura al cargar.
- **2026-08-14** — Al abrir el Timeline ya no se pisa un storyboard nuevo en memoria
  con el `project.json` anterior (el caso Muriq: 521 escenas reales reemplazadas por
  las 3 de rechazo). El Paso 1 guarda el JSON siempre. Videos largos usan ~24
  palabras/escena para no truncar el JSON ni crear 500 segmentos.
- **2026-08-14** — Storyboard GUI: un rechazo del LLM (`I'm sorry, but I can't fulfill
  that request`) ya no se convierte en escenas ni recibe el CTA de suscripción pegado.
  Si el guion queda muy por debajo del presupuesto de palabras (p. ej. 19 palabras para
  1800s), el Paso 1 aborta con error visible en vez de abrir el timeline. Wikipedia
  prueba alias del título (`Muriq-Tidnim (Muro amorrita)` → Shu-Sin / Amorite Wall).
- **2026-07-19** — Creado. Documenta: entry points de shorts (`run_pipeline`) y long-form
  (`build_long_form`), mejoras bakeadas (hooks, capítulos, metadata long-form, sanitizer,
  is_short, production_weight), los dos canales y sus diagnósticos, la métrica de swipe
  rate, y reglas de subida. Mantener actualizado al cambiar entry points o estrategia.
