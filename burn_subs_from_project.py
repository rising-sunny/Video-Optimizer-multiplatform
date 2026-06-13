"""Burn subtitles into an existing project MP4 using precomputed segment timings.

Reuses DynamicSubtitleWrapper but forces Whisper OFF (the path that crashed in
c10.dll). Subtitles are built from `timestamp_start` / `timestamp_end` already
present in each segment (timing_source = word_ratio), so this runs in seconds
on CPU with no torch dependency at runtime.

Usage:
    python burn_subs_from_project.py <project.json> [mp4_path]

If mp4_path is omitted, the script picks the most recent youtube_*.mp4 in
auto_videos/output. The output is written next to the input MP4 as
`<name>_with_subs.mp4` so the original is preserved.

Exit codes:
    0  → success (or already had subs)
    1  → invalid arguments / project not found
    2  → no segments with timings in the project
    3  → no MP4 found
    4  → subtitle generation or ffmpeg burn failed
"""
import os
import sys
import json
import glob
import argparse


def find_latest_mp4(output_dir: str) -> str | None:
    """Pick the most recent un-subbed MP4. Excludes files containing `_with_subs`
    to avoid double-burning subtitles on a file that already has them."""
    all_mp4s = glob.glob(os.path.join(output_dir, "youtube_*.mp4"))
    candidates = sorted(
        [p for p in all_mp4s if "_with_subs" not in os.path.basename(p).lower()],
        key=os.path.getmtime,
        reverse=True,
    )
    return candidates[0] if candidates else None


def load_project_segments(project_json_path: str):
    with open(project_json_path, encoding="utf-8") as fh:
        data = json.load(fh)
    storyboard = data.get("storyboard") or data
    segments = storyboard.get("segments") or []
    language = storyboard.get("language") or data.get("config", {}).get("language") or "es"
    # Project audio path can live in several places depending on save flow.
    project_dir = os.path.dirname(os.path.abspath(project_json_path))
    audio_path = (
        storyboard.get("audio_path")
        or data.get("audio_path")
        or data.get("config", {}).get("audio_path")
    )
    if audio_path:
        # Resolve relative paths against the project directory.
        if not os.path.isabs(audio_path):
            audio_path = os.path.join(project_dir, audio_path)
        if not os.path.isfile(audio_path):
            audio_path = None
    if not audio_path:
        # Fallback: pick the most recent *manual_*.mp3 in the project's audio folder.
        audio_dir = os.path.join(project_dir, "audio")
        if os.path.isdir(audio_dir):
            candidates = sorted(
                glob.glob(os.path.join(audio_dir, "*manual_*.mp3")),
                key=os.path.getmtime,
                reverse=True,
            )
            if candidates:
                audio_path = candidates[0]
    return segments, language, audio_path


