# AI Video Playbook — referencia para IAs agénticas

> **Para la IA que lee esto:** este archivo es tu punto de partida para **generar
> videos desde este repo** sin re-descubrir todo. Es permanente y **actualizable**:
> si aprendés algo nuevo (un entry point cambió, una métrica nueva, una decisión de
> estrategia), **actualizá la sección correspondiente y el Changelog al final**.
> Mantené los hechos verificables; no inventes rutas ni claves.

Última actualización: **2026-07-19**.

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

- **2026-07-19** — Creado. Documenta: entry points de shorts (`run_pipeline`) y long-form
  (`build_long_form`), mejoras bakeadas (hooks, capítulos, metadata long-form, sanitizer,
  is_short, production_weight), los dos canales y sus diagnósticos, la métrica de swipe
  rate, y reglas de subida. Mantener actualizado al cambiar entry points o estrategia.
