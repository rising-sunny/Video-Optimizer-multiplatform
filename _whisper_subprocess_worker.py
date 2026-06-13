"""Isolated Whisper transcription worker.

Runs Whisper in its own process so that crashes in torch/c10 (segfaults,
access violations, OOM kills) cannot tumble the main app. Communicates with
the parent through:
  - stdout: ONE line of JSON with the transcription result (last line)
  - stderr: human-readable progress / diagnostics (best-effort)
  - exit code: 0 on success, non-zero on any failure

Parent expected output schema (success):
  {
    "ok": true,
    "language": "en",
    "segments": [
      {
        "start": 0.0, "end": 2.34, "text": "...",
        "words": [{"word": "Cold", "start": 0.0, "end": 0.4}, ...]
      },
      ...
    ]
  }

Failure (caught Python exception):
  {"ok": false, "error": "<message>"}

If the process dies via SIGSEGV / Windows access violation, stdout will be
empty / partial and exit code will be a negative or large unsigned value.
The parent must treat any non-zero exit OR malformed JSON as a fallback signal.
"""
from __future__ import annotations

import argparse
import json
import sys
import traceback


def _emit(result: dict) -> None:
    """Single-line JSON to stdout (last line, for robust parsing on parent side)."""
    print("\n__WHISPER_RESULT__", file=sys.stderr)  # marker for log readers
    sys.stdout.write(json.dumps(result, ensure_ascii=False))
    sys.stdout.write("\n")
    sys.stdout.flush()


def main() -> int:
    parser = argparse.ArgumentParser(description="Isolated Whisper transcription worker")
    parser.add_argument("--audio", required=True, help="Path to audio file (absolute recommended)")
    parser.add_argument("--language", default=None, help="ISO 639-1 (e.g. 'es', 'en'); omit for auto-detect")
    parser.add_argument("--model", default="small", help="Whisper model size (tiny|base|small|medium|large)")
    args = parser.parse_args()

    try:
        # Heavy imports happen here — they're inside the subprocess so a crash
        # only kills the subprocess, not the parent app.
        import torch  # noqa: F401
        import whisper

        device = "cuda" if torch.cuda.is_available() else "cpu"
        print(
            f"[whisper-worker] device={device} model={args.model} "
            f"lang={args.language or 'auto'} audio={args.audio}",
            file=sys.stderr,
        )

        model = whisper.load_model(args.model, device=device)

        kwargs = {"word_timestamps": True}
        if args.language:
            kwargs["language"] = args.language

        result = model.transcribe(args.audio, **kwargs)

        # Reduce payload to only fields used by the parent's alignment code.
        whisper_segments = []
        for seg in result.get("segments", []) or []:
            words = []
            for w in (seg.get("words") or []):
                try:
                    words.append(
                        {
                            "word": str(w.get("word", "")),
                            "start": float(w.get("start", 0.0)),
                            "end": float(w.get("end", 0.0)),
                        }
                    )
                except (TypeError, ValueError):
                    continue
            whisper_segments.append(
                {
                    "start": float(seg.get("start", 0.0)),
                    "end": float(seg.get("end", 0.0)),
                    "text": str(seg.get("text", "")),
                    "words": words,
                }
            )

        # Free the model BEFORE emitting JSON — reduces peak RAM during the
        # parent's subsequent decode of stdout.
        try:
            del model
        except Exception:
            pass

        _emit(
            {
                "ok": True,
                "language": str(result.get("language", "??")),
                "segments": whisper_segments,
            }
        )
        return 0

    except Exception as exc:  # any Python-level failure
        traceback.print_exc(file=sys.stderr)
        _emit({"ok": False, "error": f"{type(exc).__name__}: {exc}"})
        return 1


if __name__ == "__main__":
    sys.exit(main())
