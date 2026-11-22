# Automatizacion — The Lost Atlas (@TheLostAtlas-Trivia): un Short de quiz por dia
- Cron **todos los dias 17:00 UTC** (+ reintentos 18:00 y 19:00, idempotentes): preguntas verificadas -> render `lostatlas` (~2,5 min) -> QA -> YouTube publico -> limpieza.
- Plantilla del dia rota por fecha: **geo** (adivina el pais por su contorno) -> **year** (adivina el ano) -> **empire** (adivina el imperio en un mapa historico).
- **Hechos:** cada pista se escribe solo con extractos de Wikipedia y se verifica con un segundo paso (DeepSeek como juez, cita literal comprobada por codigo).
  Si no se logran 5 preguntas verificadas, **el dia se salta** (sin recuperar atrasos). Estado de entidades usadas: `state.json` (cooldown geo 60 d, empire 25 d, year: nunca se repite).
- **Musica:** una pista distinta cada dia (12 de Incompetech CC BY 4.0, `lostatlas/music_pool.py`); la atribucion se agrega sola a la descripcion. Si llega un reclamo de Content ID,
  poner el titulo del tema en `lostatlas/data/music/claims.json` y deja de rotar.
- **Metadatos:** titulos/tags/descripcion segun vidIQ (2026-11-22), en `lostatlas/publish_pack.py`. La descripcion lista las respuestas (palabras clave de busqueda).
- Detener: `touch ~/tla-daily/STOP` (borrarlo para reanudar). Recibos: `days/<fecha>/receipt.json`. Log: `logs/tla.log`.
- Probar sin publicar: `python run_day.py --date AAAA-MM-DD --dry-run` (deja las preguntas y el video listos; el cron real los reutiliza).
- Autorizacion YouTube: `token_the-lost-atlas.json` (ver `authorize_channel.py`). Solo YouTube. Presupuesto DeepSeek: tope diario del `.env`.
