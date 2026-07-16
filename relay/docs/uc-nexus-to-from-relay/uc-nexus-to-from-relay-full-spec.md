# uc nexus to from relay - full spec

this is the full spec for the nexus <-> relay half of the relay work. the relay <-> gp half
(PO create + receiving against GP via eConnect, including the WHRECLINE101 sync) is built and proven and
lives in `../relay-to-from-gp/`. the shorter `nexus-relay-implementation-plan.md` in this same folder is
the earlier sketch; this doc supersedes it for the nexus-side work and is exhaustive enough to build from.

what this half has to do: get UC Nexus's cloud frontend (Railway) to drive the on-prem relay so that
creating a purchase order in UC Nexus ALSO creates the real job-cost PO in Microsoft GP in one action,
and receiving in UC Nexus posts the GP receipt - then deploy the relay on the workstations that actually
do purchasing and receiving. the one hop never exercised yet is a browser on a corporate workstation
making a cross-origin call from the https Railway page to `http://localhost:7321`. proving that hop, in
the browsers these users actually run, is the heart of this phase.

the decisions this spec is built on (locked with the user, june 2026):
- the relay GP write is auto-called INSIDE the Create PO submit. one click records the UC Nexus PO and
  creates the GP PO. it is not a separate "push to GP" action on an existing PO.
- the first end-to-end proof creates a REAL job-cost PO (Product_Indicator 2) on TUBC, not a stripped
  non-inventoried PO. so the GP field mapping is in scope from the start, not deferred.
- the relay bearer secret is backend-issued per install. UC Nexus's backend issues and stores it; the
  frontend fetches it at runtime; the relay validates it. no pasted or build-time-baked secret.
- the four GP-field sources are resolved (details in the mapping section): GP job number = the project's
  `project_id` (the 6-digit project number); cost code = a per-PO dropdown from gh issue #121; GP buyer
  id = derived by the relay from the workstation identity; GP vendor id = `Vendor.gp_vendor_id`, populated
  by a sync from GP `PM00200`.

candid state of things: the relay's PO-create and receiving procs are proven against GP, but everything
to date hit the relay from curl/PowerShell on the same box. zero browser calls have happened. and the
browser-call rules CHANGED out from under the original plan - see the next section, it is the single
biggest risk and the original plan's fix for it is now wrong.


the browser hop is governed by Local Network Access now, not Private Network Access

the original plan said: answer the Chrome Private Network Access preflight with
`Access-Control-Allow-Private-Network: true` and the hop works. that is obsolete. Chrome put PNA on hold
and shipped Local Network Access (LNA) instead, enforced from Chrome 142 (late 2025). every browser these
users run in june 2026 is past that. under LNA a request from a public https site (the Railway page) to a
loopback address (`127.0.0.1` / `localhost`) is gated by a USER PERMISSION PROMPT, not a response header.
what actually makes the hop work:

- the frontend fetch must set `targetAddressSpace: "loopback"` on the request. this does two things at
  once: it relaxes the https -> http mixed-content block for loopback, AND it deterministically requests
  the LNA permission. without it the call is blocked as mixed content before LNA even matters.
