# Approved source pins, v48.1

The Curie single-Short preflight stopped before installation and before any AI
request. Four hardcoded generation-worker pins were older than the actual
automation sources. The read-only VPS diagnostic showed all seven source files
match the existing readiness snapshot, with 36/36 checks true.

This migration binds only the four observed pins (runner, daily_core,
daily_remote, editorial). It requires the exact observed worker and readiness
hashes, rechecks the seven approved source hashes, and runs the unchanged native
preflight as videoagent. It backs up the worker and rolls back if verification
fails. It does not edit automation sources, readiness, PAUSED, budgets or grants.
It recognizes its corrected worker both before and after the v48 single-channel
patch, making the migration repeatable without reverting the installed worker.

Then the original v48 installer runs: 35 offline tests, live account availability,
single-channel selection, native QA, and the original stable request
`manual-facts-curie-ww1-20261106-v1`. Only Stunning Facts of History is generated;
YouTube/Facebook/Instagram metadata are prepared, publication is not requested.
vidIQ topic research is retained in `vidiq-research.json`.

Future source changes must be validated and committed together with their source
pins and readiness evidence. Never disable the guard or replace a known expected
hash with a live file's hash automatically. Historical deliveries remain frozen;
the correction receipt records the exact approved transition.
