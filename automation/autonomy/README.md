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

### Missing preparation inputs (v49.2)

Same-job inspection remains read-only. After claiming the authorized continuation
and archiving its original files and ledger, the worker prepares missing native
history/music snapshots, retrieves only cited public factual pages through the
existing six-GET receipt mechanism, and validates the complete plan. Existing
inputs, failed page intents and original paid counters are retained. Unsupported
citations never become verified merely because they occur in the saved response.
One evidence-bound plan correction may use the original remaining text budget,
with capacity reserved for the independent assessment. There is no new topic,
research API budget, automatic provider fallback or fabricated approval.

The native source contains an old `generation_moved_to_codex_chat` entry-point
sentinel in `build`/`invoke`. For user-authorized generation the adapter recognizes
only that exact first statement and compiles the remaining native function in
its original namespace. The pinned native file and readiness record are unchanged;
the actual native validation, sandbox, encoding, reviews and approval still run.
Other guards are never removed. The adapter applies to future Short builds as
well as saved Short continuations; documentary functions retain their own pipeline.

The JSON parser also recognizes the precise pair of premature object closes
that puts YouTube tags and Facebook outside platform metadata before a trailing
Instagram member. It removes only those two structural characters, preserves
all text/credits, and still rejects duplicates, ambiguous boundaries and unrelated
suffixes. Diagnostics validate the recovered native plan without starting a
worker or spending tokens. Context scenes become overlays with their existing
labels; music license links use the already retrieved publisher template and
the exact catalogue ISRC, with receipt hashes checked. A failed charged repair
does not automatically spend another continuation repeating the same result.

### Display correction within the original review allowance (v49.4)

All styled Short renders now fit cards by pixel width and show the existing
source-person/date labels beneath each photograph or clip. Stored sentences,
source credits and timing are not rewritten by this display adapter.

A single-channel Short stopped only for `text_readable`/`context_labels` can use
one separately claimed local presentation stage. It requires the exact completed
video/QA and negative review, an approved factual response whose exact current
evidence fingerprint is already cached, and exactly one used native visual claim.
The existing native Short limit is two visual claims; this stage does not grant
or reset one. The three continuation records remain intact. The local stage is
one-time and idempotent, with frozen source/request/control hashes and a complete
backup of the old video, failed visual assessment and paid ledger.

The stage changes only pixel typography and renders already supplied labels.
It preserves the original AAC payload, verifies unchanged textual evidence and
uses the exact factual cache. New DeepSeek transport calls are explicitly denied
inside this worker. Native technical QA and the remaining real Codex visual
assessment must approve the corrected MP4 before native production approval.
Exhausted visual limits, factual/rights failures, framing failures, changed source
evidence or an already used local claim remain blocked. No publication follows.

The display-only entry prepares the native renderer's repository import path
before claiming its work, just as native `build` normally does. A single technical
checkpoint may resume an initialization failure only when every job artifact
(apart from the failure record), every ledger file and the original request hash
are still identical to the first authorization. The original claim/auth remain;
the checkpoint gets a separate bound claim and cannot repeat. Changed renders or
used review claims never qualify. Exceptions retain sanitized type/file/line data.

Native `render_project` reuses an existing MP4. A presentation correction therefore
moves its backed-up prior file out of that output path before rendering and
requires changed video packet data afterwards. It restores the old path if no
new output is produced. After copying the original AAC payload into the new MP4,
the stage calls native `qa(video,directory,smoke=False)` again so its SHA256 binds
the actual remuxed file. Merely refreshing extended frame sheets is not technical QA.
Actual lower-panel pixels are also checked before spending the remaining vision
claim; metadata labels alone cannot pass that check.

One cache-reconciliation checkpoint applies only to the observed stale-QA/remux
case: original factual inputs, ledger, negative assessment and QA must still be
byte-identical, and the current audio/video packet hashes must match the archived
original. It retains both old claims/auths and adds one bound checkpoint. It never
grants another text request or visual review. A genuinely changed render does not
qualify for this checkpoint.

