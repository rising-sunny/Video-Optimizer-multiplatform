# Contexto para el entorno local: credenciales y activación del VPS

Fecha: 19 de octubre de 2026, America/Santiago.
Repositorio: rising-sunny/Video-Optimizer-multiplatform.
PC local conocida: C:\dev\Video-Optimizer-multiplatform.

Este documento no contiene secretos. Es un encargo para la IA que trabaja en la PC local. No debe confundirse el estado del entorno de nube con el del VPS.

## Objetivo

Preparar y transferir de forma privada las credenciales existentes al VPS, y verificar mediante consultas de lectura las seis cuentas: YouTube, Facebook e Instagram de Stunning Facts of History y Stunning Revelations.

El objetivo posterior es generar autónomamente un short 9:16 diario por canal, en estilo Catarsis, con tarjetas en inglés, fotografías y clips reales, música licenciada y publicación en las tres redes. Esta entrega debe resolver primero autenticación, configuración y persistencia. No activar aún publicaciones, cron, timers ni servicios autónomos.

## Estado confirmado y límites

El usuario accede al VPS desde Termux y ahora dispone también de su PC. Conexión SSH conocida:

    ssh root@5.78.125.169

No se ha comunicado un puerto diferente. Usar los mecanismos SSH ya configurados en la PC; no solicitar ni mostrar contraseñas o claves privadas en chats.

VPS: Ubuntu 24.04, x86_64, aproximadamente 3,7 GiB RAM, 4 GiB swap y 3 CPU. Usuario de ejecución: videoagent.

- Repositorio instalado: /home/videoagent/Video-Optimizer-multiplatform
- Python: /home/videoagent/Video-Optimizer-multiplatform/.venv/bin/python
- Automatización preparada: /home/videoagent/video-automation
- Contexto importado: /home/videoagent/video-automation/context-20261016
- Codex CLI instalado globalmente y autenticado con ChatGPT como videoagent.
- La última comprobación del usuario devolvió `Logged in using ChatGPT` y `PYTHON_OK`.
- El editor Catarsis renderizó y verificó correctamente un MP4 1080×1920, 30 fps, H.264/AAC.
- Existe una base prepare_only con bloqueo, estado, caché musical y QA. No equivale a un agente editorial ni a un programador diario activo.
- La búsqueda más reciente en /home/videoagent, hasta profundidad 5, no encontró token.json, token_stunning-revelations.json, secrets.json, import-map.json, .env ni .env.txt. Es una búsqueda acotada, no una prueba de ausencia de cualquier credencial en todo el servidor. Revalidar el estado antes de instalar.
- La generación y publicación diaria autónoma NO está activada.

Las seis cuentas sí funcionan desde el entorno de nube de esta conversación. Sus secretos están vinculados al proxy de esa plataforma; no son un mecanismo de exportación al VPS. No extraer credenciales del chat o de sus logs. Se deben utilizar los valores reales protegidos de la PC.

## Material local preparado anteriormente

Directorio conocido, fuera de Git:

    C:\Users\sunse\AppData\Local\VideoOptimizer\cloud-credentials\2026-10-15-preparation

Archivos esperados:

- import-map.json: asociaciones y configuración sin valores secretos de tokens.
- audit_safe.json y bundle_validation.json: resultados de comprobaciones previas.
- confidential\token.json: OAuth de Stunning Facts of History.
- confidential\token_stunning-revelations.json: OAuth de Stunning Revelations.
- confidential\secrets.json: valores únicos de Meta y Cloudinary.

La carpeta estaba protegida mediante ACL para el usuario Windows y SYSTEM. Comprobar que sigue protegida. No imprimir contenido confidencial ni copiar el .env completo.

Las identidades, scopes y renovaciones se comprobaron el 15 de octubre. Esa evidencia es histórica; validar el estado actual. La caducidad breve del access token de YouTube no significa por sí sola que el refresh token haya dejado de funcionar.

## Identidades y nombres de configuración

| Canal | Perfil | YouTube | Página Facebook | Instagram profesional |
|---|---|---|---|---|
| Stunning Facts of History | stunning-facts-of-history | UCXQ1_6A-JkBeQsMkiDcunGA | 1291553907375982 | 17841437696497761, @stunning.foh |
| Stunning Revelations | stunning-revelations | UC66EnGiys6V3gKe-J0XD-_Q | 533073909895353 | 17841472326324371, @stunning.revelations |

### YouTube

El código conocido asocia los perfiles a estos nombres, dentro de la raíz del proyecto:

- /home/videoagent/Video-Optimizer-multiplatform/token.json
- /home/videoagent/Video-Optimizer-multiplatform/token_stunning-revelations.json

Confirmar la resolución real con channel/channel_profiles.py en la versión del VPS antes de instalar. No utilizar token.json para Stunning Revelations.

