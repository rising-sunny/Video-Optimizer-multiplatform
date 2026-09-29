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
- **Dónde está el video (desde 2026-09-15):** cada render existe UNA sola vez, en
  `auto_videos/output/<plataforma>_<fecha>_<tema>.mp4` (Drive). La carpeta del proyecto/draft
  NO tiene copia: guarda la ruta en `pipeline_state.json` / `project.json` / `manifest.json`, y
  los cuatro uploaders la resuelven con `output_video_locator.find_output_video(output_dir)`
  (cae al mp4 más reciente de la carpeta solo para drafts viejos). No vuelvas a copiar el
  render dentro del proyecto ni a buscar `videos[0]`.

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

### 6b. El bucle de datos (2026-09-22) — de la métrica al guion, al cover y al thumbnail

Cinco capas, todas alimentadas por lo medido y no por intuición. Cómo se usan:

1. **Botón "Rendimiento"** (fila del canal en el Studio) o `performance_feedback.py`: mide
   YouTube Analytics (vistas, engaged %, retención, subs por video) + Facebook (plays, tiempo
   medio, retención 25/50/75, seguidores por reel), lo cruza con cada `project.json` y escribe
   `daily_shorts/performance_snapshot.json`. Correrlo **una vez por semana**: el prompt del
   guion lee el snapshot (bloque `WHAT IS WORKING NOW`, con fecha) y los pesos de categoría
   se recalculan. Regla empírica que usa: un short despega (≥300 vistas en 24 h) o muere (<50).
2. **Ángulo** (`format_archetype`, combo en el Studio, o `auto`): *cómo lo hicieron* /
   *hallazgo* / *historia humana* / *evento con cifra*. Vive en el Bible (`format_archetypes`,
   cada uno con su evidencia), se guarda en el proyecto y viaja: prompt del guion →
   packaging del microdoc → título → palabras del cover frame → composición del super prompt
   del thumbnail. `auto` = palabras del tema, si no el ángulo con mejor peso medido, si no
   `scale_event`.
3. **Primeros segundos** (`first_seconds` en el Bible; `hook_report`): cifra o pregunta en la
   primera frase, **la fecha en la segunda**, ≤14 palabras, sin carraspeo. Medido en Facebook:
   abrir con fecha retiene ~30 % al primer cuarto, la mejor curva (sin fecha) 50 %. Cada render
   imprime `QA DEL GANCHO` junto al QA de audio.
4. **Botón "Tendencias"** o `trend_report.py`: shorts de historia más vistos del mes (Data API,
   filtrado), Wikipedia histórica, efemérides de `anniversaries.json` (con ángulo y gancho) y
   propuestas de Groq ancladas en hechos documentados. Doble clic en una fila carga tema +
   categoría + ángulo.
5. **Short vertical autónomo**: de cada 16:9 (microdocumental) sale un Short 9:16 de 60–90 s
   que cuenta la historia completa, con imágenes nuevas en vertical y las reglas del canal —
   NO un tráiler con "mirá el video completo" (el teaser legado sigue vía `mode="teaser"`).
   Razón: Thera hizo 52 K plays en Facebook y 49 vistas en YouTube, que no distribuye 16:9 en
   Shorts.

Al publicar desde el Studio, los ids por red quedan en `project.json → publish_results`
(`publish_record.py`), que es lo que permite cruzar métricas con proyectos.

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
| `check_instagram_ingest.py` | Prueba en seco si Instagram procesa videos (no publica); correr cuando IG falle |
| `performance_feedback.py` | Snapshot YT+FB → `daily_shorts/performance_snapshot.json` (lo lee el prompt) |
| `trend_report.py` + `anniversaries.json` | Tendencias del nicho + efemérides → temas con ángulo y fecha |
| `publish_record.py` | Ids por red en `project.json` al publicar (cruce métricas ↔ proyectos) |
| `youtube_tags.py` | Tags investigados (autocompletado + competencia) y puerta final de 500 caracteres |
| `youtube_titles.py` | Títulos investigados con puntaje explicado (optimize/suggest) |
| `thumbnail_publish.py` | Miniatura al subir: formato, reintentos, aviso y verificación de lo que YouTube muestra |
| `thumbnail_research.py` | Miniaturas de la competencia → acento, brillo y texto del super prompt |
| `video_opening.py` | Arranque del video: sin placa, voz en 0 s, acercamiento, primer plano ≥1.8 s y texto de gancho (ASS) |
| `thumbnail_typography.py` + `gemini_vision.py` | Plan tipográfico medido (tamaño, peso, color, contorno, zona) y revisión con visión de la miniatura elegida |
| `facebook_metadata.py` | Título, arranque de la descripción y hashtags de Facebook e Instagram con la investigación de YouTube |
| `build_derinkuyu_long.py` | Ejemplo one-off de documental (referencia; hardcodeado) |
| `catharsis_editor.py` + `catharsis_tab.py` | Formato Catarsis: Short vertical sin voz, tarjetas + imágenes/videos + música con cortes al ritmo, efectos y diseño sonoro; pestaña "Catarsis" de la app |

---

## 10. Gotchas

- Usá SIEMPRE `.venv`; el Python global puede estar corrupto en la PC del usuario.
- No importes torch/whisper en local (pesados; Whisper va al VPS).
- Carpetas `projects/`, `daily_shorts/`, `auto_videos/` y `long_form/` son **junctions a Google
  Drive** (`G:\Mi unidad\Scripts Python\Video-Optimizer-multiplatform\...`). Ningún video
  generado vive en C:.
  Para borrar un junction: `[System.IO.Directory]::Delete($path, $false)` (no `rmdir`).
