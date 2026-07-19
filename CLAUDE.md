# CLAUDE.md

App de escritorio PyQt6 que genera videos cortos y documentales con IA (guión → TTS →
imágenes IA → ensamblaje FFmpeg → subtítulos) para el canal **Stunning Revelations**.

## Antes de generar videos o tocar el pipeline, LEÉ el playbook

**➡️ [AI_VIDEO_PLAYBOOK.md](AI_VIDEO_PLAYBOOK.md)** — referencia completa y actualizable:
entry points para generar shorts (`run_pipeline`) y long-form (`build_long_form`), los dos
canales del usuario y sus diagnósticos, el Channel Bible, reglas de subida, y las mejoras
ya bakeadas en el código. Empezá por ahí en vez de re-descubrir todo. Mantené su Changelog
al día si cambiás un entry point o la estrategia.

## Esencial

- Corré todo con el venv local: `\.venv\Scripts\python.exe <script.py>` (no el Python global).
- **Nunca subas videos a YouTube automáticamente.** Subida = paso explícito; `unlisted` primero.
- Secretos en `.env` (gitignored) — nunca los commitees.
- Setup de una PC nueva: `CONTEXTO_OTRA_PC.md` / `SETUP_OTRA_PC.md`.
- Guardar en git = cuando el usuario lo pida; `git push origin main`; no incluir los videos
  pesados de `long_form/*_project/` ni artefactos de runtime.
