# -*- coding: utf-8 -*-
"""Decisiones puras de la cadena de audio del ensamblaje.

Viven fuera de `auto_video_generator_v2.py` para poder testearlas sin levantar
la app entera: ver `test_audio_mix_sync_guards.py`.

Cada funcion de aca corresponde a un bug real del 2026-08-18 que se colaba a
produccion porque el pipeline degradaba en silencio:

- `build_duck_filter`  -> el filtergraph reusaba la etiqueta `[v]` y FFmpeg
  abortaba con -22 en TODOS los renders; la mezcla caia al fallback y la
  musica tapaba la voz.
- `compute_mix_gains`  -> no habia nivelado: musica masterizada (-18 dBFS)
  contra TTS (-21 dBFS).
- `should_inject_transition_sfx` -> con efectos cinematograficos el swoosh no
  se inyectaba en ninguna de las dos rutas de ensamblaje.
- `compute_cover_offset_seconds` -> el cover frame corria los timestamps de
  los segmentos sin desplazar la narracion.
"""

from __future__ import annotations

from typing import Any, Sequence, Tuple

# Nivel objetivo de la narracion y cuanto queda la CAMA de musica por debajo.
# Ojo: la musica se atenua DOS veces -- este colchon fijo y despues el ducking.
# Con 10 dB de cama + un sidechain de ratio 8 la musica terminaba ~26 dB bajo
# la voz durante la narracion, o sea inaudible. Para subir o bajar la musica,
# tocar MUSIC_UNDER_VOICE_DB: menos dB = mas musica.
TARGET_VOICE_DBFS = -16.0
MUSIC_UNDER_VOICE_DB = 6.0

# Auto-ducking. El sidechain baja la musica solo mientras hay voz; entre frases
# vuelve a la cama. Con estos valores queda ~10 dB de reduccion sobre una voz
# de -16 dBFS: musica presente entre frases, discreta debajo de la narracion.
# CALIBRADOS MIDIENDO, no derivados de la formula del compresor: con
# threshold=0.03/ratio=3 la reduccion real medida sobre narracion+musica era de
# 14.2 dB, no los 9.6 que predecia el modelo. Barrido sobre material real:
#   thr 0.03 ratio 3.0 -> 14.1 dB      thr 0.10 ratio 2.0 ->  5.5 dB
#   thr 0.05 ratio 3.0 -> 11.2 dB      thr 0.15 ratio 2.0 ->  3.8 dB
#   thr 0.08 ratio 2.5 ->  7.6 dB  <-- elegido
DUCK_THRESHOLD = 0.08
DUCK_RATIO = 2.5
DUCK_ATTACK_MS = 20
DUCK_RELEASE_MS = 400

# Reduccion real del sidechain con esos parametros (medida, no calculada).
MEASURED_DUCK_DEPTH_DB = 7.6

# El swoosh se nivela por PICO contra la voz: su media es muy baja (-27 dBFS)
# y nivelarlo por media lo dejaba pegado al techo del limitador.
SFX_PEAK_UNDER_VOICE_DB = 6.0

# Aire que se le saca al maestro para que el swoosh entre SIN que el limitador
# se lo coma. MEDIDO: el maestro sale del ducking picando en -0.3 dBFS, o sea
# pegado al techo; sumarle el swoosh ahi solo hacia trabajar al `alimiter`, que
# bajaba la mezcla entera 1 dB y dejaba el swoosh 1 dB MAS BAJO que sin mezclar.
# YouTube normaliza a -14 LUFS, asi que bajar 3 dB parejo no cuesta nada.
SFX_MASTER_HEADROOM_DB = -3.0

OVERLAY_TRANSITION_KEYWORDS = ("film burn", "light leak", "overlay")
NO_TRANSITION_KEYWORDS = ("none", "corte directo", "direct cut")


def compute_cover_offset_seconds(segments: Sequence[dict] | None) -> float:
    """Segundos que el cover frame le corre a TODOS los segmentos.

    El storyboard inserta el cover como segmento 0 y desplaza el resto, pero la
    narracion sigue arrancando en 0.0s: hay que padear la voz con este offset o
    imagenes, subtitulos y SFX quedan corridos todo el video.
    """
    try:
        segs = list(segments or [])
    except TypeError:
        return 0.0
    if not segs or not isinstance(segs[0], dict) or not segs[0].get("cover_frame"):
        return 0.0
    try:
        start = float(segs[0].get("start", 0) or 0)
        end = float(segs[0].get("end", 0) or 0)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, end - start)