Los archivos autorizados contienen refresh token y cliente OAuth. El proceso necesita su contenido real, no placeholders. Deben ser escribibles por videoagent para guardar renovaciones y mantenerse entre reinicios y despliegues. No sobrescribirlos con una copia inicial antigua al arrancar. No hace falta client_secrets.json para renovar estas autorizaciones existentes, salvo que una comprobación actual demuestre lo contrario.

### Meta

Resolver los nombres nativos a través del mapa real existente; no introducir las referencias secret_XX como si fueran tokens.

| Variable nativa | Referencia histórica en confidential\secrets.json |
|---|---|
| FACEBOOK_PAGE_ACCESS_TOKEN_STUNNING_FACTS_OF_HISTORY | secret_01 |
| INSTAGRAM_USER_ACCESS_TOKEN_STUNNING_FACTS_OF_HISTORY | secret_02 |
| FACEBOOK_PAGE_ACCESS_TOKEN_STUNNING_REVELATIONS | secret_03 |
| INSTAGRAM_USER_ACCESS_TOKEN_STUNNING_REVELATIONS | secret_02 |

Los dos bindings de Instagram compartían el mismo token. Mantener ambos nombres de configuración y sus páginas propias. Confirmar las asociaciones en import-map.json; el archivo existente prevalece sobre esta tabla si ha cambiado.

Variables no secretas:

    FACEBOOK_PAGE_ID_STUNNING_FACTS_OF_HISTORY=1291553907375982
    INSTAGRAM_PAGE_ID_STUNNING_FACTS_OF_HISTORY=1291553907375982
    FACEBOOK_PAGE_ID_STUNNING_REVELATIONS=533073909895353
    INSTAGRAM_PAGE_ID_STUNNING_REVELATIONS=533073909895353
    VPS_UPLOAD_ENABLED=0
    INSTAGRAM_UPLOAD_MODE=resumable

No depender de respaldos globales de Meta que puedan mezclar canales. INSTAGRAM_PAGE_ID contiene el ID de la página Facebook vinculada, no el ID profesional de Instagram.

### Cloudinary

El mapa histórico contiene:

- CLOUDINARY_CLOUD_NAME en settings.CLOUDINARY_CLOUD_NAME.
- CLOUDINARY_API_KEY → secret_04.
- CLOUDINARY_API_SECRET → secret_05.

Confirmar las asociaciones reales. Cloudinary se usa para portadas propias y respaldo por URL. El video directo de Instagram puede funcionar sin él, pero no todos los flujos quedan habilitados así. La versión conocida usa HTTP Basic hacia api.cloudinary.com: en el VPS debe recibir valores reales y protegidos.

## Trabajo solicitado a la IA local

1. Leer las instrucciones aplicables del repositorio y revisar el material preparado sin mostrar secretos. No volver a preparar todo si ya es suficiente.
2. Comprobar el acceso SSH autenticado al VPS con verificación normal de su clave de host. Si la clave cambió, investigar antes de aceptarla; no desactivar StrictHostKeyChecking.
3. Inspeccionar de forma acotada el estado del usuario videoagent, las rutas, la versión del repositorio, los perfiles y la carga de configuración. No leer archivos de proyectos ajenos en /opt o /root para buscar secretos.
4. Si hay autorizaciones o configuración existentes, preservar sus asociaciones y resolver posibles conflictos antes de sustituir archivos. No sobrescribir a ciegas.
5. Transferir por SCP/SFTP sobre SSH solamente los archivos necesarios a una carpeta privada nueva. No usar GitHub, releases, correo, chat, URLs públicas ni ZIP sin cifrar para mover secretos.
6. Resolver import-map.json contra confidential/secrets.json sin imprimir valores. Materializar la configuración que realmente carga el programa del VPS. El loader conocido prioriza variables del proceso, después .env y después .env.txt; confirmar el comportamiento actual. Un .env puede ser adecuado si está excluido de Git y protegido; no guardarlo en unidades systemd, argumentos de comandos, historial ni logs con valores visibles.
7. Instalar los OAuth en las rutas verificadas, con propietario videoagent y modo 0600. Usar directorios privados 0700 donde corresponda. Confirmar también permisos de las copias temporales y de seguridad. Comprobar con git check-ignore y git ls-files que los secretos no están ni quedarán versionados. No cambiar permisos de todo el repositorio indiscriminadamente.
8. Ejecutar las validaciones como videoagent, con el Python de su venv y la configuración efectiva que utilizará el proceso diario. No validar solo desde root o desde una sesión con variables que luego no tendrá el servicio.
9. Renovar OAuth si corresponde y comprobar identidades y scopes de YouTube; comprobar páginas, cuentas profesionales vinculadas y permisos de Meta mediante lecturas. Comprobar Cloudinary mediante una consulta de uso/autenticación, sin subir recursos. No mostrar tokens en errores, cabeceras, URLs de paginación ni respuestas completas.
10. Confirmar que los OAuth renovados se guardan con permisos correctos, que la configuración se puede cargar desde un proceso nuevo y que un reinicio/despliegue no la elimina. No reiniciar todo el VPS para demostrarlo.
11. Entregar un informe sin secretos con el resultado por cuenta, rutas y permisos, pruebas realizadas, configuración aplicada y pendientes. No afirmar que una lectura valida una subida real.

