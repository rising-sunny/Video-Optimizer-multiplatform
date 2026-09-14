# Canales y piloto de microdocumentales

Auto Video Studio permite elegir **@StunningFactsofHistory** o **@Stunning-Revelations** en **Publicar en YouTube**. El destino se autoguarda como `upload_channel`; cambiarlo conserva el proyecto, timeline, medios y formato. `channel_profile` conserva el contexto editorial previo, independiente de la publicación. Al cargar proyectos antiguos, el destino inicial se toma de su `channel_profile`. El selector no carga otro proyecto ni publica por sí solo.

El perfil existente de Facts of History permanece en `daily_shorts/channel_strategy_profile.json`. Revelations tiene un perfil independiente en `channel_profiles/stunning-revelations.json`. Su política propone lotes de tres microdocumentales y revisión después de tres y seis; el comando de campaña Shorts rechaza ese perfil durante el experimento. Los otros canales mantienen Shorts.

## GUI

1. En Análisis, escribe el tema. En Auto Video Studio selecciona el canal y **Microdocumental · 16:9 · 4–5 min**.
2. Pulsa **Generar storyboard**: la aplicación crea o reutiliza automáticamente la carpeta del proyecto y comienza la propuesta editorial. **Preparar / abrir piloto…** permite revisarla en el proyecto actual. Para continuar otro piloto, abre su proyecto mediante **Abrir proyecto**.
3. Opcionalmente importa un JSON editorial con `selection_reason`, `trend_source`, `trend_window`, `trend_signal`, `channel_fit`, `notes` y fuentes históricas.
4. **Generar propuesta** crea tres títulos, tres conceptos de miniatura, gancho, primeros 30 segundos y afirmaciones con fuentes y nivel de certeza. La primera llamada siempre se detiene aquí.
5. Revisa la pestaña Propuesta editorial; puedes cambiar las selecciones o corregir fuentes en Editar propuesta (JSON). **Aprobar y crear guion** expresa la revisión editorial y genera un guion completo. La comprobación automática no certifica la exactitud histórica.
6. **Cargar en Studio** permite trabajar con el storyboard. Los cambios se autoguardan; al continuar el piloto se sincroniza también el estado pendiente del timeline, sin guardar manualmente. **Ensamblar piloto** reutiliza ese guion y los medios, genera narración y completa el render mediante los componentes existentes. Usa el proveedor configurado en el diálogo.

El autoguardado comienza activado en todos los proyectos nuevos y ambos canales. La configuración se guarda tras una breve pausa, incluso antes de generar el storyboard si ya hay un tema. La propuesta editorial también se autoguarda; un JSON incompleto se conserva como borrador recuperable al reabrir el diálogo. Guardar una propuesta no equivale a aprobarla para generar o ensamblar.

El diálogo hereda el proveedor de imágenes seleccionado en Studio. Con **Manual (Gratuito)**, pulsa **Aprobar y crear guion**, luego **Cargar en Studio** y asigna tus imágenes/videos a los segmentos. Al ensamblar se usan esos archivos sin llamar a generadores de imágenes. Si falta algún archivo, se muestran los segmentos pendientes antes de comenzar la narración o el render. Los conceptos de miniatura y prompts visuales son referencias escritas; crearlos no genera imágenes.

Cada carpeta conserva `experiment.json`, `storyboard.json`, `project.json` y metadatos de YouTube. El título elegido se conserva también en la publicación desde Studio. Los conceptos de miniatura quedan disponibles para producir la imagen en las herramientas de miniaturas existentes; esta etapa no renderiza automáticamente la miniatura.

## CLI

Primera propuesta, sin imágenes ni render:

```powershell
.\.venv\Scripts\python.exe long_form_builder.py "Battle of Coronel" --channel stunning-revelations --format micro_documentary --minutes 4.5 --output-dir long_form/sr_microdoc_001 --no-assemble
```

Después de revisar y corregir `long_form/sr_microdoc_001/experiment.json`, generar el guion:

```powershell
.\.venv\Scripts\python.exe long_form_builder.py "Battle of Coronel" --channel stunning-revelations --format micro_documentary --output-dir long_form/sr_microdoc_001 --approve-preflight --no-assemble
```

Ensamblar ese piloto, conservando el paquete y guion aprobados:

