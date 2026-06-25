# localhost relay - remaining implementation plan (nexus <-> relay)

where things stand right now (read this first if you're picking this up cold)

the relay is a working FastAPI service at `localhost relay/` in this repo (a sibling to `backend/` and `frontend/`, but deployed on-prem, not on Railway). it bridges UC Nexus to Microsoft Dynamics GP by calling eConnect-registered stored procedures directly via pyodbc. two GP workflows are built and PROVEN end to end:
- PO creation - `POST /po` runs the 5-step orchestration (taGetPONextNumber -> taPoHdr -> taPoLine -> wsiWSCreateUpdatePurchaseOrderIntegration -> taPoHdr subtotal), including the WennSoft job-cost commitment (WS10101 / JC00102 / JC00701). takes a UC-Nexus-supplied PO number (e.g. `ucnexus...`) or reserves GP's next number.
- receiving - `POST /receipt` runs taGetPurchReceiptNextNumber -> taPopRcptLineInsert x N -> taPopRcptHdrInsert, and for UBC/UCSH ALSO writes the custom `WHRECLINE101` rows (in the same transaction) that UC Connects' dashboards read.
both were proven against TUBC (sandbox), and receiving was validated twice on live UBC under explicit one-time approval (PO502088 GP-only, PO502090 GP + PMUBC.WHRECLINE101). PO creation on production is NOT yet validated (no go-ahead given) but is expected to work - same procs / schema / WennSoft config as TUBC.

how to run it (from `localhost relay/`):
- `poetry install` once, then `poetry run uvicorn ucnexus_relay.main:app --app-dir src --host 127.0.0.1 --port 7321`
- config is `config.toml` (gitignored - holds the bearer secret, the SQL target `10.0.0.246,1435` reached via ODBC Driver 17 + Windows SSPI, the company allowlist, and the `[gp.custom_db]` map). `config.example.toml` is the committed template.
- endpoints: `/health`, `/info` (read-only identity probe), `/po/next-number`, `/po`, `/receipt`. all but `/health` require `Authorization: Bearer <secret>`.
- code map: `src/ucnexus_relay/` - `main.py` (routes), `econnect.py` (all proc wrappers + the WHRECLINE101 insert + PO-read helpers), `db.py` (pyodbc + `SET NOCOUNT ON`), `models.py`, `auth.py`, `cors.py`, `config.py`, `errors.py`.

hard guardrails, do NOT break:
- GP writes go ONLY through eConnect-registered procs. NO direct INSERT/UPDATE/DELETE on GP business-logic tables. the ONE sanctioned exception is `PMUBC/PMUCSH.WHRECLINE101`, a custom data-store table with no procs - the legacy app wrote it with a plain INSERT, so the relay does too, and that does not bypass GP business logic.
- the company allowlist is SANDBOXES-ONLY (TUBC/TUCSH) by default. UBC/UCSH (production) get added ONLY for a specific user-approved run and removed/re-locked immediately after. never leave production in the allowlist.
- the WHRECLINE101 dual-write only engages for companies mapped in `[gp.custom_db]` (UBC->PMUBC, UCSH->PMUCSH). sandboxes have no paired PM database, so TUBC/TUCSH are GP-only with zero UC Connects dependency.
- all GP discovery stays read-only unless the user explicitly authorizes a write; pause for explicit OK before any first live write on a new company.

gotchas already solved - do not re-derive; the long-form detail is in `../relay to from gp/localhost-relay.md`:
- pyodbc + eConnect needs `SET NOCOUNT ON` on the session, or the trailing `SELECT @err` after an EXEC fails.
- `taPoLine` can't set Product_Indicator; the wsi proc must run for EVERY line (PI=1 non-inv / PI=2 job cost).
- the trailing digit of a cost code (`210-200-2`) is the `Cost_Element`, not COSTTYPE (which stays 0).
- PO lines must be created Released (`@I_vPOLNESTA=2`), or the wsi proc commits zero job cost.
- receiving: lines go in BEFORE the header (eConnect processes lines first), and the header SUBTOTAL must equal the sum of the autocosted lines (`AUTOCOST=1`, line cost 0).
- GP stores PONUMBER uppercase; receiving validates against REMAINING qty (ordered minus already-received), not just ordered.

test artifacts already in the systems: TUBC POs PO0000042-44 + UCNEXUS0000001 (+ receipts RC0000038/39); live UBC PO502088 (GP-only receipts) and PO502090 (GP + PMUBC.WHRECLINE101), both received in full into unposted `POC-*` batches for accounting to post.

the next concrete step is sequencing step 1 below: add the relay's Private-Network-Access preflight handling, then build the minimal frontend relay-client + presence detection and prove the browser -> localhost -> GP hop against TUBC.

the rest of this doc is the plan for that remaining work.

the relay-to-from-gp half is built and proven: PO creation and receiving against GP via eConnect, including the WHRECLINE101 sync to PMUBC so receives show on UC Connects' dashboards. that work and all its references live in `../relay to from gp/`. what's left, and what this doc plans, is the OTHER half - getting UC Nexus (the cloud web app) to actually talk to the relay, plus the on-prem deployment that makes the relay real for end users.

the one hop we have NOT exercised yet is a browser on a corporate workstation making a cross-origin `https -> http://localhost:7321` call to the relay. everything to date has hit the relay from curl/PowerShell on the same machine. proving that browser hop is the heart of this phase.

the communication model everything below assumes

- UC Nexus's frontend runs in the user's browser. when the user creates a PO or receives goods, the frontend does `fetch('http://localhost:7321/po', { headers: { Authorization: 'Bearer <secret>' }, body: ... })`.
- the relay is on the SAME workstation, bound to 127.0.0.1:7321, holding the GP connection. it runs the eConnect procs and returns the result.
- the UC Nexus cloud backend (Railway) is NOT in the GP path - it can't reach a user's localhost. it stays involved only for UC Nexus's own data: after the relay returns, say, the new PO number, the frontend posts that to the backend to record it against the UC Nexus order.
- so it's two independent calls from the frontend per action: one to the relay (the live GP write), one to the UC Nexus backend (UC Nexus's own tracking).
- this only works where the browser and the relay are the same machine. so the relay has to run on the workstations where people do purchasing / receiving - the same stations that run GP and the Excel macro today.