- the browser shows the user a one-time permission prompt ("allow this site to connect to devices on your
  local network" / loopback). until the user grants it, every relay call fails. once granted it persists
  for that origin like any other site permission.
- the page can read the state ahead of time with `navigator.permissions.query({ name: "loopback-network" })`
  and guide the user instead of letting the first call silently fail.
- standard CORS still applies on TOP of LNA. the relay's existing CORS already allows the Railway origin
  plus the localhost dev origins and the Authorization + Content-Type headers, so the OPTIONS preflight
  for the POST should pass. that part of the original plan holds.
- the old `Access-Control-Allow-Private-Network` response header is harmless to add for any straggler on
  an older Chrome, but it is NOT the mechanism and must not be relied on. the relay does not need a new
  server header for LNA; LNA is a client-permission gate.

two consequences that ripple through the rest of this spec:
- the `/health` presence ping is itself a loopback call, so it ALSO needs `targetAddressSpace: "loopback"`
  and it is what triggers the permission prompt. presence detection and permission-acquisition are the
  same moment. plan the UX around that: the first time the user opens the PO page, the prompt appears.
- the exact api shape shifted across Chrome 141 -> 145 (the permission split into `local-network` for LAN
  devices and `loopback-network` for localhost landed in 145). so the spec REQUIRES an in-browser probe
  of the actual Chrome versions purchasing and warehouse run, rather than trusting any one spec snapshot.
  `targetAddressSpace` and the `loopback-network` permission name are also not in the standard TS DOM lib
  types yet, so the relay client needs a small type augmentation / casts.

the deployment lever for this: Chrome has (planned/rolling) enterprise policy to pre-grant local network
access per origin. if IT pushes a policy granting the UC Nexus Railway origin loopback access on the
purchasing/warehouse machines, no user ever sees the prompt. that belongs in the deployment workstream and
is the clean answer to "we don't want every user clicking allow".


the communication model

- UC Nexus's frontend runs in the user's browser. on a GP action it makes TWO independent calls: one to
  the relay (`http://localhost:7321`, the live GP write, loopback + LNA) and one to the UC Nexus backend
  (Railway, UC Nexus's own record).
- the relay is on the SAME workstation, bound to 127.0.0.1:7321, holding the GP connection over Windows
  SSPI. the Railway backend is NOT in the GP path - it cannot reach a user's localhost. anything that
  must touch the relay (creating a PO, receiving, syncing vendors) is therefore frontend-initiated.
- this only works where the browser and the relay are the same machine. the relay has to run on the
  stations where people create POs and receive - the same stations that run GP and the Excel macro today.


the GP field mapping (the crux of the job-cost path)

UC Nexus stores none of the GP identifiers a job-cost PO needs. historically nobody created POs from an
app - in UC Connects POs were typed straight into GP's purchasing module and the app only read them back
(the one eConnect create-stub in the legacy code was dead test code: hardcoded TUCSH, dummy lines, never
called). so UC Nexus auto-creating a job-cost PO is genuinely net-new, and every GP field below has to be
sourced or mapped. the relay's `/po` request already has slots for all of these (header vendor_id /
buyer_id / confirm_with / currency_id, and per-line item / qty / cost / product_indicator / job_number /
cost_code) - the work is filling them from UC Nexus data.

each block below is: relay `/po` field, then bulleted - the UC Nexus source, then the resolution / any
constraint.

1. company
   - the GP company database the PO lands in
   - TUBC for the proof. in prod, the project's company / the user's company (legacy CompanyId 1 = UCSH /
     Markham, 2 = UBC / Vancouver). allowlist stays sandboxes-only until a signed-off prod run.

2. po_number
   - leave it unset so the relay reserves GP's next `PO` number via taGetPONextNumber
   - we want GP to assign its real `PO######` so the PO lives in GP's purchasing naturally. do NOT pass a
     `ucnexus...` number here. store the returned number back on the UC Nexus PO.

3. header.vendor_id (GP VENDORID, char 15)
   - `Vendor.gp_vendor_id`, a NEW column populated by the vendor sync from GP `PM00200`
   - block the GP push (clear message) if the chosen vendor has no `gp_vendor_id` yet. the sync + a small
     admin mapping screen keep it populated.

4. header.buyer_id (GP BUYERID, char 15)
   - derived BY THE RELAY from the workstation identity (the device hostname and/or the SSPI login the
     relay already exposes via `SUSER_NAME()` in `/info`)
   - company policy names each device after its owner, so the hostname is a usable handle. but GP BUYERID
     is a configured value that may not equal the hostname verbatim, so the relay resolves it through a
     `[gp.buyers]` config map (hostname/login -> BUYERID) with a per-company default fallback, and
     validates the resolved id against GP's buyer list, rejecting an unknown buyer with a clear error.
     the frontend does not send a buyer id - the relay fills it when the request omits it, because the
     machine that knows the device is the relay. confirm the real GP buyer ids vs hostnames during
     deployment.

5. header.confirm_with (char 20)
   - default to the vendor contact name, truncated to 20
   - cosmetic on the GP side; a sane default is fine.

6. header.doc_date
   - today (the relay/UI clock)

7. header.currency_id
   - CAD. USD is ~3% of real POs and is tracked as relay hardening; the relay assumes CAD today.

8. line.item_number (GP ITEMNMBR, char <=31) and line.item_description (char <=101)
   - item_number from the line's `order_as` (how we actually order it, e.g. `ML2010`) when present, else
     `product_code`; item_description a composed string from `product_code` + `hardware_category`
   - non-inventoried GP lines accept a free item string, so this is flexible; confirm the order_as vs
     product_code choice against how purchasing reads a GP PO before prod. truncate to the GP lengths.

9. line.quantity / line.unit_cost / line.uofm / line.location_code
   - quantity = `ordered_quantity`, unit_cost = the line's `unit_cost`, uofm = "Each"
   - location_code per company (UBC -> VANCOUVER, UCSH -> MARKHAM; the relay default is VANCOUVER). confirm
     the per-company site code.

10. line.product_indicator (1 non-inv / 2 job cost)
   - DERIVED: project-linked PO -> 2 (job cost) on every line; stock PO with no project -> 1 (non-inv)
   - this is the clean rule and it means the UI does not ask. note the assumption that every line of a
     project PO books to the job; if a project PO can carry a non-job line, this needs a per-line flag.

11. line.job_number (GP JOBNUMBR, char 17) - job-cost lines only
   - `project.project_id` (the field the admin UI labels "Project Number"; the 6-digit integer)
   - only set for project-linked (PI=2) lines. guard: only push as job cost when `project_id` looks like a
     valid GP job (the 6-digit project number); otherwise treat as non-job and flag it.

12. line.cost_code (GP COSTCODE) - job-cost lines only
   - a per-PO cost code chosen from the gh issue #121 dropdown (e.g. `210-200` Supply Hardware,
     `220-000` Supply Washroom Accessories, ... excluding the DO-NOT-USE rows), applied to every job-cost
     line on the PO. issue #121's confirming comment: "cost codes values are assigned at a per po level".
   - the dropdown value is the 2-segment `Cost_Code_Number_1 - Cost_Code_Number_2`. the relay also needs
     the 3rd segment, `Cost_Element` (the `-2` in `210-200-2`); the proven TUBC run used element 2.
     confirm the element per cost code with the user / GP before prod (default 2 for now). issue #121 also
     allows flagging a PO with MULTIPLE cost codes - out of the first build; one cost code per PO to start,
     a multi-code PO is a later extension.