- No commitees secretos (`.env`, `.env.txt` están gitignored; mantenelo así).
- Convención de guardado: cuando el usuario diga "guardá/subí a git" → `git add` de los
  archivos relevantes + `commit` descriptivo + `git push origin main`. No barras
  artefactos de runtime ni los videos pesados de `long_form/*_project/`.

---

## Changelog

- **2026-09-29** — **Catarsis acepta material de archivo `.mpg`, `.mpeg`, `.ogv` y `.wmv`** (Internet Archive y Wikimedia
  lo entregan así; antes se tomaban como imágenes y fallaban, y el diálogo de la pestaña no dejaba elegirlos).
  Probado con un Short del Hindenburg (noticiero de Universal de 1937, dominio público).
- **2026-09-28e** — **Catarsis con pistas largas** (Biblioteca de Audio: temas de 2 a 5 min con introducción casi muda).
  En la pestaña, Música → "Desde el segundo" + "Auto: su caída en el quiebre" (por defecto): `find_music_start()`
  busca la caída más fuerte de la pista y la toma desde donde esa caída queda al 80 % del video, sin arrancar en
  silencio; `music_analysis(..., start)` y `render(..., music_start=)` la usan (CLI: `--music-start auto`).
  Sin frases, la subida es solo de imágenes (antes el clímax se la comía). Guardas: 22.
- **2026-09-28d** — **Catarsis con video de archivo** (probado con la película de Trinity, 1945: tramos en `in`/`out`,
  sin su audio). El texto sobre imagen ahora es blanco con halo oscuro (el invertido se perdía en los grises) y
  el video sigue corriendo debajo; el autocontraste tiene tope de ganancia (en un destello o un cielo parejo
  estiraba los bloques de la compresión); los impact frames salen de fotos; una tarjeta roja cuenta como
  destello rojo para el limitador. Guardas: `test_catharsis_editor.py` (20).
- **2026-09-28c** — **Catarsis: efectos pro** (motor `catharsis_editor.py` + casillas "Imagen" y "Ritmo y sonido"
  en la pestaña; todos prendidos por defecto y se apagan por proyecto).
  - **Imagen:** texto cinético (entra agrandado y desenfocado, con eco) y 1 de cada 3 frases encima de la
    imagen; impact frames de anime (dos tonos + líneas de velocidad, 3 cuadros)
    antes de las palabras del clímax, con desenfoque de zoom en los golpes; color por acto (frío en la
    subida, rojo en el clímax, cálido al cierre) + resplandor; una doble exposición y una pantalla dividida
    (2-3 franjas) en la subida. Tipos nuevos en la tabla: texto sobre imagen, doble exposición, pantalla
    dividida, impact frame; movimiento nuevo: rampa.
  - **Ritmo y sonido:** el quiebre termina en la caída de la música (mayor salto de energía entre el 55 % y
    el 92 %; el clímax conserva su largo y la subida se estira o se acorta); rampas de velocidad en los
    videos sin audio (0.4x y de golpe 2.5x, cada video la primera vez, al menos 0.9 s); diseño sonoro
    sintetizado sin derechos (whoosh, golpe grave, subida antes del quiebre, pitido en el silencio, boom en
    la caída); loop perfecto (arranca y termina con la pregunta, sin fundido a negro). Texto siempre dentro
    de la zona segura de Shorts; casilla "Guías de zona segura" las marca en la vista previa.
  - **Bug corregido:** con un video con audio, la música se cortaba al terminar el último clip
    (`sidechaincompress` termina con su entrada de control); ahora el control se rellena hasta el final.
  - Subida: piso de 0.45 s de imagen por frase. Guardas: `test_catharsis_editor.py` (18).
- **2026-09-28b** — **Pestaña Catarsis en la app** (`catharsis_tab.py`, entre Auto Video Studio y Metadata).
  - **Qué se elige:** tema y tarjetas (voz del personaje o del narrador; botón "Escribir con IA", que pasa
    las tarjetas por `script_fact_check`), imágenes y videos (encuadre, zoom, tramo y casilla "Usar su
    audio"), música (archivo o buscador de Jamendo) y estilo (duración, velocidad de cortes, destellos,
    variantes, transiciones glitch / film burn / zoom, grano, viñeta, temblor).
  - **Armar automático + retoque:** `auto_sequence()` arma el arco como una lista de planos editable (contenido,
    variante, segundos, transición, movimiento; subir, bajar, duplicar, eliminar). Vista previa rápida
    (540x960, 15 fps) y render final a `auto_videos/output/catarsis_<fecha>_<tema>.mp4`. Proyecto en JSON
    (`projects/catarsis/`).
  - **Motor:** acepta videos (cuadros por tubería de FFmpeg); su audio se mezcla y la música baja
    (sidechain). En la subida, un video con audio dura al menos 1.2 s, porque si no, no se oye.
  - Guardas: `test_catharsis_editor.py` (11).
- **2026-09-28** — **Formato Catarsis, piloto** (`catharsis_editor.py`). Short vertical sin voz y de impacto,
  con el lenguaje de los monólogos finales de Evangelion pero con material propio (nada de clips, música
  ni tipografía de la serie).
  - **Entrada:** guion de tarjetas en JSON (apertura, frases, palabras del clímax, frase final, firma),
    carpeta de imágenes y música apta. Ejemplos: `examples/catharsis_oppenheimer.json` (voz del personaje)
    y `..._narrator.json` (narrador), con citas reales de Oppenheimer (1965).
  - **Arco:** apertura; subida con cortes que se aceleran y se ajustan a los golpes de la música
    (librosa); clímax de palabras sueltas y destellos; quiebre en blanco con la música muda; cierre con
    un boceto y la frase final. Cada imagen da cinco variantes: B/N, negativo, rojo, dos tonos y boceto.
  - **Seguridad:** tope de 3 destellos por segundo (WCAG 2.3.1). Un plano largo atrasa su corte en vez de
    desaparecer: en el primer piloto el limitador se había llevado el quiebre.
  - **Pendiente:** guion con LLM + verificación de hechos, alinear el quiebre con la caída de la música,
    integrarlo al Studio. Guardas: `test_catharsis_editor.py` (6).
