# Video delivery from this chat

Scope: Stunning Facts of History and Stunning Revelations only. MathRelaxing,
The Books Wanderer, cron entries, systemd timers and exporter configuration are
not modified. Generation remains on demand in this chat.

## Install

Run `install_chat_receiver.py` as videoagent using the existing project Python.
The installer verifies kit checksums and readiness, makes private backups, runs
offline tests against candidate code, then installs only daily_core.py,
daily_remote.py, chat_package.py and chat_receiver.py. It updates readiness with
the new code hashes and test evidence, retaining previous evidence timestamps.
On ordinary installation failure it restores original code and readiness. A
process killed during replacement can leave a code/readiness mismatch; that
fails closed and requires restoring the backup before publication.

The installer creates a private 32-byte acceptance key in
runtime/production/.chat-acceptance-key. Never print, export in a delivery ZIP,
or delete this key. Existing chat approvals require the same key. Back up the
key with the server's protected credential backup procedure.

Installation does not import videos, create containers, query account identities
or publish anything. The installer does not revive old manual_release tools.

## Package created here

Each request has a UUID, date, channel, topic and topic_key. The metadata marker
must equal `VA-CHAT:DATE:CHANNEL:UUID` and appear in all platform descriptions.
The package includes video.mp4, thumbnail.jpg, metadata.json, chat-review.json,
sources.json, asset-credits.json, music_credits.json, review images, and any
required licensed music/proof. Only allowlisted files are admitted; scripts,
credentials, transport state, previous approvals and publication receipts are
not accepted from the package. Captions are rejected rather than truncated.

The chat review declares origin=codex_chat, approved=true, review_reference,
request_id, date, channel, video_sha256, nonempty checks with all values true,
and image_inputs containing packaged review image paths and their SHA256 values.
It must result from an actual visual review in this chat. A chat declaration is
not an independently authenticated ChatGPT signature. The operator explicitly
accepts that declaration by supplying its exact package manifest hash.

Build and check the ZIP here with chat_package.py. The package uses stored ZIP
members, bounded sizes, per-file hashes and a canonical manifest. Transfer the
finished ZIP to the VPS using an approved transport such as SCP/SFTP. The
receiver does not install SSH keys, create transfer accounts or expose a web
upload endpoint.

## Receive on the VPS

    python -B chat_receiver.py receive /path/video.zip \
      --manifest-sha256 EXACT_HASH --accept-chat-review

The receiver snapshots and validates the ZIP, checks the current authorized
Santiago date and refuses any existing destination job, including empty jobs.
It uses ffprobe, full ffmpeg decoding and thumbnail validation. It retains the
native music preflight; Epidemic audio must match its SHA256 in the protected
cache or be included as music/FILENAME. Existing cache files are never replaced.

The operator's acceptance is signed locally and binds the manifest, exact video,
review, approval and artifact hashes. The approval records codex_chat as the
review origin; it does not invent successful_agent_exit or a Codex CLI version.
Legacy approvals retain their original validation branch.

Receiving creates a publication block. Even if a timer is enabled, Publisher.run
requires a separate signed authorization for chat-origin jobs before identity
reads and remote publication. Existing legacy jobs retain their existing gates.

## Publish only when separately requested

    python -B chat_receiver.py publish --channel CHANNEL --date DATE \
      --request-id UUID --execute

This command validates the exact imported request, approval, readiness, activation,
pause state and native publication window. It signs authorization only for this
job and date, removes only its known receipt-awaiting-authorization block and
uses the original Publisher. Native identity checks, music authorization, IDs,
reconciliation and per-platform receipts remain in force. Already published
platforms are skipped. Ambiguous outcomes must be reconciled on the same IDs.

The calendar currently comes from activation-package-20261019/activation-policy.json;
this kit does not extend its end date, permit backfill or authorize another channel.
