# SEO basado en investigación: el playbook para portarlo a otra app

Qué se construyó en **Video Optimizer** (canal *Stunning Facts of History*, septiembre 2026)
para que título, tags, miniatura y metadata de YouTube, Facebook e Instagram salgan de
**datos de búsqueda y de competencia**, no de pedirle a un LLM "15 tags muy buscados".
Está escrito para reusar la idea en otra app parecida: cada sección explica la regla, por
qué existe (casi siempre un error real que pasó) y dónde está el código de referencia.

---

## 0. Los principios, en una pantalla

1. **Una sola investigación por video**, reusada por todo: tags, título, texto de la
   miniatura, Facebook e Instagram. Se paga la cuota una vez.
2. **La demanda sale del autocompletado de YouTube** (lo que la gente escribe) y **la
   competencia sale de los videos que ya rankean** para esa búsqueda (sus tags, títulos y
   miniaturas). El LLM propone; los datos deciden.
3. **Todo lo que se publica es una afirmación sobre el video**: cada palabra de un tag,
   hashtag, título o texto de miniatura tiene que estar respaldada por el guion.
4. **Puntaje explicado**, al estilo del "title score" de vidIQ: cada candidato trae sus
   partes y sus motivos, y el panel muestra por qué ganó.
5. **El usuario manda**: si el texto lo escribió una persona, se respeta y solo se sugiere
   la alternativa (modo `suggest`). Si lo inventó la app, se optimiza (modo `optimize`).
6. **Verificar lo que la plataforma GUARDÓ, no lo que se mandó** (tags guardados,
   miniatura servida, portada preferida).
7. **Nada falla en silencio**: cada paso informa al panel. Un fallo de SEO o de miniatura
   nunca tumba la publicación.
8. **Cada arreglo lleva su guarda**: una función pura y un test que falla con el código
   viejo, con el caso real en el comentario.

---

## 1. Arquitectura

```
                    tema + título borrador + guion
                               │
                    gather_research()  (1 vez por video, ~101 unidades de cuota)
          ┌────────────────────┼─────────────────────────────┐
  autocompletado YT     search.list + videos.list      sujeto / entidades / corpus
  (gratis, demanda)     (top 15: tags, títulos,         (palabras del guion y el tema)
                         vistas, miniaturas)
          └────────────────────┼─────────────────────────────┘
                               ▼
        research = {keyword, subject, entities, corpus, suggestions,
                    suggest_ranks, competitors, sources_ok}
     ┌──────────────┬──────────────┼───────────────┬───────────────────┐
research_tags   optimize_title   thumbnail brief   facebook_metadata   instagram
 (500 car.)     (puntaje +        (color, brillo,   (título, 125 car.,  (caption =
                 verificación)     texto)            hashtags)           título + cuerpo)
```

La investigación se encadena entre redes dentro de la misma tanda de publicación:
**YouTube → Facebook → Instagram**. Cada red deja en su resultado lo que usó
(`title_sent`, `tags_sent`, `research_used`) y la siguiente lo reusa sin volver a investigar.

---

## 2. Capa 0: la investigación (`youtube_tags.gather_research`)

**Fuentes**
- Autocompletado de YouTube, gratis y sin cuota:
  `https://suggestqueries.google.com/complete/search?client=firefox&ds=yt&hl=en&q=<consulta>`
- Competencia: `search.list` (100 unidades) + `videos.list` (1 unidad). Da título, canal,
  vistas, **tags** y miniatura de los videos de otros canales que rankean.

**Sujeto y consultas semilla** (`subject_token`, `seed_queries`)
- Sujeto = el primer nombre propio del tema (`kaiten`, `castle bravo`, `pompeii`).
- Semillas = el tema limpio, el título, 3 entidades del guion, y **el sujeto combinado con
  una palabra que lo desambigua** (una palabra del guion cercana al sujeto, y `<sujeto> history`).
- Por qué: el autocompletado de `kaiten` a secas devuelve un videojuego. `kaiten torpedo`,
  `kaiten suicide` y `kaiten history` devuelven lo que se busca sobre el tema real.

**Palabra clave principal** (`pick_main_keyword`)
- Tiene que ser una sugerencia REAL del autocompletado, y **todas sus palabras tienen que
  estar en el guion o el tema**.