```powershell
.\.venv\Scripts\python.exe long_form_builder.py "Battle of Coronel" --channel stunning-revelations --format micro_documentary --output-dir long_form/sr_microdoc_001 --approve-preflight --provider flux_dev
```

`--editorial-json archivo.json` añade contexto manual al crear una propuesta. Para un piloto existente, edita el manifiesto; sus valores de duración, WPM y contexto son los que se reutilizan. Usa una carpeta distinta por video. Cada invocación genera como máximo un piloto, sin publicación ni escalamiento automáticos. Tras los primeros tres, revisa métricas antes de producir otros tres.

## Duración y arquitectura

La revisión confirmó que `long_form_builder._plan_dimensions` impone al menos tres capítulos y cinco párrafos por capítulo, planifica con 155 WPM y asigna tiempos con 120 WPM. El modo tradicional conserva ese comportamiento para no modificar proyectos existentes. El nuevo módulo `micro_documentary.py` evita ese plan: 270 segundos a 120 WPM equivalen a 540 palabras. El WPM efectivo se configura por perfil.

El guion completo tiene hasta tres intentos para quedar a ±25 segundos del objetivo y dentro de 210–330 segundos; no se eliminan párrafos finales ni se duplican párrafos para rellenar. Tras TTS, se exige narración real dentro de 210–330 segundos antes de generar imágenes. Si la voz real se sale del rango, se detiene para revisar el guion o calibrar WPM. FFprobe comprueba también duración final y proporción 16:9. Los tiempos internos de segmentos siguen siendo estimaciones proporcionales a palabras del constructor existente; no constituyen alineación fonética exacta.

`studio_channel_controls.py` integra selección, revisión y trabajo en segundo plano. `studio_project_manager.py` persiste/restaura canal y estrategia. `youtube_uploader.py` selecciona `token.json` para Facts of History y `token_stunning-revelations.json` para Revelations; verifica el ID de la cuenta antes de insertar un video. No se copian ni intercambian tokens. Si hace falta reautorización, el flujo OAuth existente se ejecuta al publicar, no al seleccionar el canal.

## Analítica

```powershell
.\.venv\Scripts\python.exe microdoc_analytics.py export.csv --output reports/autopsy
.\.venv\Scripts\python.exe microdoc_analytics.py export.csv --all-durations --output reports/pilots --manifest long_form/sr_microdoc_001/experiment.json
```

Sin `--all-durations`, se selecciona la cohorte de 181–300 segundos. Admite encabezados habituales de Studio en inglés/español, CSV/TSV y columnas canónicas. Para correlacionar pilotos, registra `youtube_video_id` en cada manifiesto. `--manifest` se puede repetir, en orden cronológico, para comparar contra el piloto anterior y guardar instantáneas de métricas. Cada CSV debe representar una observación coherente del mismo periodo; las diferencias acumulativas de impresiones no prueban por sí solas expansión de distribución.

Retención opcional: `retention_10s_percent`, `retention_30s_percent`, `retention_60s_percent`. Se preservan valores desconocidos como `null`. CTR de una fuente de tráfico, pruebas A/B y otras anotaciones pueden guardarse como extensiones del manifiesto; el clasificador inicial utiliza CTR agregado y no lo equipara a Browse/Suggested.

La autopsia inicial está en `docs/stunning_revelations_historical_autopsy.md` y `.json`. Deriva exclusivamente de los seis ejemplos del brief adjunto. El CSV de ejemplo deja vacías las duraciones individuales y vistas que no se proporcionaron. No reemplaza una comprobación de los exports originales. Los umbrales son heurísticas; retención intermedia no se clasifica automáticamente como fracaso, y ninguna métrica agregada revela el segundo exacto de abandono.

## Verificación

```powershell
.\.venv\Scripts\python.exe -m unittest test_micro_documentary test_studio_channel_controls test_project_config_persistence test_youtube_uploader_metadata test_daily_short_editorial_focus test_daily_short_dedup test_daily_short_cli_comfy_provider
```

Estas pruebas usan respuestas simuladas para LLM, TTS, render y YouTube; los controles Qt se prueban en modo offscreen. No requieren generar ni publicar videos reales. La validación de un piloto real sigue dependiendo de las credenciales, servicios de imágenes/TTS y FFmpeg instalados.
