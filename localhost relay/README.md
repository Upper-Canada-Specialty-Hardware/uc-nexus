# UC Nexus localhost relay

bridges UC Nexus (cloud, Railway) to Microsoft Dynamics GP on the corporate network. UC Nexus
runs in the browser and can't reach the on-prem SQL server; this relay runs on a machine inside
the network, takes HTTP from UC Nexus, and creates POs in GP by calling the eConnect-registered
stored procedures directly via pyodbc.

the design + full reference is in `docs/localhost-relay.md`. the POC gate + auth notes are in
`docs/relay-poc-next-steps.md`.

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
`config.toml`. restart the relay afterwards. the frontend then fetches the same secret at runtime via the
`relayCredential` query - it's never baked into the build.

run
```
poetry run uvicorn ucnexus_relay.main:app --app-dir src --host 127.0.0.1 --port 7321
```

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
- `POST /po/next-number` — reserve a PO number via `taGetPONextNumber`, bearer auth
- `POST /po` — create a PO end-to-end via the 5-step orchestration, bearer auth. `buyer_id` is optional in the request — when omitted the relay fills `BUYERID` from the workstation via `[gp.buyers]`, resolving `by_host` (explicit map) → `by_login` → `use_hostname` (the device's own traceable name) → `default`
- `POST /receipt` — receive against a PO (taPopRcptLineInsert xN then taPopRcptHdrInsert, autocosted), and for a company mapped in `[gp.custom_db]` also writes the matching `WHRECLINE101` rows (the custom warehouse table the dashboards read) in the same transaction. needs a `rack_location` per line. bearer auth

browser hop (the cloud frontend → `http://localhost:7321` call) is governed by Chrome Local Network Access from Chrome 142: the frontend fetch must set `targetAddressSpace: "loopback"` and the user grants a one-time loopback permission prompt (or IT pre-grants it via enterprise policy). that is a client-side gate — the relay needs no LNA server header. the relay does echo the legacy `Access-Control-Allow-Private-Network: true` on the preflight for stragglers on a pre-LNA Chrome, but it is not the mechanism.
