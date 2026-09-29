# Simulated User Testing Guide

This is a tester's knowledge journal for UC Nexus. It documents how the app works from a front-end user's perspective and how to drive it through the Claude in Chrome browser extension.

**Maintain this file:** Update it when you discover new behaviors, gotchas, or workflows during testing. This is a living document that grows with each testing session.

---

## Environment

**End-to-end testing happens on production, after the PR has merged, and nowhere else** (product owner ruling, 2026-09-25). PR environments are retired: their workflows and the backend and relay plumbing behind them were removed under #868 (PRs #874 and #877), so there is no environment to open, no check to wait on and no sign-in token to mint.

- **Before the merge, verification is CI and code review only.** A PR is not click-tested before it merges. That is not permission to merge and forget: the click-through on production is part of finishing the work.
- **Wait for the deploy.** Railway deploys the backend and frontend services automatically once master CI passes. Confirm it before testing:
  ```bash
  railway deployment list --service backend --environment production
  railway deployment list --service frontend --environment production
  ```
  The newest row of each must be `SUCCESS` and newer than the merge. The two services deploy separately, so check both.
- **Production URLs**: frontend `https://frontend-production-34fc.up.railway.app`, backend `https://backend-production-7866.up.railway.app` (GraphQL at `/graphql`).
- **Production carries only dev data**, so it is safe to test on. It is still the one shared database everybody else is looking at, so create only what the scenario needs and name test records so they are recognisable.
- **Drive it with Claude in Chrome only.** The agent drives the frontend through the Claude in Chrome extension (`mcp__claude-in-chrome__*`: `tabs_context_mcp`, `tabs_create_mcp`, `navigate`, `find`, `read_page`, `get_page_text`, `computer`, `browser_batch`, `read_console_messages`, `tabs_close_mcp`, plus `javascript_tool` and `file_upload` when needed) in the owner's own Chrome session. Never the Chrome DevTools MCP, never desktop-level clicking, and never a local runtime.
- **No sign-in step.** The owner's Chrome is already signed in to UC Nexus. Never mint a sign-in token and never enter a password. If the page shows the Clerk sign-in form, stop and ask the owner to sign in.
- **Test against TUBC only.** TUBC is the test company in GP, and the only one to test against. Production also holds UBC and UCSH data; leave it alone.
- **A UC NEXUS ADMIN works in one GP company at a time (#845, PRs #849, #862 and #864).** The owner's account is an admin, so the app bar carries a company switcher (its `aria-label` reads `GP company: <company>. Switch company`). Switching remembers the pick and resets the Apollo store. The pick is per tab (sessionStorage), and a new tab starts on the last pick made in any tab (localStorage). Every request carries the choice in the `X-Nexus-Company` header, which scopes the PO table, projects, warehouse, shipping and the GP reads to that company. User Management, Relay Installs, NEXUS GP TRAFFIC, Reset data and Database Access are cross-company and say "All GP companies - the company in the app bar does not apply here" under the title. **Switch to TUBC before touching test data, and switch back to the owner's usual company when you finish**, because the owner's next new tab opens on whatever you picked last.
- **Anything that writes to GP is an outward write, even on TUBC.** Registering a PO, approving a receive and creating a GP job all write into the live GP SQL server. Say what will be written before doing it.
- **A relay change ships as an auto-built relay release on merge.** The workstation relay picks it up on its daily poll, or when someone presses "Update now" on the relay window. Before testing a flow that depends on relay changes, confirm the relay is on the new build: the feature's live list loads instead of the "relay out of date" fallback, or `{ relayStatus { connected companies build } }` reports the new build. (`relayStatus` has no `company` field; it carries `companies`, the codes the relay serves, and `gpCompanies { id name }`, the same list with GP's names.)
- **Test XML file**: `testing/fixtures/contracterp-74.xml` - TITAN hardware schedule export (job `22713`), use for Import wizard testing. It is too large for the extension's upload tool, and the tool only accepts files the session was given, so upload a trimmed copy built in the session's scratchpad; see "Lessons from driving the app" under Claude in Chrome Patterns.

### Every resolver needs a token now (#415)

Until #415 most resolvers were reachable with no `Authorization` header at all, so an injected
`fetch('/graphql', ...)` helper that forgot the token still returned data and nothing looked wrong.
That is over: every resolver in `app/schemas/` calls `require_user` / `require_admin` / `require_role`
as its first statement, enforced by `backend/tests/test_resolver_gate_completeness.py`. The only
exception is `enrollRelayInstall`, which carries its own enrollment-token auth.

Consequences when driving the app by script:

- Always mint a token first - `await window.Clerk.session.getToken({skipCache: true})` - and send it
  as `Authorization: Bearer <token>`. A helper without one now gets
  `{"data": null, "errors": [{"message": "Authentication required", "extensions": {"code": "UNAUTHENTICATED"}}]}`
  on *every* query, not just the handful that used to be gated.
- Distinguish the three failure shapes: **no header** -> `Authentication required`; **unparseable
  token** -> `Malformed authentication token`; **valid token, wrong role** -> `FORBIDDEN`, e.g.
  `UC Nexus Admin role required`. Getting `Authentication required` from inside a signed-in page means
  your helper dropped the header, not that the session died.
- Admin-gated reads worth knowing, because a non-admin session gets FORBIDDEN rather than an empty
  list: `users`, `adminStats`, `adminOpeningStatuses`, `adminOpeningDeepDive`, `locationDuplicates`. Their writes too -
  the warehouse CRUD, `overrideInventoryQuantity`, `mergeLocations`.
