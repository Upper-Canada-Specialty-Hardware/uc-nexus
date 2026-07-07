# UC Nexus localhost relay

bridges UC Nexus (cloud, Railway) to Microsoft Dynamics GP on the corporate network. UC Nexus
runs in the browser and can't reach the on-prem SQL server, and the relay sits behind corporate
NAT with no public inbound, so the connection is relay -> backend, not backend -> relay: this
relay runs on a machine inside the network and dials an outbound WebSocket to the UC Nexus
backend's `/relay-link` endpoint, then services GP job frames the backend pushes down that socket
- reading/writing GP by calling the eConnect-registered stored procedures directly via pyodbc. No
browser ever talks to this relay directly; the backend is the only client.

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
cp config.example.toml config.toml          # then set [auth] shared_secret and [backend] url
poetry install
```

`[backend] url` is the `wss://` address of the backend's `relay-link` endpoint (issue #189) - the
socket this relay dials out to on every boot. it is separate from the `--backend-url` below, which
is the one-time enrollment mutation's `https://.../graphql` address.

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
relay afterwards. this same secret is sent as the `Authorization: Bearer` header on the outbound
`relay-link` WebSocket handshake - it's never baked into the frontend build.

set the secret by hand instead? put a plaintext `[auth] shared_secret` in `config.toml`, then run
`python -m ucnexus_relay.protect_secret` (or `ucnexus-relay.exe protect-secret`) to DPAPI-encrypt it in
place. on read the relay decrypts an `enc:dpapi:` value transparently and passes a plaintext value through
unchanged, so dev configs keep working.

run (dev)
```
poetry run python -m ucnexus_relay serve
```
this starts both the outbound `relay-link` channel and a local `/health` HTTP listener in the same
process (`ucnexus_relay.cli._serve`). there's no standalone `uvicorn ucnexus_relay.main:app` path
anymore - the channel wouldn't start that way.

on a deployed workstation you don't run this by hand - the packaged `ucnexus-relay.exe serve` is launched
at logon by a scheduled task and restarts on failure. see `docs/relay-deployment.md`.

smoke (no GP)
```
curl http://localhost:7321/health
```
GP connectivity (channel connected, jobs dispatched) shows up in the relay log (`[logging] file` in
`config.toml`), not over HTTP - there is no local GP-facing endpoint left to curl. `create_po` and
`create_receipt` perform live eConnect writes against TUBC when dispatched by the backend - see the
phase gates in `docs/relay-poc-next-steps.md` before exercising them.

test
```
poetry run pytest          # channel dispatch + auth/validation gates, mocked - never touches GP
poetry run ruff check src tests
```

inbound HTTP
- `GET /health` — liveness, no auth. the only inbound surface; no GP work happens over HTTP anymore

outbound channel ops (dispatched by the backend over the `relay-link` WebSocket; see `channel.py`)
- `list_vendors` — active PM00200 vendors (VENDORID / VENDNAME / class / status)
- `list_buyers` — registered GP buyers (`POP00101`). eConnect validates `BUYERID` against this, so a `create_po` buyer must come from here
- `list_cost_codes` — active per-job cost codes from `JC00701` (`cost_code` two-segment number / `description` / real `cost_element`) for one job (`payload.job`, required). cost codes are per-job and each carries its own `Cost_Element`, so `create_po`'s cost_code is `'phase-step-element'` (e.g. `310-000-3`) from the code's own element, not a hardcoded `2`
- `list_jobs` — the job/project master `JC00102` (job number + display name), left-joined to `JC00901` for an active/inactive status
- `create_po` — create a PO end-to-end via the 5-step orchestration. `payload.header.buyer_id` (picked from `list_buyers`) is validated against `POP00101`; if omitted, falls back to `[gp.buyers]` (`by_host` → `by_login` → `default`). a device hostname is NOT a registered buyer, so it can't be used as one
- `create_receipt` — receive against a PO (`taPopRcptLineInsert` xN then `taPopRcptHdrInsert`, autocosted), and for a company mapped in `[gp.custom_db]` also writes the matching `WHRECLINE101` rows (the custom warehouse table the dashboards read) in the same transaction. needs a `rack_location` per line

every op reply is `{id, ok: true, result}` or `{id, ok: false, error: {error, message, context}}` -
the same three-key error envelope every op used to raise as an HTTP `detail`.
