# Setting up a PR test environment

How to get a UC Nexus PR environment into a state you can actually click through, and what it can and
cannot show you. Read this **before** a testing session; the module-by-module knowledge you need
*during* one is in [CLAUDE.md](CLAUDE.md) alongside it.

Separate from that file on purpose: this is a procedure invalidated by infrastructure changes, and it
went stale silently once already - it claimed for months that adding a relay channel needed a restart,
which stopped being true at #456 and cost a session. Anything here that describes relay behaviour
should cite the code it came from so a reader can check rather than trust.

**Every open, non-draft PR gets an environment automatically**, cloned from production with a fresh
empty database, at `https://frontend-uc-nexus-pr-<N>.up.railway.app` and
`https://backend-uc-nexus-pr-<N>.up.railway.app`. Draft PRs do not get one.

For signing in (`/testing/clerk-sign-in`, `TESTING_ENABLED`, the `X-Testing-Secret` header) see
the Environment and Getting Started sections of [CLAUDE.md](CLAUDE.md) - the runbook below refers to
them rather than restating them.

**In a hurry:** `testing/scripts/connect-pr-env.ps1 <PR#>` does the whole hookup and tells you
whether it worked. The rest of this file is what it does and how to diagnose it when it does not.

## A PR environment is relay-disconnected by default, and that is useful

By default a PR environment always reports `relayStatus.connected: false`, and no amount of waiting
changes it. Two independent reasons, both addressed by #414 but neither automatic:

1. The relay dials whatever `[channel] backend_url` in its `config.toml` names. Since #414 that takes
   a LIST, so a PR backend can be added *alongside* production rather than replacing it - but somebody
   has to add it. **No restart** since #456: `channel.run_forever` re-reads `config.toml` every
   `CHANNEL_RECONCILE_SECONDS` (see `relay/src/ucnexus_relay/channel.py` for the live value), adding a
   channel for a URL that appears and cancelling one for a URL that disappears. Editing the file is
   the whole procedure - see the runbook below.