The native helper also caches `receipt.json`, not just `video.mp4`. Both outputs
are moved aside after a verified backup; the receipt is preserved as an audit
artifact. A regression fixture contains the exact native `render_project` body
and exercises its first-render, reuse and fresh-render receipt branches. After
native QA passes on the final remux, its real SHA256 updates the new receipt.
One final receipt-only reconciliation is limited to an unchanged original AV
payload, unchanged factual cache/ledger and unspent original visual allowance;
it cannot repeat or qualify a changed render. Old authorizations and claims stay.

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
control sockets hidden. Staged sources live under `/var/lib/video-workflow-test-staging`,
outside the private `/tmp` and `/var/tmp` namespaces; an empty read-only `/run`
also hides credentials and control sockets that do not exist yet at bootstrap.
Host process files under `/proc` are inaccessible to test code.
Only the isolated working directory and private temporary space are writable. Zero
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

## Catarsis visual continuity (v50)

Pixel fitting preserves the channel's original condensed bold serif for narrative
cards. Center, left, word, inverted and red variants retain their meaning; source
labels remain readable sans serif below the archival image. Long cards can unfold
as contiguous original phrases with brief native kinetic entrances. The adapter
keeps all source words, integer-frame boundaries of archival shots and the quiet
break; it does not paraphrase history or add media.

A new explicitly user-requested style revision of the approved, unpublished Curie
Short is separate from automatic recovery. The exact single-channel generation
request `revise-curie-catarsis-style-20261107-v1` is bound to its approved source
video/approval hashes and returns that same batch. It archives the original job,
ledger and approval byte-for-byte before making the revised working version.
All original text counters and visual claims remain intact. New research/text
transport is forbidden. This revision has one separately recorded real Codex
visual assessment, with new MP4 scene/entry samples and labeled published style
references. The original generation allowance is not reset or extended. It cannot
be triggered by the observer, another request/topic or a publication operation.
The native technical QA, exact factual-cache binding and native approval still
have to pass. The soundtrack's original AAC packet payload and all source dates,
credits and metadata are preserved. Repository code and installed/readied video
status remain separate evidence; this entry is not a completed-render receipt.


### Crisp text-entry checkpoint (v50.1)

The first actual revision assessment accepted framing/context/intentional stills
but blocked text readability in blurred/doubled entry frames. Its negative
assessment and visual claim remain preserved. The display renderer now replaces
blur/echo with a crisp 3.5% scale entrance over six frames, including the encoder's
private render namespace. No source words or archival timing change.

One exact checkpoint is bound to the observed failed MP4 hash and only the
text_readable failure. It requires the untouched original factual evidence,
ledger and original archived approval, and the first revision's used claim.
The explicit single request `revise-curie-catarsis-style-clean-entry-20261107-v2`
can render changed pixels and obtain one actual fresh assessment, separately
claimed. Across both deliberate style stages there are at most two assessments;
neither the generation budget nor any old claim is reset/replayed. Other failed
videos, unrelated defects, changed evidence or repeated checkpoints are rejected.

### Exact positive-check scope finalization (v50.4)

The crisp MP4 passed all seven actual Codex visual checks and all visual platform
checks, with no findings, but retained an overall false flag. Its sole suggestion
said frame sheets cannot confirm full playback or audible quality. The raw false
flag, response/cache and successful provider events remain unchanged and archived.
A separate controller-owned final quality decision may resolve only this exact
MP4/response: native full AV decode, audio levels, duration and unchanged original
AAC must pass; the actual crisp entry sheet inspected in the current chat is
hash-bound. Any failed/missing check, other finding or other suggestion rejects
this path. This does not label the provider's overall flag true, does not claim
full content watching/listening and does not authorize publication. The normal
native review/approval tail combines the exact approved factual cache, existing
positive visual/platform checks and this explicit local scope verification.
No render or provider call is allowed. The native vision trace identifies reuse
and controller decision ownership; old budgets and all claims remain untouched.