- Se descartan juegos, películas y series con un regex de medios (`_MEDIA_RE`).
- Se prefieren las sugerencias que nombran al sujeto (bonus ×1.6).
- Puntaje de especificidad según la cantidad de palabras:

  | Palabras | 1 | 2 | 3–4 | 5 | 6+ |
  |---|---|---|---|---|---|
  | Factor | 0.3 (ambigua) | 0.9 | 1.0 | 0.9 | 0.6 |

- Resultado real: Hannibal → `hannibal crossing the alps`, Kaiten → `kaiten torpedo`,
  Pompeii → `plaster casts of pompeii`.

**Tokens**: minúsculas, sin posesivo (`'s`), plural simple a singular, sin stopwords. El
"corpus" es el conjunto de tokens de tema + título + guion. Contra ese corpus se valida todo.

---

## 3. Tags de YouTube (`youtube_tags.py`)

### Lo que estaba roto (auditando los tags GUARDADOS de 33 videos con la Data API)
- 6 videos sin ningún tag.
- Un "tag" gigante, porque el campo se partía solo por comas.
- Hashtags usados como tags (`#shorts`, `MongolCatapults`).
- Relleno fijo (`documentary`, `history`).
- `tags[:500]` recortaba 500 **tags**, no 500 caracteres, y metía `Shorts` primero.

### La puerta final (`finalize_youtube_tags`), por la que pasa todo camino de subida
- **500 caracteres contados como los cuenta YouTube**: las comas entre tags cuentan, y un
  tag con espacios suma 2 (YouTube lo guarda entre comillas).
- Normaliza a ASCII en minúsculas. Separa CamelCase y hashtags. Parte por comas, punto y
  coma o saltos de línea (`split_tag_field`).
- Descarta basura (`shorts`, `viral`, `fyp`, años sueltos, `subscribe`…), tags de más de
  60 caracteres o 7 palabras, y duplicados.
- Conserva el orden de relevancia, no el alfabético. Si un tag no entra en el presupuesto,
  prueba con los siguientes, que pueden ser más cortos.

### Puntaje de candidatos (`research_tags`)
```
puntaje = 1.5 × rango_en_autocompletado            # demanda (0..1)
        + 1.0 × min(1, peso_competencia / 6)       # Σ log10(vistas+10) por canal distinto
        + 0.4  si lo usan ≥2 canales                # consenso
        + 0.25 si venía en el borrador              # LLM / Metadata Studio
        + 0.5  si contiene la palabra clave
        + 10   si ES la palabra clave
```

### Filtros (cada uno nació de un caso real)
| Regla | Caso que la originó |
|---|---|
| Fuera nombres de canales ajenos (marcas) | `history hit youtube`, `oversimplified` |
| Fuera juegos, películas y series | `world of warships`, `total war rome 2` |
| Todas las palabras en el guion, salvo consenso FUERTE (≥3 canales) con la mitad en el guion | con 2 canales se coló `hannibal lecter` |
| Una palabra suelta solo si es un nombre propio completo del guion o el sujeto | `blast`, `castle`, `japanese` no traen a nadie |
| Casi duplicados: mismo conjunto de tokens (`frozenset`), gana el mejor | `japanese submarine` / `japanese submarines` |
| La marca propia tiene lugar reservado al final | se caía cuando el presupuesto se llenaba |

**Después de subir**: `videos.list` lee los tags que YouTube GUARDÓ. Si difieren de los
enviados, se avisa en el panel. El resultado guarda `tags_sent`, `tags_stored` y la
evidencia de cada tag (rango, canales, vistas).

---

## 4. Títulos (`youtube_titles.py`)

### Candidatos
1. El borrador (del usuario o del LLM).
2. El borrador con la palabra clave al frente, sin repetir palabras.
3. Unos 10 del LLM, con TODO el contexto: la palabra clave, las búsquedas secundarias, los
   títulos que rankean (para diferenciarse, no para copiar), los ganadores propios, las
   plantillas del ángulo y el guion **como única fuente de cifras**.
   Con modelos que razonan (gpt-oss), el modo JSON puede volver vacío: se usa
   `max_tokens=8192` y, si falla, se reintenta en modo texto, un título por línea.