schema and api changes

backend (UC Nexus):
- `Vendor.gp_vendor_id` (nullable string) + alembic migration. populated by the vendor sync.
- purchase order: a header `cost_code` (nullable string), a `gp_sync_status` enum
  (`NOT_PUSHED` / `SYNCED` / `FAILED`), and storing GP's returned `po_number` on the existing nullable
  `po_number` column. migration for the new columns.
- a `relay_installs` table for the per-install secret (see the secret section): id, label/workstation,
  the secret (encrypted at rest), company, created_at, last_seen_at.
- GraphQL: extend `CreatePOInput` line/header path so the resolver can build the relay request server-side
  is NOT possible (the backend can't call the relay) - instead the FRONTEND builds the relay request and
  the backend just records the result, so the backend changes are: the new columns, a `relayCredential`
  query that returns the install secret to the authenticated user, and a `syncGpVendors(list)` mutation
  that upserts `gp_vendor_id` from a relay-provided vendor list.

relay:
- a `GET /vendors` read endpoint: reads `PM00200` (VENDORID, VENDNAME, and class) for the company, returns
  the list. read-only, bearer auth. this is what the vendor sync calls.
- workstation-identity + buyer resolution: expose the hostname (e.g. `socket.gethostname()`) alongside the
  existing `SUSER_NAME()` login in `/info`, and add the `[gp.buyers]` config map + resolution so `/po`
  fills `buyer_id` from the workstation when the request omits it, validating against GP's buyer list.
- `/po` and `/receipt` request/response bodies are otherwise already sufficient - no new fields needed for
  job cost (they already carry job_number / cost_code / product_indicator / rack_location).
- confirm the CORS preflight from the real Railway origin actually passes for the POST (it should, given
  the existing allowlist), and add the legacy `Access-Control-Allow-Private-Network: true` answer to the
  OPTIONS for stragglers on older Chrome. no LNA-specific server header is needed.

frontend:
- a `relayClient` module: typed wrappers over `/health`, `/info`, `/vendors`, `/po`, `/po/next-number`,
  `/receipt`; the bearer header; `targetAddressSpace: "loopback"` on every fetch; and error mapping from
  the relay's structured errors (`econnect_error` with proc + error_state, the pydantic validation errors,
  `qty_exceeds_remaining`, `line_not_receivable`, `po_not_found`, `company_not_allowed`) to readable,
  actionable messages.
