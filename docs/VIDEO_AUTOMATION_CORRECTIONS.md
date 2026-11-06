# Correcciones del flujo de Video Automation

Registro consolidado el 6 de noviembre de 2026. Los instaladores históricos se
conservan en `deliveries/`; el índice legible por máquina es
`automation/documentary/workflow-corrections.json`. La instalación de esta
consolidación requiere un recibo de la VPS; un commit por sí solo no demuestra
que el servidor haya ejecutado nada.

## Resultado verificado más reciente

Chrome Dome, job `d1da2fe6dfb746e09694bb2129ff6f80`, quedó publicado en
Stunning Revelations: https://www.youtube.com/watch?v=B8QPUmNCfCY .
La continuación final reutilizó el vídeo existente, con cero nuevas cargas y cero
llamadas de IA; confirmó miniatura y subtítulos ingleses antes del readback público.

## Historial de correcciones

| Entrega | Problema y mejora conservada | Aplicación |
| --- | --- | --- |
| v23 | Descargas reanudables, reutilización de investigación y diagnósticos de transferencias. | Infraestructura general; la continuación del vídeo viejo era específica. |
| v24–v25 | Correcciones editoriales acotadas y compactas; conservar segmentos no afectados, fuentes y presupuestos. | General con recuperaciones autorizadas por job. |
| v26–v27 | Encuadre de archivo y revisión visual tras recuperación de cuota. | Encuadre general; el intento adicional era específico y ya consumido. |
| v28.2 | Vídeos reales, música con ducking, SFX y transiciones; conservar narración y número de fotogramas. | Revisión audiovisual; la primera versión falló sus pruebas y fue sustituida. |
| v29 | Rótulos de contexto claros con audio AAC y tiempos conservados. | Mejora general y corrección del vídeo concreto. |
| v31 | Catarsis horizontal, montaje por planos, arco musical y SRT separado; miniatura proporcionada aparte. | Flujo horizontal. |
| v32 | Decodificar toda la imagen antes de usarla; reanudar desde planos ya completados. | Validación general; continuación de Goldsboro específica. |
| v33 | Rótulos breves, fuentes pertinentes y conservación de audio/movimiento. | Presentación general y corrección local. |
| v34–v35 | Catálogo de medios verificado antes de pedir el plan y preservado en el contexto editorial. | Shorts generales. |
| v36–v37 | Planes locales validados por el motor y vínculo con el tema original completo. | Herramienta y continuación del lote concreto. |
| v38.1 | MP4 sin capítulos/pistas de datos extra; remux sin recodificación; inspección con el UID propietario. | Codificación general y recuperación del par concreto. |
| v39 | Reutilizar revisiones textuales positivas vinculadas a sus entradas; evaluar la presentación real de imágenes fijas. | Recuperación del par concreto, no autorización universal. |
| v40 | Revisar todo el historial mediante particiones completas. | General. |
| v41 | Fuentes factuales públicas alternativas, acotadas y con snapshots/recibos verificados. | General; continuar SL-1 requería su job exacto. |
| v42 | Normalizar campos formales de recursos contra el catálogo, sin inventar licencias ni IDs. | General. |
| v43 | Selección musical de documental, tensión y subida épica; revisión sólo del audio. | Perfil general y revisión específica de SL-1. |
| v44.4 | Reparación JSON sintáctica acotada, tiempos nativos, guardas de fuentes y fixtures de prueba con permisos privados correctos. | General y continuación Balto/Indianapolis. |
| v45–v46 | Consumir correctamente respuestas positivas guardadas, fragmentos con movimiento antes del grano y listas JSON de créditos/encuadre. | General; conservar los fallos de pruebas iniciales como historial. |
| Chrome Dome v1–v3 | Recuperar fuentes válidas; dividir segmentos conservando narración; completar referencias editoriales; corregir tipo imagen/vídeo desde el archivo ofrecido. | Recuperación específica. Las referencias de planos requieren pertinencia editorial, no asignación arbitraria. |
| Chrome Dome v4 | Preparar y documentar música real antes de la revisión textual; reutilizar recibos, no una afirmación de licencia. | Orden del worker general; resolver el dictamen antiguo era específico. |
| Chrome Dome v5 | Medir duración y movimiento de clips originales; aceptar archivo SD documentado, conservar proporción y rotular su resolución. | Módulos generales de medios y montaje; reanudar ese render era específico. |
| Chrome Dome v6 | Consultar cuota real antes de conceder un único nuevo intento visual sobre el mismo vídeo. | Recuperación específica, ya consumida. No convertir un fallo de cuota en aprobación. |
| YouTube v1–v2 | Recibo persistente, sesión de carga reanudable, ID conservado, espera de procesamiento, manejo preciso de `captionNotFound`, pista inglesa y publicación al final. | Núcleo probado y adaptador permanente para futuros documentales. |