### Puntaje determinístico (0–100)
| Parte | Puntos |
|---|---|
| Base | 12 |
| Contiene la búsqueda exacta | 30 (15 si solo nombra al sujeto) |
| La búsqueda va al principio | 15 (5 si va después; 8/3 si es solo el sujeto) |
| Largo en la franja visible (Shorts 40–55, largos 50–70) | 20 (10 cerca, 0 lejos) |
| Cifra respaldada por el guion | 10 |
| Búsquedas secundarias que agrega | hasta 8 (4 cada una) |
| Encaja con el ángulo elegido | 5 |
| Title Case (no se pueden verificar los nombres) | −4 |

**Penalizaciones**
- −15 por palabra que "murió" en el canal (medido: `mystery`, `curse`, `unexplained`).
- −15 por apertura prohibida (`Uncovering the`, `Discover the truth`).
- −15 si es casi igual (≥72 %) a un título que ya rankea.
- −10 por emoji. −10 por hashtag en el título.
- −5 por palabra en MAYÚSCULAS (máximo −10).
- −6 por palabra repetida.

### Invalidan el candidato (no puede ganar)
- **Una cifra sin respaldo, o con otra unidad**: `30 km` de ceniza no respalda
  `30 eruptions`. Si en cualquiera de los dos lados la cifra es una medida (km, kg, horas,
  años…), la unidad tiene que coincidir. Entre sustantivos no se juzga:
  `100 were launched` sí respalda `100 suicide subs`.
- **Un nombre propio que el guion no menciona** (`Napoleonic`). En sentence case la
  mayúscula marca los nombres; en Title Case no se puede, por eso ahí solo resta 4.
- **No pasa la verificación de hechos del LLM**:
  - antes de elegir, un LLM revisa los 4 mejores candidatos contra el guion (hasta 2 rondas);
  - el borrador del usuario entra siempre en la primera tanda;
  - atrapó *"Plaster casts of Pompeii hold bodies…"*, cuando el video dice justamente que
    NO son cuerpos. Ninguna regla determinística lo agarraba.
- Más de 100 caracteres.

### Elección
- `optimize`: cambia el título solo si el mejor le gana al borrador por **5 puntos o más**.
- `suggest`: deja el del usuario y reporta la mejor alternativa con su puntaje. Si el título
  del usuario no pasó la verificación, lo avisa.
- Resultados en vivo: Hannibal 65→95, Kaiten 54→91, Pompeii 38→87.

---

## 5. Miniaturas

### 5a. Que la miniatura llegue de verdad (`thumbnail_publish.py`)
| Problema real | Regla |
|---|---|
| El selector aceptaba `.webp` y el uploader solo buscaba png/jpg: se publicaba sin miniatura y sin decir nada | Detectar el formato por el CONTENIDO y convertir a JPEG |
| `thumbnails.set` tiene tope de 2 MB, JPEG/PNG | Recomprimir o escalar hasta que entre; avisar si el lado corto tiene menos de 640 px |
| Se pedía en el mismo instante en que terminaba la subida, sin reintento | Reintentos a los 8 s y a los 20 s; clasificar el error (403 → verificar el canal, 400 imagen inválida, 429 cuota) |
| El panel decía "publicado" aunque la miniatura fallara | `thumbnail_set` / `thumbnail_error` en el resultado y aviso en el panel |
| No se podía auditar qué imagen se mandó | Guardar `thumbnail_sent` |

**Verificación posterior**: se baja `i.ytimg.com/vi/<id>/maxresdefault.jpg` y se compara
con la local por *average hash* 16×16 (umbral 0.22). En un Short, YouTube sirve un 16:9 con
la miniatura al centro y los bordes difuminados: hay que recortar el centro antes de comparar.

Dato comprobado: en este canal los Shorts SÍ muestran la miniatura personalizada en la
página del canal y en la búsqueda. En el feed de Shorts, YouTube nunca la usa.

### 5b. Qué poner en la miniatura, con datos (`thumbnail_research.py`)
1. Se bajan las miniaturas de los videos que rankean (de la misma investigación) y se mide
   cada una con numpy: brillo, contraste, saturación, familia de color dominante (cálida,
   fría o neutra por tono HSV) y carga visual (densidad de bordes).
2. **Diferenciarse** (`differentiate`):
   - acento de color = la familia MENOS usada por la competencia;
   - si ≥50 % son oscuras → sujeto bien iluminado (luminancia 125–165);
   - si ≥50 % son claras → clima oscuro con un solo punto de luz (70–110);
   - si ≥40 % están cargadas → una sola cosa, mucho espacio vacío, 2 palabras.
