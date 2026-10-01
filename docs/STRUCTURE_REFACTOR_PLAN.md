# Plan de refactorización: de estructura monolítica plana a paquetes por dominio

> **Estado:** PROPUESTA — sin ejecutar.
> **Objetivo:** eliminar la estructura monolítica plana (233 módulos `.py` en la raíz)
> agrupándolos en paquetes por dominio, **sin romper** los entry points documentados en
> `AI_VIDEO_PLAYBOOK.md` ni los lanzadores (`RUN.bat`, `GENERATE_SHORT.bat`).
> **Regla de oro:** mover un módulo solo después (o junto con) todo lo que importa.
> Hojas primero, módulos "dios" al final.

---

## 1. Situación actual (medida)

Métricas obtenidas analizando el grafo de imports con `ast` (2026-10, DSH):

| Métrica | Valor |
|---|---|
| Módulos de producción (raíz) | 157 |
| Módulos de test (raíz) | 76 |
| **Total `.py` en un solo directorio** | **233** |
| LOC producción | ~105.000 |
| LOC tests | ~15.700 |

### Módulos "dios" (más de 2.700 líneas)

| Módulo | Líneas | Dependencias locales |
|---|---|---|
| `auto_video_integration_pyqt6.py` | 6.450 | 47 |
| `timeline_editor_widget.py` | 5.564 | 28 |
| `auto_video_generator_v2.py` | 3.805 | 33 |
| `storyboard_generator.py` | 3.620 | 13 |
| `daily_short_pipeline.py` | 2.807 | 26 |
| `studio_project_manager.py` | 2.724 | 9 |

### Módulos fundacionales (más importados)

`env_loader` (20), `channel_strategy` (18), `video_config` (14), `groq_client` (13),
`auto_video_generator_v2` (10). Nota: `auto_video_generator_v2` es a la vez *fundacional*
(10 lo importan) y *dios* (33 dependencias): es el nudo central del acoplamiento.

### Módulos "hoja" (no importan nada local)

49 módulos (clientes de API y utilidades) — los más baratos de mover.

### Dato de seguridad

Ningún módulo de producción importa `test_*` (solo tests importan tests). Mover la suite a
`tests/` tiene riesgo ≈ 0.

---

## 2. Problema

1. **Sin fronteras de dependencia.** Todo vive plano e importa por nombre, así que nada
   impide que un diálogo importe un uploader o que un cliente importe el ensamblador. No hay
   "dirección" de dependencias, y eso es lo que deja crecer módulos dios.
2. **Imposible de navegar.** 233 archivos en un directorio, sin agrupar por dominio.
3. **Cambios de alto riesgo.** Tocar un módulo fundacional tiene 18–20 puntos de impacto que
   no se ven de un vistazo.
4. **Test suite mezclada** con el código de producción.

---

## 3. Estructura objetivo

```
app/          → entry point + shell GUI + diálogos genéricos de proyecto/video
studio/       → Auto Video Studio (tab, handlers, timeline, buscador de música, previews)
catharsis/    → formato Catarsis (casi autocontenido)
pipeline/     → generación: engine, guión, TTS, imágenes, ensamblaje, subtítulos, thumbnails
ai/           → clientes LLM + imagen + búsqueda + fact-check + prompts
media/        → adquisición de stock (pexels, wikimedia, archive, bing, youtube, música)
publish/      → uploaders + SEO (tags/títulos) + miniaturas + atribución de música
channel/      → estrategia, analytics, tendencias, feedback
infra/        → config, entorno, ffmpeg, vast.ai, whisper VPS, utilidades
tests/        → los 76 test_*.py
```

### Principios

- **Sin renombres en esta fase.** Solo mover archivos (conservando nombre) y prefijar imports.
  Los renombres (p. ej. `video_optimizer_pyqt6` → `main`) se encaran después, si hace falta.
- **Dirección de dependencias en un solo sentido** (los paquetes de abajo no importan a los de
  arriba). Si aparece un ciclo, se rompe con import local dentro de función (patrón ya usado
  en el código).
- **Shims en la raíz** para los entry points de CLI/documentados, de modo que nada cambie para
  quien invoca `python daily_short_pipeline.py ...` o `RUN.bat`.

---

## 4. Mapa completo de módulos → paquete

> Asignación indicativa; la decisión final de ~10 módulos "ambiguos" se toma al migrar. Los
> módulos de test no se listan: van todos a `tests/`.

### `app/` — shell GUI + diálogos genéricos