2. Relay installs live in Postgres and a PR environment boots a fresh empty one, so the handshake is
   refused (4403) even if the relay does dial. Since #414 the backend seeds a trusted install on
   startup from `RELAY_SEED_SECRET_HASH` - the SHA-256 already in production's row, copyable from
   Admin -> Relay Installs ("Seed hash" column). Where that variable goes is the part that catches
   people out (#431):
   - It belongs on the **production** backend service and stays there inert. PR environments are cloned
     from production, so that is the only place a new one can inherit it from; production refuses to
     seed and logs the refusal at INFO, which is the intended steady state, not something to tidy up.
   - **Inheritance happens at environment creation only.** Setting it on production does nothing for a
     PR environment that already exists - set it on that environment's own backend service as well.
     Verified 2026-07-30: pr-430 predated the variable and stayed GP-blind until it had its own copy.
   - Seeding runs at backend startup, so the variable only takes effect on that service's next deploy.

Read the default state as a free test fixture rather than a limitation. The relay-down half of any
GP-gated feature - disabled controls, "not connected" copy, held values still displaying, buttons that
must not be clickable - is exactly what a PR environment exercises by construction, and it is the half
that is otherwise awkward to reach on production without stopping the relay for everyone.

**But "by default" is doing real work in that heading.** Disconnected is a state you were handed, not
a property of PR environments, and leaving it that way is a choice with a cost: with no relay there
are no projects (they come from the GP job sync), and with no projects there is no schedule import, no
PO, no receiving, no inventory, no assembly, no shipping. Nearly the whole spine of the app is
unreachable. If you find yourself writing "this surface cannot be tested here", connect the relay
first and check whether that is still true. It usually is not.

A PR environment with a connected relay is pinned to **TUBC** and refuses every other company with
`company_not_allowed_on_channel`, reads and writes alike. Reads and writes both work against TUBC;
that pin is what makes serving writes off a test backend acceptable at all.

## Connect a PR environment for full click-through testing

`testing/scripts/connect-pr-env.ps1 <PR#>` does steps 2-4 and waits for the confirmation in step 5.
Run it rather than doing this by hand; the manual steps are here so a failure is diagnosable, and
because a script that nobody can read is its own kind of stale documentation.

Each step lists **the signal that proves it worked**. Check the signal rather than assuming - every
step here has failed silently at least once.

1. **Find the Railway environment.** It is named `uc-nexus-pr-<N>`, NOT `pr-<N>` - the CLI answers
   `Environment "pr-511" not found` for the latter, which reads like the environment is missing.
   Services inside it are `backend` and `frontend`; the public hostnames are
   `backend-uc-nexus-pr-<N>.up.railway.app`.
   - Signal: `railway environment list --json` lists it, with `meta.prNumber` matching.
2. **`TESTING_SIGN_IN_SECRET_HASH` on that environment's backend**, so you can mint a session. See the
   Auth bullet in [CLAUDE.md](CLAUDE.md)'s Environment section for what it is and why production must
   not have one.
   - Signal: `railway variables --environment uc-nexus-pr-<N> --service backend --json` shows it set,
     and `GET /testing/clerk-sign-in` with the matching `X-Testing-Secret` answers 200 rather than 401.
3. **`RELAY_SEED_SECRET_HASH` on that same backend**, so the relay's handshake is accepted rather than
   refused 4403. Usually inherited at environment creation; set it by hand if the environment predates
   the variable.
   - Signal: same `railway variables` read shows it set.
4. **Add the PR backend to the relay's channel list.** In
   `%LOCALAPPDATA%\UCNexusRelay\config.toml`, under `[channel]`:
   ```toml
   extra_backend_urls = ["wss://backend-uc-nexus-pr-<N>.up.railway.app/relay-link"]
   ```
   **Never touch `backend_url`** - production's URL comes from the baked default, and retyping it with
   one character wrong silently demotes the production channel to the TUBC pin (see the safety note in
   #414). Write the file as UTF-8 **without a BOM**: PowerShell's `Set-Content -Encoding utf8` adds one
   in 5.1, `tomllib` then refuses the file, and the relay crashes at startup.
   - Signal: within ~10s, `%LOCALAPPDATA%\UCNexusRelay\relay.log` logs `backend channels changed` with
     your URL under `added`, then `channel connected` with `restricted_to: ["TUBC"]`.
5. **Confirm the app sees it.** Sign in and open the PO module.
   - Signal: the header reads `RELAY CONNECTED`, not `GP RELAY NOT DETECTED`.
6. **Assign your GP buyer to the project you will test on**, or Register in GP refuses with "Buyer X is
   not assigned to this project" (#216). Admin -> Buyers -> Add Buyer.
   - Signal: the buyer grid lists a row pairing your buyer with that project.
7. **Tear down when the PR closes**: remove the URL from `extra_backend_urls` (or run the script with
   `-Disconnect`). A closed environment otherwise retries forever against a backend that is gone.
   - Signal: `relay.log` logs `backend channels changed` with your URL under `removed`.

With that done the whole chain is click-through: GP job sync populates real TUBC projects, the import
wizard runs against a real schedule, Register in GP writes a real PO to TUBC and stamps the PM00200
vendor onto it, and receiving populates from that. Proven end to end on pr-511 (2026-08-05): PO0000095
against ALLEGION, from Create-GP-Job through to the back-order grid, entirely by clicking.

What a PR environment cannot show out of the box is a NEW op. The workstation runs a packaged build, so
a PR that adds to `_OPS` answers `unknown_op` -> `RELAY_OP_UNSUPPORTED` there just as it does on
production before the relay is rebuilt (its own distinct UI state, worth checking on purpose during the
deploy-before-rebuild window). To exercise the op itself, build the PR's branch with
`gh workflow run relay-release.yml --ref <branch>` and install that zip on the workstation for the
session - the full procedure, including how the release build gets restored afterwards, is the
"testing a PR that adds a new op" section of `relay/README.md`. It is a manual install by design.

Verified on PR #412 (issue #409's buyer dropdown), in the default disconnected state: the field
rendered `role="combobox"`, disabled, still showing the stored `mira`, with "The GP relay is not
connected, so this cannot be changed right now." - all four assertions met without touching production.

Seeding verified live on PR #421 (#414 itself), against that PR's own environment: setting
`RELAY_SEED_SECRET_HASH` produced exactly one install row labelled `seed:uc-nexus-pr-<N>` (company
TUBC, ENROLLED), the Seed hash cell truncated to 8 chars with a copy button carrying the full 64-char
digest, a provisioned-but-unenrolled row showing `—` and no button, and a second full redeploy still
leaving exactly one seeded row. Note the label takes `RAILWAY_ENVIRONMENT_NAME` verbatim, which on a
PR environment is `uc-nexus-pr-<N>` rather than `pr-<N>`.