3. **Texto que COMPLEMENTA al título, no lo repite** (`text_options`, de 1 a 3 palabras,
   18 caracteres como máximo). En orden de preferencia:
   1. una cifra del guion con su sustantivo común (`1,000 CASTS`, `63 SAILORS`). Sin años.
      Una cifra que ya está en el título no suma.
   2. una búsqueda real de 2 o más palabras que no repite la palabra clave.
   3. una palabra del ángulo.

   **Toda palabra tiene que estar en el guion**. La primera versión propuso `HE LIVED` para
   los pilotos kaiten, que morían.
4. El brief (paleta, luminancia, texto y motivos) reemplaza los valores fijos del
   "super prompt" que se pega en una IA de imágenes externa (`claude_client.generate_thumbnail_super_prompt(research_brief=...)`).

---

## 6. Facebook (`facebook_metadata.py` + `facebook_uploader.py`)

Facebook **no tiene campo de tags**. Lo que indexa y lo que ve la gente es el **título**
(en videos de página), el **arranque de la descripción** (lo visible antes de "Ver más",
unos 125 caracteres) y los **hashtags**. Facebook no expone datos de búsqueda por API: se
usa la investigación de YouTube como aproximación, y conviene decirlo así.

- **Título**: el investigado en modo `optimize`; en `suggest` se respeta el del usuario.
- **Arranque**: si el sujeto o la palabra clave no aparecen en los primeros 125 caracteres,
  se antepone el título.
- **Hashtags** (3 a 5):
  - hasta 3 salen de la investigación, en este orden: el hashtag amplio del sujeto
    (`#Hannibal`), la palabra clave y después los tags investigados;
  - cada uno tiene que sumar una palabra nueva, y como mucho 2 pueden repetir el sujeto;
  - cada palabra tiene que estar en el guion: la competencia dio `#RomanArmy` para Aníbal,
    que era cartaginés;
  - un hashtag de una sola palabra solo si es el sujeto o un nombre propio a mitad de frase
    (salió `#Recovered` de un "Recovered…" al empezar la oración);
  - siempre van `#History` y **la marca de la página real** (se toma del nombre de la página
    por API, nunca de la configuración del canal de YouTube);
  - fuera: `#mystery`, `#shorts`, `#reels`, `#fyp`, `#viral`, `#foryou`, `#explore`;
  - CamelCase de hasta 24 caracteres (`KaitenTorpedo`).
- **Reparación**: el texto de respaldo viejo recortaba el guion a 260 caracteres y dejaba
  `…rations every s`. Si el primer párrafo es largo y no termina en puntuación, se corta en
  el último fin de oración, sin confundir abreviaturas (`St. Bernard`).
- **Miniatura**: `POST /{video_id}/thumbnails` con `source=<imagen>` e `is_preferred=true`,
  tanto para reels como para videos de página. Reintentos a los 10, 30 y 60 s (el video
  recién subido puede seguir procesando). No se reintenta un token vencido (error 190) ni un
  error de permisos. Después se compara la miniatura *preferida* guardada con la local.

---

## 7. Instagram (`instagram_uploader.py`)

- Tampoco hay campo de título: **caption = título + línea en blanco + descripción**. El
  título ya es la primera línea visible, así que no se antepone nada. El tope de 2200
  caracteres incluye al título, y el recorte nunca se come los hashtags.
- Mismas reglas de hashtags que Facebook, con la marca del nombre de la cuenta vinculada.
- **Portada**: la API solo la acepta **al crear el contenedor**, como `cover_url` (una URL
  pública de un JPEG).
  - La miniatura se convierte a JPEG (hasta 8 MB), se sube a Cloudinary, va en el contenedor
    (en la subida resumable y en la subida por URL) y se borra al terminar (`finally`).
  - Se verifica contra el `thumbnail_url` del reel publicado.
  - Si Meta rechaza la portada, se publica sin ella. Un error del video se propaga como antes.
  - Después de publicado no se puede cambiar por API (a mano en la app, sí).

---

## 8. El bucle de datos que alimenta todo

El SEO trae clics; lo que decide el alcance es qué temas y ángulos retienen. Por eso la
estrategia se mide y entra a los prompts.

