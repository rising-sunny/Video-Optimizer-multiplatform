# Miniaturas de los Shorts automáticos

El generador usa un fotograma del MP4 validado, el título del episodio y el avatar original del canal. Produce un JPEG vertical de 1080 × 1920. Los cuatro publicadores comprueban que su portada está preparada antes de iniciar la subida a YouTube.

| Canal | Portada persistente en la VPS |
| --- | --- |
| The Daily Lab | `/var/lib/one-rule-lab/covers/<episodio>.jpg` |
| MathRelaxing | `/var/lib/mathrelaxing-auto/covers/<id>.jpg` |
| Stunning Facts of History | `/home/videoagent/foh-daily/days/<fecha>/youtube-short-cover.jpg` |
| Nostalgic Mood | `/home/videoagent/nm-daily/days/<fecha>/youtube-short-cover.jpg` |

`sudo ./install.sh` instala el generador, los parches de los publicadores y el temporizador de conciliación. Conserva la fecha de primera activación y verifica los parches antes de sustituir los archivos de producción.

Cada dos minutos, el servicio lee los identificadores emitidos por los publicadores. Verifica la cuenta, el propietario del video, la fecha de publicación, la visibilidad pública y que YouTube haya terminado de procesar el Short. Guarda la aceptación de `thumbnails.set` en `/var/lib/youtube-short-covers/receipts.sqlite`. Cuando la API falla, guarda el error y reintenta la miniatura del mismo ID. La fecha de activación excluye publicaciones anteriores. Las credenciales se leen de los publicadores existentes.

Para consultar el estado local, ejecutar `/opt/mathrelaxing-publisher/venv/bin/python -B /opt/youtube-short-covers/reconcile.py --status`. Las pruebas de procesamiento, identidad, caché y recuperación se ejecutan con `/opt/mathrelaxing-publisher/venv/bin/python -B -m unittest test_covers` desde esta carpeta.