def main() -> int:
    parser = argparse.ArgumentParser(description="Burn subs onto a project MP4 (Whisper subprocess by default).")
    parser.add_argument("project_json", help="Path to project.json")
    parser.add_argument("mp4", nargs="?", help="Path to MP4 (auto-detected from auto_videos/output if omitted)")
    parser.add_argument("--style", default="hormozi", help="Subtitle style (default: hormozi)")
    parser.add_argument("--width", type=int, default=1920)
    parser.add_argument("--height", type=int, default=1080)
    parser.add_argument(
        "--no-whisper",
        action="store_true",
        help="Disable Whisper alignment (fallback to segment timings). Whisper runs isolated in a subprocess, so a crash will not tumble this script.",
    )
    args = parser.parse_args()

    project_path = os.path.abspath(args.project_json)
    if not os.path.isfile(project_path):
        print(f"[ERROR] project.json no encontrado: {project_path}", file=sys.stderr)
        return 1

    segments, language, audio_path = load_project_segments(project_path)
    if not segments:
        print(f"[ERROR] project.json sin segmentos", file=sys.stderr)
        return 2
    timed = [s for s in segments if s.get("timestamp_start") is not None and s.get("timestamp_end") is not None]
    if not timed:
        print(f"[ERROR] Ninguno de los {len(segments)} segmentos tiene timestamp_start/end", file=sys.stderr)
        return 2

    # Resolver mp4 a ruta ABSOLUTA — FFmpeg se ejecuta posiblemente con un cwd
    # distinto al del script, los paths relativos rompen el subprocess.
    script_dir = os.path.dirname(os.path.abspath(__file__))
    if args.mp4:
        mp4_path = os.path.abspath(args.mp4)
    else:
        # Buscar en auto_videos/output relativo al script (no al CWD del shell)
        mp4_path = find_latest_mp4(os.path.join(script_dir, "auto_videos", "output"))
        if not mp4_path:
            print(f"[ERROR] No se encontró MP4 en {script_dir}/auto_videos/output", file=sys.stderr)
            return 3
        mp4_path = os.path.abspath(mp4_path)

    if not os.path.isfile(mp4_path):
        print(f"[ERROR] MP4 no encontrado: {mp4_path}", file=sys.stderr)
        return 3

    use_whisper = not args.no_whisper
    effective_audio = audio_path if use_whisper else None

    print(f"[INFO] Proyecto: {project_path}")
    print(f"[INFO] Segmentos con timing: {len(timed)} de {len(segments)}")
    print(f"[INFO] MP4 origen: {mp4_path}")
    print(f"[INFO] Estilo subtitulo: {args.style}")
    if use_whisper and effective_audio:
        print(f"[INFO] Whisper: ACTIVADO (subprocess aislado) — audio: {effective_audio}")
    elif use_whisper and not effective_audio:
        print(f"[INFO] Whisper: ACTIVADO pero NO se encontró audio_path en el proyecto → fallback a timings")
    else:
        print(f"[INFO] Whisper: DESACTIVADO por --no-whisper")

    # Ensure Whisper is enabled at env-var level when user opts in.
    if use_whisper and effective_audio:
        os.environ["VIDEO_OPTIMIZER_SUBS_USE_WHISPER"] = "1"

    from dynamic_subtitle_wrapper import DynamicSubtitleWrapper

    wrapper = DynamicSubtitleWrapper(style=args.style)
    ass_path = os.path.abspath(os.path.splitext(mp4_path)[0] + ".ass")

    try:
        wrapper.generate_ass_from_segments(
            timed,
            ass_path,
            video_width=args.width,
            video_height=args.height,
            audio_path=effective_audio,
            force_whisper=bool(use_whisper and effective_audio),
            language=language,
        )
    except Exception as exc:
        print(f"[ERROR] Falló generate_ass_from_segments: {exc}", file=sys.stderr)
        return 4

    if not os.path.isfile(ass_path) or os.path.getsize(ass_path) < 50:
        print(f"[ERROR] ASS no generado o vacío: {ass_path}", file=sys.stderr)
        return 4

    print(f"[OK] ASS generado: {os.path.basename(ass_path)} ({os.path.getsize(ass_path)} bytes)")

    out_mp4 = os.path.splitext(mp4_path)[0] + "_with_subs.mp4"
    print(f"[INFO] Quemando subtítulos a: {out_mp4}")

    try:
        success = wrapper.engine.burn_subtitles_with_ffmpeg(
            mp4_path,
            ass_path,
            out_mp4,
            video_width=args.width,
            video_height=args.height,
        )
    except Exception as exc:
        print(f"[ERROR] Falló burn_subtitles_with_ffmpeg: {exc}", file=sys.stderr)
        return 4

    if not success or not os.path.isfile(out_mp4):
        print(f"[ERROR] burn_subtitles_with_ffmpeg no produjo archivo", file=sys.stderr)
        return 4

    print()
    print(f"[OK] Video final con subtítulos: {out_mp4}")
    print(f"     Tamaño: {os.path.getsize(out_mp4) / 1024 / 1024:.1f} MB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
