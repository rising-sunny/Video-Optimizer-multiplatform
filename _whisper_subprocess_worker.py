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

REMOTE MODE
-----------
If the environment variable WHISPER_REMOTE_URL is set (e.g. through an SSH
tunnel to a VPS running the whisper-svc FastAPI service), this worker POSTs the
audio file to <WHISPER_REMOTE_URL>/transcribe and re-emits the JSON it gets
back. In that mode torch / whisper are NOT imported locally at all, which keeps
the local machine light.

Relevant env vars:
  WHISPER_REMOTE_URL     Base URL of the remote service (e.g. http://127.0.0.1:8771)
  WHISPER_REMOTE_TOKEN   Bearer token for the remote service (optional)
  WHISPER_REMOTE_MODEL   Override model size sent to the remote (default: caller's --model)
  WHISPER_REMOTE_TIMEOUT_S  HTTP timeout in seconds (default: 600)
  WHISPER_REMOTE_STRICT  If "1"/"true", do NOT fall back to local whisper when the
                         remote call fails (emit error instead).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import traceback


def _emit(result: dict) -> None:
    """Single-line JSON to stdout (last line, for robust parsing on parent side)."""
    print("\n__WHISPER_RESULT__", file=sys.stderr)  # marker for log readers
    sys.stdout.write(json.dumps(result, ensure_ascii=False))
    sys.stdout.write("\n")
    sys.stdout.flush()


def _transcribe_remote(base_url: str, audio: str, language: str | None, model: str) -> dict:
    """POST the audio to the remote whisper-svc and return its parsed JSON.

    Raises on any network/HTTP error so the caller can decide whether to fall
    back to local transcription.
    """
    import requests  # lightweight, already a project dependency

    endpoint = base_url.rstrip("/") + "/transcribe"
    token = os.environ.get("WHISPER_REMOTE_TOKEN", "").strip()
    headers = {}
    if token:
        headers["Authorization"] = "Bearer " + token

    send_model = os.environ.get("WHISPER_REMOTE_MODEL", "").strip() or model or "base"
    data = {"model": send_model}
    if language:
        data["language"] = language

    try:
        timeout_s = float(os.environ.get("WHISPER_REMOTE_TIMEOUT_S", "600"))
    except (TypeError, ValueError):
        timeout_s = 600.0

    print(
        f"[whisper-worker] REMOTO endpoint={endpoint} model={send_model} "
        f"lang={language or 'auto'} audio={audio}",
        file=sys.stderr,
    )

    with open(audio, "rb") as fh:
        files = {"audio": (os.path.basename(audio) or "audio.wav", fh)}
        resp = requests.post(endpoint, headers=headers, data=data, files=files, timeout=timeout_s)
    resp.raise_for_status()
    payload = resp.json()
    if not isinstance(payload, dict):
        raise ValueError("remote returned non-object JSON")
    return payload


def _transcribe_local(audio: str, language: str | None, model: str) -> dict:
    """Local whisper transcription (imports torch + whisper inside this process)."""
    import torch  # noqa: F401
    import whisper

    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(
        f"[whisper-worker] LOCAL device={device} model={model} "
        f"lang={language or 'auto'} audio={audio}",
        file=sys.stderr,
    )

    wmodel = whisper.load_model(model, device=device)

    kwargs = {"word_timestamps": True}
    if language:
        kwargs["language"] = language

    result = wmodel.transcribe(audio, **kwargs)

    segments = []
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
        segments.append(
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
        del wmodel
    except Exception:
        pass

    return {
        "ok": True,
        "language": str(result.get("language", "??")),
        "segments": segments,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Isolated Whisper transcription worker")
    parser.add_argument("--audio", required=True, help="Path to audio file (absolute recommended)")
    parser.add_argument("--language", default=None, help="ISO 639-1 (e.g. 'es', 'en'); omit for auto-detect")
    parser.add_argument("--model", default="small", help="Whisper model size (tiny|base|small|medium|large)")
    args = parser.parse_args()

    remote_url = os.environ.get("WHISPER_REMOTE_URL", "").strip()

    # ── REMOTE first (no torch import) ───────────────────────────────────────
    if remote_url:
        try:
            payload = _transcribe_remote(remote_url, args.audio, args.language, args.model)
            _emit(payload)
            return 0 if payload.get("ok") else 1
        except Exception as exc:
            strict = os.environ.get("WHISPER_REMOTE_STRICT", "").strip().lower() in ("1", "true", "yes")
            if strict:
                traceback.print_exc(file=sys.stderr)
                _emit({"ok": False, "error": f"remote failed: {type(exc).__name__}: {exc}"})
                return 1
            print(
                f"[whisper-worker] remoto fallo ({type(exc).__name__}: {exc}); "
                f"fallback a whisper local",
                file=sys.stderr,
            )
            # fall through to local path below

    # ── LOCAL fallback / default ─────────────────────────────────────────────
    try:
        payload = _transcribe_local(args.audio, args.language, args.model)
        _emit(payload)
        return 0
    except Exception as exc:  # any Python-level failure
        traceback.print_exc(file=sys.stderr)
        _emit({"ok": False, "error": f"{type(exc).__name__}: {exc}"})
        return 1


if __name__ == "__main__":
    sys.exit(main())