- relay presence + permission detection: on the PO and receiving pages, check
  `navigator.permissions.query({ name: "loopback-network" })`, then background-ping `/health`. drive the
  UI off the combined state: connected -> show GP actions; permission not granted -> a "grant local network
  access to use GP" affordance that triggers the prompt; relay down / not installed -> a "GP relay not
  detected on this machine" banner; version mismatch (read `/info`) -> warn. this is what stops a confusing
  silent failure.
- the Create PO dialog: add the per-PO cost-code dropdown (issue #121 list, DO-NOT-USE rows filtered),
  required when the PO is project-linked. everything else derives (job number from the project, vendor GP
  id from the synced vendor, buyer from the relay, product_indicator from project-linkage), so the form
  stays close to what it is today plus that one control.


the one-click create-in-both orchestration

the GraphQL create and the relay call are two separate network calls with no shared transaction, so the
submit handler sequences them and records state rather than pretending atomicity. recommended order, to
avoid a half-saved order or an orphan GP PO:

1. create the UC Nexus PO first as a DRAFT (the existing `createPo` mutation, extended to carry the chosen
   cost_code), `gp_sync_status = NOT_PUSHED`. now there is a durable record + a request number even if the
   GP step fails.
2. build the relay `/po` request from the form + the mappings above and call the relay. GP reserves and
   returns its `PO######`.
3. on relay success: record GP's `po_number` on the UC Nexus PO, set status to ordered and
   `gp_sync_status = SYNCED`.
4. on relay failure: leave the PO DRAFT, `gp_sync_status = FAILED`, surface the mapped relay error, and
   make the GP push retryable from the PO (a retry reuses steps 2-3). block the action up front, with the
   presence banner, when the relay is down or the permission is not granted - never start a push that
   can't reach GP.

the trade-off in this order: a GP PO is only ever created after UC Nexus has a record, so the failure mode
is "UC Nexus PO with no GP number yet" (visible via gp_sync_status, retryable) rather than "GP PO nobody
in UC Nexus knows about". the reverse order would risk the latter.


the backend-issued per-install secret

each relay install has its own secret. the backend issues and stores it; the frontend fetches it at
runtime over https; the relay holds the same secret in its `config.toml` and validates the bearer. the
frontend needs the RAW secret to send as `Authorization: Bearer`, so the backend stores it ENCRYPTED at
rest (not just hashed) and returns it decrypted to the authenticated user - a hash-only store can't return
the raw value the bearer header needs.

provisioning an install:
- generate a secret in the backend for the install, store it (encrypted) in `relay_installs` with the
  install's label/company.
- write that same secret into the workstation's relay `config.toml` (DPAPI-protected at rest for a real
  rollout, per the deployment workstream).
- the frontend, for the authenticated user on that workstation, calls a `relayCredential` query and gets
  `{ secret }` back; it uses it as the bearer to the relay.

for the POC this is one install and one secret returned to the authenticated user. production keys the
secret to the workstation/user assignment so each station gets its own. the secret is never committed,
never in a Vite build var (those ship to every client), and only travels backend -> authed frontend over
https and frontend -> relay over loopback.


vendor sync

because only the workstation's own browser can reach the relay, the sync is frontend-initiated:
- an admin action calls the relay `GET /vendors` for the company, gets the GP `PM00200` list (VENDORID,
  VENDNAME).
- the frontend posts that list to the backend `syncGpVendors` mutation, which matches UC Nexus vendors to
  GP vendors by name and sets `gp_vendor_id`; unmatched vendors are surfaced for a one-time manual mapping.
- after the sync, any vendor with a `gp_vendor_id` can be used on a GP PO; one without is blocked with a
  clear "this vendor isn't linked to GP yet" message at PO time.


receiving (the second workflow, wired the same way)

the relay `/receipt` is built and proven; wiring it from `ReceiveModal` needs the same kind of mapping:
- `po_number`: the GP `PONUMBER` stored on the UC Nexus PO at create time (so receiving-via-relay depends
  on the PO having been created through the relay, which is the normal path now).
- `po_line_ord`: GP's line `ORD` (16384, 32768, ...). record the UC-Nexus-line -> GP-ORD mapping at PO
  create time (the relay assigns ORD = line index * 16384 in order), or read it back from the relay's PO
  read. without it we can't target the right GP line.