| Módulo actual | Nota |
|---|---|
| `video_optimizer_pyqt6` | entry point (shim en raíz) |
| `ui_themes`, `thumbnails_mixin` | chrome compartido |
| `api_status_checker`, `api_status_dialog` | |
| `project_manager_dialog`, `project_manager_v2` | |
| `video_edit_dialog`, `video_preview_dialog`, `video_history_dialog` | |
| `video_recommendations_dialog`, `video_recommender`, `video_registry` | |

### `studio/` — Auto Video Studio + timeline + handlers

| Módulo actual | Nota |
|---|---|
| `auto_video_integration_pyqt6` | tab principal (dios, 6.450 líneas) |
| `auto_video_generator_pyqt6_adapter` | adapter engine ↔ GUI |
| `studio_project_manager`, `studio_channel_controls`, `studio_categories` | |
| `studio_image_handlers`, `studio_storyboard_handlers`, `studio_video_assembly_handlers` | |
| `platform_metadata_tab` | Metadata Studio |
| `timeline_editor_widget`, `timeline_editor_window`, `timeline_segment_widget` | |
| `timeline_segment_editor`, `timeline_video_widget`, `timeline_workers` | |
| `music_browser_dialog` | |
| `interactive_thumbnail_editor` | |
| `waveform_widget`, `waveform_geometry` | |
| `opening_style_preview`, `pilot_render_settings` | |
| `video_region_editor`, `video_region_effects` | |
| `subtitle_style_preview`, `subtitle_style_preview_dialog` | preview GUI |

### `catharsis/` — formato Catarsis

`catharsis_editor`, `catharsis_tab`, `catharsis_media_input`, `catharsis_player`,
`catharsis_preview`, `catharsis_timeline`, `catharsis_timeline_view`.

### `pipeline/` — generación (no-GUI)

| Módulo actual | Nota |
|---|---|
| `daily_short_pipeline`, `long_form_builder`, `micro_documentary`, `microdoc_analytics` | entry points |
| `build_derinkuyu_long` | ejemplo one-off (referencia) |
| `auto_video_generator_v2` | engine (dios, 3.805 líneas) |
| `storyboard_generator`, `video_assembler` | |
| `tts_generator`, `subtitle_generator`, `dynamic_subtitle_wrapper`, `dynamic_subtitles_generator` | |
| `image_generation_manager`, `video_generation_manager`, `video_export_manager` | |
| `cover_frame_generator`, `video_opening` | |
| `cinematic_director`, `cinematic_effects`, `glitch_transitions` | |
| `audio_mix_utils`, `sfx_client` | |
| `thumbnail_pipeline`, `thumbnail_compositor`, `thumbnail_context_enricher`, `thumbnail_intelligence` | |

### `ai/` — clientes + fact-check + prompts ✅ (Fase 3)

| Módulo actual | Nota |
|---|---|
| `ai_factory`, `groq_client`, `gemini_ai_client`, `gemini_vision`, `claude_client` | LLM |
| `gemini_watermark_remover` | visión |
| `fal_ai_client`, `stability_client`, `recraft_client`, `recraft_style_catalog` | imagen |
| `comfyui_image_client`, `google_ai_image_client`, `google_images_client` | imagen |
| `google_search_api`, `serp_api_client`, `research_search` | búsqueda |
| `script_fact_check`, `script_fact_guard`, `text_correction_engine` | verificación de hechos |
| `prompt_processor`, `visual_art_direction`, `tone_profile` | prompts |

### `media/` — adquisición de stock ✅ (Fase 4)

| Módulo actual | Nota |
|---|---|
| `bing_images_client`, `bing_images_search_dialog` | |
| `pexels_video_search_dialog` | |
| `wikimedia_client`, `wikimedia_search_dialog`, `wikimedia_video_search_dialog` | |
| `internet_archive_client`, `internet_archive_search_dialog` | |
| `youtube_downloader_fixed`, `youtube_video_client`, `youtube_video_search_dialog` | |
| `resource_downloader`, `gdrive_file_utils` | |
| `local_video_picker_dialog`, `video_source_alternatives`, `mixed_media_acquisition` | |
| `music_recommender` | Jamendo (búsqueda + descarga) |

### `publish/` — distribución + SEO + miniaturas

| Módulo actual | Nota |
|---|---|
| `youtube_uploader`, `facebook_uploader`, `instagram_uploader` | |
| `tiktok_uploader`, `x_uploader`, `x_video_uploader` | |
| `vps_publish_scheduler`, `telegram_notify`, `publish_record` | |
| `upload_metadata`, `upload_progress` | |
| `facebook_metadata`, `youtube_tags`, `youtube_titles` | SEO |
| `thumbnail_publish`, `thumbnail_formats`, `thumbnail_art_direction` | |
| `thumbnail_research`, `thumbnail_typography`, `thumbnail_quality_validator` | |
| `cloudinary_uploader`, `output_video_locator` | |
| `music_license` | atribución + gate Content ID |
| `production_checklist` | |