def is_overlay_transition(transition_type: Any) -> bool:
    """True para transiciones que se aplican como overlay (Film Burn, etc.)."""
    name = str(transition_type or "").lower()
    return any(kw in name for kw in OVERLAY_TRANSITION_KEYWORDS)


def uses_transition(transition_type: Any) -> bool:
    """False cuando la transicion es corte directo / ninguna."""
    if not transition_type:
        return False
    name = str(transition_type).lower()
    return not any(kw in name for kw in NO_TRANSITION_KEYWORDS)


def should_inject_transition_sfx(
    enable_transition_sfx: bool,
    pydub_available: bool,
    transition_type: Any,
    clip_count: int,
    will_use_direct_ffmpeg: bool,
) -> bool:
    """Decide si el swoosh se mezcla en la pista de voz antes de ensamblar.

    La ruta rapida (`_assemble_direct_ffmpeg`) inyecta el SFX ella misma,
    alineado con los clips de overlay. La ruta MoviePy (efectos cinematograficos)
    NO pasa por esa funcion, asi que si aca tambien se saltea -- como pasaba con
    las transiciones overlay -- el swoosh no suena en ningun lado.
    """
    if not (enable_transition_sfx and pydub_available):
        return False
    if clip_count <= 1:
        return False
    if not uses_transition(transition_type):
        return False
    return not will_use_direct_ffmpeg


def speech_level_dbfs(audio, ventana_ms: int = 100, percentil: int = 65):
    """Nivel de la voz MIENTRAS habla, no el promedio del archivo.

    Es lo que decide la mezcla percibida: el oyente compara la voz en sus
    tramos fuertes contra la musica en su nivel tipico. Medir la voz con el
    promedio del archivo (o con LUFS integrado) la subestima ~2 dB y a la
    musica la sobreestima ~3.5 dB: juntos, 5.6 dB de error que hacian que la
    cama quedara 11.6 dB bajo la voz cuando la constante pedia 6.
    """
    try:
        tramos = []
        for inicio in range(0, len(audio), ventana_ms):
            nivel = audio[inicio:inicio + ventana_ms].dBFS
            if nivel != float("-inf"):
                tramos.append(nivel)
        if not tramos:
            return audio.dBFS
        tramos.sort()
        corte = tramos[min(len(tramos) - 1, int(len(tramos) * percentil / 100.0))]
        fuertes = [t for t in tramos if t >= corte]
        return sum(fuertes) / len(fuertes) if fuertes else audio.dBFS
    except Exception:
        return getattr(audio, "dBFS", 0.0)