- **2026-09-25e** — **`GENERATE_SHORT.bat` usa el `.venv`, y `SETUP_OTRA_PC.md` al día.**
  - **`.bat`:** buscaba Python en `%LOCALAPPDATA%\venvs\video_optimizer_*`, de antes del `.venv`;
    en una PC nueva no arrancaba (el "sigue funcionando" de 2026-09-22b solo valía donde quedaba
    ese venv viejo). Ahora usa `.venv\Scripts\python.exe`, igual que `RUN.bat`.
  - **`SETUP_OTRA_PC.md`** (de junio) suma lo que faltaba: `client_secrets.json`/`token.json`,
    `.env.txt`, `transition_overlays/`, renombrar `daily_shorts`/`long_form` antes del `mklink`,
    `VPS_UPLOAD_ENABLED=0` sin SSH al VPS y Claude Code opcional; saca la referencia a
    `project_whisper_vps.md`, que no está en el repo.
- **2026-09-25d** — **El título del video también se verifica, y los gentilicios sirven de gancho.**
  - **Título:** Cannae quedó con el título "86,000 Dead" mientras el guion corregido decía que 86.000
    pelearon. Ahora `fact_check_scenes(title=...)` juzga el título como un ítem más ("VIDEO TITLE") y lo
    repara con tope de 70 caracteres. `process_manual_json` reemplaza `json_data['title']`, así el tema
    del storyboard, la miniatura y los metadatos toman el título corregido. No entra en la firma de la
    narración ni frena la subida: si no se pudo corregir queda como nota. Prueba real: "86,000 Dead…"
    → "Tens of Thousands Dead…".
  - **Gancho** (`text_options`): las cifras con gentilicio en plural ya valen ("300 SPARTANS",
    "86,000 ROMANS"). Antes toda palabra con mayúscula se descartaba como nombre propio y Cannae quedó
    sin texto de gancho.
  - **Atribución de problemas:** cuando la escena que indica el juez contiene la cita, se respeta, y
    el título y la escena 1 pueden compartir "86,000".
- **2026-09-25c** — **Cannae: sin investigación y subida frenada por un guardia.**
  - **Búsqueda del tema** (`research_search.topic_search_queries`): normaliza guiones y espacios
    tipográficos (U+2011, U+202F) y prueba el sujeto antes de los dos puntos ("The Battle of Cannae",
    "Battle of Cannae"). Antes "…double‑envelopment in 216 BC" solo traía "Pincer movement", el guion
    se escribió sin investigación (6.000 cartagineses, los Apeninos, dos cónsules muertos) y el
    arranque se quedó sin texto de gancho.
  - **Guardia de largo de la reparación:** ahora tiene un margen absoluto de ±10 palabras (mínimo 6),
    y el prompt le dice al reescritor el rango de cada escena. "25 vs 17 palabras" se descartaba 3
    veces y dejaba frenada la subida, aunque la voz se genera después, con el texto ya corregido.
- **2026-09-25b** — **Claude CLI primero y más rápido.** Con Gemini primero, cada verificación esperaba a
  que fallaran sus modelos sin cuota. Cambios:
  - **Orden de jueces:** Claude CLI → Gemini + Google → Gemini + Wikipedia → Groq. Para reescribir:
    Claude → Gemini → Groq.
  - **`--effort low`** (`FACT_CHECK_CLAUDE_EFFORT`): el juez pasó de 50,7 s a 11,8 s, y encontró 5
    problemas contra 3. La reescritura, de 9,6 s a 3,7 s.
  - **Búsqueda web solo si hace falta** (`grounded="as_needed"`), usando primero los párrafos de
    Wikipedia.
  - **Otra ronda de reescritura solo si quedan afirmaciones falsas o inventadas.** Los matices
    "engañosos" que aparecen al re-verificar quedan como notas.
  - **Resultado:** la etapa completa con el guion de Trafalgar pasó de 241 s (3 rondas) a 78 s
    (2 rondas).
- **2026-09-25** — **Claude CLI de la PC como juez de hechos** (`script_fact_check.claude_judge`).
  - **Orden de jueces:** Gemini + Google (gratis mientras haya cuota) → **Claude CLI + WebSearch/WebFetch**
    → Gemini + Wikipedia → Groq + Wikipedia. También reescribe, sin herramientas, antes de Groq.
  - **Cómo se llama:** `claude -p --output-format json`, con el prompt por stdin (el límite de Windows
    es ~8000 caracteres), solo las herramientas web, sin MCP ni sesión guardada, desde una carpeta
    temporal (sin el CLAUDE.md del proyecto).
  - **Entorno limpio:** sin `ANTHROPIC_*` ni `CLAUDE_CODE*`. Si el Studio se abre desde una sesión de
    Claude, esas variables dejan al CLI "Not logged in".
  - **Costo:** usa la cuenta de Claude de la PC y su límite de uso.
  - **Configuración:** modelo en `FACT_CHECK_CLAUDE_MODEL` (por defecto `sonnet`); `FACT_CHECK_CLAUDE=0`
    lo saca.
  - **Sin sesión o sin cuota:** se salta 15 minutos y el log dice cómo loguearse.
  - **De paso:** las llamadas de respaldo a Groq pasan de 4000 a 8000 tokens. `gpt-oss-120b` razona y
    con 4000 truncaba, y todo terminaba en `gpt-oss-20b`.
