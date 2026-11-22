# Barredor de videos publicados

Pedido del usuario (2026-11-22): **cada video ya publicado en cualquiera de sus canales se borra de la VPS** para no ocupar disco
(la VPS comparte disco con el sistema de pedidos de thebookswanderer.com; el monitor avisa al pasar del 90 %).

- `python automation/published-cleanup/sweep.py` simula y escribe el manifiesto; `--apply` borra. Cron diario 04:30 UTC con `--apply`.
- **Prueba por video:** YouTube debe confirmar ahora `public`/`unlisted` + `processed` (token del canal dueño). Un Short programado y todavia privado NO cuenta.
  En jobs de `video-automation` ademas TODAS las plataformas de `publication.json` deben estar `published` (si Instagram sigue `uploading`, se conserva).
- Solo archivos de video/audio (.mp4 .mov .mkv .webm .avi .m4v .wav). Nunca JSON, miniaturas ni material crudo (footage, clips, music, img, blender_cache).
- Excluye: archivos modificados hace < 6 h, variantes `_ig/_fb/_reel`, enlaces simbolicos, y archivos que otro JSON NO historico nombre por su ruta.
- Sin registro de publicacion no se toca (p. ej. `runtime/manual-documentary`, `james-caird-1916`, proyectos sin `upload_result.json`).
- Registro: `~/published_cleanup/deleted.log` (ruta, bytes, sistema, id de YouTube) y `~/published_cleanup/manifest-<fecha>.json`.
- Detener: `touch ~/published_cleanup/STOP` (borrarlo para reanudar).
- Un video borrado se recupera desde YouTube Studio (Contenido -> ... -> Descargar) o regenerandolo desde sus fuentes, que se conservan.