def music_level_dbfs(audio, ventana_ms: int = 100):
    """Nivel tipico de la musica: mediana de ventanas, no RMS global.

    El RMS del archivo lo dominan los picos y queda ~3.5 dB por encima de lo
    que se percibe como 'el nivel de la cama'.
    """
    try:
        tramos = []
        for inicio in range(0, len(audio), ventana_ms):
            nivel = audio[inicio:inicio + ventana_ms].dBFS
            if nivel != float("-inf"):
                tramos.append(nivel)
        if not tramos:
            return audio.dBFS
        tramos.sort()
        return tramos[len(tramos) // 2]
    except Exception:
        return getattr(audio, "dBFS", 0.0)


def compute_mix_gains(
    voice_dbfs: float,
    music_dbfs: float,
    target_voice_dbfs: float = TARGET_VOICE_DBFS,
    music_under_voice_db: float = MUSIC_UNDER_VOICE_DB,
) -> Tuple[float, float]:
    """Ganancias (dB) para que la voz mande sobre la musica.

    Los niveles que entran tienen que venir de `speech_level_dbfs` y
    `music_level_dbfs`, no de `AudioSegment.dBFS` (ver esas funciones).

    Se aplican dentro de FFmpeg (float + limitador) y no en pydub: subir una
    narracion con picos en -3 dBFS a 16 bits la clipearia.
    """
    if voice_dbfs is None or voice_dbfs == float("-inf"):
        return 0.0, 0.0
    voice_gain = target_voice_dbfs - float(voice_dbfs)
    if music_dbfs is None or music_dbfs == float("-inf"):
        return voice_gain, 0.0
    music_gain = (target_voice_dbfs - music_under_voice_db) - float(music_dbfs)
    return voice_gain, music_gain


def estimate_ducked_music_under_voice_db(
    music_under_voice_db: float = MUSIC_UNDER_VOICE_DB,
    voice_dbfs: float = TARGET_VOICE_DBFS,
) -> float:
    """Cuantos dB queda la musica por debajo de la voz MIENTRAS hay narracion.

    Cama fija + reduccion del sidechain. La reduccion es una constante MEDIDA
    (`MEASURED_DUCK_DEPTH_DB`), no el resultado de la formula del compresor: esa
    formula subestimaba 4.6 dB y, sumada al error de medicion de niveles, hacia
    que el log informara 15.6 dB cuando la musica quedaba 25.8 dB abajo -- o
    sea, casi inaudible mientras el QA decia que estaba todo bien.
    """
    return float(music_under_voice_db) + MEASURED_DUCK_DEPTH_DB


def build_duck_filter(voice_gain_db: float, music_gain_db: float) -> str:
    """Filtergraph de auto-ducking: entrada 0 = musica, entrada 1 = voz.

    La voz alimenta DOS ramas (la mezcla y la llave del sidechain), por eso hay
    que duplicarla con `asplit`. Reutilizar la misma etiqueta en dos consumidores
    hace fallar el filtergraph entero ("Error binding filtergraph inputs/outputs",
    exit -22) -- ese era el bug que dejaba la musica a la par de la voz.

    `amix ... normalize=0` evita que el volumen se divida por la cantidad de
    entradas; `alimiter` cubre los picos de la voz ya amplificada.
    """
    return (
        f"[1:a]volume={voice_gain_db:.2f}dB,asplit=2[v_mix][v_key];"
        f"[0:a]volume={music_gain_db:.2f}dB[m];"
        f"[m][v_key]sidechaincompress="
        f"threshold={DUCK_THRESHOLD}:ratio={DUCK_RATIO}:"
        f"attack={DUCK_ATTACK_MS}:release={DUCK_RELEASE_MS}[ducked];"
        "[v_mix][ducked]amix=inputs=2:duration=first:"
        "dropout_transition=0:normalize=0[mixed];"
        "[mixed]alimiter=limit=0.95[out]"
    )


def compute_transition_sfx_positions(
    clip_durations: Sequence[float],
    escenas_nuevas: Sequence[int] | None = None,
    transition_duration: float = 0.0,
    created_count: int | None = None,
    peak_offset_s: float = 0.0,
    total_duration_s: float | None = None,
) -> list:
    """Segundos de la pista maestra donde tiene que sonar cada swoosh.

    Dos formas de cortar, dos cuentas distintas:

    - `escenas_nuevas` (Film Burn MEZCLADO sobre el clip entrante): el corte
      esta al INICIO del clip que arranca escena, o sea la suma de los clips
      previos. No hay clip de overlay intermedio que buscar -- buscarlo era el
      bug que dejaba 0 swooshes.
    - crossfade real: cada transicion se COME `transition_duration` segundos,
      asi que el corte i va corrido -i*duracion y el pico cae a la mitad.

    `peak_offset_s` alinea el PICO del swoosh con el corte, no su inicio: el
    archivo dura 4s y arranca con un build-up.
    """
    try:
        duraciones = [float(d) for d in (clip_durations or [])]
    except (TypeError, ValueError):
        return []

    cortes = []
    if escenas_nuevas:
        for idx in escenas_nuevas:
            try:
                i = int(idx)
            except (TypeError, ValueError):
                continue
            if 0 < i <= len(duraciones):
                cortes.append(sum(duraciones[:i]))
    elif created_count and created_count > 1:
        acumulado = 0.0
        for i in range(1, min(int(created_count), len(duraciones) + 1)):
            acumulado += duraciones[i - 1]
            offset = max(0.0, acumulado - (i * float(transition_duration)))
            cortes.append(offset + float(transition_duration) / 2.0)

    posiciones = []
    for corte in cortes:
        pos = max(0.0, corte - float(peak_offset_s))
        if total_duration_s is not None and pos >= float(total_duration_s):
            continue
        posiciones.append(round(pos, 3))
    # Dos cortes en el mismo milisegundo suman el swoosh sobre si mismo: 6 dB
    # de mas justo en el pico.
    return sorted(set(posiciones))


def compute_sfx_gain_db(
    master_peak_dbfs: float,
    sfx_peak_dbfs: float,
    under_db: float = SFX_PEAK_UNDER_VOICE_DB,
    master_headroom_db: float = SFX_MASTER_HEADROOM_DB,
) -> float:
    """Ganancia del swoosh para que su PICO quede `under_db` bajo el maestro.

    Por pico y no por media: el archivo tiene media -27 dBFS y pico -2 dBFS;
    nivelarlo por media lo pegaba al techo del limitador. Este nivelado ya
    existia en la ruta MoviePy pero NO en la ruta rapida de FFmpeg, que es la
    que se usa por defecto -- por eso el swoosh se oia bajo incluso cuando si
    se mezclaba.

    La referencia es el maestro YA bajado por `master_headroom_db`: si se toma
    el maestro sin bajar, el swoosh queda por encima del techo del limitador y
    el resultado medido es que la mezcla suena MAS BAJA en el corte que sin
    swoosh.
    """
    for valor in (master_peak_dbfs, sfx_peak_dbfs):
        if valor is None or valor == float("-inf") or valor <= -90:
            return 0.0
    referencia = float(master_peak_dbfs) + float(master_headroom_db)
    return (referencia - float(under_db)) - float(sfx_peak_dbfs)


def build_transition_sfx_filter(
    positions_s: Sequence[float],
    gain_db: float = 0.0,
    master_input: int = 1,
    sfx_input: int = 2,
    sample_rate: int = 44100,
    limit: float = 0.95,
    master_headroom_db: float = SFX_MASTER_HEADROOM_DB,
) -> str:
    """Filtergraph que mete el swoosh en la mezcla DENTRO de FFmpeg.

    Reemplaza el camino viejo (pydub: overlay en memoria + `export()` a un mp3
    intermedio). Ese export fallaba con `[Errno 22] Invalid argument` y el
    `except` se comia el error: el video salia sin un solo swoosh. Ademas
    re-encodeaba el maestro entero a mp3 por segunda vez, sin necesidad.

    Detalles que NO son cosmeticos:
    - `asplit` para las N copias: reusar la misma etiqueta en dos consumidores
      rompe el filtergraph entero (exit -22), igual que en `build_duck_filter`.
    - `aformat` fija formato/rate/layout en las dos ramas: el maestro es mono
      24 kHz y el swoosh estereo 48 kHz, y depender de la negociacion
      automatica de FFmpeg es justo el tipo de cosa que falla en silencio.
    - `normalize=0` en el amix (si no, mezclar divide el volumen por N) y
      `alimiter` despues, porque sumar N swooshes sobre un maestro ya limitado
      clipea.
    - `master_headroom_db`: el maestro entra bajado. Sin esto el limitador se
      come el swoosh entero (medido: -1 dB en el corte respecto de NO mezclarlo).
    - `duration=first`: la salida dura lo que el maestro, no lo que el ultimo
      swoosh.

    Devuelve "" si no hay posiciones (el llamador debe muxear sin filtro).
    """
    posiciones = [float(p) for p in (positions_s or [])]
    if not posiciones:
        return ""

    fmt = (f"aformat=sample_fmts=fltp:sample_rates={int(sample_rate)}:"
           f"channel_layouts=stereo")
    n = len(posiciones)
    partes = [f"[{master_input}:a]{fmt},volume={master_headroom_db:.2f}dB[m];"]

    if n == 1:
        partes.append(f"[{sfx_input}:a]{fmt},volume={gain_db:.2f}dB[s0];")
    else:
        etiquetas = "".join(f"[s{i}]" for i in range(n))
        partes.append(
            f"[{sfx_input}:a]{fmt},volume={gain_db:.2f}dB,asplit={n}{etiquetas};"
        )

    for i, pos in enumerate(posiciones):
        partes.append(f"[s{i}]adelay={int(round(pos * 1000))}:all=1[d{i}];")

    entradas = "[m]" + "".join(f"[d{i}]" for i in range(n))
    partes.append(
        f"{entradas}amix=inputs={n + 1}:duration=first:"
        f"dropout_transition=0:normalize=0[sfxmix];"
    )
    partes.append(f"[sfxmix]alimiter=limit={limit}[aout]")
    return "".join(partes)


__all__ = [
    "TARGET_VOICE_DBFS",
    "MUSIC_UNDER_VOICE_DB",
    "SFX_PEAK_UNDER_VOICE_DB",
    "SFX_MASTER_HEADROOM_DB",
    "MEASURED_DUCK_DEPTH_DB",
    "speech_level_dbfs",
    "music_level_dbfs",
    "estimate_ducked_music_under_voice_db",
    "compute_cover_offset_seconds",
    "is_overlay_transition",
    "uses_transition",
    "should_inject_transition_sfx",
    "compute_mix_gains",
    "build_duck_filter",
    "compute_transition_sfx_positions",
    "compute_sfx_gain_db",
    "build_transition_sfx_filter",
]