- **2026-09-24g** — **Prompt de video por segmento** (botón "Copiar prompt video" junto a "Copiar prompt
  imagen", también en segmentos agrupados). Es para IAs de video externas (Kling, Runway, Veo, Sora).
  - **Mismo plano que la imagen:** la consulta de dirección de arte ahora devuelve también
    `camera_move`, `subject_motion`, `environment_motion`, `pace` y `sound`, sin llamadas extra.
    `VERSION=2` rehace una vez los planos guardados.
  - **Reglas de movimiento:** un solo movimiento de cámara lento; movimiento de sujeto chico (nada de
    peleas, multitudes corriendo, gestos de manos o hablar, que las IAs de video rompen); el ambiente
    (humo, velas, mar, brasas) lleva la vida del plano; sonido ambiente sin voces ni música.
  - **El texto copiado trae tres bloques:** prompt completo (texto a video) con la duración real del
    segmento y las zonas de gancho y subtítulos; "solo movimiento" para animar la imagen del segmento
    (imagen a video); y un negative con artefactos de video (caras que se deforman, manos, flicker,
    cortes).
  - **Respaldo:** si la dirección de arte no responde, arma uno con `visual_prompt` + `motion_prompt`.
  - **Firma del plano:** ahora incluye el `motion_prompt` del segmento.
  - **Limpieza de "evitar":** sin "No ..." (doble negativo en un negative prompt) y sin aclaraciones.
- **2026-09-24f** — **Descarga robusta de Jamendo** (`music_recommender.download_audio`). En el buscador,
  la forma de onda falló por DNS de `prod-1.storage.jamendo.com` y la vista previa se cortó al 21%
  ("Read timed out"): no había reintentos, y los dos pedían el mismo archivo a la vez. Ahora:
  - reintenta y reanuda con Range;
  - prueba el espejo `mp3l.jamendo.com` (mismo archivo, más rápido);
  - baja a `.part` y renombra al terminar;
  - hace una sola descarga por tema: vista previa, forma de onda y "Guardar" comparten el caché,
    que ahora va por id de Jamendo y no por título;
  - `download_track` (rutas fijas como `temp_bgm.mp3`) siempre baja de nuevo, para que un video no
    herede la música del anterior.
- **2026-09-24e** — **Prompts de imagen con dirección de arte** (`visual_art_direction.py`). Motivo: el
  usuario pega "Copiar Prompts" en una IA de imagen externa. Ese texto salía del armado para FLUX
  (refuerzos, sufijo de variación, negative en etiquetas), y cada escena elegía luz y paleta por su
  cuenta. Ahora hay dos pasos:
  - **Biblia visual por video,** una sola vez desde la narración verificada. Incluye época, clima y hora
    reales; el aspecto documentado de cada personaje a esa fecha (rango, edad, heridas, uniforme); los
    barcos y objetos; la paleta en tres actos con colores hex y temperatura de luz; una cámara y un look
    para todo el video; y los mitos y anacronismos a evitar (por ejemplo, Nelson sin parche).
  - **Un plano por segmento:** el momento exacto que narra ese segmento, tamaño y ángulo variados,
    lente, capas de profundidad, luz con fuente, dirección y K, paleta del acto, atmósfera, emoción y
    detalles de época.
  - **El prompt copiado es prosa por secciones:** escena, sujeto, acción, ambiente, composición, luz,
    paleta, atmósfera, detalles de época, cámara y lo que hay que evitar. Deja libres la banda del
    gancho en la escena 1 y la zona de subtítulos. Trae además un negative corto.
  - **Guardado:** queda en `storyboard["visual_bible"]` y `segment["art_direction"]` con firma. Si se
    edita la narración o el `visual_prompt` de un segmento, ese plano se rehace. La primera copia
    tarda entre 20 y 50 s por video; las siguientes son instantáneas. El orden de modelos es Gemini
    3.5 → 2.5 → 3.1-lite → Groq; si nadie responde, se copia el prompt de siempre.
    `VISUAL_ART_DIRECTION=0` lo apaga.
  - **Verificador de hechos:** cuando corrige una escena, ahora también corrige su `visual_prompt`,
    para que la imagen no siga mostrando el dato falso.
- **2026-09-24d** — **Música de Jamendo apta para video, con atribución automática**
  (`music_license.py`). Motivo: Shorts bloqueados en todo el mundo por "The Prophecy" (Paul Werner),
  reclamada por WAMI_CS, MINT y BMI. Es CC BY-NC-ND y `content_id_free: false`, y la app aceptaba
  cualquier licencia CC. Auditoría: 65 de 67 proyectos con Jamendo usaban NC o ND; "The Prophecy"
  aparecía en 30.
  - **Licencias aptas:** NC no se puede monetizar, y ND no se puede usar en un video (Creative
    Commons considera obra derivada sincronizar música con imagen). Quedan CC BY y CC BY-SA.
  - **Búsqueda:** la del diálogo y la de la música automática usan `ccnc=false&ccnd=false`.
    `content_id_free` no sirve como filtro: Jamendo solo lo marca en temas NC-ND.
  - **Artistas reclamados:** se descartan los de `daily_shorts/music_claims.json` (va a git). Se
    agregan con clic derecho en el buscador ("Bloquear artista") o con
    `python music_license.py claim <id> --claimants "..."`.
  - **Atribución:** el ensamblador registra la música que mezcló (`music_used`,
    `music_attribution`). Cada uploader (YouTube, Facebook, Instagram, también vía VPS) pega el
    crédito en inglés al final de la descripción ya optimizada, antes de los hashtags y sin
    recortarlo. Formato: título, autor, fuente y licencia.
  - **Al publicar:** el Studio frena con aviso si el tema es NC o ND, o si su artista está
    reclamado; en proyectos viejos resuelve la licencia por el `trackid` del `audio_url`.
  - **Riesgo que queda:** un artista CC BY que registre su música en Content ID reclama igual. Se
    bloquea al primer reclamo. Riesgo cero solo con la Biblioteca de Audio de YouTube, cargada como
    Música Local.
- **2026-09-24c** — **Hechos verificados antes de la voz** (`script_fact_check.py`). El short de
  Trafalgar salió publicado diciendo que el disparo del Victory mató a Villeneuve (lo capturaron y
  murió en 1806; el que murió fue Nelson), con una "advertencia de Collingwood" inventada y el mito de
  que la batalla "evitó la invasión". El prompt ya decía "no inventes"; `script_fact_guard` solo mira
  cifras y años y solo escribe en el log; el reintento de largo pedía "hora exacta, víctimas, testigos
  con nombre". Ahora, en `process_manual_json` (short automático, largo por lotes y JSON pegado a
  mano) y en el camino clásico, ANTES de la voz: (1) evidencia de Wikipedia: artículos del tema y de
  cada persona nombrada, buscada junto al tema porque "Villeneuve" suelto trae al piloto de F1;
  (2) un juez externo enumera cada afirmación con su veredicto (falso / inventado / engañoso):
  Gemini + Google Search → Gemini con los párrafos de Wikipedia → Groq con los párrafos. Cada modelo
  tiene cuota diaria propia y la búsqueda de Google otra aparte; un juez con 429/503 se salta 15 min.
  (3) Las escenas con problemas se reescriben con el dato documentado, con largo parecido y desde la
  2.ª ronda en modo conservador (sin horas, cifras ni "mientras"). (4) Se re-verifica solo lo
  reescrito. Lo falso o inventado que sobrevive deja el informe en `needs_review`. El informe queda
  en `storyboard["fact_check"]` con una firma de la narración, y la subida lo mira: el Studio
  (`_fact_check_gate`) y `daily_short_pipeline` re-verifican si falta o si se editó la narración, y
  frenan. El Studio deja "Publicar igual" como decisión explícita. El checklist previo a publicar
  suma `facts_verified`. Prueba en vivo con el guion real: marcó Villeneuve (falso), Collingwood
  (inventado), la hora de la orden de columnas y la frase de las rutas comerciales, y dejó el guion
  corregido y re-verificado en 20-60 s. `SCRIPT_FACT_CHECK=0` lo apaga; `FACT_CHECK_GEMINI_MODELS`
  elige los modelos.