- `rack_location`: the relay wants one string; UC Nexus receiving captures aisle/bay/bin. compose
  `aisle-bay-bin` (the relay requires a non-empty rack location even for sandboxes, where no WHRECLINE101
  row is written). the put-away/deficient detail stays UC-Nexus-side.
- the relay enforces remaining quantity (ordered minus already received), so the UI reflects remaining and
  surfaces `qty_exceeds_remaining` / `line_not_receivable` cleanly.
- same two-call shape: post the GP receipt via the relay, record the UC Nexus receive via the existing
  `createReceive` mutation.


remaining relay hardening (carried from the relay <-> gp half)

uniform error-response shapes across all endpoints; checking client-supplied PO numbers against history
(`POP30100`) not just active POs; USD PO handling (the ~3% the relay doesn't do yet); and the production
service-account swap (a dedicated GP service account with narrow grants instead of a personal login) from
the deployment workstream.


sequencing

1. relay-side prep: confirm the CORS preflight passes from the real Railway origin; add the legacy PNA
   header to the OPTIONS for stragglers; expose the workstation hostname in `/info` and add the
   `[gp.buyers]` map + buyer resolution; add `GET /vendors`. small, and it unblocks the browser hop.
2. browser-hop spike (the gate): a minimal `relayClient` with `targetAddressSpace: "loopback"` + presence
   and permission detection; from the real Railway origin, prove a bare `/health` (which triggers and
   clears the LNA prompt) and then a single hardcoded job-cost `/po` against TUBC, in the actual Chrome
   versions purchasing and warehouse run. confirm OPTIONS + POST both succeed with no CORS / mixed-content
   / LNA failure in the network panel. this proves the genuinely-new piece before any UI work.
3. backend-issued secret: `relay_installs` + `relayCredential` + the relay config; wire `relayClient` to
   fetch the secret instead of any placeholder.
4. vendor sync: relay `/vendors` + `syncGpVendors` + the admin mapping screen; populate `gp_vendor_id`.
5. schema + Create PO UI + orchestration: the new columns, the cost-code dropdown, the derivations, and
   the one-click create-in-both flow; prove a real job-cost PO on TUBC end to end from the browser, with
   WS10101 / JC committed for the job line.
6. receiving: wire `ReceiveModal` -> relay `/receipt` with the po_number / ORD / rack-location mapping;
   prove a receive on TUBC end to end with a rack location.
7. deployment: package the relay (Windows service or PyInstaller exe, start on logon/boot); stand up the
   dedicated GP service account with narrow grants; DPAPI-protect the secret; push the Chrome enterprise
   policy pre-granting LNA for the UC Nexus origin so users don't get prompted; provision one workstation,
   then roll out to the purchasing and BC warehouse stations and flip the allowlist to production with
   per-site sign-off.


simulated user testing

this verifies the browser hop, which is the genuinely new piece. prerequisites: the relay running locally
on the test machine with TUBC in the allowlist and a valid per-install secret in its config, and UC Nexus
(Railway) open in a browser on that same machine, in the Chrome version the real users run. driving the UC
Nexus page with Chrome DevTools MCP:

- navigate to the Create PO page. expect the LNA permission prompt the first time (the `/health` presence
  ping triggers it); grant it. expect the relay-presence indicator to read "connected".
- check `navigator.permissions.query({ name: "loopback-network" })` reads "granted" after the grant.
- fill a PO: pick a project (so it's job cost), a synced vendor (one with a `gp_vendor_id`), a cost code
  from the dropdown, and one line. submit. expect a GP `PO######` back within a second or two, shown in the
  UI, the UC Nexus PO recorded with that number and `gp_sync_status = SYNCED`, and NO console errors and no
  CORS / mixed-content / LNA failure on the `http://localhost:7321/po` request - verify in the network
  panel that the OPTIONS preflight and the POST both succeed.
- verify read-only in TUBC that the PO landed (POP10100 / POP10110, plus WS10101 / JC for the job-cost line
  with the right JOBNUMBR and cost code).
- stop the relay process and reload. expect the presence indicator to flip to "relay not detected" and the
  Create PO GP action to be blocked with a clear message (and the order not half-saved), not a silent hang.
- restart the relay, perform one receive against that PO with a rack location, and confirm the received
  quantities show in the UI and land in TUBC.

the same script is the gate for any production run, against UBC / UCSH only with explicit approval and the
production allowlist - exactly the manual pattern used for the receiving validations on PO502088 and
PO502090.
