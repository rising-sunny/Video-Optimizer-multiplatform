# Análisis del canal Stunning Revelations — septiembre 2026

**Canal:** Stunning Revelations · `UC66EnGiys6V3gKe-J0XD-_Q` · `@stunning-revelations`
**Fecha del análisis:** 2026-09-08
**Fuente:** 5 exports de YouTube Studio, rango 2020-06-28 → 2026-09-08:
contenido, fuente de tráfico, audiencia por comportamiento de visualización,
origen de las suscripciones, tráfico orgánico y de pago.

> **Alcance y límites.** Todo lo que sigue sale de esos CSV. No hubo acceso a la API
> del canal. La clasificación Short / no-Short es una **inferencia** a partir de la
> métrica "Se quedaron viendo" (que YouTube solo reporta para el feed de Shorts); el
> corte es limpio en los 180s, lo que la hace sólida, pero la fuente de verdad es el
> contador de horas válidas en Studio → Monetización. La dimensión orgánico/pagado
> solo tiene datos de los últimos ~12 meses.

---

## 1. Conclusión en cinco líneas

1. La publicidad de 2025 **no** es el problema actual: el 97% del tráfico de los últimos 12 meses es orgánico.
2. No hay castigo algorítmico: en marzo–abril de 2026 el canal tuvo distribución real.
3. **Todo lo que el canal produce son Shorts verticales**, y su watch time no cuenta para monetizar.
4. Horas válidas acumuladas para el umbral de 4,000: **15.6 h (0.4%)**.
5. El formato con alcance (Shorts) y el formato monetizable (horizontal) son, en este canal, incompatibles: en horizontal nunca hubo tracción.

---

## 2. Corrección importante sobre este mismo análisis

Este documento contiene una conclusión que **cambió a mitad del análisis**. Queda
registrada porque afecta qué se produce.

| | Primera lectura | Lectura corregida |
|---|---|---|
| Hallazgo | La banda 121-180s genera el 67% de las horas del canal | El dato es correcto |
| Conclusión | "Producir en la banda 121-180s" | **Errónea para monetizar** |
| Por qué | — | 70 de esos 73 videos son **Shorts verticales**; sus horas no cuentan |
| Horas válidas | Se asumieron ~587 h | **15.6 h** |

**Regla de YouTube (desde oct-2024):** un video es Short si cumple las dos
condiciones a la vez — dura **≤3 minutos** *y* es **vertical o cuadrado** (1:1 o más
alto). El watch time de Shorts **no** cuenta para las 4,000 horas del programa de
socios. Un video horizontal cuenta sin importar su duración; un vertical de más de
3 minutos también cuenta.

---

## 3. Totales del canal (histórico completo)

| Métrica | Valor |
|---|---|
| Visualizaciones | 350,784 |
| Tiempo de visualización | 1,568.33 h |
| Suscriptores | 3,470 (4,022 ganados / 552 perdidos) |
| Me gusta | 7,551 |
| Impresiones de miniatura | 394,031 |
| CTR de miniatura | 1.55% |
| Duración media de visualización | 0:00:31 |

### 3.1 La biblioteca vieja fue borrada

Los 223 videos vivos se publicaron **todos** entre dic-2025 y ago-2026. La diferencia
contra los totales pertenece a videos que ya no existen:

| Métrica | Biblioteca viva (223 vids) | Total canal | Gap (borrado) |
|---|---|---|---|
| Visualizaciones | 47,204 | 350,784 | 303,580 |
| Watch time | 587.3 h | 1,568.3 h | **981.1 h** |
| Suscriptores | 220 | 3,470 | 3,250 |
| Me gusta | 1,526 | 7,551 | 6,025 |
| Impresiones | 31,719 | 394,031 | 362,312 |

Las 981 h borradas **no cuentan** para monetización: solo computa contenido público
vivo. **No borrar más videos con retención decente.**

---

## 4. La publicidad (feb–mar 2025)