- **2026-09-24b** — **Títulos bien redactados.** Trafalgar salió "Nelson Trafalgar how the victory
  secured British seas" (la búsqueda del autocompletado pegada literal: el pedido al LLM decía "la
  clave en las primeras 3-4 palabras") y Facebook/Instagram pisaron "How Nelson Won Trafalgar Against
  a Bigger Fleet" con ese. Ahora (`youtube_titles.py`): el pedido integra la clave con conectores y
  puntuación ("Nelson at Trafalgar: …") y escribe los compuestos como el guion (U-boat,
  Franco-Spanish); `readability_issues` invalida la búsqueda pegada sin puntuación;
  `apply_canonical_forms` corrige "U boat" → "U-boat" y los guiones no separables; la verificación
  del LLM también juzga si el título es inglés fluido (`natural`); el título del guion compite como
  candidato; en Facebook/Instagram un título investigado mal redactado no reemplaza a uno que se lee
  bien. Prueba en vivo con el guion real: eligió "Nelson at Trafalgar: 1805 double-column wins".
  Pendiente aparte: el guion de Trafalgar afirma que el disparo del Victory mató a Villeneuve (falso)
  y la verificación de títulos toma el guion como verdad.
- **2026-09-24** — **Arranque del video sin placa quieta** (`video_opening.py`, por defecto en todo
  video nuevo). Antes: placa de 0.7 s con una palabra ("FEEDING"), un "ding" y la voz corrida 0.7 s
  (medido en el short de Hannibal). Los 20 shorts de historia más vistos del mes: 18/20 con sonido
  antes de 0.3 s, 3/20 quietos en el primer medio segundo, primer corte ~1.8 s, 9/12 con texto en el
  primer cuadro. Ahora: (1) sin placa, la escena 1 y la voz arrancan en 0.0 s (el relleno de
  silencio desaparece solo); (2) el primer clip arranca con acercamiento de salida rápida;
  (3) el primer plano dura ≥1.8 s (se toma del segundo, que no baja de 0.8 s); (4) texto de gancho
  arriba, encima de la escena en movimiento, como evento ASS: la cifra de las primeras frases del
  guion (`50,000 TROOPS`, `100 KM A DAY`), estilo editorial (Georgia, cifra dorada, rótulo marfil),
  ~1.8 s con fundido. El prompt de la imagen de la escena 1 pide el tercio superior despejado.
  El segmento 0 guarda `hook_overlay` {enabled, text, duration}: el **timeline editor** lo muestra
  ("Gancho: …" en la tarjeta) y lo deja editar (bloque "Texto de gancho" en la escena 1).
  Config en el Bible: `hook_overlay` (enabled, duration_seconds, min_first_shot_seconds,
  push_in_zoom); `cover_frame.enabled` quedó en false (vuelve solo si se apaga `hook_overlay`).
  **Medición**: cada proyecto guarda `opening.style`; `performance_feedback` agrupa por arranque y
  el resumen compara "placa" vs "gancho" (retención tras el inicio y tasa de despegue) cuando hay
  ≥8 de cada uno. Proyectos viejos con placa se re-renderizan igual (`generate_cover_frame` ya no
  corta por `enabled`). Checklist: `opening_hook_present`. Guardas: `test_video_opening.py` (29).