- **`performance_feedback.py`**:
  - junta YouTube Analytics (vistas, engagedViews, retención, subs por video), Facebook
    Graph (plays, tiempo medio, retención, seguidores por reel) y cada `project.json`
    (tema, categoría, ángulo, duración);
  - escribe `performance_snapshot.json` con ganadores y perdedores, agregados por ángulo,
    categoría y duración, recomendaciones y pesos;
  - umbral empírico del feed de Shorts: a las 24 h un short pasó las ~300 vistas o se quedó
    en menos de 50. No hay término medio.
- **Ángulos (`format_archetypes`)**:
  - *mecanismo* (cómo lo hicieron), *hallazgo* (noticia), *historia humana* y
    *evento con cifra*;
  - salieron de muestrear los 106 shorts de historia más vistos del mes y de las métricas
    propias;
  - el ángulo viaja del guion al título, al cover y a la miniatura, cada uno con sus
    plantillas y palabras.
- **Channel Bible** (`channel_strategy_profile.json`): palabras prohibidas medidas,
  aperturas prohibidas, ejemplos ganadores, franja de largo del título. Es la configuración
  por nicho que usa el puntaje del título.
- **`trend_report.py`**: shorts del nicho más vistos en los últimos N días (Data API),
  artículos más vistos de Wikipedia filtrados al nicho, efemérides próximas y lo medido en
  el canal. Resultado: temas propuestos con su ángulo, cargables con un clic.
- **Primeros segundos** (retención, conectado al título y la miniatura):
  - la primera frase lleva una cifra concreta o una pregunta de CÓMO o POR QUÉ, con 14
    palabras como máximo;
  - la fecha va en la segunda frase o después; nunca "In 1540, …";
  - medido en Facebook: los reels que abren con fecha retienen ~30 % al primer cuarto; la
    mejor curva, sin fecha, 50 %.

---

## 9. Principios de ingeniería que conviene copiar tal cual

- **Funciones puras con la red inyectada** (`suggest_fn`, `competitor_fn`, `generate_fn`,
  `verify_fn`, `fetch`): todo se testea sin red y sin cuota.
- **Un generador inyectado sin verificador no llama al LLM real**: así los tests nunca
  gastan tokens por accidente.
- **Tests de regresión con el caso real en el comentario**, que fallan con el código viejo.
  Más tests de lectura de fuente para el cableado de la GUI.
- **Interruptores en `.env`** para apagar cada capa sin tocar código:
  - `YOUTUBE_TAG_RESEARCH`, `YOUTUBE_TITLE_MODE`, `YOUTUBE_TITLE_FACTCHECK`;
  - `THUMBNAIL_RESEARCH`, `FACEBOOK_SEO`, `FACEBOOK_SEO_RESEARCH`, `INSTAGRAM_SEO`.
- **Degradación elegante**: sin investigación, igual se limpian los hashtags y la marca.
  Sin Pillow (en el VPS), se manda JPG/PNG tal cual.
- **El panel narra cada paso**: la palabra clave elegida, el título elegido y su puntaje
  contra el anterior, los tags con su fuente, la miniatura y su verificación, los hashtags
  quitados.
- **Registro por publicación** (`publish_record.py`): id y url por red, más `title_sent`,
  `tags_sent`, `tags_stored`, `hashtags_sent`, `thumbnail_sent`, `thumbnail_set`. Sirve
  para cruzar después con las métricas.
- **Seguridad**:
  - nunca subir a YouTube automáticamente: la subida es un paso explícito, y primero en
    `unlisted`;
  - no modificar videos ya publicados sin confirmación;
  - el token de Meta va en el cuerpo del POST, no en la URL, y se censura en los logs.

---

## 10. Errores reales que no hay que repetir