## Reglas para los siguientes vídeos

1. Consultar el estado y los recibos actuales. Los mensajes `accepted`, un servicio
   terminado o un MP4 existente no prueban aprobación ni publicación.
2. Revisar historial completo y conservar el catálogo oficial en el contexto del
   editor. Respetar los límites ya fijados; no reiniciar contadores por un error.
3. Validar el plan antes de narrar: referencias de recursos presentes, tipo real,
   rótulos pertinentes y breves, segmentos y cantidad de palabras dentro del
   contrato. Una recuperación escrita para otro tema no sirve como normalizador universal.
4. Abrir imágenes completas y medir clips reales antes de seleccionarlos para el
   timeline. El movimiento, la duración o el formato no se deducen del nombre.
5. Preparar música y acreditar el alcance de la cuenta antes de revisar derechos.
   Mantener suspense documental y un arco musical que acompañe el tema sin tapar la voz.
6. Reutilizar planos, narración, descargas, música y SRT cuando sus hashes y sus
   entradas siguen siendo los aprobados. La revisión visual evalúa los materiales
   corregidos, no unas hojas de fotogramas antiguas.
7. Mantener la distinción entre generación, revisión y publicación. Una generación
   aprobada no concede por sí sola permiso para publicar en otras redes.

## Publicación permanente en YouTube

Tras instalar la consolidación, el punto de entrada de la VPS es:

```text
/usr/local/sbin/video-documentary-youtube
```

El asistente debe obtener del estado del documental su job y el SHA256 de
aprobación, y usar la miniatura final elegida. El publicador lee el título y la
descripción completos del archivo aprobado; no los vuelve a generar ni recorta créditos.

```bash
video-documentary-youtube \
  --job-id JOB_ID \
  --approval-sha256 SHA256_DE_LA_APROBACION \
  --thumbnail-url URL_HTTPS_DE_LA_MINIATURA_PNG_1280x720 \
  --inspect
```

`--inspect` sólo verifica archivos locales. Con la publicación del documental
autorizada, se usa el mismo comando con `--publish`. Para una continuación se
utiliza `--resume-existing --video-id ID_GUARDADO`, manteniendo el mismo job,
aprobación, miniatura y recibo. Los tags son los de metadata o los `--tag` explícitos;
no se heredan los de Chrome Dome ni se solicitan nuevas llamadas de IA.

El motor carga primero en privado, guarda la sesión antes de enviar bytes, consulta
el desplazamiento del servidor al reanudar y guarda el ID remoto inmediatamente.
Las operaciones ambiguas bloquean antes de crear otra carga. La miniatura elegida
debe ser PNG de 1280×720; se prepara dentro del límite real de YouTube.

Se espera `uploadStatus=processed` antes de operar con subtítulos. Únicamente un
HTTP 404 con razón `captionNotFound` se interpreta como pista ausente o todavía
no visible. No se ocultan errores de permisos, vídeos inexistentes ni otros fallos.
Un ID de pista conocido nunca provoca una segunda inserción. Sólo se publica al
confirmar el ID, idioma y nombre esperados y `status=serving`; después se verifica
que el vídeo esté público en el canal correcto y con los metadatos aprobados.

## Persistencia y privacidad

La consolidación copia documentación y herramientas permanentes, crea un archivo
de fuentes Python declaradas del runtime y compara nueve módulos clave con los
ejemplares entregados. No cambia `/opt/video-agent-mcp`, no consume cuotas,
no genera ni publica y no habilita temporizadores. Cualquier diferencia en las
fuentes instaladas se registra para revisión, conservando la versión existente.

Los recibos de publicación quedan en
`/home/videoagent/video-automation/runtime/manual-documentary-publication/JOB/`.
Contienen la URI privada de la sesión y permanecen con permisos 0600: no copiarlos
al repositorio ni mostrarlos completos. Tampoco guardar credenciales, cookies,
tokens OAuth, enlaces firmados de descarga, auth de Codex ni configuración secreta.

Las fuentes de referencia no son un instalador para sustituir todo el runtime.
Las recuperaciones que autorizaban intentos adicionales siguen limitadas a sus
jobs originales; archivarlas no concede intentos nuevos.