Cuando el usuario solicite ejecutar esta fase, su alcance propuesto es la transferencia privada al VPS y la configuración reversible necesaria para estas comprobaciones. No autoriza nuevas publicaciones, pruebas de subida, borrados de contenido remoto, revocación de autorizaciones, ampliación de permisos ni activación de la automatización diaria. No modificar el funcionamiento original de la PC ni hacer commits/push con secretos. Si una credencial existente no sirve, explicar el resultado seguro y el paso oficial que hace falta; no pedir su valor por chat.

## Conectividad que debe comprobarse

HTTPS/443, con TLS verificado, a los endpoints que utilice el cliente:

- oauth2.googleapis.com
- youtube.googleapis.com
- www.googleapis.com
- graph.facebook.com
- graph-video.facebook.com
- rupload.facebook.com
- api.cloudinary.com
- res.cloudinary.com para medios públicos

Validar también los destinos de carga que devuelvan las APIs. accounts.google.com solo se necesita si hace falta una nueva autorización interactiva oficial. No desactivar TLS, el firewall ni el sandbox de Codex para resolver errores de conectividad.

## Generación y siguiente fase

No se ha identificado otra API key obligatoria para el flujo Catarsis actual de tarjetas, medios reales y música. El render local ya funciona. Codex está autenticado con ChatGPT en el VPS, sujeto a la vigencia de la sesión y los límites del plan. Esa sesión no sustituye una API key para módulos del repositorio que llamen por su cuenta a proveedores de IA.

Después de verificar las seis identidades, revisar /home/videoagent/video-automation/NEXT_PHASE.md y el estado existente antes de diseñar el agente y los temporizadores. La base anterior bloqueaba publicación deliberadamente: no quitar esa protección sin implementar la fase de publicación, sus controles y su autorización correspondiente.

La fase posterior debe incluir selección editorial, investigación, medios con licencias, revisión visual, QA técnica, persistencia, ejecución secuencial compatible con la RAM del VPS y reintentos con reconciliación de IDs. Si falta evidencia o falla un control, detener ese video y registrar el motivo.

## Publicaciones recientes: evitar duplicados

Además de consultar el historial remoto vigente, conservar estos recibos conocidos. Son publicaciones confirmadas desde nube, no desde el VPS:

| Canal / tema | YouTube | Facebook | Instagram |
|---|---|---|---|
| History — Operation Pedestal | yKqCNggRiQk | 1623166856254881 | 18137849542715588 |
| Revelations — Phoenix Lights | THQDwFb5_hw | 1839595697032214 | 17913347832550154 |
| History — Nicholas Winton | -MyPkSTwZYw | 1111883001428099 | 18143523550565473 |
| Revelations — Acoustic Kitty | 8bSKxMfllbk | 1643493147429302 | 18118882528761287 |
| History — Desmond Doss | Hz5VFbkb7gE | 1140413125007799 | 17908389483560008 |
| Revelations — Starfish Prime | mvgGXbPompA | 1476567577719643 | 18022901423926494 |

Existe además el documental B-59 en YouTube, ID COIdhPZtR10, en Stunning Revelations: subido privado y programado para el lunes 26 de octubre de 2026, 19:00 America/Santiago (22:00 UTC). Miniatura y subtítulos ingleses verificados. No volver a subirlo ni cambiar su programación durante esta tarea.

Esta tabla es contexto parcial, no reemplaza el historial completo ni los recibos ya importados del día 1. No reiniciar el calendario como si el canal estuviera vacío, no recuperar atrasos automáticamente y no producir fechas futuras sin las reglas acordadas.

## Informe de vuelta a la nube

Generar un Markdown compartible sin secretos que indique:

- Resultado de identidad/autenticación de cada una de las seis cuentas y fecha de verificación.
- Si se verificaron scopes/permisos y qué parte no pudo comprobarse.
- Cloudinary: autenticación verificada o pendiente.
- Rutas instaladas, propietario y permisos; exclusión de Git.
- Carga de configuración desde un proceso nuevo y conservación de renovaciones.
- Versión/commit del código instalado y cambios locales de configuración, sin valores secretos.
- Estado real del agente y los temporizadores: todavía desactivados en esta fase.
- Pendientes concretos para implementar y probar el flujo diario.

No incluir tokens, client secrets, claves privadas, archivos OAuth, dumps de entorno, URLs firmadas ni enlaces que contengan credenciales. Compartir el informe; conservar el material confidencial en la PC y el VPS protegidos.
