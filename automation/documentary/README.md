# Documentary workflow — consolidated 2026-11-06

Read [`../../docs/VIDEO_AUTOMATION_CORRECTIONS.md`](../../docs/VIDEO_AUTOMATION_CORRECTIONS.md).

`publication/` is the permanent, parameterized adapter around the publisher that
successfully published Chrome Dome. `tests/` preserves the 25 publisher regressions
and adds coverage for other jobs/channels, inspection without publication, archive
privacy, permissions under umask 077 and rollback after an interrupted installation.

`runtime-reference/` contains the exact nine important generation modules delivered
during the previous corrections, with `runtime-reference-sha256.json`. These are
reference copies, **not an alternative PYTHONPATH or a complete standalone runtime**.
The VPS installer compares them with `/opt/video-agent-mcp` and snapshots the declared
Python runtime modules and Chrome Dome recovery helpers for audit. Existing delivered
release archives and job-specific recovery packages remain in `deliveries/`.

Installing this release writes documentation, an archive and a permanent publication
entrypoint. It does not run a generation, publish a video, replay a recovery, modify
the generation service or enable daily timers.

The final verified result for Chrome Dome is YouTube video `B8QPUmNCfCY`, public with
the accepted vidIQ thumbnail and an English subtitle track.