| Origen de suscripción | Netos | Ganados | Perdidos |
|---|---|---|---|
| **Publicidad de YouTube** | **2,677** | 2,693 | 16 |
| Página de visualización | 758 | 761 | 3 |
| Feed de Shorts | 464 | 480 | 16 |
| Tu canal de YouTube | 53 | 69 | 16 |
| Lista de suscripciones | −76 | 2 | 78 |
| Cuentas cerradas | −105 | 8 | 113 |
| Otros | −301 | 9 | 310 |

La campaña aportó el **67%** de todos los suscriptores ganados, concentrada en
**feb-2025 (+1,587)** y **mar-2025 (+1,090)**. Pero en los últimos 12 meses:
77,868 vistas orgánicas contra **2,312 pagadas (2.9%)**. La publicidad ya no toca
la distribución.

### 4.1 Los suscriptores están inertes

Últimos 12 meses, vistas por tipo de audiencia:

| Audiencia | Vistas | Watch time |
|---|---|---|
| Usuarios nuevos | 78,415 | — |
| Usuarios ocasionales | 1,610 | — |
| **Usuarios habituales** | **148** | — |

Histórico: los "habituales" acumulan 165 vistas y **0.58 h** en toda la vida del
canal, sobre 3,470 suscriptores. YouTube además está cerrando esas cuentas solo
(−105 históricos, −53 en los últimos 12 meses).

**El número de suscriptores no es una métrica útil de este canal.** La métrica real
es horas orgánicas válidas por semana.

---

## 5. Rendimiento por duración (biblioteca viva)

| Duración | n | Watch hours | h/video | Mediana vistas |
|---|---|---|---|---|
| ≤60s | 55 | 90.5 | 1.65 | 26 |
| 61-120s | 60 | 86.1 | 1.43 | 32 |
| **121-180s** | **73** | **396.4** | **5.43** | **157** |
| 181-300s | 26 | 8.3 | 0.32 | 7 |
| 301-600s | 2 | 0.7 | 0.36 | 12 |
| >600s | 6 | 5.2 | 0.87 | 6 |

La banda 121-180s concentra el **67% de todas las horas**. Los 26 videos de 3-5 min
produjeron 8.3 horas entre todos.

### 5.1 Pero esas horas son de Shorts

Clasificación por presencia de métrica de feed de Shorts:

| Duración | Shorts (vertical) | horas | NO-Short | horas |
|---|---|---|---|---|
| ≤60s | 55 | 90.5 | 1 | 0.0 |
| 61-120s | 58 | 86.1 | 2 | 0.0 |
| 121-180s | **70** | **395.1** | 3 | 1.3 |
| 181-300s | 0 | 0.0 | **26** | **8.3** |
| >300s | 0 | 0.0 | **8** | **5.9** |
| **Total** | **183** | **571.7** | **40** | **15.6** |

- **Shorts:** 183 videos, 46,590 vistas, **571.7 h que no monetizan**.
- **No-Shorts:** 40 videos, **614 vistas en total**, **15.6 h válidas**.

El corte es perfecto en los 180 segundos, exactamente donde YouTube pone el límite
de Shorts. Los 26 videos de 181-300s ya están siendo tratados como no-Shorts por
YouTube: es evidencia empírica del propio canal, no teoría.

---

## 6. Distribución de vistas (223 videos vivos)

| Percentil | Vistas |
|---|---|
| Mediana | 29 |
| p75 | 367 |
| p90 | 751 |
| p99 | 1,013 |
| Máximo | 1,197 |

**122 de 222 videos tienen menos de 50 vistas.** El top 10 concentra el 21.1% de
las vistas. El volumen no es el cuello de botella: se publicaron 220 videos en
8 meses.

---

## 7. La caída de 2026: causa raíz

Vistas orgánicas por mes:

| Mes | Vistas orgánicas |
|---|---|
| 2026-01 | 923 |
| 2026-02 | 1,568 |
| 2026-03 | **22,873** |
| 2026-04 | **15,148** |
| 2026-05 | 2,126 |
| 2026-06 | 2,287 |
| 2026-07 | 4,097 |
| 2026-08 | **412** |
| 2026-09 (parcial) | 27 |

