# Install the chat receiver from this delivery branch

This branch adds only `ops/chat-receiver-v1/`. It does not change application
sources on main or switch the VPS worktree to this branch.

As root on the VPS, fetch the delivery branch as videoagent, then run the
bootstrap from the exact commit supplied in the chat:

```bash
cd /home/videoagent/Video-Optimizer-multiplatform
sudo -u videoagent git fetch origin deploy/chat-receiver-v1
sudo -u videoagent bash -o pipefail -c 'git show COMMIT:ops/chat-receiver-v1/install-vps.sh | bash -s -- COMMIT'
```

Replace both COMMIT occurrences with the commit SHA supplied with the release.
The bootstrap accepts a 12–40 hexadecimal commit prefix, resolves it once and
reads the binary kit from that same commit. It checks the pinned SHA256, refuses
an existing kit destination, extracts only the expected regular files and runs
the tested installer as videoagent. No checkout or main merge is involved.

Expected result: `status: installed`, `receiver: ready`. The reported number of
tests is at least 34, or 42 when the earlier Instagram regression suite is present.
No video is received or published during installation. Existing readiness and
source fingerprints must match before any application file is replaced.

Read README.md for the reception and explicit publication commands. The Books
Wanderer, MathRelaxing, cron, systemd timer configuration and global AI CLI
installations are outside this kit's changes.

The source `.py` files and extended tests are included here for review. The kit
itself contains the runtime, narrow source adapters, installation smoke tests,
checksums and documentation. `LOCAL-VALIDATION.json` records the original local
validation; bootstrap transfer checks are recorded separately in
`DELIVERY-VALIDATION.json`.