### `channel/` — estrategia + analytics

`channel_strategy`, `channel_profiles`, `youtube_channel_analyzer`, `youtube_analytics_client`,
`youtube_trend_signals`, `trend_report`, `trend_spotter`, `performance_feedback`,
`cost_calculator`.

### `infra/` — config, entorno, VPS, utilidades

| Módulo actual | Nota |
|---|---|
| `output_naming`, `worker_context`, `moviepy_pillow_compat`, `attribution_manager`, `project_autoload`, `project_media_paths`, `project_video_result` | ✅ movidos (Fase 2) |
| `env_loader`, `video_config`, `vast_ai_instance_manager`, `vast_ai_provisioner`, `_whisper_subprocess_worker` | ✅ movidos (Fase 2b): `_upload_via_vps` envía `infra/` con `scp -r`; shim raíz para el CLI `vast_ai_provisioner` |

---

## 5. Entry points y shims de compatibilidad

Para no romper los comandos documentados, se dejan **shims de 3–5 líneas en la raíz** que
re-exportan la función real desde el paquete. Lista de shims necesarios (lo que referencia el
playbook y los `.bat`):

| Shim en raíz | Re-exporta |
|---|---|
| `video_optimizer_pyqt6.py` | `app.video_optimizer_pyqt6.main` (RUN.bat) |
| `daily_short_pipeline.py` | `pipeline.daily_short_pipeline` (`run_pipeline`, `upload_to_youtube`) |
| `long_form_builder.py` | `pipeline.long_form_builder` (`build_long_form`) |
| `tiktok_uploader.py` | `publish.tiktok_uploader` (CLI `--setup/--auth/--check/--upload`) |
| `telegram_notify.py` | `publish.telegram_notify` (CLI `--setup/--test`) |
| `music_license.py` | `publish.music_license` (CLI `claim`) |
| `trend_report.py` | `channel.trend_report` |
| `performance_feedback.py` | `channel.performance_feedback` |
| `check_instagram_ingest.py` | `publish.check_instagram_ingest` |
| `build_derinkuyu_long.py` | `pipeline.build_derinkuyu_long` (ejemplo) |

Los imports **programáticos** que usa el playbook (`from daily_short_pipeline import
run_pipeline`, `from long_form_builder import build_long_form`) siguen funcionando porque el
shim re-exporta esos nombres.

---

## 6. Plan de migración por fases

Cada fase = un commit + correr la suite completa. No se pasa a la siguiente hasta que esté
verde. Dentro de cada paquete, el script de migración calcula el orden hoja-primero.

| Fase | Qué se mueve | Riesgo | Validación |
|---|---|---|---|
| **0. Línea base** | Commitear el WIP (15 modificados + 5 nuevos) + correr suite | — | suite verde + repo limpio |
| **1. `tests/`** | los 76 `test_*.py` | ≈ 0 | suite verde con `unittest discover` |
| **2. `infra/`** | 7 utilidades hoja (`output_naming`, `worker_context`, `moviepy_pillow_compat`, `attribution_manager`, `project_autoload`, `project_media_paths`, `project_video_result`) | bajo | suite verde |
| **2b. `infra/`** | `env_loader`, `video_config`, `vast_ai_*`, `_whisper_subprocess_worker` | bajo-medio | suite verde + VPS |
| **3. `ai/`** | clientes + fact-check + prompts | bajo | suite verde |
| **4. `media/`** | clientes de búsqueda + diálogos | bajo-medio | suite verde |
| **5. `channel/`** | estrategia + analytics | medio | suite verde |
| **6. `publish/`** | uploaders + SEO + thumbnails | medio | suite verde |
| **7. `pipeline/`** | núcleo de generación | medio-alto | suite verde |
| **8. `catharsis/`** | los 7 `catharsis_*` | medio | suite verde |
| **9. `studio/` + `app/`** | los dios al final | alto | suite verde + arranque manual GUI |

**Orden de las fases 2–9 justificado:** los módulos hoja (clientes, utilidades) no importan
nada local, así que se mueven primero con cero reescritura interna; los módulos dios
(`auto_video_integration_pyqt6`, `timeline_editor_widget`, `auto_video_generator_v2`) dependen
de todo lo demás, así que se mueven últimos, cuando sus dependencias ya están en paquetes.

---

## 7. Mecánica de la migración (script)

Como todos los imports son absolutos y planos (`import env_loader`,
`from channel_strategy import validate_hook`), la migración es **determinista y automatizable**:

