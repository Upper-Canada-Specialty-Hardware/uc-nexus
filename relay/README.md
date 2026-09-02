# UC Nexus relay

bridges UC Nexus (cloud, Railway) to Microsoft Dynamics GP on the corporate network. UC Nexus
runs in the browser and can't reach the on-prem SQL server; this relay runs on a machine inside
the network, takes HTTP from UC Nexus, and creates POs in GP by calling the eConnect-registered
stored procedures directly via pyodbc.

the design + full reference is in `docs/localhost-relay.md`. the POC gate + auth notes are in
`docs/relay-poc-next-steps.md`. per-workstation deployment - auto-start at logon + DPAPI-protected
secret, packaged as a single `ucnexus-relay.exe` - is in `docs/relay-deployment.md`.

hard rule: every GP write goes through an EXEC of an eConnect-registered proc (`taPo*`,
`taGetPONextNumber`, `wsiWS*`). no direct INSERT/UPDATE/DELETE against GP tables, ever.

prerequisites
- Python 3.11
- Poetry
- an ODBC driver for SQL Server. Driver 17 or 18 both work; set which one in `config.toml` under `[sql] driver`.
- the machine must be able to authenticate to GP. on a domain-joined box that's just Windows SSPI
  (`Trusted_Connection=yes`) as a user who is in GP's DYNGRP role — no password stored anywhere.

setup
```
cd relay
cp config.example.toml config.toml          # then set [auth] shared_secret
poetry install
```