workstream A - the UC Nexus frontend relay client

- a small relay-client module in the frontend: typed wrappers over the relay endpoints (`/health`, `/info`, `/po`, `/po/next-number`, `/receipt`), the bearer header, JSON, and error mapping. the relay returns structured errors (`econnect_error` with proc + error_state, the pydantic validation errors, `qty_exceeds_remaining`, `line_not_receivable`, `po_not_found`) - surface these as readable, actionable messages rather than raw 5xx.
- relay presence detection: background-ping `/health` on the PO and receiving pages and drive UI off it. relay up -> show the GP actions; relay down / not installed -> a banner like "GP relay not detected on this machine"; version mismatch -> read `/info` and warn. this is what stops a confusing silent failure when the relay isn't running.
- the shared secret: each install has its own. a per-user secret issued and stored by the UC Nexus backend, fetched by the frontend at runtime, is cleaner than the user pasting it into a local setting. it must NOT be hardcoded or committed.
- wire the PO-creation form: on submit, call the relay `/po`, show the returned GP PO number, then record it against the UC Nexus order via the backend. handle the relay-down case explicitly (block + message, not a half-saved order).
- wire receiving: the flow calls `/receipt` per receive, carrying the rack location and the multi-receive splitting, and shows received vs remaining (the relay now enforces remaining, so the UI should reflect it).

workstream B - the browser-to-localhost wrinkles to handle

- CORS: the relay already allows the UC Nexus Railway origin plus the localhost dev origins. confirm the preflight OPTIONS for the `/po` and `/receipt` POSTs (which carry the Authorization header) actually passes from the real origin.
- Chrome Private Network Access: chrome is tightening public-site -> localhost requests. the relay will need to answer the PNA preflight - respond to the OPTIONS with `Access-Control-Allow-Private-Network: true` when the request carries `Access-Control-Request-Private-Network`. this belongs in the relay's CORS handling, and it is the single most likely thing to silently break the browser hop if we skip it.
- secure context: `http://localhost` is exempt from mixed-content blocking, so the https UC Nexus page is allowed to call it. verify this holds across the exact browsers/versions the warehouse and purchasing users run, not just one dev machine.

workstream C - relay deployment on-prem

- packaging: a PyInstaller `ucnexus-relay.exe` or a proper Windows service, set to start on logon/boot on each workstation that does PO/receiving.
- GP auth in production: the POC connects via a personal Windows login (jayp, in DYNGRP). production should use a DEDICATED service account with narrow grants - EXECUTE on the eConnect proc surface and the wsi proc, SELECT on the read tables and `DYNAMICS.taErrorCode`, INSERT on `PMUBC`/`PMUCSH.WHRECLINE101` - not a personal account. decide whether the relay runs AS that service account or uses the workstation's own domain user for SSPI.
- config + secret: ship `config.toml` per install with that install's secret and the company allowlist; once past testing the allowlist is the production companies (UBC/UCSH). protect the secret at rest (DPAPI) rather than plaintext for a real rollout.
- scope: which workstations get the relay - the purchasing PC, the BC warehouse receiving station, and whichever others actually create POs or receive.

workstream D - remaining relay hardening

the cumulative over-receipt guard is done. still open: uniform error-response shapes across all endpoints, checking client-supplied PO numbers against history (`POP30100`) not just active POs, USD PO handling (~3% of real POs - the relay assumes CAD today), and the production service-account swap from workstream C.

sequencing

1. relay-side prep: add the PNA preflight handling and confirm CORS for the real origin. small, and it unblocks the browser hop.
2. minimal frontend relay-client + presence detection, wire ONE operation (PO create) end to end, and prove browser -> localhost -> GP against TUBC from an actual browser.
3. wire receiving (with rack location) end to end.
4. deployment: package the relay, stand up the service account, provision the secret, on one workstation.
5. roll out to the purchasing / warehouse stations and flip the allowlist to production with per-site sign-off.

simulated user testing

this verifies the browser hop, which is the genuinely new piece. prerequisites: the relay running locally on the test machine with TUBC in the allowlist, and UC Nexus (Railway) open in a browser on that same machine. driving the UC Nexus page with Chrome DevTools MCP:

- navigate to the PO-creation page. expect the relay-presence indicator to read "connected" (the page's background `/health` ping succeeded).
- fill a PO (vendor, one job-cost line) and submit. expect a GP PO number back within a second or two, shown in the UI, with NO console errors and no CORS / mixed-content / PNA failures on the `http://localhost:7321/po` request - check the network panel that the OPTIONS preflight and the POST both succeed.
- verify read-only in TUBC that the PO landed (POP10100/POP10110, plus WS10101/JC for the job line).
- stop the relay process and reload. expect the presence indicator to flip to "relay not detected" and the GP action to be blocked with a clear message, not a silent hang.
- restart the relay, perform one receive against that PO with a rack location, and confirm the received quantities show in the UI and land in TUBC.

the same script is the gate for any production run, against UBC/UCSH only with explicit approval and the production allowlist - exactly the manual pattern we used for the receiving validations on PO502088 and PO502090.