1. **Parsear** el grafo de imports con `ast` (mismo extractor que produjo las métricas de §1).
2. **Calcular** el orden topológico hoja-primero.
3. **Mover** cada módulo a su paquete y **reescribir** en todo el repo:
   - `import X` → `from paquete import X`
   - `from X import a, b` → `from paquete.X import a, b`
4. **Re-ejecutar** idempotentemente (un segundo run no cambia nada = señal de convergencia).
5. **Verificar** con `python -m compileall` + suite.

El script se puede re-ejecutar por fase y se revierte con git.

---

## 8. Riesgos y mitigación

| Riesgo | Mitigación |
|---|---|
| Imports dinámicos (`importlib`, `__import__`, cadenas) que el rewriter no ve | Grep de patrones dinámicos antes de cada fase |
| Ciclos de import al crear paquetes | Import local dentro de función (patrón ya usado en el código) |
| Rutas relativas a `cwd` / `Path(__file__)` (junctions a Drive) | Auditar usos de `__file__`/`cwd`; `env_loader` resuelve contra la raíz |
| Romper comandos del playbook | Shims en raíz (§5) |
| Regresión silenciosa | Suite completa tras cada fase + baseline limpio |
| Test→test imports planos (`from test_X import ...`) | Se convierten a relativos/`tests.X` al mover a `tests/` (4 casos detectados) |

---

## 9. No-objetivos (no en esta fase)

- **No** partir aún los módulos dios (`auto_video_generator_v2`, `timeline_editor_widget`,
  `auto_video_integration_pyqt6`). Es un refactor de mayor riesgo que se encara *después*, ya
  con paquetes que lo faciliten.
- **No** renombrar variables ni limpiar estilo (ensucia el diff y mezcla riesgos).
- **No** migrar todo de una (big-bang).

---

## 10. Definition of Done

- [ ] Repo limpio con la suite completa en verde tras la Fase 0.
- [ ] 0 archivos `.py` de producción en la raíz (solo shims de CLI).
- [x] 76 tests en `tests/`, corriendo con `unittest discover -s tests -t .`.
- [ ] `RUN.bat`, `GENERATE_SHORT.bat` y los comandos CLI del playbook funcionan sin cambios.
- [ ] `python -m compileall` sin errores.
- [ ] Ningún módulo de producción importa `test_*`.

---

## Changelog

- **2026-10-01 (Fase 4)** — `media/` con 17 módulos (búsqueda/descarga de imágenes, videos y
  música; 54 imports + 4 strings reescritos). Ajustes: `__file__`→raíz en `youtube_video_client`
  (token OAuth), `video_source_alternatives` (`local_videos`) y `music_recommender` (dir de
  descarga). Suite verde: 1205 tests.
- **2026-10-01 (Fase 3)** — `ai/` con 22 módulos (clientes LLM/imagen/búsqueda, fact-check,
  prompts; 127 imports + 17 strings reescritos). Ajustes: `__file__`→raíz en `claude_client`
  (`env_file`) y `comfyui_image_client` (`PROJECT_DIR`); `patch()`/`open()` por string en tests
  pasaron a `ai.`/`ai/`. Suite verde: 1205 tests.
- **2026-10-01 (Fase 2b)** — `infra/` completo: `env_loader`, `video_config`,
  `vast_ai_instance_manager`, `vast_ai_provisioner`, `_whisper_subprocess_worker` (45 imports
  reescritos). Ajustes: `Path(__file__).resolve().parent` → `.parent.parent` en 4 módulos;
  `_upload_via_vps` envía `infra/` con `scp -r`; shim raíz para el CLI `vast_ai_provisioner`;
  ruta del worker en `dynamic_subtitles_generator`; `patch()` por string en tests. Suite verde:
  1205 tests.
- **2026-10-01 (Fase 2)** — `infra/` con 7 utilidades hoja movidas: `output_naming`,
  `worker_context`, `moviepy_pillow_compat`, `attribution_manager`, `project_autoload`,
  `project_media_paths`, `project_video_result` (27 imports reescritos). `env_loader` +
  `video_config` se difieren a Fase 2b: `env_loader` se envía plano al VPS
  (`_upload_via_vps`) y `video_config` depende de él. Suite verde: 1205 tests.
- **2026-10-01 (Fase 1)** — Tests movidos a `tests/` (76 archivos + `tests/__init__.py`).
  Imports entre tests pasaron a `from tests.test_...` (16 en 8 archivos); 5 tests que leían
  fuentes de producción recalcularon la raíz (`__file__` → raíz del repo). Suite verde con
  `unittest discover -s tests -t .`. Nota: no hay pytest instalado; la suite es unittest.
- **2026-10-01** — Documento inicial: métricas del grafo de imports, estructura objetivo,
  mapa módulo→paquete, plan de fases y mecánica de migración.