enrollment (one-time, gets the relay's Bearer secret without hand-copying it)

the relay's `[auth] shared_secret` can be set by hand, or provisioned from UC Nexus so nothing long-lived
is pasted. in UC Nexus an admin runs "provision relay install" and gets a one-time enrollment token. then,
on this workstation:
```
poetry run python -m ucnexus_relay.enroll --token <ENROLLMENT_TOKEN> --backend-url https://<backend-host>/graphql
```
the relay generates its own long-lived secret, registers it with the backend using that one-time token
(the backend can't reach the relay, but the relay can reach the backend), and writes the secret into
`config.toml` DPAPI-encrypted at rest (CurrentUser scope; see `src/ucnexus_relay/dpapi.py`). restart the
relay afterwards. the frontend then fetches the same secret at runtime via the `relayCredential` query -
it's never baked into the build.

set the secret by hand instead? put a plaintext `[auth] shared_secret` in `config.toml`, then run
`python -m ucnexus_relay.protect_secret` (or `ucnexus-relay.exe protect-secret`) to DPAPI-encrypt it in
place. on read the relay decrypts an `enc:dpapi:` value transparently and passes a plaintext value through
unchanged, so dev configs keep working.

run (dev)
```
poetry run uvicorn ucnexus_relay.main:app --app-dir src --host 127.0.0.1 --port 7321
# or via the CLI dispatcher (same entry point the packaged exe uses):
poetry run python -m ucnexus_relay serve
```

on a deployed workstation you don't run this by hand - the packaged `ucnexus-relay.exe serve` is launched
at logon by a scheduled task and restarts on failure. see `docs/relay-deployment.md`.

smoke (no GP)
```
curl http://localhost:7321/health
curl -H "Authorization: Bearer <shared_secret>" http://localhost:7321/info
```

`/info` does a read-only identity probe against GP (who are we connected as, DYNGRP membership).
`/po/next-number`, `/po`, and `/receipt` perform live eConnect writes against TUBC - see the
phase gates in `docs/relay-poc-next-steps.md` before running them.

test
```
poetry run pytest          # health + auth only; never touches GP
poetry run ruff check src tests
```

endpoints
- `GET /health` — liveness, no auth
- `GET /info` — config + read-only SQL identity + the workstation `hostname` and the `resolved_buyer` that hostname maps to, bearer auth
- `GET /vendors` — active PM00200 vendors (VENDORID / VENDNAME / class / status) for the vendor sync, bearer auth. takes `?company=` (required - there is no default company)
- `GET /buyers` — registered GP buyers (`POP00101`) for the Create PO buyer dropdown, bearer auth. `?company=` like `/vendors`. eConnect validates `BUYERID` against this, so the UI must pick from it
- `GET /cost-codes` — active, account-usable per-job cost codes from `JC00701` (`cost_code` two-segment number / `description` / real `cost_element`) for the Create PO cost-code dropdown, bearer auth. takes `?job=` (the GP job number = UC Nexus `project_id`, required) and `?company=` like `/vendors`. cost codes are per-job and each carries its own `Cost_Element`, so the `/po` cost_code is `'phase-step-element'` (e.g. `310-000-3`) from the code's own element, not a hardcoded `2`. codes whose `WS_Account_Index_1` is non-zero and absent from `GL00105` are excluded (#425) - a PO on one registers but can never be received, and the `create_po` `cost_code_account_invalid` guard refuses it anyway
- `POST /po/next-number` — reserve a PO number via `taGetPONextNumber`, bearer auth
- `POST /po` — create a PO end-to-end via the 5-step orchestration, bearer auth. the request's `buyer_id` (picked from `/buyers`) is validated against `POP00101`; if omitted, falls back to `[gp.buyers]` (`by_host` → `by_login` → `default`). a device hostname is NOT a registered buyer, so it can't be used as one
- `POST /receipt` — receive against a PO (taPopRcptLineInsert xN then taPopRcptHdrInsert, autocosted), and for a company mapped in `[gp.custom_db]` also writes the matching `WHRECLINE101` rows (the custom warehouse table the dashboards read) in the same transaction. needs a `rack_location` per line. bearer auth

browser hop (the cloud frontend → `http://localhost:7321` call) is governed by Chrome Local Network Access from Chrome 142: the frontend fetch must set `targetAddressSpace: "loopback"` and the user grants a one-time loopback permission prompt (or IT pre-grants it via enterprise policy). that is a client-side gate — the relay needs no LNA server header. the relay does echo the legacy `Access-Control-Allow-Private-Network: true` on the preflight for stragglers on a pre-LNA Chrome, but it is not the mechanism.

outbound channel (additive - the HTTP endpoints above are unchanged)

alongside the inbound HTTP server, `ucnexus-relay serve` also dials OUT to the backend over a
persistent `wss://` connection (`src/ucnexus_relay/channel.py`), authenticating with `[auth]
shared_secret` on the connect handshake. the backend's `relay_call(company, op, payload)` sends a job
down that socket as `{id, op, company, payload}`; the relay answers `{id, ok, result|error}` by
running the same eConnect logic the HTTP routes use (`ops.py` holds the shared `create_po`/
`create_receipt` orchestration). set `[channel] backend_url` in `config.toml` to enable it; leave it
blank to run HTTP-only, as before. op dispatch (`_OPS` in `channel.py`, which is also what the relay
advertises to the backend on connect so an out-of-date relay is caught before the round-trip):
- reads: `list_vendors`, `list_buyers`, `list_buyers_detailed`, `list_tax_details`, `list_cost_codes`,
  `list_cost_code_master`, `list_jobs`, `list_customers`, `list_customer_addresses`,
  `list_tax_schedules`, `list_divisions`, `list_employees`, `read_po_totals`
- writes: `create_po`, `create_receipt`, `create_job`, `create_buyer`

`create_job` also provisions the job's cost codes (#448): `wsiJCJobMaster` writes only the `JC00102`
row, so a job created without them has no `JC00701` cost structure at all - an empty register-PO
dropdown and an instant #425 quarantine - and the codes named in the request's `cost_codes` are written
with `wsiJCJobDetailMSTR` in the same transaction, every value taken from the company master
(`JC40202`, account index from `JC40302` for the job's division) rather than from the request.

reconnects with exponential backoff on drop; the `websockets` client's default 20s ping/pong keeps the
channel alive through a corporate proxy's idle timeout.

which companies this relay serves

read from GP itself - the company master `DYNAMICS..SY01500` (`[sql] system_db`), by
`src/ucnexus_relay/companies.py`. nothing to maintain in config.toml, and nothing to edit in the
source when a company is added in GP. the set is re-read on every channel connect and every 15 minutes
while a channel is up, and each hello frame carries it as `companies` + `company_names`; a changed set
re-sends the hello on the same socket. a relay that cannot read the master serves NO company - the
frame carries `companies_error` and every op is refused with `company_not_allowed` quoting it.

more than one backend (#414)

the relay holds one independent reconnecting channel per configured URL. that exists so a Railway PR
environment can be tested without re-pointing the workstation: production's connection is never
dropped, and the same enrolled secret authenticates on every channel (the backend matches on its hash,
and a PR environment is seeded with that hash via `RELAY_SEED_SECRET_HASH` rather than issued a
credential of its own).

**add a test backend with `extra_backend_urls`, naming only the new one:**

```toml
[channel]
extra_backend_urls = ["wss://backend-pr-414.up.railway.app/relay-link"]
```

production's URL comes from the baked default and is never retyped, which matters more than it looks:
whether a channel is production is decided by matching `config.PRODUCTION_BACKEND_URL`, so one wrong
character in a hand-typed production URL makes the PRODUCTION channel non-primary and every real
UBC/UCSH job is refused. `backend_url` does also accept a list (a bare string, the pre-#414 shape,
still means exactly one channel), but overriding it means retyping production alongside the new URL -
the one way to express that mistake. the relay logs a WARNING at startup when no configured channel is
the production one.

the production channel is unrestricted. every other URL is pinned to the sandboxes `TUBC` and `TUCSH`
(`config.NON_PRIMARY_ALLOWED_COMPANIES`) - reads AND writes are served there, since a PR touching GP
has to be verifiable before it merges, and the company pin is the only thing making that safe. a job
for any other company comes back `company_not_allowed_on_channel` before it reaches GP. both sandboxes
are in the pin because UCSH-side work is only reproducible against TUCSH, and the alternative is aiming
a PR backend at live UCSH.

the sandbox the PR is testing has to exist in GP. the channel pin decides what a test backend may ASK
for; `ops.check_company_served` decides what this workstation will serve, and that set is read from
GP's own company master (`companies.py`), not configured. a company GP does not hold is refused with
`company_not_allowed`.

**the backend side of this - `RELAY_SEED_SECRET_HASH` - lives on the PRODUCTION backend service, and a
PR environment inherits it only at creation (#431).** Railway clones a new PR environment from
production, so production is the only place the variable can sit for a PR environment to get it at all;
the production backend refuses to seed and logs that refusal, which is the intended steady state rather
than something to clean up. the copy is taken when the environment is created and is never refreshed
afterwards, so setting it on production does NOT reach a PR environment that already exists - set it on
that environment's own backend service as well (verified 2026-07-30: pr-430 predated the variable and
could not read GP until it had its own copy). seeding runs at backend startup, so either way the change
lands on that service's next deploy.

**adding or removing a URL takes effect on its own, within about ten seconds (#456).** the supervisor
re-reads config.toml on a tick and reconciles its channel set against it: a URL that appears gets a
channel, a URL that disappears has its channel cancelled and its `/health` row dropped. no restart, and
production's channel is never touched either way. it used to need the app's Restart Relay button, which
is a click nobody could automate - and since a preview environment's database is empty, nothing at all
is testable there until the channel is up, because the project list comes from GP.

a hand-added URL still has to be removed when you are done with it: the channel goes away when you do,
and until then a torn-down environment retries forever (quietly - a non-production channel logs a
repeated failure once, then at DEBUG). the enrolled secret is re-read on every reconnect as before, and
a config.toml caught mid-write kills neither: the channels keep dialling with the last good settings and
the finished edit lands on the next tick. the setup wizard preserves a hand-added `[channel]` block, so
re-running it will not silently drop the URL.

**a re-enrolment now takes effect on a live channel too.** `_run_channel` re-reads the secret before
every dial, so a channel that is DOWN heals itself, but a CONNECTED one holds a socket authenticated
with the old secret and would never dial again to find out - which reads as "enrolled fine, still not
working". the supervisor records a hash of the secret each channel connected with, and restarts any
channel whose hash no longer matches config.toml, logging a WARNING with `category: secret_changed`.

preview environments (no longer configured here at all)

**production pushes the preview list; nothing on this workstation names it.** production knows which
Railway PR environments exist and pushes the full list down the socket it already holds, as a
`{"type": "channels", "urls": [...]}` frame - once after the relay's hello, then again whenever the list
changes. the relay unions it with whatever config.toml names and dials the difference within about a
second. a URL that stops being listed has its channel cancelled, so a closed PR's environment stops
being dialled without anyone touching this machine.

what the relay will accept off that frame is narrow, on purpose - this process holds GP credentials, so
"the backend said so" is not on its own a reason to dial a host:

- only `wss://backend-uc-nexus-pr-<N>.up.railway.app/relay-link`, matched whole. anything else is
  dropped with a WARNING naming it (`category: pushed_channels_rejected`)
- only off the PRODUCTION channel. a preview backend that could name the next backend to dial would be
  able to walk the relay onto a host of its choosing, so a frame from anywhere else is ignored
- never production's own URL, so a pushed channel is always non-primary and always carries the sandbox
  company pin

`accept_pushed_preview_backends = false` under `[channel]` turns the whole thing off and the relay dials
exactly what config.toml names. that key used to be `discover_preview_backends`, from when the relay
polled production over https for the same list; the old name still loads and still means the same thing,
so a config.toml written before the push model needs no edit. the relay advertises `features:
["channels"]` on its hello frame, which is how the backend knows a build will understand a push at all.

`extra_backend_urls` still works and still only ADDS. it is now for what production cannot know about: a
local dev backend, or anything outside the Railway project.

the ops newer than `create_po` / `create_receipt` are channel-only - they have no HTTP route, because
the browser hop is no longer the live path.

testing a PR that adds a new op (#431)

`extra_backend_urls` above gets a PR environment served by the relay already installed on the
workstation, but that relay is the published release build: an op the PR adds to `_OPS` does not exist
in it, so the backend refuses the call off the advertised op-set with `RELAY_OP_UNSUPPORTED` before it
is even sent (#315). testing that op end to end needs a relay built from the PR's branch, installed on
the workstation for the length of the session. the install step is manual on purpose - nothing reaches
the workstation remotely.

1. **build it**: `gh workflow run relay-release.yml --ref <branch>`. any branch in this repo works (a
   fork's branch cannot be dispatched; the workflow definition used is the one on that branch). the run
   builds the same onedir bundle and uploads it as a workflow artifact - a dispatch publishes NO
   Release, so no other workstation ever sees it.
2. **download it**: `gh run download <run-id>`. the artifact is named
   `ucnexus-relay-zip-relay-v<version>-branch.<branch>.<sha>`, so two branch builds cannot be swapped by
   accident.
3. **install it over the release build**: quit the relay app first (X on the window, then confirm - the
   installer deletes the app folder the running exe holds open), then `install\install-relay-user.ps1
   -ZipPath <the zip> -StartNow` (or `install-relay.ps1` on an admin/scheduled-task install). it
   re-extracts the bundle, repoints the `current` junction, and leaves `config.toml` and the enrolled
   DPAPI secret alone, so no re-enrollment is involved. Admin -> Relay Installs reports the live build
   tag - confirm it reads `relay-v<version>-branch.<branch>.<sha>` before testing anything.
4. **restore the release build** when the session is done: re-run the same installer with
   `ucnexus-relay.zip` from the latest `relay-v*` GitHub Release, or press Update now on the app's
   Updates tab. a branch build is stamped without a `build.<N>` number, so every release counts as newer
   than it and the update is offered rather than refused as a downgrade.

that last point cuts both ways, deliberately: the app's auto-update poller reads the branch build as
behind too, so it will pull the workstation back to the latest release on its own - first check 10-15
minutes after the app starts, daily after that. a branch build therefore cannot quietly become the
fleet's permanent build, but a long session can have the build swapped underneath it. if a run suddenly
starts answering `RELAY_OP_UNSUPPORTED` again, check the build tag before anything else and re-install
the branch zip.

release channels

each workstation takes one of two channels, set in `config.toml`:

```toml
[update]
channel = "latest"   # this workstation proves a build before it is promoted; default is "stable"
```

- `stable` (the default) - full GitHub Releases only. a release flagged PRERELEASE is skipped even when
  it is the higher build.
- `latest` - prereleases too.

that is the promote step, and the whole point of it: CI cuts a relay release as a prerelease, the one
workstation on `latest` installs it and proves it against GP, and `gh release edit <tag>
--prerelease=false` is what hands it to everyone else. nothing else about update selection changes -
highest build number wins and a downgrade is never offered, so promoting is the only action that moves
the fleet. an unknown channel value is read as `stable` with a WARNING in relay.log naming it, rather
than refused - a typo in this one key must not make config.toml unreadable and keep serve from starting.

post-update self-check and rollback

the apply helper health-gates its relaunch, but `/health` answers as soon as uvicorn binds - which says
nothing about whether the new build can still reach the backend. a build that starts cleanly and never
connects would therefore record `success` and leave the workstation dark, with nobody on site to notice.

so the first app start after an update lands watches for up to five minutes:

- `/health` reports the backend channel connected -> the ledger is stamped and that is the end of it
- it never connects, and a previous `app-<build>\` folder is still on disk -> the `current` junction is
  repointed back to it, the serve child is restarted from that junction (not from the running exe, which
  IS the build being rolled back), and `update-state.json` records `rolled_back` with the reason
- it never connects and there is no previous version left -> the build stays; a broken channel beats no
  relay at all

after a rollback the poller refuses to stage that same build again, so the workstation does not walk
through the same install and the same five minutes offline every day. publish a higher build to escape
it, exactly as with a failed install.

the check runs ONCE per update - its verdict is stamped on `update-state.json` - so a workstation that
happens to boot offline a week later cannot roll a good build back. an unenrolled relay dials no channel
by design, and that is recorded as `no_channel` rather than judged as a bad build.

fixture mode / stub relay

the relay can run with no GP at all, answering every channel op out of a checked-in snapshot of the
TUBC and TUCSH sandbox companies (`src/ucnexus_relay/fixture_ops.py`, `fixtures/gp-snapshot.json`).
that is what makes a Railway preview environment testable on its own: nothing relay-dependent works
there until a relay dials it, and the workstation is a physical machine somebody has to be sitting at.
in fixture mode the relay is a Linux container the preview environment brings up itself - no GP, no
ODBC driver, no pyodbc.

the op set is identical: same names, same result shapes, same error codes, so the backend cannot tell
the difference and nothing backend-side is conditional on it. writes are real within the process -
`create_po` reserves the next PO number in GP's shape (suffix rules included) and appends the PO,
`create_receipt` moves the received quantities on it, and `sync_pos` / `read_po_totals` then see both.
nothing is written back to the snapshot file, so a container restart is a clean company again.

what it is NOT: a test of GP. no eConnect proc runs, so a change to the eConnect call path is not
verified by anything a fixture relay does. that still needs the workstation - see "testing a PR that
adds a new op" above.

configuration is entirely environment variables, because a container has no config.toml to enroll and
no DPAPI to decrypt with. each one wins over the file when there is one:

- `UCNEXUS_RELAY_MODE` - `fixture`, or `sql` (the default) for the workstation relay, unchanged
- `UCNEXUS_RELAY_FIXTURE_PATH` - the snapshot to serve; unset means the bundled `fixtures/gp-snapshot.json`
- `UCNEXUS_RELAY_SHARED_SECRET` - the channel secret, PLAINTEXT. never DPAPI-decrypted, so an
  `enc:dpapi:` value in a config.toml carried into the image is replaced rather than choked on
- `UCNEXUS_RELAY_BACKEND_URL` - the `wss://.../relay-link` to dial
- `UCNEXUS_RELAY_LOG_FILE` - `-` for stdout only, so nothing is written to an ephemeral filesystem

```
docker build -f Dockerfile -t ucnexus-relay-fixture .
docker run --rm \
  -e UCNEXUS_RELAY_BACKEND_URL=wss://backend-pr-999.up.railway.app/relay-link \
  -e UCNEXUS_RELAY_SHARED_SECRET=<the secret that environment's RELAY_SEED_SECRET_HASH was seeded from> \
  ucnexus-relay-fixture
```

the GP-touching HTTP routes (`/info`, `/vendors`, `/buyers`, `/tax-details`, `/cost-codes`, `/po`,
`/po/next-number`, `/receipt`) answer `503` with error `fixture_mode` there. the outbound channel is
the transport this mode serves, and the browser hop is no longer the live path anyway. `/health`
answers normally.

replacing the snapshot with real sandbox data

the checked-in file is synthetic, hand-written so the container has something to serve on day one. to
swap it for the real TUBC/TUCSH, run this on the workstation - the only machine that can reach GP -
and commit what it writes:

```
poetry run python -m ucnexus_relay capture --companies TUBC,TUCSH --out fixtures/gp-snapshot.json
```

read-only throughout: every call is one of the `list_`/`read_` handlers the channel already serves.
three things GP holds have no read op and are derived instead - a job's usable cost codes are stored at
account index 0 while only the codes `job_setup_health` already calls broken keep their dangling index
(so #425 still reproduces), PO lines are stored at index 0 and are therefore receivable, and the PO
counter starts one past the highest number captured. `capture.py` says which is which.

the same per-company record is served over the channel as the `capture_snapshot` op, and the backend
exposes it to admins as the `relaySnapshot` GraphQL query - so a re-capture is a query against
whichever relay is connected, and nobody has to be at the workstation to run it. the query assembles
the identical envelope and hands back the file's text, ready to write over `fixtures/gp-snapshot.json`.
a stub relay answers the op from its own fixture, so running it against a preview gives back what that
preview was built with.
