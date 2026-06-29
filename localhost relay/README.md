# UC Nexus localhost relay

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
cd "localhost relay"
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
- `GET /cost-codes` — active per-job cost codes from `JC00701` (`cost_code` two-segment number / `description` / real `cost_element`) for the Create PO cost-code dropdown, bearer auth. takes `?job=` (the GP job number = UC Nexus `project_id`, required) and `?company=` like `/vendors`. cost codes are per-job and each carries its own `Cost_Element`, so the `/po` cost_code is `'phase-step-element'` (e.g. `310-000-3`) from the code's own element, not a hardcoded `2`
- `POST /po/next-number` — reserve a PO number via `taGetPONextNumber`, bearer auth
- `POST /po` — create a PO end-to-end via the 5-step orchestration, bearer auth. the request's `buyer_id` (picked from `/buyers`) is validated against `POP00101`; if omitted, falls back to `[gp.buyers]` (`by_host` → `by_login` → `default`). a device hostname is NOT a registered buyer, so it can't be used as one
- `POST /receipt` — receive against a PO (taPopRcptLineInsert xN then taPopRcptHdrInsert, autocosted), and for a company mapped in `[gp.custom_db]` also writes the matching `WHRECLINE101` rows (the custom warehouse table the dashboards read) in the same transaction. needs a `rack_location` per line. bearer auth

browser hop (the cloud frontend → `http://localhost:7321` call) is governed by Chrome Local Network Access from Chrome 142: the frontend fetch must set `targetAddressSpace: "loopback"` and the user grants a one-time loopback permission prompt (or IT pre-grants it via enterprise policy). that is a client-side gate — the relay needs no LNA server header. the relay does echo the legacy `Access-Control-Allow-Private-Network: true` on the preflight for stragglers on a pre-LNA Chrome, but it is not the mechanism.
