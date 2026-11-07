# Publicación autorizada: Skylab

Solicitud del usuario: «Bien, sube el vídeo». Alcance: el documental aprobado de Skylab en YouTube, Stunning Revelations, con la portada entregada, SRT inglés y metadatos/créditos completos. No genera ni publica en otras plataformas.

Job: `51c0cfdb56e743d88c68859e5b6df165`.
Approval SHA256: `049724008ad43e4cf42d8bed9a1ff8ea994213b119d725ea2c7d4fb2eee4742b`.
Video SHA256: `60d35a45c8a75634e42d46560a33ed8c7cbcba9ecf0f4dcfecf988989cfbb326`.
Thumbnail SHA256: `64011b446d2a89ec2edc5bb4612c0d559c9d96985e762780bf696a80cb8054ba`.

El conector disponible no ofrece publicación de documentales, y su mantenimiento está limitado a generación. El entorno Cloud no tiene credenciales SSH, VPN ni OAuth de YouTube. La preparación en el repositorio no significa que el servidor ejecutó una carga.

El lanzador del propietario ejecuta el publicador probado bajo `videoagent` y systemd. Verifica archivos y canal, revisa duplicados, carga en privado, conserva la sesión y el ID, aplica la miniatura JPEG exacta y espera que el SRT esté sirviéndose antes de hacer público el vídeo. Repetir el mismo lanzador reutiliza sus recibos; los estados ambiguos bloquean antes de crear otra carga.

El soporte nuevo de `--thumbnail-file --thumbnail-sha256` mantiene los bytes de la imagen elegida, evita URLs temporales y admite JPEG/PNG reales dentro del límite de 2 MiB. La comprobación local no solicita credenciales ni publica. Los cambios del publicador están probados junto con los casos existentes de `captionNotFound`, procesamiento asíncrono, continuidad por ID y metadatos completos.

El adaptador y núcleo se ejecutan desde un paquete privado con hashes comprobados. El lanzador no cambia los módulos de generación, sus presupuestos, los temporizadores o las cuentas. Los recibos privados de publicación permanecen en la VPS; no se guardan sesiones, credenciales o tokens en este repositorio.