| Síntoma | Causa | Regla |
|---|---|---|
| Tags vacíos o gigantes | El campo se partía solo por comas; se recortaban 500 tags en vez de 500 caracteres | Puerta final única que cuenta como YouTube |
| `hannibal lecter` como tag | Consenso débil (2 canales) sobre una palabra ambigua | Consenso fuerte (≥3) y corpus |
| La palabra clave de "kaiten" era un juego | El autocompletado del sujeto solo está tomado | Semillas sujeto + contexto; filtro de medios |
| "30 eruptions" en un título | Se chequeaba que la cifra existiera, no a qué se refería | Cifra + unidad |
| "Casts hold bodies" en un título | Contradicción semántica, invisible para las reglas | Verificación de hechos con el LLM |
| `HE LIVED` en la miniatura de pilotos suicidas | Palabra del ángulo sin respaldo | Toda palabra, en el corpus |
| `#StunningRevelations` en la página de SFOH | La marca salía de la config del canal de YouTube | Marca = nombre de la página o cuenta por API |
| `#Mystery` en todos los respaldos | Texto fijo viejo | Lista de hashtags prohibidos + medir qué muere |
| "…every s" al final del párrafo | Recorte por caracteres | Recortar en fin de oración, cuidando abreviaturas |
| La miniatura no aparecía | `.webp` no se buscaba; sin reintento; sin aviso | Detectar por contenido, reintentar, avisar, verificar |
| Tests que "pasaban" consultando APIs reales | El código nuevo resolvía identidad e investigaba dentro de la función testeada | Parchear la identidad y la red en los tests viejos |
| El mismo número en el título que en la miniatura | El texto no miraba el título | Una cifra ya presente en el título no suma |

---

## 11. Checklist para portar esto a otra app

1. **Definir el nicho**: el Bible (palabras prohibidas medidas, aperturas prohibidas, franja
   de largo del título, ejemplos ganadores), los ángulos del nicho, las consultas del
   reporte de tendencias y la marca de cada red.
2. **Capa de investigación**: autocompletado + top de búsqueda. Una llamada por video,
   guardada en un dict y reusada. Validar todo contra el corpus del guion.
3. **Puerta final de tags** antes que cualquier otra cosa: arregla la mitad de los problemas
   sin ninguna investigación.
4. **Tags investigados**, con los filtros de la sección 3 y la evidencia de cada tag.
5. **Títulos**: candidatos, puntaje, validadores (cifra + unidad, nombres), verificación de
   hechos, y los modos `optimize` y `suggest`.
6. **Miniatura**: primero que llegue (formato, reintentos, verificación); después, qué
   poner (competencia → diferenciación → texto respaldado).
7. **Otras redes**: título, arranque visible y hashtags; marca por API; portada con la API
   de cada red (Facebook: `/thumbnails`; Instagram: `cover_url` al crear el contenedor).
8. **Encadenar la investigación** entre redes en la misma tanda.
9. **Bucle de datos**: snapshot de rendimiento → bloque en el prompt del guion → pesos de
   temas.
10. **Tests** con los casos reales y **prueba en seco** con datos reales antes de publicar.

---

## 12. Mapa de archivos de referencia (en este repo)

| Archivo | Qué hace |
|---|---|
| `youtube_tags.py` | `gather_research` (la investigación), `research_tags`, `finalize_youtube_tags`, autocompletado y competencia |
| `youtube_titles.py` | Candidatos, `score_title`, `unsupported_numbers` (cifra + unidad), `factcheck_candidates`, `optimize_title` |
| `youtube_uploader.py` | Orquesta la investigación, el título y los tags; verifica los tags guardados; publica la miniatura |
| `thumbnail_publish.py` | Formato, reintentos, verificación de la miniatura servida |
| `thumbnail_research.py` | Análisis de las miniaturas de la competencia y brief para el super prompt |
| `facebook_metadata.py` | Motor de título, arranque y hashtags para Facebook e Instagram; encadenado de la investigación |
| `facebook_uploader.py` | Aplica la optimización y pone la miniatura en reels y videos de página |
| `instagram_uploader.py` | Aplica la optimización; portada vía `cover_url` + Cloudinary |
| `performance_feedback.py`, `channel_strategy.py` | Bucle de datos, ángulos, primeros segundos |
| `trend_report.py` + `anniversaries.json` | Tendencias del nicho y efemérides |
| `publish_record.py` | Qué se mandó y qué se guardó, por red |
| `test_youtube_tags.py`, `test_youtube_titles.py`, `test_thumbnail_publish.py`, `test_thumbnail_research.py`, `test_facebook_metadata.py`, `test_instagram_metadata.py` | Las guardas, con los casos reales |

Detalle cronológico de cada cambio: `AI_VIDEO_PLAYBOOK.md`, en el Changelog (entradas del
2026-09-22).
