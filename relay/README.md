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
- `GET /vendors` — active PM00200 vendors (VENDORID / VENDNAME / class / status) for the vendor sync, bearer auth. takes `?company=` (defaults to `default_company`)
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
  `list_jobs`, `list_customers`, `list_customer_addresses`, `list_tax_schedules`, `list_divisions`,
  `list_employees`, `read_po_totals`
- writes: `create_po`, `create_receipt`, `create_job`, `create_buyer`

reconnects with exponential backoff on drop; the `websockets` client's default 20s ping/pong keeps the
channel alive through a corporate proxy's idle timeout.

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

the production channel is unrestricted. every other URL is pinned to `TUBC`
(`config.NON_PRIMARY_ALLOWED_COMPANIES`) - reads AND writes are served there, since a PR touching GP
has to be verifiable before it merges, and the company pin is the only thing making that safe. a job
for any other company comes back `company_not_allowed_on_channel` before it reaches GP.

**`TUBC` must also be in `[gp] allowed_companies`.** the channel pin decides what a test backend may
ASK for; `ops.check_company_allowed` still decides what this workstation will serve, and it reads
`[gp] allowed_companies` from config.toml. a workstation set up only for production companies refuses
every PR-environment job with `company_not_allowed`. nothing checks the two lists intersect at startup.

**the backend side of this - `RELAY_SEED_SECRET_HASH` - lives on the PRODUCTION backend service, and a
PR environment inherits it only at creation (#431).** Railway clones a new PR environment from
production, so production is the only place the variable can sit for a PR environment to get it at all;
the production backend refuses to seed and logs that refusal, which is the intended steady state rather
than something to clean up. the copy is taken when the environment is created and is never refreshed
afterwards, so setting it on production does NOT reach a PR environment that already exists - set it on
that environment's own backend service as well (verified 2026-07-30: pr-430 predated the variable and
could not read GP until it had its own copy). seeding runs at backend startup, so either way the change
lands on that service's next deploy.

the URL list is read once at `serve` start, so adding or removing a test backend needs a relay restart
(the app's Restart Relay button). the enrolled secret is still re-read on every reconnect, unchanged,
and a config.toml that fails to parse mid-edit no longer kills the channel - it retries with the last
good settings. the setup wizard preserves a hand-added `[channel]` block, so re-running it will not
silently drop the URL. remove the URL when the PR closes - a torn-down environment retries forever
otherwise (quietly: a non-production channel logs a repeated failure once, then at DEBUG).

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