- **2026-09-23** — **Texto de miniatura con impacto, medido.** `thumbnail_typography.py` +
  `gemini_vision.py` (Groq ya no tiene modelos de visión; Gemini por REST, clave en el header).
  Medido con visión: la miniatura del caballo mongol salió con "100 KILOMETERS" a 2.6–3.3% de
  alto de letra, peso regular y sin contorno (la regla fija pedía "small and restrained"). En los
  60 shorts de historia más vistos del mes (47 miniaturas `oardefault.jpg`, sin cuota), los
  rótulos de 1–3 palabras miden mediana 6% y cuarto superior ~8%; 12/13 bold/black; 10/13 con
  contorno o caja. **Plan**: la cifra sola y grande (11% en 9:16), el resto 8%, llenando hasta
  86% del ancho; negrita condensada (sin Impact), contorno oscuro de 1/10 de la letra; el color de
  la cifra por tono opuesto a la paleta y contraste WCAG con el fondo (blanco sobre el cielo
  naranja daba 1.65:1); en vertical el texto va en y 11–34% y el sujeto baja a y 34–71% (solo en
  el super prompt; el validador interno no cambia). La investigación mide también el texto de las
  miniaturas que compiten (y evita su color de acento). **Revisión al elegir la miniatura**: la
  lee a tamaño completo y de grilla (190 px, recorte 2:3), mide el alto real y avisa si es chica,
  fina, sin contorno, ilegible o mal escrita (la del caballo: "débil"; la maqueta con el plan:
  "con impacto"). Texto con ritmo: "100 kilometers a day" → `100 KM A DAY`.
  `THUMBNAIL_TEXT_RESEARCH=0` / `THUMBNAIL_TEXT_CHECK=0` apagan la visión.
  Guardas: `test_thumbnail_typography.py` (27); `test_thumbnail_superprompt.py` actualizado.
- **2026-09-22g** — **Instagram: lo mismo que Facebook.** `instagram_uploader.upload_from_metadata`
  llama a `facebook_metadata.prepare_instagram_metadata` (mismo motor; en Instagram no hay campo
  de título: el caption arranca con el título, así que no se antepone nada). Marca = nombre de la
  cuenta (@stunning.foh, "Stunning Facts of History"); fuera `#stunningrevelations #mystery #reels
  #facts` de los respaldos (Studio, Metadata Studio, pipeline) y el corte a mitad de palabra.
  Investigación encadenada: YouTube → Facebook (`research_used` en su resultado) → Instagram
  (`research_for_next_platform`), sin investigar dos veces. **Portada:** la API solo la acepta al
  crear el contenedor como `cover_url` (URL pública, JPEG): se convierte a JPEG ≤8 MB, se sube a
  Cloudinary (`cloudinary_uploader.upload_image`), va en el contenedor (resumable y por URL), se
  borra después, y se verifica contra `thumbnail_url`. Si Meta rechaza la portada se publica sin
  ella; un error del video (la caída de ingesta) se propaga igual que antes. Después de publicado
  no se cambia por API (sí en la app). `INSTAGRAM_SEO=0` apaga la optimización;
  `FACEBOOK_SEO_RESEARCH=0` apaga la investigación propia de las dos redes. **Ojo:** el 22-09
  `check_instagram_ingest.py` seguía fallando (Meta no procesa videos desde el 15-09), así que
  esto no se pudo ver en vivo. Guardas: `test_instagram_metadata.py` (22).
- **2026-09-22f** — **Facebook: título/hashtags investigados + la misma miniatura que YouTube.**
  (1) `facebook_metadata.py`, llamado desde `facebook_uploader.upload_from_metadata` (cubre
  Studio, `run_pipeline` y el scheduler del VPS). Facebook no tiene campo de tags: se optimizan
  el título, el arranque de la descripción (lo visible antes de "Ver más", ~125 car.) y 3-5
  hashtags. Reusa lo que YouTube ya investigó en la misma tanda (`research_from_youtube`, el
  Studio lo deja en `facebook_metadata.json['research']`); si no hubo YouTube, investiga igual
  que `youtube_uploader`. Título: `optimize` (respaldo) usa el investigado, `suggest` (lo
  escribiste en el Metadata Studio) lo deja y reporta la alternativa. Hashtags: sujeto amplio
  primero, palabra clave, variedad (máx. 2 con el sujeto), cada palabra respaldada por el guion,
  `#History` y la marca de la PÁGINA real (Stunning Facts of History) al final; fuera
  `#Mystery`, `#StunningRevelations`, `#fyp`/`#viral`/`#reels`. Repara el primer párrafo cortado
  a mitad de palabra por el respaldo viejo (reel de Hannibal: "...every s"). `FACEBOOK_SEO=0`
  apaga todo; `FACEBOOK_SEO_RESEARCH=0` solo la investigación propia. (2) Miniatura:
  `POST /{video_id}/thumbnails` (source + `is_preferred=true`) para reels y videos de página, con
  WebP→JPEG, reintentos (10/30/60 s), verificación contra la preferida que guarda Facebook, aviso
  en el panel y `thumbnail_set/thumbnail_error` en el resultado. (3) Encontrado al probar, arreglado
  para YouTube también: `youtube_titles.unsupported_numbers` exige la misma unidad ("30 km" de
  ceniza no respalda "30 eruptions") y `factcheck_candidates` hace que el LLM verifique los mejores
  candidatos contra el guion antes de elegir (rechazó "casts hold bodies" y "30 eruptions";
  `YOUTUBE_TITLE_FACTCHECK=0` lo apaga). (4) El VPS ahora recibe `facebook_metadata.py`,
  `thumbnail_publish.py` y `output_video_locator.py` (este último faltaba desde f2e531d).
  Guardas: `test_facebook_metadata.py` (33), `test_youtube_titles.py` (29).