- **Send `X-Nexus-Company` too** (#845). Apollo adds it to every request from the switcher's pick,
  but a hand-built `fetch` does not, and an admin request without it is unscoped: it reads every
  company at once. Send `X-Nexus-Company: TUBC` so a scripted read sees what the page sees. A code the
  backend does not know is refused with `Unknown GP company 'X'.` (`VALIDATION_ERROR`); for anyone who
  is not a UC NEXUS ADMIN the header is ignored.
- `require_admin` costs a Clerk Backend API round-trip per call (`require_user` does not), so a page
  hitting several admin resolvers at once is legitimately slower than the equivalent user page.

### New inventory can only enter through the relay

**Nothing puts new hardware into inventory except `createReceive`, and `createReceive` is
unconditionally GP-first through the relay.** With the relay down there is no supported way to add
stock. What production's TUBC data already carries is yours to use, but every scenario that needs
hardware that does not exist yet waits on the relay. Establish both in the first minute:

```
{ relayStatus { connected companies build } }
{ inventoryRows { inventoryLocation { hardwareCategory quantity } } }
```

**What comes back through the relay is GP.** It is the workstation relay on the other end of a live
eConnect round trip, on TUBC - a registered PO carries a GP-minted number and a PM00200 vendor stamp,
and a receive posts against a real purchase order. Write on TUBC and nowhere else.

**A disconnected relay is not a blocker to work around.** Tell the user the workstation relay must be
up, poll `relayStatus` (or the backend's `/health`) every two minutes, and spend the wait on the
relay-down half of the app if there is something worth checking there. Do not improvise a seeding
path; there isn't one.

**The real relay runs on a separate GP-credentialed workstation. Never install, start, or configure one
on the machine your session runs on** - `%LOCALAPPDATA%\UCNexusRelay` being absent and
`127.0.0.1:7321` being closed are the expected state here, not a dependency to satisfy. Setting one up
locally cannot work anyway, because this box is not domain-joined and cannot authenticate to GP SQL.

`connected: false` is a state on that workstation, and it is not yours to diagnose:
report it and poll. `relayInstalls { label enrolled enrolledAt lastSeenAt }` is a read you can do from
the app if the user asks what the backend thinks; everything below is background for reading an
answer, not a procedure to run.

- A relay that is **running but not trusted** logs `"WebSocket /relay-link" 403` every ~30s forever.
  Something is dialling out fine; the backend is refusing the handshake - the secret the relay
  presents does not match the install row's hash.
- **`lastSeenAt == enrolledAt` is suggestive, NOT proof.** `last_seen_at` is written in two places:
  `enroll_install` (`relay_repository.py:70-71`) and `authenticate_secret` on a successful match
  (`:95`, committed by `main.py:170`). But `authenticate_secret` runs *only on the connect handshake* -
  the liveness heartbeat is an app-level ping/pong that never touches the DB. So a relay that connects
  once and holds the socket open for two days also shows exactly one write. The timestamp alone cannot
  tell "never authenticated" from "authenticated once at enrolment and still connected".
- **The deploy log is what settles it.** A held-open socket silences the ~30s dial cadence for its
  whole duration, so look for a *gap*: an unbroken 403 cadence with no `[accepted]` line means the
  channel never came up. Read it across the whole life of the deployment, not a sample window.
- **A 403 cadence that runs unbroken *through* the enrolment instant means a stale secret.**
  `enroll_install` stores a SHA-256 hash of whatever secret the relay generated, so a successful
  enrolment cannot leave the row wrong about it; if auth still 403s seconds later, the mismatch is in
  the secret the relay is presenting. Usual cause: enrolment rewrote `[auth] shared_secret` in
  `config.toml` while the **already-running relay service kept dialling with its old in-memory
  secret**. It needs a *restart*, not another enrol. The relay's inbound server is bound to
  `127.0.0.1:7321`, so there is no remote restart — **but since #353 PR B there is a remote fix.**
  Admin → Relay Installs → **Adopt next connection** on that install opens a 5-minute, single-use
  window in which the relay's next dial is accepted with whatever secret it is already presenting,
  and the secret is rebound. Watch for `relay adopt: presented secret bound to install` at WARNING,
  then an accepted `/relay-link`. The adoption is stamped on the row as `adoptedAt` / `adoptedBy`.
- The silent-decrypt path is gone (#352 logs the cause; #353 PR C removed the key from the
  authentication path entirely). Since migration `067` the relay secret is a SHA-256 hash, so a
  rotated or missing `RELAY_SECRET_ENC_KEY` can no longer orphan a relay. On a `relay handshake
  rejected` line, read `hash_rows` and `cause`. Since #382 retired the key, `legacy_rows` is always 0
  and `encryption_key_present` always false, so neither of those two distinguishes anything any more -
  a false `encryption_key_present` is the healthy state now, not a config problem to chase.
- `POST /admin/reset-data` never orphans the on-prem relay: it preserves the `relay_installs` rows
  across the rebuild (#352). On production it still drops and rebuilds everything else, so never run
  it without the owner's explicit go-ahead.

### A queued GP write is not a failed one

Since #353 PR E, a `createReceive` or `registerPoInGp` submitted while the relay is unreachable is
**accepted onto a durable outbox** instead of failing. Recognise it before you conclude anything
about GP:

- The receive modal shows an amber *"Queued — the GP relay is offline"* panel, not the green
  "items added to inventory" one, and **nothing is in inventory yet** — the UC Nexus persist is
  deferred along with the GP write.
- A queued-writes chip appears in the app bar. Read the queue with:

```
{ gpOutboxSummary { pending inFlight failed oldestPendingAt lastDrainedAt } }
{ gpOutbox(limit: 20) { label op status attempts failureKind lastError } }
```

- **Bring the relay back and it drains itself** within about a second of `/relay-link` accepting
  (the route wakes the worker). `pending` goes to 0, `lastDrainedAt` advances, and the browser
  refreshes the affected lists on its own. Do not re-submit — the idempotency key belongs to the
  queued row, so a resubmit returns the same entry rather than posting twice.
- A `FAILED` entry is the one that needs a person: Admin → Relay Installs → **GP write queue**.
  `failureKind` says which kind of trouble it is — `gp_rejected` (eConnect said no; fix the input),
  `persist_failed` (GP committed but UC Nexus refused the state change), `exhausted` (retry budget
  gone), and `ambiguous`, which means the job reached the relay and **GP may already hold the
  write** — check GP before retrying, because a retry there can genuinely duplicate a receipt.
- If a scenario needs inventory *now* and the queue is stuck, the blocker is still the relay: seeding
  stock has no non-relay path. Re-scope the session rather than improvising.

Verified in this state on 2026-07-26: install `TAGGING3W10 (re-enroll after schema rebuild)` (company
TUBC), one row, enrolled 7/24 22:54:27.662369Z with `lastSeenAt` byte-identical to `enrolledAt`. The
403 cadence runs unbroken from 22:53:14Z (i.e. *before* enrolment) through 23:12Z and was still going
on 7/26, with no `[accepted]` line anywhere - so the WS channel has never once authenticated, while
the HTTP enrolment plainly succeeded. "The relay was working yesterday" refers to the service being
up and healthy on `127.0.0.1:7321`; that is independent of whether the backend trusts it.

**That outage is over - as of 2026-07-28 the same install authenticates normally** (`connected: true`,
company TUBC, `relay-v0.1.0-build.40`), and a full `registerPoInGp` + `createReceive` round trip
succeeds live with `gpOutboxSummary.pending` never leaving 0. Do not re-derive the 7/26 diagnosis from
this section; re-check `relayStatus` first. Two things worth knowing from that session:

- **The relay can drop mid-session and come back on its own, and the backend cannot tell you why.**
  Observed 2026-07-28: accepted 03:09:25Z, serving GP calls fine at ~03:40Z, `connected: false` by
  03:42Z, re-accepted 03:45:59Z - a ~4-5 minute hole. **Do not blame a redeploy without checking**;
  that was the first guess here and it was wrong. Rule-outs worth repeating:
  - `list-deployments` showed no backend deploy anywhere near the drop (the only one that day
    finished 03:09:22Z - which *caused* the 03:09:25 reconnect, 300ms after the old instance was
    removed, and is a different event from the drop).
  - `build.40` was already the newest relay tag and the relay was already running it, so there was no
    pending self-update to restart the process.
  - **An absent disconnect line means nothing.** `RelayGateway.unregister` logs *nothing*; the only
    relay line uvicorn ever emits is the `"WebSocket /relay-link" [accepted]` access log. A held-open
    socket therefore logs exactly one accept for its whole life, so "one accept and then silence" is
    ambiguous between healthy and dead - only `relayStatus` settles it.
  - What *is* signal: reconnect backoff is 1s doubling to a 30s ceiling, so 4-5 minutes of silence is
    ~8-10 missed dials, not one blip. And a rejected handshake would have logged 403s; there were
    none. So the relay either was not running or could not reach the backend at TCP/DNS level - both
    invisible from Railway, because neither reaches the ASGI app.
  - The answer lives in `relay.log` on the workstation (the file #370 gitignored). `_run_once`'s
    reconnect handler logs every attempt with a `category` - `dropped` / `server_restarting` /
    `unauthorized` / `conflict` - plus the error and current backoff. That log names the cause; the
    backend never can.
  - Reap timing for dating the drop: `HEARTBEAT_INTERVAL_SECONDS` 20s x `HEARTBEAT_MAX_MISSED` 2, so
    an armed connection flips to disconnected ~40s after the relay actually goes quiet.
- A `relay_status` traceback in the deploy log ending `jwt.exceptions.ExpiredSignatureError` /
  `AuthError: Invalid or expired authentication token` is **your own browser token ageing out**, not a
  relay fault. `relayStatus` is `require_user`-gated now, so a stale `getToken()` value in a
  `javascript_tool` fetch helper logs a full stack trace server-side. Re-mint with `getToken({skipCache:true})`.

### Seeding inventory: any received PO counts, a wizard PO also moves the schedule

**Stock from any received PO can now be batched for shop assembly.** An earlier revision of this
section said a PO from the Create PO dialog could not open the assembly wizard's Reconciliation gate.
That gate is gone twice over: a shop-assembly request is a flag over openings that checks nothing at
creation (#646, PR #660), and the wizard's Reconciliation step was retired (#814, PR #825). The
availability check now runs when the Shop Assembly Manager creates a batch
(`create_shop_assembly_batch` gates on the project's live inventory), so received stock counts
whichever dialog raised its PO.

**The schedule is where the origin still matters.** Only a PO raised through the wizard with purpose
**Create Purchase Orders** has lines bound to the schedule's hardware items, so only receiving that
PO moves those items to received in Hardware Status by Project and `adminOpeningDeepDive`. Use the
wizard when the test is about schedule status, and either path when all you need is stock.

**A wizard-created PO loses that binding if you register it by calling `registerPoInGp` yourself.** The
mutation *replaces* the draft's line items with the set you send (that is its documented job - the
register dialog is allowed to edit them), so hand-built `lineItems` produce lines with no link back to
the schedule rows. The PO registers, GP takes it, the receive posts and inventory appears - and every
schedule item still reads as unpurchased. Verified 2026-08-03: two POs (PO0000082, PO0000083) and two
receipts landed in TUBC and `projectInventoryAvailability` showed all four products, while the
opening's hardware still read as unpurchased across the board (`adminOpeningDeepDive` reports the
severed binding as `notPurchased`). Drive the register **dialog** when the schedule linkage matters;
scripting the mutation is only safe when all you want is stock in the pool. Keep the GP footprint
small on the wizard's Organize PO Drafts step: tick a single draft card (every card starts unticked),
and trim it with each line's `Line actions for <productCode>` menu -> `Remove line`. Fill **Order As**
on that step - an import-created draft otherwise blocks the register dialog with per-line `Required`
errors.

**A PO whose lines share a GP item number used to fail with eConnect 9191. It is the item numbers,
not the line count** (issue #538, fixed). An earlier revision of this file blamed the line count and
told you to seed inventory one product at a time. That was wrong: TUBC holds relay-created four-line
POs that registered cleanly (`PO0000093`, `PO0000094`), and one of them carries the very product set
recorded here as failing.

```
GP PROC   taPoLine
ERROR STATE 9191
DESCRIPTION Invalid PO Status (POLNESTA), the line item cannot be manually released
```

What actually happened: `create_po_line` called `taPoLine` with no `@I_vORD`, so eConnect resolved
each line by item number. Two lines sharing an `ITEMNMBR` updated each other instead of both landing
- the second silently overwrote the first with `err=0`, and a third raised 9191. Because
`gp_po.py` truncates the item number to GP's 30-character `ITEMNMBR` and hardware part numbers carry
their handing as a suffix, three codes differing only past character 30 collapse into one. The
registrations logged here as "3 lines, short clean codes" were sharing a truncated item number.

The relay now dictates `ORD = idx * 16384`, so this shape registers correctly and you can seed
inventory with a multi-line PO. If you see 9191 again, look at what the four lines truncate to at 30
characters before suspecting anything else.

**A USD-currency GP vendor fails registration with `taMCCurrencyValidate` error state 961.** Hit
2026-08-10 with BANNER SOLUTIONS (currency showed USD, tax detail disabled as
"Not applicable for a foreign-currency PO"): the push died in `taPoHdr` with
`An error occurred in the taMCCurrencyValidate proc` - TUBC has no exchange setup for a
foreign-currency PO. Pick a CAD vendor instead (ALLMAR INC. worked on the same PO seconds later).
The dialog's Currency field tells you before you submit.

**There is no buyer-assignment gate any more (#695), and no Buyers page.** The register dialog's
read-only `Buyer (you)` field shows the signed-in user's GP identity, set in User Management; since
#724 that identity needs the PO User role, and removing the role clears it.

**Receiving is now draft-first with a required packing slip and a manager approval gate.** The
Receive wizard's location step is gone: select POs -> quantities -> ATTACH A PACKING SLIP (any
image/pdf; required, submit stays blocked without it) -> Submit for Approval. Nothing posts to GP or
lands in inventory until a Warehouse Manager approves it at `/app/warehouse/receive-approvals`
(Approve & Post to GP -> confirm). Approval posts the GP receipt and the units land UNLOCATED - they
appear on Put Away for aisle/row/bay assignment. Budget one extra hop when seeding: receive, approve,
then put away.

Two other things worth knowing when GP is refusing outright:

- **There is no way to fake a placed PO, and that is deliberate (#509).** `markPoAsOrdered` used to
  flip a DRAFT straight to `GP_REGISTERED` with no relay involvement, and earlier revisions of this
  file advertised it as the way to exercise on-order quantities and back-order reads without GP. It
  is deleted. Its only guard was the local vendor link - never a GP vendor, just an invented one -
  and it had no frontend caller, so nothing reachable by clicking could ever produce that state. A
  seeding backdoor is not an end-to-end test; if a surface cannot be reached by clicking, the honest
  answer is that it needs a relay-connected run, not a fabricated row.

  `GP_REGISTERED` now comes only from `registerPoInGp` (relay push, real PM00200 vendor) or
  `create_po`'s GP-first branch for a caller already holding a GP result. With the relay line reading
  connected that path is reachable by clicking and what comes back is a real GP row on TUBC. With it
  disconnected there are no NEW placed POs, and what production already holds for TUBC is all that
  POs Awaiting Receipt, back-order reads and receiving history will show.
- The stock pool is not an escape hatch either: there is no `createStockItem`. Stock only enters
  through a receive, or out of project inventory via `destockInventory`, so it has the same root
  dependency.

**A re-import wipes the classification of every item it does not re-classify.** `finalize_import_session`
re-persists the selected openings' hardware items with whatever the Classification step sent, so a
run whose step only lists some of the items leaves the rest with `classification = null`. Anything
reading Site/Shop - the #451 coverage groups, the shop-assembly filter - then sees them as
unclassified. Re-run the PO purpose over the opening and classify the whole grid to restore it, or
correct the items on the Tenant Owner's hardware classification page (`/app/tenant-owner/projects/:id/classifications`, #735).

### A stacked PR gets NO CI, and backend tests are the thing you lose

`.github/workflows/ci.yml` triggers on `push`/`pull_request` to **master only**. A PR based on
another feature branch - the shape a stack of dependent PRs takes - therefore runs no Frontend, no
Backend, no Migration Integrity and no Relay job at all. `gh pr checks` on it shows none of those
jobs, and whatever few checks remain can be green, which reads exactly like a healthy PR.

That matters most for the backend, because there is no local Postgres: `pytest` skips ~470 of ~600
tests here, so CI is the only thing that ever runs them. A stacked backend change is effectively
unverified until it reaches master.

The cheap fix is a throwaway **draft PR from the top of the stack to master**, which runs the whole
stack's suite in one go; close it once green. Done on the #451 stack (PR #466) and it immediately
caught two failures that all three stacked PRs were reporting as clean:

- migration 083 creating its enum twice, because the column referenced a bare `postgresql.ENUM`,
  which emits its own `CREATE TYPE` during `create_table` on top of the explicit `.create()`. Fresh
  database -> `DuplicateObject` -> Migration Integrity dead AND every backend test dead, since they
  all build the schema. Pass `create_type=False` on the column's reference.
- a delivery-request test payload one field short after `DELIVERY_REQUEST_FIELDS` grew.

### What CI runs on a PR to master

- **The frontend tests run in four shards** (`Frontend tests (1/4)` to `(4/4)`, `vitest run
  --shard=i/4`) beside one `Frontend build` job (npm ci, lint, build). A `Frontend` job gathers them,
  and it is the check the master ruleset requires (#837 and #870, PRs #867 and #880). A red shard
  shows under its own name; `Frontend` only says that something below it failed.
- **A PR only runs the jobs for the folders it touches** (#869, PR #883). A `Changes` job diffs the
  PR: `frontend/` runs the frontend jobs, `backend/` runs Backend and Migration Integrity, and
  `relay/` runs Relay. A job skipped this way counts as passing, so a docs-only or frontend-only PR
  legitimately shows Backend as skipped. A change to `ci.yml` and every push to master run
  everything, and so does a failed `Changes` job.

## Getting Started (Every Session)

1. **Confirm the change is on production.** The PR is merged, master CI is green, and the newest
   `railway deployment list --service backend --environment production` row (and the same for
   `frontend`) is `SUCCESS` and newer than the merge. A tab opened before the deploy keeps the old
   bundle; open a fresh tab or add a cache-buster (`?cb=1`).
2. **Confirm the relay build, if the flow depends on it.** A relay change reaches the workstation on
   its daily poll or through "Update now". Check that the feature's live list loads rather than the
   "relay out of date" fallback, or read `{ relayStatus { connected companies build } }`.
3. **Open a tab.** Load the Claude in Chrome tools (one `ToolSearch` call for the whole set), call
   `tabs_context_mcp` to see the session, then `tabs_create_mcp` for a tab of your own, and `navigate`
   it to `https://frontend-production-34fc.up.railway.app/app`.
4. **You are already signed in.** The tab shares the owner's Chrome session, so you land on `/app`,
   the Module Selector. No token, no password, no verification code. If you see the Clerk sign-in form
   instead, stop and ask the owner to sign in.
5. **Switch to TUBC.** Pick TUBC in the app-bar company switcher, work in TUBC's projects and POs
   only, and say what will be written to GP before any step that writes there.
6. **Put the switcher back and close your tabs.** Switch back to the company the owner was working in
   (a new tab opens on the last pick), then close your tabs with `tabs_close_mcp`.

**Reset data is not a testing step any more.** On production the UC Nexus Admin -> Reset data page
(`/app/nexus-admin/reset-data`) drops and rebuilds the whole schema. Never use it to get back to a
known state; build the state you need in TUBC instead, and run a reset only on the owner's explicit
instruction.

## Claude in Chrome Patterns

### General Rules
- Read the page after any navigation or click before acting on it: `find` for a specific element
  (it returns refs you can click), `read_page` for the accessibility tree, `get_page_text` for plain
  text. Use a `computer` screenshot when you need to verify visual rendering (layout, colours,
  spacing) or a state the tree does not expose.
- **If every extension call times out on UC Nexus while other sites work, the extension is signed
  out.** Ask the owner to sign it in before theorising about the app.
- **On a fresh full page load, a screenshot can time out while the project list loads (~20s).** A
  `read_page`, `get_page_text` or `find` call gets through first, and screenshots work after it.
- **A screenshot or zoom can also stall while a very large list renders** (for example the PO table
  filtered to Closed, 100k+ rows). Wait a few seconds and retry.
- **A `left_click` on a `find` ref sometimes does nothing** on MUI ToggleButton/ButtonBase segments
  and Tabs-like buttons (seen on the PO table status strip and the Shop Assembly
  Pending/Worked/Rejected tabs). Take a screenshot and click by coordinate instead.
- **`find` cannot see `aria-pressed`.** Confirm a toggle's state from a screenshot or zoom.
- Batch predictable steps with `browser_batch`. The `computer` tool has no `mouse_move` action; use
  `hover`.
- **Typing into a MUI number input that already holds a value appends to it** (a spinbutton defaulted
  to `2` typed with `1` ends up `21`, over max, submit disabled). Click the field, select all
  (`ctrl+a`), then type the digits, and re-read the value before submitting. `form_input` sets a
  value directly and avoids the append.
- **`div[role="dialog"]` selectors hit the WRONG dialog inside the Import wizard.** The fullscreen
  wizard is itself a `role="dialog"`, so when it opens an inner modal (Split line, Finalize confirm,
  over-order warning) `document.querySelector('div[role="dialog"] input...')` in a `javascript_tool`
  script matches the wizard's FIRST matching input, not the modal's. On 2026-08-10 that silently
  wrote a split quantity into the first draft card's unit-cost spinbutton (persisted to the PO; caught
  only by re-reading the line later). Always scope to the LAST dialog in document order
  (`[...document.querySelectorAll('[role="dialog"]')].pop()`) and re-read the value you set before
  submitting.
- **The native-setter + `input` event trick can fail to reach React state** (the DOM shows the value,
  React re-renders it away - the split dialog's qty field did this while the button label still read
  "Move 1"). When it does, drive the field with real keystrokes instead: click it, select all, type
  the digits, and confirm on a state-derived readout (a button label, a total) rather than the
  input's DOM value.
- **Scripted GraphQL calls from the page go through `javascript_tool`.** Mint a token first
  (`await window.Clerk.session.getToken({skipCache: true})`) and send it as a bearer header, with
  `X-Nexus-Company: TUBC` beside it; see "Every resolver needs a token now" above.
- **Check that the tab is visible before measuring anything or typing.** When the Chrome window sits
  behind other windows, the tab reports `document.visibilityState === "hidden"` and Chrome throttles
  its timers. A timing loop built on `await new Promise(r => setTimeout(r, n))` then shows fake
  multi-second freezes, keystrokes can land in the wrong field, and count-up gauges (the Warehouse
  landing's, for example) stay at 0. Read `document.visibilityState` first; if it is `hidden`, bring the
  window forward with the Windows MCP `App` tool (mode `switch`, name `UC Nexus - Google Chrome`), and
  take measurements synchronously (`performance.now()` around the work itself) rather than across
  awaited timers.

### MUI Select Dropdowns
- MUI `<Select>` renders its dropdown in a **portal** (`<div role="presentation">`), not inside the Select element.
- After clicking a Select, `find` the option again (or read the page) to reach the portal-mounted `<MenuItem>` elements.
- Click the desired `<MenuItem>` to select it.

### MUI Autocomplete
- Click the input, type, wait about 2 seconds for the options, then `find` the option and click it.

### MUI Dialogs
- MUI `<Dialog>` also renders in a portal overlay.
- After triggering a dialog, read the page again to see the dialog content.
- Confirm/cancel buttons may use `data-testid="confirm-dialog-confirm"` / `data-testid="confirm-dialog-cancel"`.

### MUI DataGrid
- DataGrid virtualizes rows - only visible rows appear in the DOM.
- Off-screen rows will not appear in `read_page` or `find`; use `javascript_tool` to query grid data as a fallback.
- Column headers are in `role="columnheader"` elements.
- Click a row's `gridcell` to trigger row click handlers (e.g., open detail modal).

### window.alert()
- Some actions trigger `window.alert()`; Reset data no longer does (it reports under the button and as a toast).
- **A native alert blocks the page**, and extension calls against that tab stall until it is
  dismissed. Avoid triggering one from the extension; if one is open, ask the owner to dismiss it.

### Lessons from driving the app

- **`file_upload` caps at 10 MB and `contracterp-74.xml` is 11.5 MB**, so the real file cannot be uploaded through the tool at all. **The tool also accepts only files the session was given**; the session's scratchpad directory counts, so build the upload there rather than in the repository. Either take the "Use last uploaded schedule" card (almost always right), or build a subset: keep everything up to and including `<Detail>` (the part before it holds all 1998 opening/assignment definitions, ~1.07 MB), then the first ~600 `</Material_List>`-delimited blocks, then `</Detail></Contract>`. That lands at about 3.6 MB, parses clean, still carries `Submittal_Job_No` 22713, and yields "1998 openings parsed / 12746 hardware items parsed / 22 opening(s) had no hardware items assigned". Parsing is entirely client-side - nothing is persisted until Finalize - so uploading a trimmed file is safe on a database you are trying to preserve.
- **`navigate` costs a full reload and wipes any instrumentation you injected.** React Router picks up `history.pushState(...)` + `window.dispatchEvent(new PopStateEvent('popstate'))`, so route sweeps can be done client-side with a `fetch` wrapper still installed. That wrapper is far better evidence than `read_network_requests`, which only starts recording when first called and misses everything before it, and it can see GraphQL errors - which come back **HTTP 200** with an `errors` array, so status-code filtering finds nothing.
- **A `javascript_tool` call that hits the 45s CDP timeout keeps running in the page.** Its `await` chain continues after the tool has given up, so the next call races it and you get results tagged with the wrong route. Keep loops under ~8 route-hops, or step one route per call. If output ever looks mismatched, sleep ~6s and start over.
- `computer screenshot` times out with "renderer may be frozen" while the Import wizard renders 1998 openings or 26k classification rows. It is not frozen - wait 10s and take it again. Same for the first paint after "Use last uploaded schedule".
- The screenshot image is scaled down from the real viewport (1568px wide image for a 1918px window), so a card that looks cut off at the right edge usually is not. Check `document.documentElement.scrollWidth === clientWidth` before reporting a horizontal-overflow regression.
- The Pull Request detail modal **closes on Escape since the 2026-07-28 UI revamp** (it used to swallow it). Its nested confirm dialogs are siblings, so an Escape inside a confirm closes only the confirm. "Cancel Pull" is still a real destructive action - never use it as a way out.
- MUI option cards (module "Go to" cards, the PO module's "Create a PO" chooser) are `useNavigate` buttons with no `href`, so there are no anchors to click and `find`'s ref sometimes lands on the inner text node rather than the clickable card. Setting the underlying `input[type=radio]`/`input[name=select_row]` via native `.click()` works reliably and does update React state.
- The import landing project card is a `MuiCardActionArea` **button** wrapping the `MuiPaper`. Coordinate clicks land on it only sometimes (it takes focus but does not activate, and Enter does not help either). Reliable: find the element whose `textContent` matches the project *and* whose `tagName === 'BUTTON'`, then `.focus()` + `.click()`.
- **Select Openings is paginated at 50 rows/page, ordered by the schedule, not sorted**, and the "Filter" control is a Select (column filter), *not* a text search - there is no way to type an opening number. To enumerate or tick specific openings, scroll the `.MuiDataGrid-virtualScroller` in ~150px steps, and after each `scrollTop` assignment **dispatch a `scroll` event and wait ~450ms** or the virtualizer does not re-render and you silently collect only the first screenful (17 of 50). Keep the sweep under ~40s of `await` or the 45s CDP cap kills the call mid-loop - it leaves the page in a valid state (rows already ticked stay ticked), so just re-run and top up the selection.
- The Receive modal has **two** confirmations: `Submit for Approval` opens a nested `Submit for Approval` confirm ("Submit N items across M PO(s) for a Warehouse Manager to review? ...") whose button is just `Submit`. Scripting only the outer button looks like a silent no-op - no receive draft appears because no mutation ever fired.
- **DataGrid rows can be invisible to the accessibility tree.** A read may give you `columnheader`s
  and the pagination controls and *nothing else* - no row refs - so a ref click cannot reach a row.
  Read rows with `javascript_tool` over `[role="row"]`, and prefer the per-cell form, which
  gives you the column names too:
  `[...r.querySelectorAll('[role="gridcell"]')].map(c => ({field: c.getAttribute('data-field'), text: c.innerText}))`.
  To open one, dispatch the event yourself:
  `cell.dispatchEvent(new MouseEvent('click', {bubbles:true, cancelable:true, view:window}))`.
- **Read grid rows twice after switching tabs.** A read ~3s after a tab click came back with the last
  two cells missing (`... | Jay Puzon | 2` and nothing else); the same read a moment later had the
  full six. It is render timing, not a bug - do not report a missing column off a single sample.
- **Multi-line cells arrive as one string.** The Phase cell is a tag over a caption, so its `innerText`
  reads `PENDING
Not started` - replace newlines before matching, or assert on the parts.
- **Waiting for a Railway deploy**: `railway deployment list --service backend --environment
  production` (and `frontend`) says when each finished. To confirm the backend is serving the new
  build, poll the *schema* for a field it adds rather than guessing at a duration -
  `{ __type(name: "PickSheetSection") { fields { name } } }` until the new field appears. Backend and
  frontend deploy separately; the backend took ~225s from merge to serving on 2026-07-28. `/health`
  answering is not sufficient, it answers on the old build too.
- **A scripted GraphQL read is faster than the UI for setup and assertions.** Every resolver needs a
  token since #415, so run it from the signed-in page with `javascript_tool` and a fresh
  `getToken({skipCache: true})` bearer, plus `X-Nexus-Company: TUBC`. A query that is partly refused returns HTTP 200 with
  `data.<field>: null` *and* an `errors` array - if a list looks mysteriously empty, print `errors`
  before concluding the data is missing.
- **No horizontal scroll anywhere, tables included (#856, PR #907).** The project instructions file's
  second UI law now covers tables and grids: columns fit their container through the shared
  `useFitColumns` hook (`frontend/src/components/fitColumns.ts`) and the `FitTable` component, and
  each header edge is a resize handle (drag it, or focus the `Resize <column> column` separator and use
  the arrow keys). Widths are remembered per person in localStorage. A table that scrolls sideways
  inside its own box is a regression now, not an acceptable fallback; check the table container's
  `scrollWidth === clientWidth` as well as the page's.

---

## App Navigation Map

```
/                          -> Clerk Sign-In
/app                       -> Module Selector (6 module cards)
/app/import                -> Hardware schedule wizard (project landing -> wizard). NOT in the sidebar
                              since #471. The purpose is fixed by the link (#642): Shop Assembly's
                              "Start a Request" appends ?purpose=assembly, the PO module's "Create a PO"
                              chooser opens "From schedule - by opening" (?purpose=po) or "From schedule -
                              by hardware" (?purpose=po&mode=hardware), and a bare /app/import is the
                              schedule import itself. An old ?purpose=shipping link redirects to
                              /app/shipping/requests/new
/app/po                    -> The PO table (no project landing; ?project=<id> and ?highlight=<ids>, #851)
/app/po/document-settings  -> PO Document Settings
/app/warehouse             -> Warehouse landing (stat cards + Go-to cards for sub-routes)
/app/warehouse/inventory   -> Inventory (hardware items by project)
/app/warehouse/locations   -> Locations (master-detail bin browser)
/app/warehouse/receiving   -> Receiving (POs awaiting receipt, back-ordered items, recent activity)
/app/warehouse/receive-approvals -> Receive approvals (Warehouse Manager)
/app/warehouse/put-away    -> Put Away (unlocated items queue)
/app/warehouse/pull-requests -> Pull Requests (and /:id/pick, the pick page)
/app/warehouse/stock-pool  -> Stock Pool (non-project stock items)
/app/warehouse/deficient-items -> Deficient Items Review
/app/warehouse/shipments   -> redirects to /app/shipping/shipments
/app/shop-assembly         -> Shop Assembly landing (stat cards, Start a Request, one Go-to card)
/app/shop-assembly/requests  -> Requests: Pending / Worked / Rejected; batches are made here (#646)
/app/shipping              -> Shipping landing (Start a Request opens /app/shipping/requests/new)
/app/shipping/requests     -> Shipping requests: Pending / Accepted / Rejected, "New request"
/app/shipping/requests/new -> Request workspace (schedule and loose lines in one cart, #608)
/app/shipping/staging      -> Staging (the staged pool, packing slips)
/app/shipping/shipments    -> Shipments (packing slip list, lifecycle, return dialog; ?slip=PS-...)
/app/tenant-owner          -> Tenant Owner (projects, warehouses, dashboards, users)
/app/nexus-admin           -> UC Nexus Admin (users, relay, GP traffic, system setup)
```

---

## The request lifecycle, end to end

The module guides below are organised by *screen*, which is the wrong shape for a first read: one
request's journey crosses three of them. This is that journey once, with the screen that owns each
step. Everything in it is exercisable on production against TUBC.

**v1 does not manage doors.** The opening is a label - demand attribution before receiving, a text
tag on a line after it - and hardware exits the system when a pull completes. There is no assembled
unit, no bench tracking and no per-leaf anything downstream of the schedule, so "which doors can we
build / ship / are complete" is not a question this version answers.

| # | What happens | Where you do it | What changes underneath |
| --- | --- | --- | --- |
| 1 | **Raise** a request | Shipping -> Start a Request (the request workspace); Shop Assembly -> Start a Request (the wizard) | Shipping out: the workspace offers `owed - sent - claimed` per opening; you assign what is free to each line, and the hardware is **reserved** on the spot (#342). Shop assembly: the request only flags openings and records what each is owed. It reserves nothing and checks nothing (#646) |
| 2 | **Accept** it (shipping out) or **batch** it (shop assembly) | Shipping -> Requests, or Shop Assembly -> Requests | Shipping out: accepting mints a PENDING warehouse pull, a pure human gate; rejecting is what releases the claim. Shop assembly: the Shop Assembly Manager batches pending openings with per-line allocations. A batch is gated on available inventory for exactly those allocations, reserves under its own id and mints one pull numbered `<request>-B<n>` |
| 3a | **Start the pick** | Warehouse -> Pull Requests -> Start pick | The pull is claimed and opened. **Nothing moves**, and there is no sufficiency gate - a pull with an empty shelf still opens (#367) |
| 3b | **Confirm the pick** | The pick page, `/pull-requests/:id/pick` | The picker dictates a quantity per location; confirming deducts *those rows* and consumes the claim, atomically. This is the only moment inventory moves |
| 4 | **Hand it over** | Warehouse -> Pull Requests -> Send to shop / Send to staging | The pull completes. **This is a terminal exit** - for shop assembly the cart goes to the bench and the system stops looking; for shipping out the hardware joins the staged pool |
| 5 | **Ship** (shipping out only) | Shipping -> Staging | A packing slip against what the completed pull staged, then SCHEDULED -> PICKED_UP -> DELIVERED |
| - | **Undo the pull** while it is being picked | Warehouse -> Pull Requests -> Cancel Pull | Stock restocked to the rows it came off (#343). A shipping request goes back to Pending with its claim re-created; a shop-assembly batch's openings go back to pending and nothing is re-reserved (#646). Refused on a completed pull - the hardware has been handed over |
| - | **See where every request is** | Shop Assembly -> Requests, Shipping -> Requests | The stage chip: Requested -> Accepted -> Pulling -> Done, with Rejected off the ladder |

Three things a fresh reader gets wrong every time:

- **Reserved is not deducted.** Between steps 1 and 3b the hardware is claimed but still on the shelf,
  so the Warehouse inventory number and the request workspace's availability number legitimately disagree.
- **Started is not picked either (#367).** A pull sits IN_PROGRESS from the moment somebody presses
  Start pick, which is *before* any stock has moved. `Status` alone can no longer tell you whether
  the hardware has left - the queue's **Phase** column and `pickedAt` are what answer that.
- **The composer does not re-offer what has gone out.** An opening whose hinges left on a completed
  pull reads zero next time, even though the schedule still says it needs them. That is the `sent`
  term working, not a bug. Two requests for one opening are both allowed; the second one is simply
  offered nothing.

---

## Module Guides

### Purchase Orders Module

**Entry**: `/app/po` opens the PO table directly; there is no project landing in front of it.

**The PO table** (#851, PR #892):
- Header: **Document Settings** (PO Manager and Tenant Owner) and **Create a PO**, which opens a
  chooser: "From schedule - by opening", "From schedule - by hardware" (both open the import wizard)
  and "Manual entry" (the Create PO dialog).
- **It opens on every status, newest first** (creation date descending, Nexus drafts and GP-mirrored
  POs together). An earlier default showed only the open GP statuses and hid a draft someone had just
  raised; that is gone.
- **Status strip**: two captioned boxes, NEXUS (Total, Nexus Draft) and GP STATUSES (GP-Registered,
  Vendor Confirmed, Partially Received, Closed, Cancelled). A segment only narrows the table
  (`aria-label="Filter by <label>"`, `aria-pressed`); the pressed one is tinted and underlined, and
  nothing reads pressed when nothing narrows it (Total never does).
- **Search ignores the status filter.** While the box (`Search PO #, request #, vendor, or project…`)
  holds text the query sends no statuses, the strip dims, and "Searching all statuses" shows beside
  it; clearing the box brings the pressed segment back. The search also matches the project's job
  number and name, case-insensitively.
- **There is no project dropdown.** `?project=<project id>` (the Nexus id, not the job number; the
  project detail page links this way) shows a removable project chip beside the search box. An
  All / Nexus / GP toggle filters by origin.
- **`?highlight=<id>,<id>`** tints those rows amber, fading over about 4 seconds, and scrolls the first
  into view; the parameter is dropped once the tint fades. The wizard's "View purchase orders" button
  opens the table this way on the POs it just created.
- Columns: Project (job number over the name), PO / Request #, Status, Vendor, Created By, Creation
  Date, Order Date, Items. PO / Request #, Status, Vendor, Creation Date and Order Date sort on the
  server. A draft shows its request number with a `Nexus Draft` chip; a GP-born PO carries a `GP` chip.
  The whole row opens the detail modal, and so does the trailing `Open <PO> details` button. There is
  no expandable line-item mini-table any more.
- **Held PO registrations** sits above the table when there is anything to show (#854, PR #895). It
  lists only pending, in-flight and failed GP writes, each labelled
  `Register PO-REQ-nnn (job nnnnn) in GP` (a stock PO has no job). The admin GP write queue still
  lists everything.
- Paged server-side, 25, 50 or 100 rows a page.

**Create PO Dialog** (manual PO creation, issue #256 - draft-first, NO relay needed):
- Title "Create PO Request (Draft)"; reached through Create a PO -> "Manual entry", and it works with
  the relay offline
- Project selector (optional)
- Preferred delivery date. There is NO vendor field (#509): GP owns vendors, and the GP one is picked
  at register time
- Shipping costs / Tariffs (optional), Notes
- Line items grid: Hardware Category, Product Code, Qty, Unit Cost, Order As (REQUIRED per line; no Classification column - the PM sets site/shop at import)
- "Add Item" button to add rows, delete button per row (minimum 1 item)
- Submit ("Create Draft") creates a DRAFT PO with auto-generated request number (PO-REQ-XXX); no GP push. Registering into GP is the separate "Register in GP" action on the draft (relay + GP buyer identity required there)

**PO Detail Modal**:
- Shows: status chip, PO number, vendor (the GP `vendorNameSnapshot`, blank on an unregistered
  draft), quote #, dates, "No Project" label if project-less
- Line items grid: product code, hardware category, Order As, classification, ordered/received qty, unit cost, line total
- Documents section with upload capability
- Receiving history
- Actions: Edit (header fields + line item Order As/costs), Register in GP (disabled while the relay
  is down), Generate PO Document (see below), and Cancel PO, which only a draft offers. There is no
  "Mark as Ordered" button - the mutation behind it was deleted outright in #509

**The "Openings on this PO" section is gone from the detail modal.** It used to list the openings and
leaves a wizard-created PO was bought for. The link it drew on still exists in the data (a wizard PO's
lines are bound to the schedule's hardware items), so a wizard PO still moves the schedule when it is
received; there is just no section on the PO that shows it.

**Register Purchase Order in GP dialog** (#858, PR #915):
- The GP vendor is a type-to-search pick that matches the vendor id or any part of the name; each
  option shows the name with the mono id. The "no saved or matching GP vendor for <manufacturer>"
  hint clears as soon as a vendor is picked.
- One totals row under the lines: subtotal, trade discount (only when entered), freight,
  miscellaneous, tax and total, in the vendor's currency, updating live, with the caption "Tax is an
  estimate; GP calculates the final amount". With no tax schedule picked it reads "Pick a tax schedule"
  and "Total before tax"; a foreign-currency PO carries no tax. The estimate can be a cent or two off
  GP, which rounds per line.

**PO Lifecycle**:
```
DRAFT -> GP_REGISTERED -> VENDOR_CONFIRMED -> PARTIALLY_RECEIVED -> CLOSED
                       \-> PARTIALLY_RECEIVED -> CLOSED
  \-> CANCELLED (a Nexus draft only)
```
- **DRAFT -> GP_REGISTERED** happens only by registering the PO in GP (`registerPoInGp`, relay
  required), or via `create_po`'s GP-first branch for a caller already holding a GP result. Both
  carry a real PM00200 vendor. #509 deleted `markPoAsOrdered`, which used to fake this transition
  with no relay and no GP vendor
- **VENDOR_CONFIRMED** auto-triggers when a GP_REGISTERED PO has both vendor quote number and vendor acknowledgement document; auto-reverts if either is removed
- **Receiving** a PO without a project will show error: "PO must be associated with a project before receiving"

**A draft cancelled in Nexus disappears from the table entirely.** `cancel_po` (`po_repository.py`)
only accepts a DRAFT, and it sets `status = CANCELLED` *and* `deleted_at` in the same write, while the
table filters `deleted_at IS NULL`. So the cancelled draft is gone from the rows and from Total, and
it is never counted under Cancelled. The Cancelled segment counts only POs mirrored from GP as
cancelled there, which keep `deleted_at` empty.

Two consequences when testing:

- **A PO count that drops between two measurements is a cancel, not data loss.** This costs real time
  if you meet it cold - the PO simply vanishes with nothing in the audit log to say so (PO cancels are
  not audit-logged). `deleted_at` has exactly one writer in the whole backend, `cancel_po`, reachable
  only through the user-triggered `cancelPo` mutation, so a vanished PO always means somebody
  cancelled one.
- **Record PO ids, not just counts**, when you need a before/after. Aggregating by status tells you
  something changed but not which row, and you cannot query a soft-deleted PO back through GraphQL to
  find out afterwards.

**Generate PO Document** (issue #230; gated and prefilled from GP since #858, PR #915): a button on the PO detail modal action bar that opens a dialog building the finished supplier PO as a client-side PDF (`@react-pdf/renderer`).
- **When the button shows** (`poDocumentGate.ts`): hidden on a Nexus draft and on a cancelled PO. It
  shows disabled with a spinner as "Registering in GP, please wait" while the PO's registration sits
  in the pending GP writes, or while GP has it but GP-PROCESSING has not read it back yet (a Nexus PO
  past draft with no GP read stamped on it); the detail re-reads the PO every 10 seconds until that
  settles. It is disabled with a tooltip while the GP relay is not connected, and enabled once the PO
  is registered, read back, and the relay is up.
- **The dialog prefills from GP.** Each time it opens, `gpPoTotals` reads the PO's header from GP
  (shipping method, vendor address code, buyer, currency, the vendor purchase address and the ship-to).
  Saved document values always win, GP fills only the empty fields, and anything typed before GP
  answers is kept. GP-fed fields show "Reading from GP…" while the read runs. The header read needs
  relay build 87 or later (the build cut from PR #915); an older relay sends no header, and the dialog
  says the addresses and shipping method must be filled in by hand. Freight prefers GP's freight over
  the order-time shipping cost when nothing is saved.
- Dialog fields also pre-fill from the PO, its saved `PODocumentData`, and `poDocumentSettings`: vendor mailing address, buyer (from `buyerId`), currency (CAD `$` / USD `$US`), ship-to (warehouse dropdown | "Use project site" button | custom text - the resolved block is stored verbatim), shipping method, quote # (stored as `quotation_number`), required-by (defaults to `expectedDeliveryDate`), freight/misc/tax + tax label, and three conditional toggles (wood-door FSC, USA tariff, international customs).
- **Generate & preview** opens the PDF in a new tab (`window.open` blob). **Save to PO documents** persists `PODocumentData` + uploads the PDF as a `GENERATED_PO` document (appears in the Documents list, label "Generated PO", downloadable via presigned URL). Both first call `savePoDocumentData`, so re-opening the dialog pre-fills.
- Doc math: each line ext = ordered x unitCost; Subtotal = sum of ext; Order Total = Subtotal + Freight + Miscellaneous + Tax. The item column shows `hardwareCategory` (main line) + `orderAs` (Reference line). Boilerplate (tax numbers, mandatory bullets, signature, footer) always prints; the FSC / USA-tariff / customs blocks print only when their toggle is on.
- Company-wide boilerplate lives at the PO module's Document Settings page (`/app/po/document-settings`, "Document Settings" button in the PO list header - it moved out of Admin); the per-PO gaps are captured in this dialog.

### Import Module (the hardware schedule wizard)

**Entry**: `/app/import` has no sidebar entry (#471). It is a project landing; choosing a project
opens the wizard (a full-screen dialog). **There is no Purpose step (#642):** the link that opened the
wizard fixes its purpose, and the wizard's header names it together with the project -
`<title> · <job number> <name>` (#859, PR #904), for example `Create Purchase Orders · 22713 ...`.

**The project landing shows jobs active in GP (#852, PR #898).** It is the same landing the
Warehouse Inventory page uses. The grid holds recent projects plus the jobs active in GP; inactive,
closed and not-in-GP jobs sit behind a `Show inactive jobs (N)` toggle beside the search box. The
search spans every job, draws at most 100 cards and says `Showing 100 of N matches. Keep typing to
narrow.` A company with no active job shows a hint pointing at the toggle rather than an empty grid.
A TUBC test project that has gone inactive in GP is behind the toggle, not missing.

| Opened from | Title | Steps |
| --- | --- | --- |
| PO -> Create a PO -> "From schedule - by opening" (`?purpose=po`) | Create Purchase Orders | Upload File -> Select Openings -> Classification -> Organize PO Drafts -> Finalize |
| PO -> Create a PO -> "From schedule - by hardware" (`?purpose=po&mode=hardware`) | Create Purchase Orders | Upload File -> Select Hardware -> Classification -> Organize PO Drafts -> Finalize |
| Shop Assembly -> Start a Request (`?purpose=assembly`) | Create Shop Assembly Request | Upload File -> Select Openings -> Finalize |
| A bare `/app/import`, or the shipping workspace's schedule link (`?purpose=schedule`) | Import Hardware Schedule | Upload File -> Classification -> Finalize |

- **The Reconciliation step is gone (#814, PR #825).** The PO flow's Organize PO Drafts step carries
  every column it showed (needed, ordered, on order, received, available, and the lifecycle
  breakdown per line), a finalize confirm warns about over-buying (#736), and products the project
  already covers can be added back on that step. Anything in an older note about Reconciliation's
  `Deselect All`, its product checkboxes or its assembly gate describes a step that no longer exists.
- **The shop-assembly flow flags openings and nothing else (#646, PR #660).** No compose step, no
  availability check and no reservation at creation; the Shop Assembly Manager allocates and checks
  stock when making a batch (see the Shop Assembly module). Site/Shop comes from the persisted
  schedule (#492).
- **Shipping requests are not composed here any more.** They are built in the shipping request
  workspace (`/app/shipping/requests/new`, #608), and an old `?purpose=shipping` link redirects there.

**Result**: the wizard persists the openings and hardware items and creates the purpose's output: PO
drafts, a shop-assembly request, or just the schedule. The success screen (`ImportSuccessDialog`)
offers one primary button per kind created - **View purchase orders** (the PO table with
`?highlight=` on the new drafts), **View shop assembly requests** or **View shipping requests** - and
Return to Home. There is no "View Warehouse" button any more.

**You almost never need to upload the XML.** Step 1 offers two cards: "Upload new TITAN XML" and
**"Use last uploaded hardware schedule"**, the second captioned with what is already persisted
("1998 openings, 29126 hardware items"). It rebuilds the wizard's working set from
`projectHardwareSchedule` - the openings and hardware items already in the DB - so every later step
behaves identically without a multi-megabyte parse. Take it unless the thing under test *is* the
parser. "Choose Different Source" on the loaded panel gets you back to the two cards.

**A file for another job holds Next (#855, PR #901).** When the TITAN file's `Submittal_Job_No`
differs from the chosen project's job number (trimmed, case-insensitive), step 1 shows a warning
naming both jobs and a checkbox, `Import it into <job> anyway`; Next stays disabled until it is
ticked. The tick belongs to that parsed file, so a new upload asks again. A file with no job number
gets a quiet note instead of a block. **Owner note (2026-09-28): on TUBC any available test schedule
may be uploaded onto any TUBC project; tick the confirmation.** `contracterp-74.xml` and its trimmed
subsets are job 22713.

**Organize PO Drafts** seeds one draft card per manufacturer, every card unticked; tick the cards to
order. Lines move between cards (`Line actions for <productCode>` -> Move all to / Split… / Remove
line), and each card carries the vendor label, preferred delivery date, cost code, vendor quote
number, notes and attachments. The line ledger fits the card with resizable columns (#856, PR #907);
below 1000px of ledger width the six project numbers (Selected Qty, Needed, Ordered, On Order, Rcvd,
Avail) fold into one **Selected / Needed** column, whose value shows the full split on hover or
focus.

**Re-upload with `replaceSchedule: true`** is never blocked. Live PENDING requests are rewritten to
the openings that survived, a request that loses everything is auto-REJECTED by "Hardware Schedule
Import", accepted requests are left alone, and every live request gets an `integrityNote` that shows as
an amber alert on its request screen.

### Warehouse Module

**Two different "available" numbers, and they are supposed to differ (#342).** The Inventory view's
availability is `on-hand - deficient`: what is physically unspoken-for in the building. The shipping
request workspace and the shop-assembly batch gate use `on-hand - deficient - reservations`: what may
still be *claimed*. A product can read 10 available in the warehouse and 0 available to a new request;
that is not a bug, it means live requests or batches are holding it.

**Confirming a pick consumes its source request's (or batch's) reservation (#367 moved this off
approve).** A pull whose request reserved exactly what it needs still picks fine - the check excludes
the request's own claim (self-coverage). **Every claim has a request behind it** - no pull holds one directly, so a
pull whose source request was rejected after the accept simply competes with everyone else and
consumes nothing.


**Entry**: `/app/warehouse` -> Warehouse landing page with stat cards and "Go to" card buttons for: Receives, Receive Approvals, Inventory, Locations, Receiving, Put Away, Pull Requests, Stock Pool, Deficient Items and Custom Items. Shipments moved to the Shipping module. Since PR #395 the Deficient Items card shows `deficientCount` (deficient units across project inventory + stock pool - the same rows the review page lists, amber edge when non-zero). The card count matching its destination page is the thing to assert.

**There is no Deliveries page any more (#416).** It was a read-only lens over active POs, and its "Upcoming Deliveries" accordion asked `expectedDeliveries` for the exact PO population `openPOs` already drew the Receiving page's awaiting-receipt table from - the same three statuses, not soft-deleted - so on one page it would have been the same list twice. Only the back-order grid survived the merge, as a **Back-Ordered Items** section of Receiving; the accordion's urgency chip moved onto the awaiting-receipt table's Expected Delivery column. `expectedDeliveries` is gone from the schema entirely (querying it errors `Cannot query field`), `backOrderedPoCount` (the count of active POs still owed anything, not a unit sum) now rides the **Receiving** card as "N POs back-ordered", and `/app/warehouse/deliveries` redirects to `/app/warehouse/receiving`. Anything in an older session note about a Deliveries card, its project landing, or its "All Projects" toggle (PR #397) describes a page that no longer exists.

**Inventory tab default**: Navigating directly to `/app/warehouse/inventory` defaults to "All Projects" view — shows the "Projects" back button, "All Projects" heading, and the Hardware Items grid immediately. There is no Opening Items tab any more: nothing assembled is tracked. The ProjectLandingPage is NOT shown on initial load. Clicking "Projects" brings up the ProjectLandingPage where you can filter to a specific project or click "All Projects" to return to the all-projects view.

**Receiving**: select POs awaiting receipt (GP-Registered, Vendor Confirmed, Partially Received) ->
enter quantities (Product Code, Ordered As, Hardware Category, Ordered Qty, Already Received, Pending,
Receive Now) -> attach a packing slip -> Submit for Approval. A Warehouse Manager approves it at
`/app/warehouse/receive-approvals`, which posts the GP receipt; the units land unlocated and go
through Put Away (see "Receiving is now draft-first" near the top). Receiving moves the PO to
PARTIALLY_RECEIVED and then CLOSED.

**Receive/History toggle since #447** (PR #450): the page header carries a two-button toggle. The
Receive side is everything below; the History side is the Receiving History view - every PO that
reached GP including CLOSED ones, one row per PO (PO #, vendor, project, status chip, "N of M"
received, receive count, last received), text search + project filter, chevron-expandable. A row's
receives load lazily on first expand via the existing `poReceivingDetails` query and show each
receive's GP receipt number, batch, timestamp, receiver and line quantities. Receipt numbers also
show in the receive success dialog ("GP Receipt ...") and as a GP RECEIPT column in Recent Activity.
Receives predating #447 render a dash. TUBC mints receipt numbers prefixed `RC` (e.g. RC0000054),
not the `RCT` prefix the UC Connects docs describe - assert on the number GP actually returned, not
on the prefix.

Three sections since #416, in this order: **POs Awaiting Receipt**, **Back-Ordered Items**, **Recent
Activity**. The back-order grid is line-level and cross-project (no project landing step), carries a
Project column that reads "Stock PO" for a project-less PO, and chips how late or soon each line is
(`3d overdue` / `Today` / `Tomorrow` / `In 5d`, nothing beyond a week or with no date). The same chip
sits on the awaiting-receipt table's Expected Delivery column.

**POs Awaiting Receipt has a search box (#857, PR #912).** It matches the PO number, vendor, and the
project's job number or name, case-insensitively, and narrows as you type (client-side, since every
open PO is already loaded). The heading reads `(12 of 265)` while searching and `(265)` otherwise, a
no-match line shows when nothing matches, and the grid shows 25 rows a page.

A successful receive now refetches this page's own three reads, so a line the receipt closed leaves
the back-order grid without a manual reload; a queued receipt that drains later evicts
`backOrderedItems` for the same reason. Before #416 a receive only refetched the inventory summaries.

**Both grids want POs at GP_REGISTERED or later, and `registerPoInGp` is relay-gated.** With the relay
connected, register one on TUBC and the grids fill from a real GP row. With the relay disconnected you
get whatever production already holds for TUBC and nothing new.

Intercept the GraphQL reads instead, when it comes to that: from a `javascript_tool` script, wrap `window.fetch`, match the operation
name in the request body (`GetOpenPOs` / `GetBackOrderedItems`) and return rows built from `new
Date()` offsets. That drives the real components, which is enough to assert the column set, the
"Stock PO" and em-dash fallbacks, and every urgency band in one pass.

Be honest about what that does and does not cover. It proves the rendering. It does NOT exercise the
receive itself, so the refetch wiring above - the thing that makes a filled line leave the grid
without a reload - stays unverified at runtime until somebody receives against a real GP-registered
PO. Say so rather than calling an intercepted pass end-to-end.

**Build the intercepted rows' dates from local components, not `toISOString()`.** `toISOString` is UTC, so
after ~20:00 Eastern it names tomorrow, and the chip you assert against is then off by a day for a
reason that has nothing to do with the code under test. This is the same trap as #238 itself.

**Inventory**: Browse by hardware category and product code, see storage locations.

**Pull Requests**: Queue of pull requests from shop assembly or shipping modules. Two tabs (Shop
Assembly / Shipping Out); clicking a row opens the detail modal. Both grids grow with their rows up
to 520px and then scroll inside the grid (#856). Since #367 the old Staging column is
a **Phase** column - a tag over a line of detail, because `Status` stopped being enough once picking
became its own phase:

| Phase | Detail line | Means |
| --- | --- | --- |
| `Pending` | Not started | Nobody has pressed Start pick |
| `Picking` | Nothing off the shelf yet | IN_PROGRESS, `pickedAt` null, no pick lines |
| `Short` | Part-picked - remainder outstanding | A short confirm landed; some stock is gone, the rest is owed |
| `Picked` | Ready to hand over | Picked. **Send to shop** (shop assembly) or **Send to staging** (shipping out) completes it, which is where v1 stops following the hardware |
| `Completed` / `Cancelled` | - | Terminal |

An IN_PROGRESS row reading `Picked` in Phase is the normal, correct state until someone hands it
over - Status and Phase disagreeing is the point of the column.

#### The pick (#367) - where inventory actually moves

Approve is gone. There is no `Approve and Start` button anywhere, and no Available Qty / Status
columns in the detail modal's Loose Items table (they forecast whether an approve would succeed, and
approving no longer moves anything).

**Driving it end to end**, verified live on Railway 2026-07-28:

1. Open a PENDING pull -> **`Start pick`**. This routes straight to
   `/app/warehouse/pull-requests/<id>/pick`; there is no toast and no confirm, because starting is
   the first step of a job rather than a decision. The pull goes IN_PROGRESS and **nothing is
   deducted** - verify with `inventoryItems` before and after.
2. The page: `PICK SHEET` eyebrow, mono PR number, phase tag, project and requester; gauges for
   `PRODUCT CODES / REQUIRED / ENTERED / REMAINING`; then one section per product code.
3. Each section lists **every opening it is owed to** (`Owed to 1 opening`) and a ledger of
   every candidate location: `LOCATION | RECEIVED | AVAILABLE | PULLED`. There is deliberately **no
   suggested column and no autofill** - assert their absence, it is the whole point of the slice.
4. Number inputs carry `aria-label="Pulled from <bin>"` and a `max` of that row's available, which is
   what makes them addressable with the extension's `find`.

**What to assert, and the traps:**

- **Deficient units are withheld.** A row with `quantity 4, deficient 1` shows Available **3**.
- **Over-entry** on a row shows `Only N here` under the input, a page-level red alert, and disables
  Confirm. Over the pull's own requirement shows `... more than this request asked for`.
- **`Save draft` then reload**: entries come back. Zeros are *not* stored, so a box you set to `0`
  returns empty - that is correct, not a lost draft.
- **The confirm button changes name**: `Confirm pick` when balanced, `Confirm short pick` when
  something is entered but not everything, disabled when any ceiling is crossed.
- **On success the page navigates back to the queue**, so a toast assertion there is racy - assert
  on the inventory rows and `pickedAt` instead.
- Once picked, the page renders read-only: inputs disabled, `Save draft` and `Confirm pick` gone,
  and a banner naming who picked it and when. `Print pick sheet` still works.

**The against-FIFO test - the one that proves the feature.** Find a product code sitting in two bins
(`inventoryItems(projectId, category, productCode)` returns `receivedAt` per row), note which is
oldest, then deliberately pick from the **newer** one. Old behaviour would have drained the oldest.
Verified live: A-1-1 (oldest, received 03:51) untouched at qty 1, A-1-3 (received 04:07) 4 -> 3, and
the `PULL_DEDUCTION` audit row carrying `aisle/row/bay`, `warehouseCode` and `oldQuantity/newQuantity`
- the record the old FIFO deduction never kept.

**Short pick**: enter less than required and Confirm. The pull stays IN_PROGRESS with `pickedAt`
null, the queue phase reads `Short`, purchasing gets one `INVENTORY_SHORTFALL` notification (deduped
per pull, so a second short confirm does not raise another), and the remainder is keyed in later.
Since PR #401 that notification speaks the pick frame - `<CATEGORY> <CODE>: N of M picked - S still
owed (A free in the project now)` - matching the pick page's own alert. The old gate-frame wording
(`need N, M available (short S)`) still belongs to the *creation-gate* and sent-short messages;
seeing it on a short pick is a regression.
An empty submission is refused *while stock is available* but **allowed when there is none** - that
is the "walked the racks, found nothing" case and it confirms short of everything.

**Fetch list**: a shipping-out pull's OPENING_ITEM lines are *fetched*, not picked - check-offs with
no quantity, persisted per leaf, editable for the whole IN_PROGRESS life of the pull (they outlive
the pick confirmation, because a pure fetch pull is confirmable before a single leaf is ticked).

**The printed sheet** (`Print pick sheet`) opens a blob URL in a new tab: per-code sections, full
leaf lists, every location with Received/Available, **blank write-in boxes**, and a
`Picked by / Date / Keyed into Nexus by` signature footer.

**There is no per-leaf staging any more.** The `Stage carts` panel, the `Staging` phase and the
`Mark as Pulled` button are gone with the door leaves: a picked pull is handed over whole with
**Send to shop** or **Send to staging**, which completes it after its own confirm dialog.

**Cancel Pull (#343)**: an outlined red button in the modal's action bar on an IN_PROGRESS pull
only. Absent on a PENDING pull (discard the shop-assembly batch, or reopen or reject the shipping
request, instead) and on a completed one.

- It opens its own modal (not the standard ConfirmDialog) with a warning alert, an optional Reason
  textarea, `Keep pull` and `Cancel pull and restock`.
- Success toast names the units returned and whether the claim was re-created. If the returned
  hardware could **not** be re-reserved you get a *warning* toast carrying the request's new
  `integrityNote` instead - that is a real state, not a failure.
- **Refusal keeps the dialog open** and renders the server's message in a red alert
  (`data-testid="cancel-blocked"`).
- **Only a pull being picked can be cancelled.** A completed one has handed its hardware over - to
  the bench or to a shipping desk - and v1 does not follow it past that point, so there is nothing
  left to reverse. The button is absent on a completed row.
- After a cancel: stock is back in project inventory on the rows it came off. A shipping request is
  back in the Shipping accept queue as Pending with its claim re-created, and re-accepting it mints a
  **new** pull with the **same request number** - so a search by number can legitimately return a
  cancelled row and a live one. A shop-assembly batch's openings go back to pending on their request
  and nothing is re-reserved (#646).

**Stock Pool** (`/app/warehouse/stock-pool`): Shows stock items not tied to a project. Has a "Warehouse" filter dropdown in the filter row with options "All warehouses", "Warden (WRD)", "VP (VP)". Grid has a "Warehouse" column (visible when data rows exist). Empty state shows "Nothing in the stock pool yet" message.

**Transfer dialog** (PR #159 / PR #160, issue #88): Accessible from two places:
- Stock Pool grid row: "Transfer (same or other warehouse)" icon button (swap-horizontal arrows) in the Actions column.
- Locations tab right-side panel: click a bin row to open the panel, then click "Item actions" on a Stock Pool or Hardware Items row → "Transfer" menu item.

Both entry points open a "Transfer <productCode>" MUI dialog with: an "X available to transfer." line, a "Destination warehouse" dropdown (defaults to the source item's warehouse), Aisle/Bay/Bin MUI Autocomplete fields (suggest existing bin values; are comboboxes with autocomplete="list", NOT plain text boxes), and a Quantity spinbutton defaulting to the available quantity (max=available). Transfer button stays disabled until all three location fields are filled. On success, the dialog closes, the grid refreshes automatically (source row qty drops, a new row appears at the destination bin if it didn't exist), and a success toast fires briefly. To open autocomplete suggestions: focus the input then dispatch a keydown ArrowDown event.

**Receiving warehouse selector** (PR #158): When receiving a PO, the Receive modal includes a "Receive into warehouse" dropdown near the top, defaulting to "Warden (WRD) · default". Only visible when a PO is GP_REGISTERED, VENDOR_CONFIRMED or PARTIALLY_RECEIVED and you open the receive flow.

**Put Away** (`/app/warehouse/put-away`): Lists unlocated project inventory items grouped by hardware category. Each row shows Product Code, Qty, PO#, Received date, and Aisle/Bay/Bin comboboxes + an "Assign" button (disabled until all three location fields filled). Has a "Filter by Project" dropdown. Items returned to project inventory via the Return dialog appear here immediately.

**Put Away several rows at once (#857, PR #912).** The project tables and the stock pool table open
with a tick column, and one selection spans both sections. **One warehouse at a time:** once a row is
ticked, rows from other warehouses are disabled with a tooltip naming both warehouses, and a table's
header box ticks that table's rows from the selection's warehouse. A selection bar sticky at the
bottom of the viewport carries aisle / row / bay pickers narrowed to that warehouse and a
`Put away N rows here` button, which sends each row whole to that bin through the per-row assign, one
at a time. Rows that fail stay ticked and are listed with the reason above the tables; the rest are
cleared. The per-row Assign stays for partial quantities. Both tables are fit-to-width tables with
resizable columns (#856); Assign is a fixed last column, always in view.

**Shipments page** (`/app/shipping/shipments`, issue #89; `/app/warehouse/shipments` redirects there):
- Global list of all shipped packing slips (across projects), in the Shipping module.
- **`?slip=PS-...` opens the page searched to that slip with its row expanded** (#859, PR #904);
  collapsing the row by hand drops the parameter. The confirm-shipment toast links here.
- Expandable rows, a slip search and a Project filter; the row layout and the status-gated actions,
  Return included, are described under the Shipping module ("Shipments carry a lifecycle").

**Return dialog** (issue #89):
- Title: "Return shipment <PS-NUMBER>"
- Subtitle: "<Project name> · loose hardware only. Opening items are not returned."
- "Destination warehouse" required select (defaults to "Warden (WRD)").
- "Reference / note (optional)" text field.
- "Cancel whole shipment" button (separate cancellation action, distinct from return).
- One section per loose line, each showing: product code (heading), hardware category + opening reference (e.g. "HINGE · opening 101"), a "returnable N" chip showing remaining returnable quantity, Qty spinbutton (min=0, max=returnable remaining), Disposition select (options: "Return to project inventory", "Move to non-stock", "Defective / RMA"), Reason (optional) text field.
- When "Defective / RMA" is selected as Disposition, a "PO / RMA reference (optional)" text field appears between the Disposition select and the Reason field.
- "Cancel" and "Record return" buttons at the bottom.
- On success: dialog closes, toast fires "Return recorded for <PS-NUMBER>".
- Validation: if any Qty exceeds its returnable max, clicking "Record return" shows an inline error alert at the top of the dialog: "<PRODUCT-CODE>: cannot return more than N". Dialog stays open, nothing is submitted.
- After a return is recorded, the returnable chip amounts decrease correctly on the next dialog open. The packing slip row remains in the grid.

**Return disposition outcomes**:
- "Return to project inventory": creates an `InventoryLocation` record for the project with no bin assigned (unlocated). Item appears in Put Away tab and in Inventory under the project. Does NOT appear in Stock Pool.
- "Move to non-stock": creates a `StockItem` with quantity=N, deficientQuantity=0. Appears in Stock Pool.
- "Defective / RMA": creates a `StockItem` with quantity=N, deficientQuantity=N (fully deficient, available=0). Appears in Stock Pool AND in Deficient Items Review page.

**GraphQL queries for verifying returns**:
- `{ stockItems(productCodeContains:"RET-") { productCode quantity deficientQuantity available } }` - checks stock pool entries
- `{ deficientItems { source productCode hardwareCategory deficientQuantity } }` - checks deficient items (DeficientItemRow type, no quantity/available fields)
- `{ unlocatedInventory(projectId:"<UUID>") { inventoryLocation { hardwareCategory productCode quantity aisle row bay bin } } }` - returns InventoryItemDetail (not InventoryLocation directly). Use nested `inventoryLocation` field for product/qty data.

### Shop Assembly Module

**Entry**: `/app/shop-assembly` -> landing page: "Active Pull Requests" and "Awaiting Review" stat
cards, a **Start a Request** button, and one "Go to" card for Requests.

The module is two screens in v1. A request is raised in the import wizard (the button deep-links to
`?purpose=assembly`), and everything after the pull completes is untracked - the bench is outside the
system.

**A request is a flag, and the Shop Assembly Manager works it in batches (#646, PR #660).** Raising a
request records the openings and what each is owed. It reserves nothing, checks nothing and mints no
pull. On the Requests page the manager opens a pending request and allocates a **batch**: a subset of
its pending openings with per-line quantities (partial is allowed). Creating the batch gates on the
project's available inventory for exactly those allocations, reserves them under the batch's own id,
and mints one warehouse pull numbered `<request number>-B<n>`. Batching an opening consumes it; an
opening with nothing allocatable cannot be batched and stays pending. **Dismiss remaining** writes off
what is left, and **Reject request** is only offered while nothing has been batched. Batch, dismiss,
reject and discard are gated to the Shop Assembly Manager role set (`SHOP_ASSEMBLY_MANAGERS` in
`backend/app/auth_policy.py`).

**Requests page**, `/app/shop-assembly/requests`. A Pending / Worked / Rejected toggle:

- **Pending** is the queue: requests with openings still waiting, where batches are made.
- **Worked** shows requests where every opening has been batched or dismissed, with each batch and
  its **stage chip** (Accepted / Pulling / Done). **Discard** undoes a batch and hands its openings
  back to pending, and only works while the warehouse has not started that batch's pull.
- **Rejected** is history. Nothing was reserved for those requests, so nothing was released.

**Cancelling a batch's pull** returns only that batch's openings to pending and re-reserves nothing;
the restocked units go back to the free pool.

### Shipping Module

**Entry**: `/app/shipping` -> Shipping landing. **Start a Request** opens the request workspace
(`/app/shipping/requests/new`, #608), which composes schedule lines and loose inventory lines in one
cart and carries its own project picker. Requests are accepted at `/app/shipping/requests`
(Pending / Accepted / Rejected, with a **New request** button), packing slips are built in Staging
(`/app/shipping/staging`), and shipped slips live on Shipments (`/app/shipping/shipments`).

**Confirming a shipment leaves a toast that stays (#859, PR #904).** It reads `Shipment PS-...
confirmed` and carries a **View shipment** action to `/app/shipping/shipments?slip=PS-...`; a toast
with an action stays until it is closed, taken or replaced. It used to be a four-second toast fired as
the dialog closed, gone before anyone could read it.

**The confirm step is the Delivery Request form since #447** (PR #450). Confirming a cart opens a
sectioned dialog (Shipment / Shipper / Pickup location / Deliver To questionnaire / Contacts), not
the old slip-number-only form. Shipper name is read-only from the signed-in identity and the email
prefills from it; pickup location prefills from the primary warehouse and is name-only when the
seeded warehouse has no address fields. Everything except the slip number is optional. The success
view's "View Delivery Request" opens the generated PDF (client-side react-pdf), which replicates the
paper Delivery Request form; a shipment's document is reprintable later from the shipments list and
regenerates from the STORED fields, so an edit shows up on the next print.

**Shipments carry a lifecycle since #447**: SCHEDULED -> PICKED_UP -> DELIVERED, strict one-way; the
states document the truck's journey only and move no inventory. The Shipments page
(`/app/shipping/shipments`) is expandable rows now, not a DataGrid: row = slip #, project, status
chip, shipped by, created, pick-up, delivery, carrier; expansion = the item lines plus the actions,
each status-gated - Delivery Request (always), Edit (SCHEDULED only, full-replace semantics, a
cleared field really clears), Mark Picked Up (SCHEDULED), Mark Delivered (PICKED_UP), Return
(unchanged). Lifecycle/edit mutations return the whole header, so the row updates through the Apollo
cache with no reload - assert on the row, do not wait for a refetch.

**Hardware only reaches the staged pool when its SHIPPING_OUT pull is COMPLETED.** Confirming the
pick leaves the pull IN_PROGRESS with phase "Picked - Ready to hand over" and Staging stays empty;
"Send to staging" in the pull detail modal is what completes it. Budget for that extra step
when scripting the chain.

**The request workspace's schedule tab composes off what is still owed.** Products show Still owed
(required, less what has already left and what other requests hold), On order and the free pool, and
the cart takes no more than is free. Since #647 the tab splits products into a shop lane
(`SHOP_HARDWARE`) and a site lane; unclassified hardware reads as site, and the site lane says so.
Sending short is the ordinary case: add less than the suggestion, or leave the line out. Creating the
request reserves its loose hardware (#342), which is why accepting it is a pure human gate.

### Tenant Owner and UC Nexus Admin Modules

**Entry**: `/app/tenant-owner` -> Tenant Owner landing: stat cards (Users, Distinct Products,
Openings) + "Go to" cards for each sub-route. `/app/nexus-admin` -> UC Nexus Admin landing, the
cross-tenant half: User Management, Relay Installs, Nexus GP Traffic, SharePoint Migration and
(DB Admins only) Database Access.

**Sub-routes**:
- Project Purchasing Progress (`/app/tenant-owner/project-purchasing-progress`)
- Hardware Status by Project (`/app/tenant-owner/hardware-status`) - loads nothing until at least one
  project is picked; the Projects Autocomplete is multi-select and quantities SUM across the
  selection (one row per (category, product code), not per project). Columns: Required /
  Not Purchased / PO Drafted / On Order / Received / On Hand / Sent to Shop / Staged / Shipped Out,
  each with an info-tooltip header stating its exact rule. "Sent to Shop" is a lifecycle EXIT
  (completed shop pulls - shop assembly is outside the Nexus pipeline), and "Staged" is completed
  shipping pulls not yet on a packing slip. Zero counts render dimmed. A "Filter products…" box
  appears once a project is selected and matches product code or category.
- Warehouses (`/app/tenant-owner/warehouses`) — warehouse CRUD (PR #158, issue #88); see below
- Projects (`/app/tenant-owner/projects`) — edit project details + OSSA flag (see below); a project's
  detail page is `/app/tenant-owner/projects/:id`, and its hardware classification page (#735) is
  `/app/tenant-owner/projects/:id/classifications`
- Inventory Value (`/app/tenant-owner/inventory-value`)
- User Management (`/app/tenant-owner/users` for the tenant, `/app/nexus-admin/users` across every
  company) — assign Clerk roles
- Location Cleanup (`/app/tenant-owner/location-cleanup`)
- (PO Document Settings moved to the PO module: `/app/po/document-settings`; see below. Unknown `/app/tenant-owner/*` sub-routes silently render the Tenant Owner landing, not a 404,
  and every `/app/admin/*` path redirects to it.)

Inventory quantity corrections are NOT here — they live in the Warehouse module (Locations tab).

**Warehouses page** (`/app/tenant-owner/warehouses`, PR #158, issue #88):
- DataGrid columns: Name, Code, Location (city + province concatenated), Primary (chip "Primary" / blank), Status (chip "Active" / "Inactive"), trash icon.
- Primary warehouse (Warden/WRD) has NO trash icon — delete is blocked on primary.
- Non-primary warehouses have a trash icon that opens a confirm dialog: "Delete [name]? This is blocked if any inventory still references it."
- Create dialog: Name (required), Code (required), Address, City, Province, Postal Code, Primary checkbox, Active checkbox (checked by default). Save toast = "Warehouse created".
- Edit dialog: same fields pre-populated, Save toast = "Warehouse updated".
- Delete confirm toast = "Warehouse deleted".
- Seeds: Warden (WRD, Primary, Active) and VP (VP, Active) are seeded by default.

**Projects page** (`/app/tenant-owner/projects`, issue #67):
- Tenant Owner only (a UC Nexus Admin holds it too). Anyone else gets a permission Alert; the backend also enforces it (see Lessons Learned).
- DataGrid columns: Project #, Description, Client, Job Site, OSSA (chip "Yes" / "—"), Openings. Click a row to open the edit dialog.
- **Edit dialog**: OSSA toggle + editable text fields (description, client, job site name, address/city/state/zip, general contractor, GC contact name/phone/email, project manager, application). A read-only "From TITAN" section shows project number, submittal job no, submittal assignment count, estimator code, TITAN user ID — these are immutable.
- Save calls `updateProject`, refetches the grid, and shows a "Project updated" toast.

**PO Document Settings page** (`/app/po/document-settings`, issue #230 - lives in the PO module, reached via the "Document Settings" button on the PO list header):
- PO Manager or Tenant Owner only (anyone else gets a permission Alert; the mutation is role-gated server-side). Single-record form, not a grid.
- Fields: company from-address, payment terms, confirm-with, tax numbers, mandatory bullets (one per line), wood-door FSC note, USA tariff note + effective-until date, customs broker block, shipping accounts (one per line), signature note, footer notes.
- Backed by `poDocumentSettings` (get-or-creates a single row seeded from the guideline doc on first read, so it never returns null) and `updatePoDocumentSettings`. Save toast = "PO document settings saved". These values print on every generated PO document.

---

## Lessons Learned

- Reset data (UC Nexus Admin -> Reset data) is two gates: type `reset all nexus data`, then confirm the MUI dialog. No `window.alert()` any more. On production it drops the whole schema, so it is never a testing step (see Getting Started).
- To test Receiving's quantity step you need at least one PO at GP_REGISTERED or later. Nexus drafts do not appear in the POs Awaiting Receipt list.
- The line item field formerly called "Vendor Alias" is now called "Order As" in pre-order screens (Create PO dialog, PO detail modal) and "Ordered As" in post-order screens (Warehouse receiving wizard).
- On the Import wizard Select Openings/Hardware step with a large XML file (1998 openings), `read_page` produces output that exceeds the tool token limit. Use `javascript_tool` with targeted DOM queries (or `get_page_text`) to check state and click buttons. Use `javascript_tool` to click "Select All" when `find` refs time out on the large DOM.
- Import wizard Classification step (#568/#586, #734): a guided pass walks the unclassified item groups, then a review lists everything. On the PO flow each group takes one answer - **UCH Shop**, **UCH Site** or **By Others** - on keys 1, 2 and 3 (By Others takes the items out of scope); the schedule flow asks Shop / Site only. The counter reads `N of M classified`, and Next waits until everything is classified.
- Import wizard step order for "Create Purchase Orders": Upload File -> Select Openings (or Select Hardware) -> Classification -> Organize PO Drafts -> Finalize (5 steps). There is no Purpose step (#642) and no Reconciliation step (#814).
- Classification step grouping: "Add group level" adds a grouping level (Level 1 defaults to Hardware Category). With tens of thousands of items `read_page` is too large; use `javascript_tool` to find and click buttons.
- Organize PO Drafts step (step 4 of 5): one draft card per manufacturer, each with an include checkbox, the vendor label, preferred delivery date, cost code, vendor quote number, notes, attachments, a PO total and the line ledger. There is no GP vendor pick here (#509); the GP vendor is chosen at register time. Only UCH-scoped items appear (By Others items are excluded). With the full contracterp-74.xml file, 41 manufacturer cards appear.
- Organize PO Drafts: Next is disabled until at least one draft card is ticked, and every card starts unticked. To tick many at once, use `javascript_tool` to `.click()` each card's `.MuiCheckbox-root`; direct DOM checkbox manipulation does NOT update React state.
- "By Others" classification in the ALD group correctly EXCLUDES those items from vendor PO cards. Items that appear under vendor "Aluminum Door By Others" (vendor name, not classification) with ALD hardware category are separate — they are items from that vendor that were classified as "By UCH". The vendor name and the hardware category name can both contain "ALD" but refer to different things.
- Finalize step: shows "Review & Finalize" with an Import Summary. "Finish Import Session" opens a "Finalize Import" dialog (an over-buying confirm stands in for it when a draft would over-buy, #736). After Finalize, a success dialog reads "Import session completed successfully!" and offers one button per kind created (View purchase orders / View shop assembly requests / View shipping requests) plus Return to Home (#859).
- The PO list used to be the canonical slow-resolver example (the old "All Projects" query loaded every line item, receive record and document for every PO, with a p99 near 4 minutes). The PO table is paged and sorted server-side now, so a slow PO table is worth an HTTP-log look (rule 6 in the project instructions file) rather than an assumption.
- Locations page redesign (PR #160, issue #88): The `/app/warehouse/locations` page uses a master-detail rail+panel layout. Unselected state: DataGrid shows 4 columns - Location, Warehouse (chip per row), Items, Total Qty. No separate Aisle/Bay/Bin columns. Selected state (row clicked): left DataGrid collapses to a single "Location" column rail (shows location name + warehouse code chip + qty in one compact cell per row), and a right-side panel fills the remaining width showing the bin's contents, a WRD/VP chip in the panel header, and recent activity. Close button in panel returns to unselected state.
- Locations page warehouse filter: A "Warehouse" combobox dropdown sits next to the Search locations input. Options: "All warehouses" (default), "Warden (WRD)", "VP (VP)". When a specific warehouse is selected, the "Warehouse" column disappears from the table (redundant), only that warehouse's bins show, and the count summary updates. A plain click on the combobox works — it opens the MUI Select portal and the options are reachable with `find` right after.
- Locations page horizontal scroll: body has `overflow-x: hidden` applied. No hard min-widths on the layout. `document.documentElement.scrollWidth === clientWidth` with panel open or closed.
- After a deploy on Railway, the previously-loaded SPA tab keeps the OLD `index.html` reference until a full page reload (a soft reload is NOT always enough). Bust by either closing the tab and opening a new one with `tabs_create_mcp`, or adding a query-param cache-buster like `?cb=1`. The HTML headers (`Cache-Control: no-cache, must-revalidate`) cover the *next* page load but not the currently-cached document.
- MUI `Autocomplete` with `freeSolo` (used by `LocationAutocomplete` and `OrderAsAutocomplete`) can be flaky to drive by typing when the value is a brand-new free-form string. Follow the Autocomplete pattern (click, type, wait, `find` the option); for a value with no option, use `javascript_tool` to set the underlying input's `value` and dispatch a synthetic `input` event, or drive the mutation directly with a token-bearing `javascript_tool` fetch to `/graphql` (the location-string normalization can be verified that way without UI flake).
- Mutation success in the new LocationsTab triggers `refetchContents()` + parent `refetch()`, but Apollo Client's normalized cache can leave the just-mutated `InventoryLocation` entity visible in the panel until the cache settles. The DB is correct (verified by full page reload). If you need to assert post-mutation UI state, reload the page rather than trusting the immediate read after the success toast.
- The Location Cleanup screen lives at `/app/tenant-owner/location-cleanup`. It queries `locationDuplicates` which groups location triples by case-insensitive canonical form (uppercase + trim + collapse whitespace) and surfaces variants. Empty state ("No location duplicates found") is the happy path. The merge dialog calls `mergeLocations` which rewrites every matching row across inventory_locations + opening_items + stock_items and writes one MOVE audit per row.
- The Tenant Owner Projects page (issue #67) is the first screen backed by real server-side auth. The frontend now sends the Clerk session token on every GraphQL request (Apollo auth link via `window.Clerk.session.getToken()`), and two resolvers are gated on the Tenant Owner role: `adminProjects` (query) and `updateProject` (mutation). Unauthenticated calls to them return a GraphQL error with `extensions.code = "UNAUTHENTICATED"`; signed-in non-admins get `FORBIDDEN`. Since #415 every other resolver is gated too (see "Every resolver needs a token now").
- Issues #198 and #380: free-form project creation is gone, and so is manual adoption. `createProject`/`CreateProjectInput` and `adoptGpJob`/`AdoptGpJobInput` no longer exist. Projects now appear on their own: the `gp_job_sync` background service creates one for every job in GP's job master (JC00102), on a ~5 minute timer and immediately on every relay reconnect, setting `projectId` = the GP job number and `description` = the GP job name. That means **there is no longer any way to seed a project through GraphQL without a relay** - the old ungated `adoptGpJob` fetch trick is dead. To get projects in a test environment, connect and enrol the relay and let the sync run, or hit the admin `syncGpJobs` mutation (Admin -> Projects -> "Sync from GP", which returns `{total, adopted}`) once a relay is up.
- Issue #380: the "Create GP Job" button (`CreateGpJobDialog`) sits on the Tenant Owner Projects page since #743 - it was on the Import landing until then, which is now only a project picker. It originates a job in GP via `createGpJob(input: CreateGpJobInput!)`, which is admin-gated and requires a connected relay. Every field except the job number and name is a live GP read (`gpCustomers`, `gpCustomerAddresses`, `gpTaxSchedules`, `gpDivisions`, `gpEmployees`), so the whole form stays disabled while the relay is down. The two address selects stay disabled until a customer is picked and re-fetch when it changes. Eight optional fields sit behind a "Show optional fields" toggle. GP validates the submit and its own message is shown in the dialog - in TUBC the fiscal calendar ends 2025-09-30, so today's date reliably produces "Job cannot be created within a closed period"; use a FY2025 `createdDate` for a success path. Issue #392: Estimator and WS Manager are selects over `gpEmployees` (the GP payroll master UPR00100), not free text - the proc rejects an id that is not in that master with "The estimator does not exist in the payroll master table" (error state 51117). TUBC has exactly two employees, IANB and JONATHANR. `createGpJob` returns `{created, project}`: `created` is false when GP already held the job number and the mutation adopted it instead of creating one, so resubmitting an existing number succeeds with "already existed in GP and is now a project" rather than erroring. New projects default `offSiteStorageAgreement` to false and the GC/address fields to null, handy for testing the Projects edit flow.
- Issue #444: both address selects in `CreateGpJobDialog` carry a "+ Add new address" row pinned last (only when that picker's customer is set). It opens a nested `AddCustomerAddressDialog` scoped to that customer and creates the code in GP via `createGpCustomerAddress` (admin-gated, relay write `create_customer_address`, RM00102 create-only - the relay pins the proc's UpdateIfExists to 0). The address code uppercases as typed; on success the picker refetches and auto-selects the new code. A duplicate code answers relay code `address_code_already_exists` rendered inside the nested dialog, which stays open with the typed input intact. Verified live 2026-07-30: NEXTEST1 under ELL100 in TUBC, then a full `createGpJob` using it (NEXUS-444-T1). The op is new, so a release relay build answers RELAY_OP_UNSUPPORTED on the create (the reads still work) until the relay is rebuilt.
- A DataGrid driven by a `cache-and-network` query (e.g. the admin Projects grid) can render "0–0 of 0" for a beat on first mount before data arrives, so a read immediately after navigation may catch the empty state. Read again, or wait for a known row value, before asserting the grid is empty.
- MUI `spinbutton` (number input) fields with a pre-filled value will APPEND when typed into - "3" becomes "31" if you type "1". Always click the field first, select all (`ctrl+a`), then type the desired value. Alternatively use `form_input`, or `javascript_tool` to set the value directly.
- The Transfer dialog success toast is very brief - by the time the next read runs after the click, it may already be gone. Confirm success by observing the grid data (dialog closed + new/updated row present) rather than waiting for the toast text.
- There is no vendor field in PO create/edit at all since #509, and no Admin > Vendors page behind it - the local vendors table is gone. The only vendor a PO carries is the GP one (PM00200), chosen in the Register in GP dialog from the live `gpVendors` list, so a draft shows a blank vendor until it is registered. `/app/tenant-owner/vendors` now falls through to the Tenant Owner landing like any other unknown sub-route.
- Receiving: after selecting POs on POs Awaiting Receipt, the Receive modal opens. The "Receive Now" spinbutton defaults to 0. Setting the DOM value alone fails (it does not stick on a React controlled spinbutton). Focus the input (click it, or `javascript_tool`), then press ArrowUp with the `computer` tool's `key` action to increment. ArrowUp from 0 goes directly to the max (pending qty) in one press.
- Transfer dialog Aisle/Bay/Bin: these are comboboxes with autocomplete="list". Use `javascript_tool` to set the underlying input value (native value setter + `input` event), or the Autocomplete pattern when the value is an existing option. This reliably sets the values without triggering dropdown selection. The Transfer button enables once all three fields are filled.
- Locations page (Warden filter, panel open): when a single warehouse filter is active, the left rail single-column shows just the bin name + qty (no warehouse chip in that column, since filter is already scoped). The right panel header still shows the warehouse chip (e.g. "WRD").
- Verifying a generated PDF (issue #230 PO document): the doc is text-based react-pdf, not an image, so `pdftotext` works. Fastest path for content assertions: use the dialog's "Save to PO documents" to upload it, query the PO's `documents { downloadUrl }` (presigned S3 URL) via GraphQL, `curl` the URL to a file, then `pdftotext -layout` (or `-raw` for the totals column, which `-layout` misaligns since Subtotal/Freight/Miscellaneous/Tax/Order-Total are right-aligned). "Generate & preview" opens a blob in a new tab that is hard to read through the extension - prefer save-then-fetch.
- pdftotext/poppler is NOT installed on the dev machine, and naive stream-inflation can't read the text (react-pdf subsets fonts to custom glyph IDs). Working alternative: open the presigned `downloadUrl` directly in a browser tab (Chrome renders PDFs natively) and take a `computer` screenshot - the full totals column is readable in the image. Verified this way for issue #156 (Tariffs line + Order Total math).
- Issue #156 fields: PO detail modal shows "Shipping Costs" / "Tariffs" info rows ('-' when null) and edit-mode number fields; the generate-document dialog's Freight prefills from the PO's shippingCost (saved documentData override wins) and its new Tariffs field from the PO's tariffAmount; the PDF prints a Tariffs totals line only when > 0.
- Issue #216 buyer identity (scoped to REGISTERING by issue #256 - drafting needs neither): registering a PO into GP requires the signed-in user to have a GP buyer identity, set in User Management and, since #724, only for a user holding the PO User role. There is no per-project buyer assignment any more (#695). The register dialog's Buyer field is read-only (your identity); its cost-code dropdown offers every code GP has active on the job.
- Issue #216 delivery dates: PO Requests capture "Preferred delivery date" per vendor card in the import wizard's PO step; the detail modal edits Preferred only while DRAFT and Expected only when GP-Registered/Vendor-Confirmed (server-enforced).
- Import-created PO drafts have EMPTY Order As values unless set in the wizard's PO step - the register dialog then blocks submit with per-line 'Required' errors until each line's Order As is filled.
- The generate dialog + admin PO-settings text fields APPEND when typed into if they already hold a value (same MUI controlled-input quirk as spinbuttons). For a pre-filled field, select all before typing, or set the value via `form_input` or `javascript_tool` using the native value setter + an `input` event (match the label's `for` attr to the input id), or drive the mutation directly. Empty fields fill fine.
- Date-only fields: a `<TextField type="date">` renders as Month/Day/Year spinbuttons in the a11y tree. Set it via a `javascript_tool` native setter with a `YYYY-MM-DD` string on the underlying input (dispatch `input` + `change`). Note: formatting a `YYYY-MM-DD` string with `new Date(str)` is UTC and prints the previous calendar day in a behind-UTC tz - the PO-document code parses date-only strings as local (fixed in #238), so the printed required-by should match what was entered.
- To seed a project's job-site address for the PO document's "Use project site" ship-to option (most test projects have null address fields), call `updateProject(id, {jobSiteName, address, city, state, zip})` via a `javascript_tool` fetch (Tenant Owner gated). Then the dialog's "Use project site" button builds a real "UC Hardware Inc. - Deliver to site / ..." block.
- PO list rows: clicking the row's text via a `find` ref may NOT open the detail modal (the click can miss the row handler). Reliable alternatives: a coordinate click from a screenshot, or `javascript_tool` finding the leaf element by text and clicking its `closest('td')`.
- Locations page bin panel "Item actions" menu (stock rows): Move / Transfer / Adjust Qty / Unlocate. "Adjust Qty" opens the shared LocationActionDialog - Confirm stays disabled until a non-zero adjustment AND a reason are entered; the helper text under the adjustment shows the computed "New qty: N" and flags negatives. Verified live: adjustment writes an ADJUSTMENT audit row (`auditLog(limit: N)`) with performedBy "UC Nexus Admin".
- Draft PO create (issue #256 dialog) works with the relay down end to end: the created draft's `preferredDeliveryDate` round-trips exactly (entered 2026-08-15 -> stored 2026-08-15 -> detail modal renders 8/15/2026, no UTC day shift). Cancelling a draft removes it from the `purchaseOrders` list entirely.
- Availability semantics (issue #229): available = quantity - deficient, so a 10-qty row with 7 deficient shows available 3. Read it per row via `inventoryRows` (`inventoryLocation.available`) or per combo via `projectInventoryAvailability`; cross-check against `deficientItems`. (The old `inventoryHierarchy` roll-up query that documented this is deleted.)
- `Notification` has no `kind` field - it is `type` (`{ notifications { id type message isRead createdAt recipientRole projectId } }`). Querying `kind` fails the whole document, so a mistyped notification field takes the relay/pull/request fields in the same query down with it.
- The bell panel is a plain MUI Popover with a "Notifications" heading and one bold row per unread item; the app-bar badge count matches `notifications` where `isRead: false`. It renders every audience regardless of your role, so 4 in the badge means 4 rows in the panel.
- Project autocompletes (the ProjectPicker used by shipping and others, Hardware Status by Project and
  Project Purchasing Progress) key their options by project id since #853 (PR #889). They used to key
  by name, and a company with repeated project names (UCSH has many) left ghost rows as the list
  narrowed - 36 options for one real match. A stale extra option in a picker is that bug coming back.
- `shopAssemblyRequests` takes a `status` and defaults to **PENDING**, so `[]` means no request is waiting, not that no requests exist. Ask for `status: APPROVED` (the Worked view) or `REJECTED` to see the rest; every row carries a derived `stage`.

## 2026-07-28 UI revamp - what changed for testers

An experimental aesthetic+motion revamp landed on master (single revertable PR). Business logic,
queries/mutations and every action are unchanged, but a lot of chrome moved:

- **Navigation is a persistent left rail on desktop** (collapsible via the panel icon in the app
  bar; state persists in localStorage `uc-nexus-rail-collapsed`). The hamburger-opens-drawer flow
  now exists only below the `md` breakpoint. Sub-items expand under
  the active module. The `<- Warehouse` / `<- Projects` back buttons are gone; since #711 every page
  below a landing has a page header whose parent link is the way back (the breadcrumbs are gone too).
- **Icons are lucide (stroke) not Material (filled)**; icon-only buttons gained aria-labels
  (e.g. `Open <PO> details`). Selectors keyed on Material icon `data-testid`s will miss.
- **Stat values animate** (count-up over ~0.5s on mount). A read or screenshot taken immediately after
  render can catch a mid-flight number - wait and read again. With
  `prefers-reduced-motion`, values render instantly.
- **PO list**: the stat tiles became one status strip (since split into NEXUS and GP STATUSES boxes, #682, and optional since #851); segments carry `aria-pressed` and `aria-label="Filter by <label>"`. The whole data row opens the detail modal. Empty modal fields render an em-dash `—` (was `-`).
- **Escape behavior changed on purpose**: Pull Request detail modal now closes on Escape;
  Receive modal and Transfer dialog now *block* Escape once you have typed values into them
  (they used to discard silently). The assembly modal's close semantics are unchanged.
- **Shipping browse** (now the Staging page, `/app/shipping/staging`) lists the staged pool - what a completed shipping-out pull put on the floor, minus what a slip has already carried out - with a text search and the container workspace beside it.
- **Import wizard**: step 1 shows a single success strip (the old second green alert is merged in). The Purpose cards this revamp introduced are gone since #642; the link that opens the wizard fixes the purpose.
- **Warehouse/Admin/Shop-Assembly landings**: the "Go to" cards now carry live counts (pending
  pulls, unlocated, deficient, etc.), driven by the same queries as before.
- **The reset button** became visible in light mode here (it was ink-on-ink); it has since left the
  bar for the Reset data page in the UC Nexus Admin module, whose confirm button is still red.
- Home's Recent Activity renders human sentences ("Staged door leaf ..."), never raw enums like
  `INSTALL_PROGRESS SHOP_ASSEMBLY_OPENING`. Since PR #396 the rows also carry a real identity mined
  from the audit `detail` payload - `Staged door leaf 62 · L1`, `Pulled inventory item 2× BB1068 ...
  · SA-E2E-367`, `Received ... · PO0000066` - with the shortened UUID only as a last resort.
- Every server timestamp in the app parses as UTC since PR #399 (`parseServerDate`; backend
  datetimes are naive-UTC with no zone suffix). Relative times reading "just now" for hours, or
  wall-clock times off by your UTC offset, are a regression of that fix, not server clock drift.
