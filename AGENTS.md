# Video Automation

For generation, recovery, rendering, music, subtitles or publication work, first read
[the workflow corrections and runbook](docs/VIDEO_AUTOMATION_CORRECTIONS.md).
The versioned sources and reusable publisher are in `automation/documentary/`.

- Reuse installed corrections and saved evidence; distinguish current status from old failures.
- Do not replay a topic-specific recovery on a different job or reset budgets/claims.
- Preserve narration, integer frame timing, SRT, downloaded assets and remote video IDs when reusing work.
- Verify actual media types, decodeability, clip duration/motion, licenses and music-account scope.
- Use the permanent documentary publisher for authorized YouTube uploads. Its `--inspect` action is read-only.
- Installing or archiving a workflow does not authorize generation or publication. Apply the user's existing authorization to the exact task without asking again.
- Keep credentials, signed URLs and resumable session URIs out of commits and user-visible output.
- Keep regression coverage for captionNotFound, asynchronous processing, known IDs, resumed transfers and publication readback.
- Report repository persistence separately from VPS installation until an installation receipt confirms it.