- **2026-09-22e** — **Miniaturas: subida confiable y prompt guiado por datos.**
  (1) `thumbnail_publish.py`: el selector aceptaba `.webp` y el uploader solo buscaba
  png/jpg (se publicaba sin miniatura, en silencio); ahora se detecta el formato por contenido y
  se convierte a JPEG ≤2 MB, `thumbnails.set` reintenta errores transitorios (8 s, 20 s), el
  resultado va al PANEL (y a `publish_results`: `thumbnail_set`, `thumbnail_error`) y el Studio
  avisa antes de publicar qué miniatura sale o si no hay. `verify_served_thumbnail` compara lo
  que YouTube muestra con el archivo local (recorta el centro en Shorts). Verificado: en este
  canal los Shorts SÍ muestran la miniatura personalizada (canal/búsqueda, nunca el feed);
  Gunnerside y Hannibal muestran miniaturas que el usuario subió a mano después.
  (2) `thumbnail_research.py`: baja las miniaturas de los videos que rankean para la palabra
  clave (misma investigación que tags/título) y mide brillo, saturación, familia de color y
  carga visual con numpy; elige el acento que MENOS usa la competencia, el brillo contrario y
  minimalismo si están cargadas; el texto complementa al título (cifra del guion con su
  sustantivo, búsqueda real de 2+ palabras, palabra del ángulo) y cada palabra tiene que estar
  en el guion. El super prompt reemplaza su paleta ámbar fija y la luminancia fija por las de la
  investigación. En vivo: Pompeii (competencia 5/8 cálida) → teal + `1,000 CASTS`; Kaiten → cálido
  + `63 SAILORS`. `THUMBNAIL_RESEARCH=0` lo apaga. Guardas: `test_thumbnail_publish.py` (13),
  `test_thumbnail_research.py` (17).

- **2026-09-22d** — **Títulos investigados** (`youtube_titles.py`). Usa la MISMA investigación que
  los tags (`youtube_tags.gather_research`, una sola llamada de cuota por video). Candidatos:
  borrador, borrador con la palabra clave al frente y ~10 de Groq con todo el contexto (búsqueda
  principal y secundarias, títulos que rankean para diferenciarse, ganadores propios, plantillas
  del Bible y del ángulo, el guion como única fuente de datos). Puntaje determinístico 0-100
  estilo vidIQ: palabra clave presente (30) y al principio (15), largo en franja (20), cifra
  respaldada (10), búsquedas secundarias (8), ángulo (5); penaliza palabras muertas, aperturas
  prohibidas, copiar a la competencia, repeticiones, emojis, hashtags, MAYÚSCULAS. **Invalida**
  cifras o nombres propios que no están en el guion. Modo `optimize` (título inventado por el
  LLM al publicar: cambia si gana por 5+) / `suggest` (Metadata Studio o piloto aprobado: deja
  el del usuario y reporta la mejor alternativa) / `off`; `YOUTUBE_TITLE_MODE` lo fuerza. En vivo:
  Hannibal 65→87-95, Kaiten 54→91, Pompeii 38→87. Guardas: `test_youtube_titles.py` (22).

- **2026-09-22c** — **Tags de YouTube investigados y bien insertados** (`youtube_tags.py`).
  Auditoría de los 33 videos (tags GUARDADOS, Data API): 6 sin tags, un tag gigante pegado
  (Great Zimbabwe), hashtags como tags (`#shorts`, `Baghdad1258`), relleno fijo del microdoc
  (`history, documentary`), el uploader cortaba `500 tags` en vez de 500 caracteres y metía
  `Shorts` primero. Ahora: (1) `finalize_youtube_tags` es la puerta final de TODOS los caminos
  (separa bien, saca `#`, descarta bloques pegados y basura, deduplica, conserva el orden y
  respeta 500 caracteres contados como YouTube: comas + 2 por tag con espacio); (2)
  `research_tags` hace lo que vidIQ: palabra clave principal validada por el autocompletado
  de YouTube y que nombre al sujeto del video, tags de los videos que rankean para esa
  búsqueda (consenso ponderado por vistas), filtros de marcas ajenas, homónimos y juegos
  (`hannibal lecter`, `world of warships`, `total war`), relevancia contra el guion,
  casi-duplicados colapsados y la marca propia con lugar reservado. (3) El uploader investiga
  con el tema y el guion (el Studio los pasa en la metadata), escribe el progreso en el panel
  y **verifica lo que YouTube guardó** (avisa si difiere). `YOUTUBE_TAG_RESEARCH=0` lo apaga.
  Cuesta ~101 unidades de cuota por video (1 search + 1 videos.list). Guardas:
  `test_youtube_tags.py` (26).

- **2026-09-22b** — Fuera la pestaña **Daily Shorts** (`daily_shorts_tab.py`, 141 KB) y
  `subtitle_style_catalog.py`: no se usaba, se colgaba al cargar ("Loading voices…") y Auto
  Video Studio cubre todo. `daily_short_pipeline.py` (el CLI y lo que usan los
  microdocumentales) se queda; `GENERATE_SHORT.bat` sigue funcionando.