### 7.1 No fue una regresión de código

El historial de git del repo arranca en el **commit inicial del 2026-06-13**. El
código de marzo–abril no existe en el repositorio, así que no hay diff posible.
Los datos respondieron igual.

### 7.2 Fue abandono de formato

Banda 121-180s, mes a mes:

| Mes | n | Mediana vistas | Retención | Watch hours |
|---|---|---|---|---|
| 2026-02 | 3 | 16 | 34.8% | 1.3 |
| 2026-03 | 32 | 160 | 64.6% | 189.8 |
| 2026-04 | 38 | 256 | 71.6% | 205.2 |
| 2026-05 | **0** | — | — | — |
| 2026-06 | **0** | — | — | — |
| 2026-07 | **0** | — | — | — |
| 2026-08 | **0** | — | — | — |

70 videos en marzo–abril generaron 395 de las 587 horas totales. **Desde el 1 de
mayo no se publicó ni uno.** Se migró a 61-120s (may/jun/ago) y a shorts (jul).

La caída de retención de julio (71% → 33.9%) tampoco es una regresión: 22 de los
25 videos de julio eran shorts ≤60s.

---

## 8. Fuentes de tráfico y CTR

| Fuente | Vistas | Watch h | Dur. media | Impresiones | CTR |
|---|---|---|---|---|---|
| Feed de Shorts | 258,204 | 858.4 | 0:00:31 | — | — |
| Publicidad de YouTube | 64,991 | 464.2 | 0:00:25 | — | — |
| Búsqueda de YouTube | 15,270 | 54.4 | 0:00:25 | 206,446 | 1.75% |
| Otras funciones | 4,767 | 21.5 | 0:00:32 | — | — |
| Páginas de canal | 3,109 | 22.8 | 0:00:54 | 25,261 | 1.90% |
| Funciones de exploración | 1,407 | 22.1 | 0:01:02 | 37,906 | 2.70% |
| **Vídeos sugeridos** | **1,146** | **93.3** | **0:04:54** | **117,751** | **0.77%** |
| Directa o desconocida | 198 | 11.3 | 0:03:42 | — | — |
| **Total** | **350,784** | **1,568.3** | **0:00:31** | **394,031** | **1.55%** |

**Videos sugeridos es el dato más revelador:** 117,751 impresiones (30% de todas
las del canal) con **0.77% de CTR**, la peor de todas las superficies — pero la
mejor duración media de visualización (4:54). YouTube ofrecía el espacio y las
miniaturas no lo convirtieron. Un CTR sano está en 4-6%.

---

## 9. El motor dual short → documental: falló

| Tema | Short | Documental hermano |
|---|---|---|
| Derinkuyu | 57s → **1,187 vistas** | 858s → **4 vistas** |
| Wow! Signal | 60s → **1,013 vistas** | 612s → **1 vista** |

La estrategia documentada en el playbook ("short ganador → documental hermano") no
produjo resultados. También se detectó contenido fuera de nicho:
*"STEM Digital Notebook — 142 Pages (GoodNotes · Notability)"* (14s).

---

## 10. Matemática de monetización

**Requisitos del programa de socios:** 1,000 subs + 4,000 horas públicas válidas en
12 meses, **o** 1,000 subs + 10M vistas de Shorts en 90 días.

| | Estado | Objetivo | Brecha |
|---|---|---|---|
| Suscriptores | 3,470 | 1,000 | ✅ cumplido |
| **Horas válidas** | **15.6 h** | 4,000 h | **0.4%** |
| Vistas Shorts (90d) | 6,742 | 10,000,000 | 0.07% |

Últimos 90 días (2026-06-10 → 2026-09-07): 6,742 vistas totales, +4 suscriptores
netos (17 ganados en el feed de Shorts, −10 cuentas cerradas, −4 desuscritos).

