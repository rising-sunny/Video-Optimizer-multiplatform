# Autonomous generation and maintenance, v49

This is the general workflow for future **Catarsis Shorts and narrated horizontal
documentaries, on either channel**. It is not a Curie-specific recovery.

One initial root installation adds the owner-authenticated MCP tools and two
persistent services. Afterwards generation, bounded recovery, diagnostics and
tested module updates use the connector. Closing SSH or the chat does not stop
the VPS worker or its recovery observer. The observer enrolls new user-requested
jobs only; it does not create daily topics or publish videos.

## Tools

- `generate_catarsis_single`: one channel, same native pipeline and stable ID.
- `video_generation_diagnostics`: current errors, budgets, artifacts and saved
  malformed provider responses, without relaying shell output.
- `resume_video_generation`: same Short batch or documentary job, using saved
  validated evidence and the original remaining budget. Keep the same request ID
  when repeating a transport call; a new deliberate repair uses a new request ID.
- `video_workflow_inventory` and `read_video_workflow_source`: installed hashes
  and allowed Python source, with credentials/config paths excluded.
- `deploy_video_workflow_release` and `video_workflow_deployment_status`:
  asynchronous, verified code updates from the user's repository.

Refresh the connector's tool list after the initial installation if the client
has cached its previous tools. Existing video status and preview tools keep
working; Short status also reports this workflow's version and diagnostics.

## Recovery and quality

The JSON reader accepts a single redundant object close after a complete object;
it rejects duplicate keys, unfinished objects and arbitrary suffixes. At most two
format/schema repair attempts per video may use the original DeepSeek transport,
preserving its paid counters and reserving capacity for mandatory reviews.
These repairs use saved evidence, with no provider fallback or fresh research.
The observer can continue stopped jobs from a complete saved plan or existing
MP4 with valid technical QA. Ready sibling channels are preserved. Original
claims remain; every continuation gets a separate durable authorization, claim,
backup and attempt record. A job has at most three such continuations.

Shorts retain their chosen music, native rendering, actual factual/rights and
visual reviews, and native approval. Documentaries retain the installed narration,
SRT, source acquisition and shot-checkpoint functions. Existing valid MP4 review
steps run without re-rendering. An approved artifact is immutable. An ambiguous
provider request, exhausted budget, unsupported facts/rights or failed quality
assessment remains a concrete diagnostic; none is converted into approval.

The installed defaults stay 10 chat requests, 4 searches, 14 fetches, 4 text
invocations, 350,000 input tokens, 24,000 output tokens and an estimated USD 0.20
per video. Existing specific grants are not reset or generalized. The independent
visual budget is unchanged. Publication is a separate authorized operation.

## Maintenance releases

The initial installer places a small root controller outside the generation-code
tree. Only the existing local videoagent broker (or root) may call its Unix socket.
The connector never gains an arbitrary shell operation. The controller can copy
allowed generation Python modules, run a fixed test command and restart the two
existing services. It cannot modify its own policy/code, credentials, systemd
units, job ledgers, claims, daily timers or source-pin readiness records through
the release protocol.

For a new correction:

1. Read inventory and the relevant allowed installed source. Preserve unrelated
   changes; prepare the complete candidate files and meaningful offline tests.
2. Commit those files and a manifest at
   `automation/releases/RELEASE_ID/manifest.json` in
   `rising-sunny/Video-Optimizer-multiplatform`.
3. Call the deployment tool with the exact commit and manifest SHA256, then poll
   its returned deployment ID. Never replace an expected installed hash silently.
4. Once deployment reports installed, resume the existing job if necessary and
   verify its current result. A successful deployment does not prove video quality.

Manifest schema:

```json
{
  "version": 1,
  "release_id": "example-fix",
  "files": [{
    "target": "workflow_example.py",
    "source": "automation/autonomy/modules/workflow_example.py",
    "sha256": "SHA256_OF_CANDIDATE",
    "expected_sha256": "SHA256_OF_INSTALLED_FILE_OR_absent"
  }],
  "tests": [{
    "source": "automation/autonomy/tests/test_example.py",
    "path": "test_example.py",
    "sha256": "SHA256_OF_TEST_FILE"
  }]
}
```

Tests execute as videoagent with networking disabled and home, credentials and
control sockets hidden. Only a temporary working directory is writable. Zero
discovered tests is a failure. The controller waits for idle jobs, rejects source
drift, backs up exact bytes, verifies service health and the authentication
boundary, and rolls back failures. An interrupted installation is reconciled from
its persisted transaction and known hashes. Deployment IDs are idempotent.

Do not call the historical topic-specific installers for a different job. Do not
remove budgets or claims, refresh readiness hashes automatically, approve a
negative review, change narration/assets just to fit metadata, or upload a second
copy when a remote video ID already exists.

## Initial installation and existing work

The one-time bootstrap checks the actual installed sources, stages adaptations
of them, runs the tests in both actual Python environments, backs up, installs,
checks owner-only service health and persists this code/runbook in the VPS repo.
The existing daily automation remains paused. It also attempts to resume the
already authorized Curie Short as the first real use of the general workflow;
that batch is retained and no second channel is generated.

Repository persistence, VPS installation, generation readiness and publication
must always be reported separately. Credentials, OAuth tokens, signed URLs,
Codex auth and resumable upload session URIs never belong in commits.