- **2026-09-22** — **Bucle de datos completo (5 capas).** Ver §6b. `performance_feedback.py`
  (snapshot YT+FB, botón "Rendimiento"), `format_archetype` (ángulo: Bible + combo + prompt +
  cover + thumbnail), `first_seconds` (regla medida "cifra o pregunta, la fecha después" +
  `QA DEL GANCHO` en cada render), `trend_report.py` + `anniversaries.json` (botón
  "Tendencias", temas cargables con un clic), Short vertical autónomo derivado del 16:9
  (`mode="standalone"`). El Bible pasó a git (`!daily_shorts/channel_strategy_profile.json`) y
  se le quitó lo que murió (cover words de misterio, "Tunguska Mystery"). `publish_results` en
  cada proyecto al publicar. Guardas: `test_performance_feedback` (18), `test_publish_record`
  (10), `test_format_archetypes` (16), `test_first_seconds` (15), `test_trend_report` (15),
  `test_standalone_short` (5).

- **2026-09-21** — **El perfil editorial seguía pegado al canal viejo.** `select_channel` es global:
  abrir un proyecto de Stunning Revelations lo dejaba activo y cada proyecto nuevo heredaba sus
  categorías, ganchos, títulos y tono sin ningún control visible. Desde el 8-9 (Coronel,
  Gunnerside, Bagdad, Berlín, Halifax, Çatalhöyük) los guiones para Stunning Facts of History
  se escribieron con `channel_profile = stunning-revelations`. Regla nueva
  (`studio_channel_controls`): hasta que haya guion, el perfil editorial sigue al destino de
  publicación; al escribir un guion nuevo se sincroniza con el destino (log "Perfil editorial:
  …"); un proyecto ya escrito conserva el suyo. El combo de categorías sale del perfil activo
  desde el arranque (antes: lista fija en español). `tone_profile` entiende los nombres en
  inglés ("Historical Disasters" → dramático-factual, "Historical Mysteries" → misterio); antes
  todo caía en documental y la categoría solo aparecía en el prompt. Guardas:
  `test_studio_channel_controls.py` (+3), `test_tone_profile.py` (7).

- **2026-09-16** — **Instagram: diagnóstico del 2207076 y subida resumable.** No era transitorio:
  el mismo mp4 que Facebook publica, Instagram lo rechaza al *procesarlo* (por rupload el detalle
  es "Video Transcoding Error: both HD and SD progressive failed to transcode"). Probado en seco
  con tres archivos (uno de junio y el Gunnerside del 9-9, ambos ya publicados en IG antes), dos
  cuentas (@stunning.foh y @stunning.revelations), tres transportes (URL/Cloudinary, POST único,
  trozos) y sin edit lists: todo falla → **es Meta**, desde el 15-09 al menos. Nada que arreglar
  en el video. Cambios: `instagram_uploader` sube ahora por **resumable en trozos de 4 MB** con
  `Content-Type: video/mp4` (un POST de 103 MB se caía; `octet-stream` da 400 genérico), sin
  Cloudinary; el flujo por URL queda de respaldo (`INSTAGRAM_UPLOAD_MODE=url`); reintentos del
  contenedor por URL bajan a 2. **`check_instagram_ingest.py`** prueba en seco si Meta ya procesa
  videos (no publica). Guardas: `test_instagram_resumable.py` (14).

- **2026-09-15b** — **Instagram: reintentos ante el error intermitente de Meta.** "Media upload has
  failed with error code 2207076" con un mp4 impecable que Facebook acababa de aceptar. Es
  transitorio del lado de Meta; ahora el contenedor se reintenta hasta 3 veces (30 s, 90 s)
  con la MISMA URL de Cloudinary (`INSTAGRAM_CONTAINER_ATTEMPTS`), solo para códigos
  transitorios (2207076/2207001/2207005/2207052/2207053); un formato no soportado (2207026)
  no se reintenta. Si al final no se publica, la copia de Cloudinary se borra igual (antes
  quedaba huérfana). `VPS_UPLOAD_ENABLED=0` en `.env` salta el VPS para Facebook/Instagram
  (cada uno esperaba 40 s a un ssh mudo). El camino local ahora escribe etapas en el panel
  (Cloudinary %, contenedor creado, "Meta procesando (n s)", reintentos, publicado) vía
  `on_status` + `upload_progress.make_byte_progress_reporter` y la señal thread-safe
  `_publish_log_signal`; antes el panel quedaba mudo minutos. Guardas:
  `test_instagram_container_retry.py` (11), `test_upload_progress.py` (10).

- **2026-09-15** — **Un solo lugar para los videos generados: `auto_videos/output/` (Drive).**
  El pipeline CLI y los microdocumentales copiaban el render dentro de la carpeta del
  proyecto (`short_HHMMSS.mp4`, `<TEMA>_DOCUMENTARY.mp4`) porque los uploaders buscaban
  "el primer mp4 de la carpeta": cada video estaba dos veces (434 MB solo en Gunnerside) y
  los documentales quedaban en C:. Ahora `assemble_video` devuelve el render y registra la
  ruta en `pipeline_state.json`; `long_form_builder` ya no copia; YouTube/Facebook/
  Instagram/X resuelven el video con `output_video_locator.find_output_video` (ruta
  registrada, si no el mp4 más reciente). `long_form/` pasó a ser junction a Drive (1,9 GB
  movidos) y está en `.gitignore`. Guardas: `test_output_video_location.py` (12).

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