Al ritmo actual de ~75 vistas/día con 65s de duración media, alcanzar 4,000 h
requeriría **608 vistas/día — 8.1x lo actual** — y eso asumiendo contenido que
compute, que hoy no es el caso.

---

## 11. El pipeline no puede producir el formato monetizable

| Entry point | Límite | Referencia |
|---|---|---|
| `daily_short_pipeline.py` | Rechaza todo lo que pase de **60s** | `channel_strategy.py:115-120` |
| `long_form_builder.py` | Apunta a **8-15 min**, storyboard 16:9 | `long_form_builder.py:253+` |

No hay un modo intermedio. Además, `build_long_form` no tiene guarda contra valores
chicos, pero su piso efectivo queda fuera de la banda 2-3 min:

- `_plan_dimensions` fuerza mínimo 3 capítulos × 5 párrafos = 15 segmentos (`long_form_builder.py:119-124`).
- `word_budget = minutes * 155`, mientras la narración real corre a `EFFECTIVE_WPM = 120` (`long_form_builder.py:50`).
- Con `--minutes 3` salen ~465 palabras ≈ 232s, pasado el techo de 180s.

**Para el objetivo corregido (16:9 de 3-5 min) esto no es un bloqueo:**
`build_long_form` ya genera 16:9, y `--minutes 4` da ~620 palabras ≈ 5.2 min. El
experimento se puede correr sin tocar código.

---

## 12. Recomendaciones

1. **No cerrar el canal.** Cerrarlo no arregla nada: no hay penalización que se
   limpie empezando de cero, y el activo real es el pipeline, no el canal. Pero el
   diagnóstico honesto es que **nunca se produjo contenido monetizable**, no que
   algo se haya roto.
2. **Dejar de producir Shorts** mientras dure el experimento. Suman alcance pero
   cero horas válidas.
3. **Correr un experimento de 6-8 videos horizontales 16:9 de 3-5 min** sobre temas
   que ya demostraron enganche en Shorts: Venona, Kursk, Coronel, Archimedes.
   Comando: `.venv\Scripts\python.exe long_form_builder.py "TEMA" --minutes 4`.
   Empezar con `--no-assemble` para validar guión y duración estimada.
4. **Criterio de decisión:** si en 60 días ningún video del experimento pasa de
   200 vistas, la monetización de este canal no es un objetivo realista y conviene
   redirigir el pipeline.
5. **Atacar el CTR de miniatura.** 117,751 impresiones desperdiciadas en videos
   sugeridos a 0.77%. Es el inventario más grande sin explotar del canal.
6. **No borrar más videos vivos** con retención decente.
7. **Ignorar el conteo de suscriptores** como métrica de salud.

---

## 13. Cómo verificar

**Fuente de verdad:** YouTube Studio → Monetización/Ganancias → contador de "horas
de visualización públicas válidas" de los últimos 12 meses.

**Predicción falsable de este análisis:** ese contador debería marcar entre **15 y
25 horas**. Si marca eso, la clasificación Short/no-Short es correcta y todo el
documento se sostiene. Si marca ~590, hay un error grande y el análisis debe
rehacerse desde cero.

La orientación de cada video se confirma en Studio → Contenido: los Shorts llevan
el ícono de Shorts en la lista.

---

## 14. Reproducir el análisis

Los exports se procesaron con scripts ad-hoc en Python (csv + statistics) sobre
los archivos `Datos de la tabla.csv`, `Datos del gráfico.csv` y `Totales.csv` de
cada uno de los 5 ZIP. Cruces principales:

- Biblioteca viva vs totales → detección de la biblioteca borrada.
- Duración × mes → detección del abandono de formato.
- Presencia de "Se quedaron viendo (%)" → clasificación Short / no-Short.
- Ventanas de 365 y 90 días sobre las series diarias → estado actual.

Para datos frescos del canal, ver `weekly_intelligence_report.py --days 30` y
`youtube_channel_analyzer.py` (requieren `GOOGLE_API_KEY` o `token.json`; la Data
API v3 da solo métricas públicas, no retención ni CTR: eso sale de estos exports).
