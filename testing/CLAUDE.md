# Simulated User Testing Guide

This is a tester's knowledge journal for UC Nexus. It documents how the app works from a front-end user's perspective and how to drive it via Chrome DevTools MCP.

**Maintain this file:** Update it when you discover new behaviors, gotchas, or workflows during testing. This is a living document that grows with each testing session.

---

## Environment

**Railway is the default** for simulated user testing (issue #182 pivot - the localdev runtime was dropped for UC Nexus e2e; zero local setup needed).

- **Railway production (default)**: frontend `https://frontend-production-34fc.up.railway.app/`, backend `https://backend-production-7866.up.railway.app/`. Deploys from master after CI passes.
- **Railway PR environments** (ENABLED 2026-07-29, `prDeploys` on the project; bot PRs like dependabot deliberately excluded): every non-draft PR gets a full ephemeral replica (frontend + backend + fresh empty Postgres, migrated on boot) named `uc-nexus-pr-<N>`. Do not wait for a Railway bot comment - none was observed; the URLs are derivable: `https://backend-uc-nexus-pr-<N>.up.railway.app` / `https://frontend-uc-nexus-pr-<N>.up.railway.app`. Substitute them into the sign-in flow below; verified live on PR #401 (`/health` 200, `/testing/clerk-sign-in` mints tokens, GraphQL serves the fresh DB). Data starts empty; seed via the import fixture. `VITE_GRAPHQL_URL` is a reference variable (`https://${{backend.RAILWAY_PUBLIC_DOMAIN}}/graphql`) so each environment self-wires; `TESTING_ENABLED` and Clerk keys inherit from production. **A PR that only touches one service's directory only deploys that service in its environment** (root-directory change filtering - PR #401 was backend-only and the frontend showed `latestDeployment: null`); trigger the missing one from the dashboard or via the API (`serviceInstanceDeployV2(environmentId, serviceId)`). Environments auto-delete when the PR closes.
- **Local (manual fallback)**: frontend `http://localhost:5173`, backend `http://localhost:8000`. Run the backend with `poetry run uvicorn main:app --reload` (from `backend/`) and the frontend with `npm run dev` (from `frontend/`). Needs a local Postgres (not provided; the worktree-localdev adoption was dropped).
- **Auth**: Clerk sign-in, automated via one-time sign-in tokens (no manual password/verification needed).
  - Backend endpoint `GET /testing/clerk-sign-in` generates the token (requires `TESTING_ENABLED=true`).
  - Navigate to the frontend URL with `?__clerk_ticket=TOKEN` to auto-authenticate.
  - Tokens are one-time use; fetch a fresh one each session. Works on any runtime with the same Clerk dev instance.
- **Test XML file**: `testing/fixtures/contracterp-74.xml` - TITAN hardware schedule export, use for Import wizard testing (upload via `upload_file`)

### A PR environment is always relay-disconnected, and that is useful

The relay dials ONE backend - the `[channel] backend_url` in its `config.toml`, which is production.
A PR environment therefore always reports `relayStatus.connected: false`, and no amount of waiting
changes it. Pointing the relay at a PR backend is not a shortcut either: relay installs live in
Postgres, and a PR environment boots a fresh empty one, so the relay would have to be re-provisioned
and re-enrolled there and then put back afterwards.

Read that as a free test fixture rather than a limitation. The relay-down half of any GP-gated
feature - disabled controls, "not connected" copy, held values still displaying, buttons that must
not be clickable - is exactly what a PR environment exercises by construction, and it is the half
that is otherwise awkward to reach on production without stopping the relay for everyone.

What a PR environment cannot show is any populated GP dropdown or any GP write. Those need
production, after merge and after the installed relay is rebuilt to a build whose `_OPS` includes the
new op (an older build answers `unknown_op` -> `RELAY_OP_UNSUPPORTED`, which is its own distinct UI
state and worth checking on purpose during the deploy-before-rebuild window).

Verified on PR #412 (issue #409's buyer dropdown): the field rendered `role="combobox"`, disabled,
still showing the stored `mira`, with "The GP relay is not connected, so this cannot be changed right
now." - all four assertions met without touching production.

### Inventory can only be seeded through the relay - check this first

**Nothing puts new hardware into inventory except `createReceive`, and `createReceive` is
unconditionally GP-first through the on-prem relay.** If the relay is down there is no supported way
to seed stock, and every scenario downstream of "hardware exists" (approve a pull, stage a cart,
assemble a leaf, flag a deficiency, ship) is unrunnable. Do not improvise a workaround - re-scope the
session instead. Establish this in the first minute:

```
{ relayStatus { connected company build } }
{ inventoryHierarchy { hardwareCategory totalQuantity } }
```

`connected: false` plus `inventoryHierarchy: []` is the signature. Confirm it from the backend side
with `relayInstalls { label enrolled enrolledAt lastSeenAt }` and the Railway backend deploy log:

- A relay that is **running but not trusted** logs `"WebSocket /relay-link" 403` every ~30s forever.
  The workstation is dialling out fine; the backend is refusing the handshake.
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
- `POST /admin/reset-data` **preserves** the `relay_installs` rows across the rebuild (#352), so a
  schema reset no longer orphans the on-prem relay.

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
  relay fault. `relayStatus` is `require_user`-gated now, so a stale `getToken()` value in an injected
  fetch helper logs a full stack trace server-side. Re-mint with `getToken({skipCache:true})`.

### Seeding inventory: the PO must come from the wizard, not the Create PO dialog

**A manually-created PO seeds inventory but cannot open the assembly Reconciliation gate.** This costs
an hour if you learn it the hard way. The gate is `computeAvailableQty` in `ReconciliationStep.tsx`,
which for `purpose === 'assembly'` returns `breakdown.get('RECEIVED')` - the *lifecycle status of the
hardware-schedule item*, not live stock. Receiving against a PO built in the **Create PO dialog**
produces real `InventoryLocation` rows (`projectInventoryAvailability` shows them, the allocator would
happily reserve them) while every schedule row stays `Gap Remaining`, so Reconciliation still says
`No items have In Inventory status` and Next stays disabled.

To seed stock that *counts*, run the wizard with purpose **Create Purchase Orders** over the openings
you intend to assemble, then register + receive that PO. Its lines are bound to the schedule items, so
receiving flips them to `In Inventory: N` and the gate opens. Keep the GP footprint small by using the
Reconciliation step's own checkboxes (PO purpose only): `Deselect All`, then tick just the one product
you want, and at the PO step check a single manufacturer card. Fill **Order As** on that step - an
import-created draft otherwise blocks the register dialog with per-line `Required` errors.

## Getting Started (Every Session)

1. **Sign in**: Use `evaluate_script` to fetch a sign-in token and navigate with it. Railway production (default):
   ```js
   (async () => {
     const resp = await fetch('https://backend-production-7866.up.railway.app/testing/clerk-sign-in');
     const { token } = await resp.json();
     window.location.href = 'https://frontend-production-34fc.up.railway.app/?__clerk_ticket=' + token + '&cb=' + Date.now();
     return 'Navigating with sign-in token...';
   })()
   ```
   For a PR environment, swap in the URLs from the Railway bot's PR comment. For the local fallback, use `http://localhost:8000` / `http://localhost:5173`.
   - Clerk auto-authenticates — no email, password, or verification code needed.
   - You land on `/app` (Module Selector) fully signed in.
2. **Reset data** (if needed): Click the "DevAction: drop and rebuild schema" button in the app bar.
   - A MUI confirm dialog appears first — click "Drop & Rebuild" to confirm.
   - Then a `window.alert()` fires with "schema dropped and rebuilt" — use `handle_dialog` with `action: "accept"` to dismiss it.
   - Only then can you `take_snapshot` again (alerts block all MCP interaction).
3. **Post-login**: You land on `/app` — the Module Selector with 6 module cards.

## Chrome DevTools MCP Patterns

### General Rules
- Always `take_snapshot` after any navigation or click before acting on the page.
- Prefer `fill_form` (batch) over individual `fill` calls — individual fills can bleed values into adjacent fields.
- Use `take_screenshot` when you need to verify visual rendering (layout, colors, spacing).

### MUI Select Dropdowns
- MUI `<Select>` renders its dropdown in a **portal** (`<div role="presentation">`), not inside the Select element.
- After clicking a Select, call `take_snapshot` again to see the portal-mounted `<MenuItem>` elements.
- Click the desired `<MenuItem>` to select it.

### MUI Dialogs
- MUI `<Dialog>` also renders in a portal overlay.
- After triggering a dialog, `take_snapshot` to see dialog content.
- Confirm/cancel buttons may use `data-testid="confirm-dialog-confirm"` / `data-testid="confirm-dialog-cancel"`.

### MUI DataGrid
- DataGrid virtualizes rows — only visible rows appear in the DOM.
- Off-screen rows won't appear in snapshots; use `evaluate_script` to query grid data as fallback.
- Column headers are in `role="columnheader"` elements.
- Click a row's `gridcell` to trigger row click handlers (e.g., open detail modal).

### window.alert()
- Reset data and some actions trigger `window.alert()`.
- **These block all MCP interaction** — `take_snapshot` will hang until the alert is dismissed.
- Use `handle_dialog` with `action: "accept"` to dismiss.

---

## App Navigation Map

```
/                          -> Clerk Sign-In
/app                       -> Module Selector (6 module cards)
/app/import                -> Hardware Schedule Import wizard
/app/po                    -> Purchase Orders (project landing -> PO list)
/app/warehouse             -> Warehouse landing (stat cards + Go-to cards for sub-routes)
/app/warehouse/inventory   -> Inventory (hardware/opening items by project)
/app/warehouse/locations   -> Locations (master-detail bin browser)
/app/warehouse/receiving   -> Receiving wizard
/app/warehouse/put-away    -> Put Away (unlocated items queue)
/app/warehouse/pull-requests -> Pull Requests
/app/warehouse/stock-pool  -> Stock Pool (non-project stock items)
/app/warehouse/deficient-items -> Deficient Items Review
/app/warehouse/shipments   -> Shipments (global packing slip list + return dialog)
/app/shop-assembly         -> Shop Assembly landing (stat card + Go-to cards)
/app/shop-assembly/requests  -> Accept / reject / reopen shop-assembly requests
/app/shop-assembly/assemble  -> Assemble List (all openings on approved pulls)
/app/shop-assembly/assign    -> Assignment Board (manager)
/app/shop-assembly/my-work   -> My Work (+ Replacement Installs)
/app/shop-assembly/pipeline  -> Pipeline (read-only; where every request and leaf has got to)
/app/shipping              -> Shipping Out (ship-ready items, packing slips)
/app/admin                 -> Admin (reports, vendors, projects, users, cleanup)
```

---

## The shop-assembly lifecycle, end to end

The module guides below are organised by *screen*, which is the wrong shape for a first read: one
door leaf's journey crosses four of them. This is that journey once, with the screen that owns each
step. Everything in it is exercisable against Railway.

| # | What happens | Where you do it | What changes underneath |
| --- | --- | --- | --- |
| 1 | **Request** a leaf for shop assembly | Import -> Start a Task | A PENDING `ShopAssemblyRequest`, and the hardware is **reserved** on the spot (#342). Creating over-subscribed is refused whole, naming every short combo |
| 2 | **Accept** it | Shop Assembly -> Requests | A PENDING warehouse pull. A pure human gate - nothing is re-checked, nothing is spent. Rejecting instead is what releases the claim |
| 3a | **Start the pick** | Warehouse -> Pull Requests -> Start pick | The pull is claimed and opened. **Nothing moves**, and there is no sufficiency gate - a pull with an empty shelf still opens (#367) |
| 3b | **Confirm the pick** | The pick page, `/pull-requests/:id/pick` | The picker dictates a quantity per location; confirming deducts *those rows* and consumes the claim, atomically. This is the only moment inventory moves |
| 4 | **Stage** each opening's cart | Warehouse -> Pull Requests -> Staging panel | One `pull_status` flips to PULLED per opening (#343). That leaf is assignable *immediately*, while the rest of the pull is still being picked. Nothing moves in inventory |
| 5 | **Claim** the leaf | Shop Assembly -> Assemble List / Assignment Board | An assignment. A manager may take one off somebody; a self-claim may not |
| 6 | **Build** it, unit by unit | Shop Assembly -> My Work -> the modal | `installed_quantity` per line, saved as you go (#340). A defect flagged here goes back to inventory *now* and mints a `PR-REPL-*` pull immediately |
| 7 | **Finish** it | Same modal -> Mark Complete | An `OpeningItem` per leaf, carrying what was actually installed. Refused while any unit is unaccounted for, or if nothing at all was installed |
| 8 | **Replacement arrives** | Warehouse -> Pull Requests -> pick+complete the `PR-REPL-*` pull | The leaf gets its expectation back (#341). Still on the bench: it becomes Remaining again. Already finished: a Replacement Install card on My Work. Already shipped: a warning, and reallocation's problem |
| 9 | **Ship** it | Shipping Out | `SHIP_READY`, then a packing slip. A leaf still owed hardware is flagged and takes an explicit "Ship it short" |
| - | **Undo the pull** at any point before assembly starts | Warehouse -> Pull Requests -> Cancel Pull | Stock restocked, openings released, request back to Pending (#343). Refused, naming blockers, once any opening is IN_PROGRESS or COMPLETED |
| - | **See all of it at once** | Shop Assembly -> Pipeline | Read-only (#344). Answers "where is opening A01 leaf 2?" without opening the other four screens |

Two things a fresh reader gets wrong every time:

- **"Pulled" is per opening, not per pull.** Since #343 a leaf can be workable while its own sibling
  on the same pull is still on the shelf. A row with no buttons on the Assemble List is not broken;
  its cart is not built yet.
- **Reserved is not deducted.** Between steps 1 and 3b the hardware is claimed but still on the shelf,
  so the Warehouse inventory number and the Start-a-Task availability number legitimately disagree.
- **Started is not picked either (#367).** A pull sits IN_PROGRESS from the moment somebody presses
  Start pick, which is *before* any stock has moved. `Status` alone can no longer tell you whether
  the hardware has left - the queue's **Phase** column and `pickedAt` are what answer that.

---

## Module Guides

### Purchase Orders Module

**Entry**: `/app/po` -> Project landing page (select a project or "All Projects")

**PO List Page**:
- Header: back to projects button, title, **"Create PO" button** (opens manual PO creation dialog)
- **Stat cards** (display-only since PR #142): Total, Draft, Ordered, Vendor Confirmed, Partially Received, Closed, Cancelled. No longer clickable — they're a dashboard, not a filter.
- The Tabs row that used to sit below the cards was removed in PR #142. Status filtering now lives in the column filter row instead.
- **Expand all / Collapse all** buttons above the table — open or close every row currently visible under the active filters/sort
- Collapsible MUI Table: leftmost chevron column + PO/Request #, Status, Vendor, Order Date, Items
- **Sortable column headers** (PR #142): every header is a `TableSortLabel` button — click to sort asc, click again to flip to desc. Nulls (Drafts without orderedAt or vendor) always sort last regardless of direction.
- **Filter row** below headers (PR #142): PO# text search · Status multi-select chip dropdown · Vendor text search · Order Date from/to date inputs · Items numeric ≥ input. All filtering is client-side; the GraphQL query no longer takes a `status` variable.
- Chevron toggles an inline line-item mini-table (Product Code, Order As, Hardware Category, Ordered Qty, optional Received Qty, Unit Cost, Line Total)
- Clicking a data cell (not the chevron) opens the PO detail modal — same modal as before
- **Expand all** targets only the currently-visible (filtered + sorted) rows — not the raw fetch.
- The Status multi-select uses underlying enum values (DRAFT, PARTIALLY_RECEIVED, etc.) but displays formatted labels. When driving via JS, the option's a11y `value` attribute reflects the display label, but the actual MUI state holds the enum value — so test by observing filtered rows, not by reading the option's a11y value.

**Create PO Dialog** (manual PO creation, issue #256 - draft-first, NO relay needed):
- Title "Create PO Request (Draft)"; the Create PO button works with the relay offline
- Project selector (optional, all projects — buyer assignments only gate the register step)
- Vendor (Nexus vendor strict-select, optional) + Preferred delivery date
- Shipping costs / Tariffs (optional), Notes
- Line items grid: Hardware Category, Product Code, Qty, Unit Cost, Order As (REQUIRED per line; no Classification column - the PM sets site/shop at import)
- "Add Item" button to add rows, delete button per row (minimum 1 item)
- Submit ("Create Draft") creates a DRAFT PO with auto-generated request number (PO-REQ-XXX); no GP push. Registering into GP is the separate "Register in GP" action on the draft (relay + buyer identity required there)

**PO Detail Modal**:
- Shows: status chip, PO number, vendor info, quote #, dates, "No Project" label if project-less
- Line items grid: product code, hardware category, Order As, classification, ordered/received qty, unit cost, line total
- "Openings on this PO" section (#302), between Line Items and Documents - one row per (opening, leaf)
  the PO's hardware was bought for: opening number, a `Leaf N` chip, the hardware ordered against it
  (`2x E90600IC 626`), and a `building / floor / location` caption on the right. See below for which
  POs have one at all.
- Documents section with upload capability
- Receiving history
- Actions: Edit (header fields + line item Order As/costs), Mark as Ordered, Cancel PO

**Only a wizard-created PO has an "Openings on this PO" section**, and its absence is not a bug. The
link is `HardwareItem.po_line_item_id`, which only the Import wizard's Create-Purchase-Orders path
stamps; a PO built in the Create PO dialog, a stock PO, or one seeded straight into GP has no hardware
schedule behind it, so `poOpenings` returns `[]` and the whole section (its rule included) renders
nothing rather than an empty heading. Check `{ poOpenings(poId: "...") { openingNumber leaf } }` before
concluding the resolver is broken.

To produce one cheaply - the whole run is a couple of minutes and touches nothing else:

1. Start a Task -> project card -> **Use last uploaded schedule** -> Purpose **Create Purchase Orders**.
2. Select Openings: tick 2 openings via `document.querySelector('.MuiDataGrid-row[data-id="0501-EX"] input[type=checkbox]').click()`. Prefer openings whose Hand column shows a pair (`RHRA/LHR`) so the section has more than one leaf to show.
3. Reconciliation: **Deselect All**, then tick exactly one product row (`data-id` is `"<category>|<productCode>"`). That is what keeps the PO to one line and one manufacturer group.
4. Classification: click By UCSH + Shop on each row (both counters must fill).
5. Purchase Orders: tick the single manufacturer card's checkbox. Vendor is optional here - leave it blank, the draft still creates.
6. Finalize -> Finish Import Session -> Finalize -> **View Purchase Orders**, then the `Open <PO-REQ-NNN> details` button.

The per-leaf quantities in the section sum to the line item's Ordered Qty - that is the cheapest
correctness check on the join (e.g. `1x` on 0442-EX leaf 1 plus `2x`/`1x` on 0501-EX leaves 1 and 2
against an ordered qty of 4).

**PO Lifecycle**:
```
DRAFT -> ORDERED -> VENDOR_CONFIRMED -> PARTIALLY_RECEIVED -> CLOSED
                                    \-> PARTIALLY_RECEIVED -> CLOSED
  \-> CANCELLED (from DRAFT, ORDERED, or VENDOR_CONFIRMED)
```
- **Mark as Ordered** requires: PO number + vendor name
- **VENDOR_CONFIRMED** auto-triggers when ORDERED PO has both vendor quote number and vendor acknowledgement document; auto-reverts if either is removed
- **Receiving** a PO without a project will show error: "PO must be associated with a project before receiving"

**A cancelled PO disappears from the list entirely, and the CANCELLED stat card is always 0.**
`cancel_po` (`po_repository.py`) sets `status = CANCELLED` *and* `deleted_at` in the same write, while
`get_purchase_orders` filters `deleted_at IS NULL`. So the cancelled PO is gone from the grid, gone
from the TOTAL, and the CANCELLED card it should be counted in can never be non-zero. Observed live
2026-07-29 with a cancelled PO definitely present in the database.

Two consequences when testing:

- **A PO count that drops between two measurements is a cancel, not data loss.** This costs real time
  if you meet it cold - the PO simply vanishes with nothing in the audit log to say so (PO cancels are
  not audit-logged). `deleted_at` has exactly one writer in the whole backend, `cancel_po`, reachable
  only through the user-triggered `cancelPo` mutation, so a vanished PO always means somebody
  cancelled one.
- **Record PO ids, not just counts**, when you need a before/after. Aggregating by status tells you
  something changed but not which row, and you cannot query a soft-deleted PO back through GraphQL to
  find out afterwards.

**Generate PO Document** (issue #230): button on the PO detail modal action bar, shown for any non-cancelled PO. Opens a dialog that builds the finished supplier PO as a client-side PDF (`@react-pdf/renderer`), replacing the old hand-edit-GP's-doc workflow. No relay involved.
- Dialog fields pre-fill from the PO, its saved `PODocumentData`, and `poDocumentSettings`: vendor mailing address, buyer (from `buyerId`), currency (CAD `$` / USD `$US`), ship-to (warehouse dropdown | "Use project site" button | custom text - the resolved block is stored verbatim), shipping method, proposal #, required-by (defaults to `expectedDeliveryDate`), freight/misc/tax + tax label, and three conditional toggles (wood-door FSC, USA tariff, international customs).
- **Generate & preview** opens the PDF in a new tab (`window.open` blob). **Save to PO documents** persists `PODocumentData` + uploads the PDF as a `GENERATED_PO` document (appears in the Documents list, label "Generated PO", downloadable via presigned URL). Both first call `savePoDocumentData`, so re-opening the dialog pre-fills.
- Doc math: each line ext = ordered x unitCost; Subtotal = sum of ext; Order Total = Subtotal + Freight + Miscellaneous + Tax. The item column shows `hardwareCategory` (main line) + `orderAs` (Reference line). Boilerplate (tax numbers, mandatory bullets, signature, footer) always prints; the FSC / USA-tariff / customs blocks print only when their toggle is on.
- Company-wide boilerplate lives at the PO module's Document Settings page (`/app/po/document-settings`, "Document Settings" button in the PO list header - it moved out of Admin); the per-PO gaps are captured in this dialog.

### Import Module

**Entry**: `/app/import` -> Opens the Import Hardware Schedule wizard (full-screen dialog)

**Wizard Steps**:
1. Upload File — drag/drop or browse for XML file from TITAN
2. Purpose — choose: Create Purchase Orders, Shop Assembly Request, or Shipping Out
3. Select Openings/Hardware — pick which openings and hardware items to include
4. Reconciliation — shows what's already been imported (for re-imports)
5. (Conditional) Classification, Purchase Orders, Shop Assembly, or Shipping PRs step
6. Finalize — review and submit

**Result**: Creates a project (or updates existing), openings, hardware items, and the selected output (POs, SAR, shipping PRs).

**You almost never need to upload the XML.** Step 1 offers two cards: "Upload new TITAN XML" and
**"Use last uploaded hardware schedule"**, the second captioned with what is already persisted
("1998 openings, 29126 hardware items"). It rebuilds the wizard's working set from
`projectHardwareSchedule` - the openings and hardware items already in the DB - so every later step
behaves identically without a multi-megabyte parse. Take it unless the thing under test *is* the
parser. "Choose Different Source" on the loaded panel gets you back to the two cards.

**Step count depends on the purpose**, and the stepper is the quickest way to tell which flow you are in:

| Purpose | Steps |
| --- | --- |
| Create Purchase Orders | Upload File -> Purpose -> Select Openings -> Reconciliation -> Classification -> Purchase Orders -> Finalize (7) |
| Pull Request for Shop Assembly | Upload File -> Purpose -> Select Openings -> Reconciliation -> Classification -> Shop Assembly -> Finalize (7) |
| Pull Request for Shipping Out | Upload File -> Purpose -> Select Openings -> Reconciliation -> Shipping PRs -> Finalize (6) |

**Reconciliation is a hard gate on the assembly flow, and it fires before the Shop Assembly step.**
With nothing in inventory it shows a red alert - `No items have In Inventory status. There is nothing
available to assemble.` - and **Next is disabled**, so the wizard stops at step 4. The per-combo detail
is in the table underneath (Hardware Category / Product Code / Qty Needed / Qty Available / Lifecycle
Breakdown, each short line chipped `Gap Remaining: N`), not in the alert text. Worth knowing because
the slice-4 shortfall alert everyone quotes (`<CATEGORY> <CODE>: need N, M available (R reserved by
other requests) - short S`) lives on the **Shop Assembly** step, which you cannot reach at all when
availability is zero across the board. To exercise *that* message you need stock on the shelf and a
competing reservation; a bare empty warehouse only ever gets you the Reconciliation gate.

The same step on the **shipping** flow is advisory, not a gate: `Items that are In Inventory or Built
onto Opening can be included in shipping pull requests. Items with zero availability are excluded. You
may proceed with partial quantities if needed.` Next stays enabled. The gate for shipping is one step
later - with nothing shippable, the Shipping PRs step shows `Nothing on the selected openings is in a
shippable state. Assembled leaves already on another shipping request are not listed.`, an added
"Shipping PR #1" card lists `Select items (0 selected):` with no rows, and Next is disabled.

**Creating a request RESERVES inventory (#342).** This is the single biggest behavioural change to
the wizard, and it changes what "it worked" looks like at every downstream step.

- The Shop Assembly and Shipping PRs steps both read `projectInventoryAvailability`, where
  `availableQuantity = onHandQuantity - deficientQuantity - reservedQuantity`. **Next is disabled**
  while the selection asks for more than that, and a red alert lists every short combo as
  `<CATEGORY> <CODE>: need N, M available (R reserved by other requests) - short S`.
- The Shop Assembly step now also renders a "Hardware this request would reserve" table (Needed /
  Available / Reserved elsewhere per product), and refuses to proceed at all when no item was
  classified as Shop Hardware.
- The Shipping PRs step shows "<n> available" under each **loose** line only. Assembled door leaves
  never show one and are never gated - their hardware left fungible inventory at assembly.
- Next is also disabled while the availability lookup is in flight or has failed. An unknown count is
  not treated as "fine", so a mocked/blocked GraphQL call reads as a blocked wizard, not a bug.
- Driving `finalizeImportSession` directly past the UI gate gets an `INSUFFICIENT_INVENTORY` error
  naming every short combo, and **nothing at all is created** - no request, no reservations, no
  openings. Useful for exercising the gate without walking the wizard.
- To make a shortfall on demand: create one request that claims most of a product, then start a
  second Start a Task for the same product. The second one is short *even though the shelf count is
  unchanged* - that is the reservation working, and `reserved by other requests` in the message is
  how to tell it from genuinely absent stock.
- Other creation-time refusals (all `VALIDATION_ERROR`): a request with zero openings; an opening
  with zero items; a shipping request with zero lines; a leaf already inside a live shop-assembly
  request; a leaf already on a live shipping-out request; a leaf claimed by the *other* request type.
- **Re-upload with `replaceSchedule: true`** is never blocked. Live PENDING requests are rewritten to
  the openings that survived (their reservations rebuilt from what is left), a request that loses
  everything is auto-REJECTED by "Hardware Schedule Import", accepted requests are left alone, and
  every live request gets an `integrityNote` that shows as an amber alert on the accept screen.

### Warehouse Module

**Two different "available" numbers, and they are supposed to differ (#342).** The Inventory view's
availability is `on-hand - deficient`: what is physically unspoken-for in the building. The Start a
Task wizard's is `on-hand - deficient - reservations`: what may still be *claimed*. A product can
read 10 available in the warehouse and 0 available in the wizard; that is not a bug, it means live
requests are holding it.

**Confirming a pick consumes its source request's reservation (#367 moved this off approve).** A pull
whose request reserved exactly what it needs still picks fine - the check excludes the request's own
claim (self-coverage). A `PR-REPL-*` replacement pull *does* hold a claim now (minted when the defect
was flagged, topped up as stock arrives), usually smaller than what it is owed, so being partly
covered is its normal resting state and a short pick on one is not an integrity error.


**Entry**: `/app/warehouse` -> Warehouse landing page with stat cards and "Go to" card buttons for: Inventory, Locations, Deliveries, Receiving, Put Away, Pull Requests, Stock Pool, Deficient Items, Shipments. (No longer "three tabs" - this has evolved to a full landing page.) Since PR #395 the Deficient Items card shows `deficientCount` (deficient units across project inventory + stock pool - the same rows the review page lists, amber edge when non-zero) and the Deliveries card carries the `backOrderedCount` figure (undelivered units on active POs, no attention edge). The two numbers matching their destination pages is the thing to assert.

**Deliveries "All Projects"** works since PR #397 (it was a dead click - `onSelect(null)` collided with "nothing chosen"). The all-projects view queries both tabs with a null projectId.

**Inventory tab default**: Navigating directly to `/app/warehouse/inventory` defaults to "All Projects" view — shows the "Projects" back button, "All Projects" heading, and Hardware Items / Opening Items sub-tabs immediately. The ProjectLandingPage is NOT shown on initial load. Clicking "Projects" brings up the ProjectLandingPage where you can filter to a specific project or click "All Projects" to return to the all-projects view.

**Receiving** (wizard):
1. Select POs to receive (shows ORDERED/VENDOR_CONFIRMED/PARTIALLY_RECEIVED POs)
2. Enter quantities received per line item — line items grid shows: Product Code, Ordered As, Hardware Category, Ordered Qty, Already Received, Pending, Receive Now
3. Assign storage locations (aisle/bay/bin)
- Receiving auto-transitions PO status (ORDERED -> PARTIALLY_RECEIVED -> CLOSED)

**Inventory**: Browse by hardware category and product code, see storage locations.

**Pull Requests**: Queue of pull requests from shop assembly or shipping modules. Two tabs (Shop
Assembly / Shipping Out); clicking a row opens the detail modal. Since #367 the old Staging column is
a **Phase** column - a tag over a line of detail, because `Status` stopped being enough once picking
became its own phase:

| Phase | Detail line | Means |
| --- | --- | --- |
| `Pending` | Not started | Nobody has pressed Start pick |
| `Picking` | Nothing off the shelf yet | IN_PROGRESS, `pickedAt` null, no pick lines |
| `Short` | Part-picked - remainder outstanding | A short confirm landed; some stock is gone, the rest is owed |
| `Staging` | `4 of 8 staged` | Picked, now building carts |
| `Picked` | Ready to mark pulled | Picked, and staging does not apply (shipping-out / `PR-REPL-*`) |
| `Completed` / `Cancelled` | - | Terminal |

An IN_PROGRESS row reading `PICKED` in Phase is the normal, correct state for a shipping-out or
replacement pull - Status and Phase disagreeing is the point of the column.

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
3. Each section lists **every leaf in full** (`OWED TO 1 LEAF`, `015.2 · L1 × 1`) and a ledger of
   every candidate location: `LOCATION | RECEIVED | AVAILABLE | PULLED`. There is deliberately **no
   suggested column and no autofill** - assert their absence, it is the whole point of the slice.
4. Number inputs carry `aria-label="Pulled from <bin>"` and a `max` of that row's available, which is
   what makes them addressable from the MCP tools.

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

**Per-leaf staging (#343, relaid out as sections in #367)** is the shop-assembly pull's execution
view, inside the detail modal between the header and the Items table, headed
`Stage carts (N of M leaves)`. **It only appears once the pick is confirmed** - before that there is
nothing on a cart to declare.

- One bordered **section per door leaf**, not a table row: header is the mono leaf identity
  (`015.2 · L1`) plus building/floor, with the hardware beneath as ledger rows
  (category | mono product code | right-aligned qty). The old single-cell bulleted list is gone.
- The section carries a 3px left edge: amber when selected, green once staged, hairline otherwise.
- Confirming is **two-step**: tick the checkboxes (`Stage <opening> · LN` - note the new identity
  format), press `Confirm N staged`, then confirm the dialog. A tick alone writes nothing.
  `Select all remaining` ticks every un-staged section.
- Each confirmed leaf is **immediately** assignable/workable in Shop Assembly, while the rest of
  the pull is still un-staged. This is the thing to exercise: stage one leaf of a pair, then go to
  `/app/shop-assembly/assemble` and claim it while its sibling still shows as waiting.
- An already-staged section has a disabled checkbox and a green "Staged" tag with who staged it and when.
- Staging the **last** leaf completes the pull (toast: "All carts staged - <PR> is complete.").
  The panel then renders read-only, so the record of who staged what survives.
- `Mark as Pulled` still exists and now means "stage everything remaining and finish"; its confirm
  dialog says so.
- Nothing moves in inventory at staging. Stock was deducted when the **pick was confirmed**, and
  `stage_pull_openings` refuses outright until it has been.

**Cancel Pull (#343)**: an outlined red button in the modal's action bar on any IN_PROGRESS pull, and
on a COMPLETED *shop-assembly* pull (there "completed" only means every cart is built). Absent on a
PENDING pull - reopen or reject the source request instead - and on a completed shipping-out pull.

- It opens its own modal (not the standard ConfirmDialog) with a warning alert, an optional Reason
  textarea, `Keep pull` and `Cancel pull and restock`.
- Success toast names the units returned and whether the claim was re-created. If the returned
  hardware could **not** be re-reserved you get a *warning* toast carrying the request's new
  `integrityNote` instead - that is a real state, not a failure.
- **Refusal keeps the dialog open** and renders the server's message in a red alert
  (`data-testid="cancel-blocked"`) listing every opening whose assembly has started. Cancelling is
  all-or-nothing; finish or unwind those leaves first.
- After a cancel: stock is back in project inventory, the pull's openings are NOT_PULLED and
  unassigned (they vanish from the Assemble List), and the source request is back in the
  Shop Assembly / Shipping accept queue as Pending. Re-accepting it mints a **new** pull with the
  **same request number** - so a search by number can legitimately return a cancelled row and a live
  one.

**Stock Pool** (`/app/warehouse/stock-pool`): Shows stock items not tied to a project. Has a "Warehouse" filter dropdown in the filter row with options "All warehouses", "Warden (WRD)", "VP (VP)". Grid has a "Warehouse" column (visible when data rows exist). Empty state shows "Nothing in the stock pool yet" message.

**Transfer dialog** (PR #159 / PR #160, issue #88): Accessible from two places:
- Stock Pool grid row: "Transfer (same or other warehouse)" icon button (swap-horizontal arrows) in the Actions column.
- Locations tab right-side panel: click a bin row to open the panel, then click "Item actions" on a Stock Pool or Hardware Items row → "Transfer" menu item.

Both entry points open a "Transfer <productCode>" MUI dialog with: an "X available to transfer." line, a "Destination warehouse" dropdown (defaults to the source item's warehouse), Aisle/Bay/Bin MUI Autocomplete fields (suggest existing bin values; are comboboxes with autocomplete="list", NOT plain text boxes), and a Quantity spinbutton defaulting to the available quantity (max=available). Transfer button stays disabled until all three location fields are filled. On success, the dialog closes, the grid refreshes automatically (source row qty drops, a new row appears at the destination bin if it didn't exist), and a success toast fires briefly. To open autocomplete suggestions: focus the input then dispatch a keydown ArrowDown event.

**Receiving warehouse selector** (PR #158): When receiving a PO, the Receive modal includes a "Receive into warehouse" dropdown near the top, defaulting to "Warden (WRD) · default". Only visible when a PO is in ORDERED/VENDOR_CONFIRMED/PARTIALLY_RECEIVED state and you open the receive flow.

**Put Away** (`/app/warehouse/put-away`): Lists unlocated project inventory items grouped by hardware category. Each row shows Product Code, Qty, PO#, Received date, and Aisle/Bay/Bin comboboxes + an "Assign" button (disabled until all three location fields filled). Has a "Filter by Project" dropdown. Items returned to project inventory via the Return dialog appear here immediately.

**Shipments page** (`/app/warehouse/shipments`, issue #89):
- Global list of all shipped packing slips (across projects). Reachable from: direct URL, Warehouse landing "Shipments" card, sidebar nav under Warehouse.
- Grid columns: Packing slip #, Project, Shipped by, Shipped date, Loose units, Actions column with "Return" button.
- Filter controls: "Search packing slip #" text input (filters by packing slip number), "Project" dropdown.
- "Loose units" column shows total loose-line qty originally shipped (does NOT decrease as returns are recorded).
- "Return" button opens the Return dialog for that packing slip.

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

**Entry**: `/app/shop-assembly` -> landing page: one "Active Pull Requests" stat card plus five "Go to"
cards - Requests, Assemble List, Assignments, My Work, Pipeline.

- Manager creates/approves Shop Assembly Requests (SARs)
- Approved SARs generate pull requests for warehouse
- Users get assigned openings, pull hardware, assemble, mark complete

**The Assemble List fills incrementally since #343.** It now lists the openings of any *approved*
pull, not only completed ones, and groups them by the opening's own pull status: Pulled ("Ready"),
Partial ("Waiting"), Not Pulled ("Pending"). Only a **Pulled** row offers "Assign to me" / "Start
assembly" - an un-staged row is visible but inert, which is deliberate (the floor can see what is
coming). If a leaf you expect is missing entirely, its pull is still PENDING in the warehouse or was
cancelled; if it is present but has no buttons, the warehouse has not staged that opening yet.

**Accept is a pure human gate since #342.** There is no inventory check on Accept any more and no
shortfall can surface there - the hardware was reserved when the request was created. Accepting
neither spends nor releases that claim; approving the warehouse pull spends it; **rejecting** is the
only thing that releases it.

- **Reopen (#325) deliberately does NOT release.** A reopened request goes back to Pending still
  holding its hardware, so a second request for the same product stays short until you *reject* the
  reopened one. The reopen confirm dialog says so. If a colleague reports "I released it but the
  stock is still claimed", they reopened instead of rejecting.
- An amber alert at the top of an expanded request is its `integrityNote`: either a schedule
  re-upload landed under it, or the reservations backfill could not cover it (that second one only
  appears on data that predates #342).

**Assembly modal is a progress editor, not a one-shot checklist (#340).** Clicking a row in My Work
(or "Start assembly" / "Continue assembly" on the Assemble List) opens it. Per line it shows Pulled /
Installed / Deficient / Remaining, with the Installed cell an editable number spinbutton labelled
`Installed units: <productCode>`.

- **Save Progress** persists the counts and leaves the modal open; the leaf stays in My Work and its
  status chip flips Pending -> In Progress. Reopening rehydrates from the saved counts, so this is the
  thing to exercise when checking resumability.
- **Mark Complete** stays disabled until every unit on every line is either installed or flagged
  deficient (the modal spells out how many are unaccounted for underneath the location fields), and
  also stays disabled if everything was flagged deficient. It saves any outstanding draft first, then
  completes, so pressing it fires *two* mutations.
- **Flag deficient** opens a nested dialog (quantity + reason, both required) with a warning alert.
  Confirming it is irreversible from this screen: the units go back to inventory flagged deficient and
  a PR-REPL replacement pull is minted immediately, before the leaf is finished. Watch for the
  spinbutton-append gotcha on the quantity field - clear it before typing. The dialog closes on
  failure as well as on success, deliberately: a flag that errored may still have committed, so it
  makes you re-open and re-read rather than offering you the same submit twice.
- **Replacement pull numbers.** The first replacement pull for a source pull is
  `PR-REPL-<source pull number>`. Flag again while that pull is still **Pending** and the units are
  added to its existing line - same pull, bigger quantity. Flag again after it has been approved or
  completed and you get a **second** pull, `PR-REPL-<source pull number>-2` (then `-3`, ...). Do not
  read the missing `-1` as a bug; do expect to search for the suffixed number in the pull queue.
- Both number inputs are MUI spinbuttons, so the usual "fill appends to the existing value" trap
  applies; the deficiency quantity is capped at the line's remaining units and the flag button stays
  disabled if you exceed it.
- Assignment: a manager may reassign an In Progress leaf to someone else (progress travels with it);
  a plain user self-claiming cannot take one that is already held - that returns a CONFLICT toast.
  Unassigning an In Progress leaf is allowed and puts it back in the pool with its counts intact.

**Replacement Installs section on My Work (#341).** Below the My Work grid, and only rendered when
there is something in it, so an empty shop shows nothing at all. It appears when a PR-REPL
replacement pull is *completed* in the warehouse for a leaf the assembler already finished.

- To produce one end to end: flag a unit deficient in the assembly modal, finish the leaf, then go to
  Warehouse -> Pull Requests, approve the `PR-REPL-<original PR number>` request and complete it. The
  card shows up on the assembler's My Work on the next fetch.
- If the leaf is *not* finished yet, completing the same replacement pull produces **no card** - the
  unit just goes back to being Remaining in the assembly modal and Mark Complete is blocked again.
  That is the intended behaviour, not a missing feature.
- "Mark Installed" is confirm-gated and installs the whole arrived quantity at once. Afterwards the
  leaf's `installedHardware` carries the extra units; the card disappears.
- A leaf that has **shipped** shows a "Leaf already shipped" chip and no button; one that is
  **SHIP_READY** (staged at the dock by a completed shipping-out pull) shows "Leaf staged for
  shipment" and no button either. The second case is recoverable - unwind the shipping-out request
  and the button comes back - which the caption says. The backend refuses both.
- A card whose leaf already shipped shows a "Leaf already shipped" chip and a warning alert instead
  of the button - it cannot be installed, only reallocated. A `REPLACEMENT_AFTER_SHIPMENT`
  notification was also raised for the SHIPPING role when the pull completed.

**Pipeline page (#344)**, `/app/shop-assembly/pipeline`, reachable from the landing "Pipeline" card.
It is **read-only on purpose** - every state it shows already has a screen that owns changing it, and
a second place to act on them would be a second place for the rules to live.

- The grid is one row per shop-assembly request across **all** projects by default, with a
  Pending / Approved / Rejected / All toggle. Columns: Request, Project, Stage, Staged (`2 of 4`),
  Progress (`6/16 units`), Assembled, Shipped, Flags.
- **Stage is the request's least-advanced opening**, not its best news. A request with one finished
  leaf and one that has not been staged reads "Awaiting pull". That is the intended reading: the
  question is what is holding it up. The ladder is Requested -> Accepted -> Awaiting pull -> Staged ->
  Assigned -> In progress -> Assembled -> Shipped, plus Rejected and "Pull cancelled" off the end.
- The Staged / Assembled / Shipped columns are **blank** on a request with no openings, the same rule
  the pull queue's staging chip follows - "0 of 0" would read as "nothing done".
- Flags appear only when something is wrong: "Needs review" (the `integrityNote`), "N awaiting
  replacement", "N arrived after shipping". A clean row shows no chips at all.
- Clicking a row opens the detail modal: the alerts first (integrity note, cancellation history,
  replacement-after-shipping), then a chip row and a progress rail, then **one table row per door
  leaf** - stage, when and by whom it was staged, who holds it, units, the assembled leaf's warehouse
  location, and what it is still owed.
- Good end-to-end exercise: stage one leaf of a pair, and watch the pair's two rows in the detail sit
  at "Staged" and "Awaiting pull" while the request itself reads "Awaiting pull".
- A **cancelled** pull is the case worth checking deliberately. Cancelling detaches the openings and
  puts the request back to Pending, so without this view the request looks as though it was never
  accepted; here it reads "Pull cancelled" with an alert naming who cancelled it and why.

**Notifications raised by this module (#344)**, all visible in the bell (which shows every audience,
so you will see all of them regardless of your role):

| Type | Fires when | Watch out for |
| --- | --- | --- |
| `ASSEMBLY_WORK_AVAILABLE` | You confirm a staging batch, or complete a pull that still had un-staged openings | **One per confirmation, not per opening.** Staging three carts in one action gives one notification naming them. Re-staging an already-staged opening gives none |
| `REPLACEMENT_ARRIVED` | A `PR-REPL-*` pull completes for a leaf that has **not** shipped | Addressed to the assembler's Clerk user id, so `recipientRole` looks like `user_2ab...`. None is raised if nobody is holding the leaf |
| `REPLACEMENT_AFTER_SHIPMENT` | Same, but the leaf has already shipped | Exactly one of these two fires, never both |
| `PULL_UNBLOCKED` | A receive lands stock that makes a blocked `PR-REPL-*` pull fully coverable | Deduped three ways: only pulls wanting a combo you actually received; only if the pull is coverable *after* the receive; and only one **unread** one per pull. Mark it read and receive again to get a second. A receive is the only path that raises it - a cancel-restock can also make a pull coverable and stays silent |

### Shipping Module

**Entry**: `/app/shipping` -> Project landing page -> ship-ready items browser

- Shows opening items and loose items ready to ship
- Create packing slips, confirm shipments

**Incomplete-leaf guard in the Start-a-Task shipping wizard (#341).** On the Shipping PRs step, an
assembled leaf that is still owed hardware carries an amber "Incomplete - awaiting replacement" chip
and a "<n> unit(s) still awaiting replacement" caption.

- Ticking its checkbox does **not** select it - it opens a "Ship an incomplete leaf?" dialog first.
  "Ship it short" selects it and records the acknowledgment; "Leave it here" leaves the checkbox
  clear. Unticking an already-selected flagged leaf never asks.
- Without that confirmation the finalize is refused by the backend with a VALIDATION_ERROR naming
  every flagged leaf, so driving the mutation directly (without `acknowledgeIncompleteLeaves: true`)
  is the way to exercise the guard from GraphQL.
- The flag is `openingItems { awaitingReplacementQuantity }` - condemned-and-unreplaced plus
  arrived-but-not-fitted. It only drops to 0 once the replacement is actually installed on the leaf.

### Admin Module

**Entry**: `/app/admin` -> Admin landing: stat cards (Vendors, Users, Hardware Items, Openings) + "Go to" cards for each sub-route.

**Sub-routes**:
- Project Purchasing Progress (`/app/admin/project-purchasing-progress`)
- Opening Status (`/app/admin/opening-status`)
- Vendors (`/app/admin/vendors`) — vendor CRUD
- Warehouses (`/app/admin/warehouses`) — warehouse CRUD (PR #158, issue #88); see below
- Projects (`/app/admin/projects`) — edit project details + OSSA flag (see below)
- User Management (`/app/admin/users`) — assign Clerk roles
- Location Cleanup (`/app/admin/location-cleanup`)
- (PO Document Settings moved to the PO module: `/app/po/document-settings`; see below. Unknown `/app/admin/*` sub-routes silently render the Admin landing, not a 404.)

Inventory quantity corrections are NOT here — they live in the Warehouse module (Locations tab).

**Warehouses page** (`/app/admin/warehouses`, PR #158, issue #88):
- DataGrid columns: Name, Code, Location (city + province concatenated), Primary (chip "Primary" / blank), Status (chip "Active" / "Inactive"), trash icon.
- Primary warehouse (Warden/WRD) has NO trash icon — delete is blocked on primary.
- Non-primary warehouses have a trash icon that opens a confirm dialog: "Delete [name]? This is blocked if any inventory still references it."
- Create dialog: Name (required), Code (required), Address, City, Province, Postal Code, Primary checkbox, Active checkbox (checked by default). Save toast = "Warehouse created".
- Edit dialog: same fields pre-populated, Save toast = "Warehouse updated".
- Delete confirm toast = "Warehouse deleted".
- Seeds: Warden (WRD, Primary, Active) and VP (VP, Active) are seeded by default.

**Projects page** (`/app/admin/projects`, issue #67):
- Admin/Manager only. Non-admins get a permission Alert; the backend also enforces it (see Lessons Learned).
- DataGrid columns: Project #, Description, Client, Job Site, OSSA (chip "Yes" / "—"), Openings. Click a row to open the edit dialog.
- **Edit dialog**: OSSA toggle + editable text fields (description, client, job site name, address/city/state/zip, general contractor, GC contact name/phone/email, project manager, application). A read-only "From TITAN" section shows project number, submittal job no, submittal assignment count, estimator code, TITAN user ID — these are immutable.
- Save calls `updateProject`, refetches the grid, and shows a "Project updated" toast.

**PO Document Settings page** (`/app/po/document-settings`, issue #230 - lives in the PO module, reached via the "Document Settings" button on the PO list header):
- Admin/Manager only (non-admins get a permission Alert; the mutation is `require_admin`-gated). Single-record form, not a grid.
- Fields: company from-address, payment terms, confirm-with, tax numbers, mandatory bullets (one per line), wood-door FSC note, USA tariff note + effective-until date, customs broker block, shipping accounts (one per line), signature note, footer notes.
- Backed by `poDocumentSettings` (get-or-creates a single row seeded from the guideline doc on first read, so it never returns null) and `updatePoDocumentSettings`. Save toast = "PO document settings saved". These values print on every generated PO document.

---

## Lessons Learned

- `fill_form` is much more reliable than sequential `fill` calls for forms with many fields.
- After "DevAction: drop and rebuild schema", there are TWO dialogs: a MUI confirm dialog, then a `window.alert()`. Must handle both.
- Clerk sign-in tokens: Fetch from `GET /testing/clerk-sign-in` on the backend, then navigate to the frontend with `?__clerk_ticket=TOKEN`. Railway production is the default runtime (issue #182); PR environments and localhost use the same flow with their own URLs. Clerk auto-authenticates - no form fill, no verification code. Tokens are one-time use; fetch a fresh one each session.
- When viewing "All Projects", `projectId` is undefined/null in queries — this returns all POs across projects.
- To test the Warehouse Receiving wizard's "Enter Quantities" step, you need at least one PO in ORDERED (or higher) status. DRAFT POs do not appear in the receiving wizard's PO selection list.
- The line item field formerly called "Vendor Alias" is now called "Order As" in pre-order screens (Create PO dialog, PO detail modal) and "Ordered As" in post-order screens (Warehouse receiving wizard).
- On the Import wizard Select Openings/Hardware step with a large XML file (1998 openings), `take_snapshot` produces an output file that exceeds the tool token limit. Use `evaluate_script` with `document.body.innerText` or targeted DOM queries to check state and click buttons. Use `evaluate_script` to click "Select All" when the snapshot uid approach times out due to large DOM.
- Import wizard Classification step columns: Opening #, Product Code, Hardware Category, Manufacturer, List Price, Discount, Unit Cost, Qty, Classification, Site/Shop. Each row has four toggle buttons - "By UCSH" / "By Others" in Classification, and "Site" / "Shop" in Site/Shop. Also has "Add group level" button and a header checkbox to select all rows. There are **two** counters ("X of Y items classified" and "X of Y in-scope items site/shop classified") and Next stays disabled until both are satisfied, so ticking only By UCSH leaves the step blocked.
- Import wizard step order for "Create Purchase Orders" purpose: Upload File -> Purpose -> Select Openings/Hardware -> Reconciliation -> Classification -> Purchase Orders -> Finalize (7 steps total).
- For a first-time import (new project, no existing data), the Reconciliation step has no data to display — it just shows "New project — all items will be ordered fresh." The step is effectively a pass-through; do NOT use `wait_for` to wait for reconciliation data. Just click Next immediately.
- Classification step grouping: Clicking "Add group level" creates a Level 1 dropdown pre-set to "Hardware Category" with a remove (X) button. Shows accordion rows per group with item counts, "By UCSH All" and "By Others All" bulk buttons on the right, and a collapse/expand chevron. Each group shows a chip: "0/N classified" (grey, unclassified), "All By Others" (orange/amber), or "All By UCSH" (green). With 26548 items the snapshot is too large — use evaluate_script to find and click buttons. Classification counter turns green when all items are classified.
- Purchase Orders step (step 6 of 7): Shows N vendor(s) each as an expandable card with checkbox, Vendor Contact field, PO Total, and a line items grid showing Product Code, Hardware Category, Total Qty, Unit Cost, Total Cost, Order As columns. Vendors default unchecked. Only By UCSH items appear (By Others items are excluded). With the contracterp-74.xml file, 41 vendors appear.
- Purchase Orders step: The Next button is DISABLED until at least one vendor checkbox is checked. All vendors start unchecked by default. To check all 41 vendors programmatically: use evaluate_script to call `.click()` on each `.MuiCheckbox-root` span inside each `.MuiPaper-outlined.MuiPaper-rounded` card (skip index 0 which may be a header). This triggers React's event handlers properly (direct DOM checkbox manipulation does NOT update React state).
- "By Others" classification in the ALD group correctly EXCLUDES those items from vendor PO cards. Items that appear under vendor "Aluminum Door By Others" (vendor name, not classification) with ALD hardware category are separate — they are items from that vendor that were classified as "By UCSH". The vendor name and the hardware category name can both contain "ALD" but refer to different things.
- Finalize step (step 7 of 7): Shows "Review & Finalize" with Import Summary (project name, opening count, hardware item count, PO count). "Finish Import Session" button opens a "Finalize Import" MUI dialog with Cancel and Finalize buttons. After clicking Finalize, shows "Finalizing import session..." progress text, then a success overlay dialog with "Import session completed successfully!", project name, POs created count, and "View Purchase Orders" / "View Warehouse" / "Return to Home" buttons.
- PO list expanded mini-table shows the optional "Received Qty" column only when `po.receiveRecords.length > 0`. POs whose line items have `receivedQuantity > 0` but `receiveRecords` is empty (e.g. GP-generated POs with status PARTIALLY_RECEIVED but no ReceiveRecord rows) will NOT show Received Qty — this is intentional and mirrors `PODetailModal`'s behavior.
- The "All Projects" PO list query (`GET_PURCHASE_ORDERS` with no projectId) is the canonical example of the slow-resolver pattern described in CLAUDE.md rule #6. It eagerly loads every line item, receive record, and document for every PO across all projects. With ~19 POs in test the p90 hit 60s and p99 was ~4min (`http_response_time`). Backend CPU/memory are idle during this — it's a DB-bound issue. A project-scoped view (`projectId` set) returns much faster. If testing All Projects times out, retry with a specific project.
- Locations page redesign (PR #160, issue #88): The `/app/warehouse/locations` page uses a master-detail rail+panel layout. Unselected state: DataGrid shows 4 columns - Location, Warehouse (chip per row), Items, Total Qty. No separate Aisle/Bay/Bin columns. Selected state (row clicked): left DataGrid collapses to a single "Location" column rail (shows location name + warehouse code chip + qty in one compact cell per row), and a right-side panel fills the remaining width showing the bin's contents, a WRD/VP chip in the panel header, and recent activity. Close button in panel returns to unselected state.
- Locations page warehouse filter: A "Warehouse" combobox dropdown sits next to the Search locations input. Options: "All warehouses" (default), "Warden (WRD)", "VP (VP)". When a specific warehouse is selected, the "Warehouse" column disappears from the table (redundant), only that warehouse's bins show, and the count summary updates. In local testing, plain `click` on the combobox uid works fine — it opens the MUI Select portal and the options are visible in the next snapshot. (The "requires mousedown + mouseup via evaluate_script" note may have been a Railway-only issue.)
- Locations page horizontal scroll: body has `overflow-x: hidden` applied. No hard min-widths on the layout. `document.documentElement.scrollWidth === clientWidth` with panel open or closed.
- After a deploy on Railway, the previously-loaded SPA tab keeps the OLD `index.html` reference until full page reload (`navigate_page type=reload` is NOT enough). Bust by either closing the tab and `new_page` to the URL, or adding a query-param cache-buster like `?cb=1`. The HTML headers (`Cache-Control: no-cache, must-revalidate`) cover the *next* page load but not the currently-cached document.
- MUI `Autocomplete` with `freeSolo` (used by `LocationAutocomplete` and `OrderAsAutocomplete`) is flaky to drive via `fill` — the tool tries to find a matching dropdown option and errors with "Could not find option with text X" when the value is a brand-new free-form string. Worse, when fill fails on a follow-up Autocomplete it sometimes mutates the previous field. For tests that need to set a specific value, use `evaluate_script` to set the underlying input's `value` and dispatch a synthetic `input` event, or drive the mutation directly via `curl` to the `/graphql` endpoint (the location-string normalization can be verified that way without UI flake).
- Mutation success in the new LocationsTab triggers `refetchContents()` + parent `refetch()`, but Apollo Client's normalized cache can leave the just-mutated `InventoryLocation` entity visible in the panel until the cache settles. The DB is correct (verified by full page reload). If you need to assert post-mutation UI state, reload the page rather than trusting the immediate snapshot after `wait_for` on the success toast.
- The Location Cleanup admin screen lives at `/app/admin/location-cleanup`. It queries `locationDuplicates` which groups location triples by case-insensitive canonical form (uppercase + trim + collapse whitespace) and surfaces variants. Empty state ("No location duplicates found") is the happy path. The merge dialog calls `mergeLocations` which rewrites every matching row across inventory_locations + opening_items + stock_items and writes one MOVE audit per row.
- The admin Projects page (issue #67) is the first screen backed by real server-side auth. The frontend now sends the Clerk session token on every GraphQL request (Apollo auth link via `window.Clerk.session.getToken()`), and two resolvers are gated on the Admin/Manager role: `adminProjects` (query) and `updateProject` (mutation). Unauthenticated calls to them return a GraphQL error with `extensions.code = "UNAUTHENTICATED"`; signed-in non-admins get `FORBIDDEN`. Every other resolver is still ungated, so existing tests are unaffected.
- Issues #198 and #380: free-form project creation is gone, and so is manual adoption. `createProject`/`CreateProjectInput` and `adoptGpJob`/`AdoptGpJobInput` no longer exist. Projects now appear on their own: the `gp_job_sync` background service creates one for every job in GP's job master (JC00102), on a ~5 minute timer and immediately on every relay reconnect, setting `projectId` = the GP job number and `description` = the GP job name. That means **there is no longer any way to seed a project through GraphQL without a relay** - the old ungated `adoptGpJob` fetch trick is dead. To get projects in a test environment, connect and enrol the relay and let the sync run, or hit the admin `syncGpJobs` mutation (Admin -> Projects -> "Sync from GP", which returns `{total, adopted}`) once a relay is up.
- Issue #380: the Import landing page's button is now "Create GP Job" (`CreateGpJobDialog`), rendered for the Admin/Manager role only - a non-admin sees the landing page with no create button. It originates a job in GP via `createGpJob(input: CreateGpJobInput!)`, which is admin-gated and requires a connected relay. Every field except the job number and name is a live GP read (`gpCustomers`, `gpCustomerAddresses`, `gpTaxSchedules`, `gpDivisions`, `gpEmployees`), so the whole form stays disabled while the relay is down. The two address selects stay disabled until a customer is picked and re-fetch when it changes. Eight optional fields sit behind a "Show optional fields" toggle. GP validates the submit and its own message is shown in the dialog - in TUBC the fiscal calendar ends 2025-09-30, so today's date reliably produces "Job cannot be created within a closed period"; use a FY2025 `createdDate` for a success path. Issue #392: Estimator and WS Manager are selects over `gpEmployees` (the GP payroll master UPR00100), not free text - the proc rejects an id that is not in that master with "The estimator does not exist in the payroll master table" (error state 51117). TUBC has exactly two employees, IANB and JONATHANR. `createGpJob` returns `{created, project}`: `created` is false when GP already held the job number and the mutation adopted it instead of creating one, so resubmitting an existing number succeeds with "already existed in GP and is now a project" rather than erroring. New projects default `offSiteStorageAgreement` to false and the GC/address fields to null, handy for testing the Projects edit flow.
- A DataGrid driven by a `cache-and-network` query (e.g. the admin Projects grid) can render "0–0 of 0" for a beat on first mount before data arrives, so `take_snapshot` immediately after navigation may catch the empty state. Re-snapshot or `wait_for` a known row value before asserting the grid is empty.
- MUI `spinbutton` (number input) fields with a pre-filled value will APPEND when driven by `fill` or `fill_form` - "3" becomes "31" if you try to fill "1". Always click the field first, then `Control+A` to select all, then `fill` with the desired value. Alternatively use `evaluate_script` to set the value directly.
- The Transfer dialog success toast is very brief - by the time `take_snapshot` runs after the click, it may already be gone. Confirm success by observing the grid data (dialog closed + new/updated row present) rather than waiting for the toast text.
- Vendor combobox in PO create/edit is NOT freeSolo - it's a strict select-from-list that pulls from the vendors DB table. Typing a new vendor name shows "No options" and pressing Escape or Enter won't commit it. You must first create the vendor via Admin > Vendors, then it appears in the PO vendor dropdown. The PO create dialog's vendor field also appears to accept free-text input visually, but the value is not saved if no matching vendor exists in DB.
- Receiving wizard: after selecting POs and clicking "Receive N Selected", the Receive modal opens. The "Receive Now" spinbutton defaults to 0. Using `fill` fails (value doesn't stick on React controlled spinbutton). Use `evaluate_script` to focus the input, then `press_key` ArrowUp to increment. ArrowUp from 0 goes directly to the max (pending qty) in one press.
- Receiving wizard: "Assign locations & flag deficient units now" toggle appears only AFTER entering a Receive Now quantity > 0. Turn it on to get the Aisle/Bay/Bin text fields (regular textbox, not autocomplete). `fill_form` works fine on these.
- Transfer dialog Aisle/Bay/Bin: these are comboboxes with autocomplete="list". Use `evaluate_script` to set the underlying input value (native value setter + `input` event). This reliably sets the values without triggering dropdown selection. The Transfer button enables once all three fields are filled.
- Locations page (Warden filter, panel open): when a single warehouse filter is active, the left rail single-column shows just the bin name + qty (no warehouse chip in that column, since filter is already scoped). The right panel header still shows the warehouse chip (e.g. "WRD").
- Verifying a generated PDF (issue #230 PO document): the doc is text-based react-pdf, not an image, so `pdftotext` works. Fastest path for content assertions: use the dialog's "Save to PO documents" to upload it, query the PO's `documents { downloadUrl }` (presigned S3 URL) via GraphQL, `curl` the URL to a file, then `pdftotext -layout` (or `-raw` for the totals column, which `-layout` misaligns since Subtotal/Freight/Miscellaneous/Tax/Order-Total are right-aligned). "Generate & preview" opens a blob in a new tab that's hard to read via MCP - prefer save-then-fetch.
- pdftotext/poppler is NOT installed on the dev machine, and naive stream-inflation can't read the text (react-pdf subsets fonts to custom glyph IDs). Working alternative: open the presigned `downloadUrl` directly in a browser tab (Chrome renders PDFs natively) and `take_screenshot` - the full totals column is readable in the image. Verified this way for issue #156 (Tariffs line + Order Total math).
- Issue #156 fields: PO detail modal shows "Shipping Costs" / "Tariffs" info rows ('-' when null) and edit-mode number fields; the generate-document dialog's Freight prefills from the PO's shippingCost (saved documentData override wins) and its new Tariffs field from the PO's tariffAmount; the PDF prints a Tariffs totals line only when > 0.
- Issue #216 buyer identity (scoped to REGISTERING by issue #256 - drafting needs neither): registering a PO into GP REQUIRES the signed-in user to have a GP buyer identity (Clerk publicMetadata.gpBuyerId, set in Admin -> User Management) AND, for project POs, a buyer assignment (Admin -> Buyers: assigned projects + designated 'cc1-cc2' cost codes). Without them the register dialog blocks and the backend rejects. The test user (Jay Puzon) is linked to GP buyer "mira" with project 80003 + cost codes 210-200/310-000 assigned. The register dialog's Buyer field is read-only (your identity); its cost-code dropdown offers only designated codes. Stock POs (no project) skip the assignment check but still need the identity.
- Issue #216 delivery dates: PO Requests capture "Preferred delivery date" per vendor card in the import wizard's PO step; the detail modal edits Preferred only while DRAFT and Expected only when GP-Registered/Vendor-Confirmed (server-enforced).
- Import-created PO drafts have EMPTY Order As values unless set in the wizard's PO step - the register dialog then blocks submit with per-line 'Required' errors until each line's Order As is filled.
- The generate dialog + admin PO-settings text fields APPEND when driven by `fill`/`fill_form` if they already hold a value (same MUI controlled-input quirk as spinbuttons). For a pre-filled field, set the value via `evaluate_script` using the native value setter + an `input` event (match the label's `for` attr to the input id), or drive the mutation directly. Empty fields fill fine.
- Date-only fields: a `<TextField type="date">` renders as Month/Day/Year spinbuttons in the a11y tree. Set it via `evaluate_script` native setter with a `YYYY-MM-DD` string on the underlying input (dispatch `input` + `change`). Note: formatting a `YYYY-MM-DD` string with `new Date(str)` is UTC and prints the previous calendar day in a behind-UTC tz - the PO-document code parses date-only strings as local (fixed in #238), so the printed required-by should match what was entered.
- To seed a project's job-site address for the PO document's "Use project site" ship-to option (most test projects have null address fields), call `updateProject(id, {jobSiteName, address, city, state, zip})` via `evaluate_script` (Admin/Manager gated). Then the dialog's "Use project site" button builds a real "UC Hardware Inc. - Deliver to site / ..." block.
- PO list rows: clicking the row's StaticText via a snapshot uid may NOT open the detail modal (the a11y click can miss the row handler). Reliable alternative: `evaluate_script` finding the leaf element by text and clicking its `closest('td')`.
- Locations page bin panel "Item actions" menu (stock rows): Move / Transfer / Adjust Qty / Unlocate. "Adjust Qty" opens the shared LocationActionDialog - Confirm stays disabled until a non-zero adjustment AND a reason are entered; the helper text under the adjustment shows the computed "New qty: N" and flags negatives. Verified live: adjustment writes an ADJUSTMENT audit row (`auditLog(limit: N)`) with performedBy "Admin/Manager".
- Draft PO create (issue #256 dialog) works with the relay down end to end: the created draft's `preferredDeliveryDate` round-trips exactly (entered 2026-08-15 -> stored 2026-08-15 -> detail modal renders 8/15/2026, no UTC day shift). Cancelling a draft removes it from the `purchaseOrders` list entirely.
- `inventoryHierarchy` returns `totalAvailableQuantity` at both category and product-code levels (issue #229): available = quantity - deficient, so a 10-qty row with 7 deficient shows total 10 / available 3. Cross-check against `deficientItems`.
- `Notification` has no `kind` field - it is `type` (`{ notifications { id type message isRead createdAt recipientRole projectId } }`). Querying `kind` fails the whole document, so a mistyped notification field takes the relay/pull/request fields in the same query down with it.
- The bell panel is a plain MUI Popover with a "Notifications" heading and one bold row per unread item; the app-bar badge count matches `notifications` where `isRead: false`. It renders every audience regardless of your role, so 4 in the badge means 4 rows in the panel.
- **Pre-#346 completed leaves read as `0/N units` everywhere.** `installed_quantity` was added with `server_default "0"`, so leaves assembled before slice 2 landed have no per-line progress and `assemblyPipelineSummaries.installedUnitCount` comes back 0 even for openings that are `completedOpeningCount`/`shippedOpeningCount`. The Pipeline grid's Progress column and the detail modal's Units column both render that faithfully - a row reading "Shipped / 2 of 2 assembled / 0/2 units" is legacy data, not a bug. Current code cannot produce it: `complete_assembly` refuses a leaf where every line is `installed_quantity == 0`.
- Same vintage: the Pipeline detail's per-leaf **Staged** column shows `-` while the pull's own staging panel shows a green "Staged" chip. The panel reads `pull_status`; the pipeline reads `staged_at`/`staged_by`, which the pre-#343 "Mark as Pulled" path never wrote. Not a contradiction, just two fields with different histories.
- The Shipping browse page's "Door leaves shipped" is a **section label**, not a stat card - there is no count in it. The `0` that lands next to it in `document.body.innerText` on the All-Projects view is the **cart badge** from the app bar. Do not read it as "zero leaves shipped"; the per-opening chips below are the truth (a shipped opening renders as a filled green chip, `Opening 0019-EX: 2 of 2 leaves shipped`).
- `shopAssemblyRequests` returning `[]` does **not** mean the pipeline is empty - it is the *pending accept queue*. `assemblyPipelineSummaries` covers every request in every state and is the right query for "what exists". A request whose pull is already approved shows up in the second and not the first.

### Driving the app with the Chrome MCP tools

- **`file_upload` caps at 10 MB and `contracterp-74.xml` is 11.5 MB**, so the real fixture cannot be uploaded through the tool at all. Either take the "Use last uploaded schedule" card (almost always right), or build a subset: keep everything up to `<Detail>` (that block holds all 1998 opening/assignment definitions, ~1.07 MB) then append `<Detail>` + the first N `</Material_List>`-delimited blocks + `</Detail></Contract>`. ~600 blocks lands at ~3.5 MB, parses clean, and yields "1998 openings parsed / 12746 hardware items parsed / 22 opening(s) had no hardware items assigned". Parsing is entirely client-side - nothing is persisted until Finalize - so uploading a trimmed file is safe on a database you are trying to preserve.
- **`navigate` costs a full reload and wipes any instrumentation you injected.** React Router picks up `history.pushState(...)` + `window.dispatchEvent(new PopStateEvent('popstate'))`, so route sweeps can be done client-side with a `fetch` wrapper still installed. That wrapper is far better evidence than `read_network_requests`, which only starts recording when first called and misses everything before it, and it can see GraphQL errors - which come back **HTTP 200** with an `errors` array, so status-code filtering finds nothing.
- **A `javascript_tool` call that hits the 45s CDP timeout keeps running in the page.** Its `await` chain continues after the tool has given up, so the next call races it and you get results tagged with the wrong route. Keep loops under ~8 route-hops, or step one route per call. If output ever looks mismatched, sleep ~6s and start over.
- `computer screenshot` times out with "renderer may be frozen" while the Import wizard renders 1998 openings or 26k classification rows. It is not frozen - wait 10s and take it again. Same for the first paint after "Use last uploaded schedule".
- The screenshot image is scaled down from the real viewport (1568px wide image for a 1918px window), so a card that looks cut off at the right edge usually is not. Check `document.documentElement.scrollWidth === clientWidth` before reporting a horizontal-overflow regression.
- The Pull Request detail modal **closes on Escape since the 2026-07-28 UI revamp** (it used to swallow it). Its nested confirm dialogs are siblings, so an Escape inside a confirm closes only the confirm. "Cancel Pull" is still a real destructive action - never use it as a way out.
- MUI option cards (import Purpose, module "Go to" cards) are `useNavigate` buttons with no `href`, so there are no anchors to click and `find`'s ref sometimes lands on the inner text node rather than the clickable card. Setting the underlying `input[type=radio]`/`input[name=select_row]` via native `.click()` works reliably and does update React state.
- The import landing project card is a `MuiCardActionArea` **button** wrapping the `MuiPaper`. Coordinate clicks land on it only sometimes (it takes focus but does not activate, and Enter does not help either). Reliable: find the element whose `textContent` matches the project *and* whose `tagName === 'BUTTON'`, then `.focus()` + `.click()`.
- **Select Openings is paginated at 50 rows/page, ordered by the schedule, not sorted**, and the "Filter" control is a Select (column filter), *not* a text search - there is no way to type an opening number. To enumerate or tick specific openings, scroll the `.MuiDataGrid-virtualScroller` in ~150px steps, and after each `scrollTop` assignment **dispatch a `scroll` event and wait ~450ms** or the virtualizer does not re-render and you silently collect only the first screenful (17 of 50). Keep the sweep under ~40s of `await` or the 45s CDP cap kills the call mid-loop - it leaves the page in a valid state (rows already ticked stay ticked), so just re-run and top up the selection.
- The Receive modal has **two** confirmations: `Complete Receive` opens a nested `Confirm Receive` ("Receive N items across M PO into inventory?") whose button is just `Receive`. Scripting only the outer button looks like a silent no-op - inventory stays empty and the outbox stays at 0 because no mutation ever fired.
- Receive modal quantity + location fields take a native value-setter + `input`/`change` event fine (no need for the ArrowUp trick), and the location block only appears once a Receive Now qty > 0. `all placed` chips per product gate `Complete Receive`.
- **DataGrid rows are invisible to `take_snapshot`.** The a11y snapshot gives you `columnheader`s and
  the pagination controls and *nothing else* - no row uids - so `click(uid)` cannot reach a row at
  all. Read rows with `evaluate_script` over `[role="row"]`, and prefer the per-cell form, which
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
- **Waiting for a Railway deploy**: poll the *schema* for a field the new build adds rather than
  guessing at a duration -
  `{ __type(name: "PickSheetSection") { fields { name } } }` until the new field appears. Backend and
  frontend deploy separately; the backend took ~225s from merge to serving on 2026-07-28. `/health`
  answering is not sufficient, it answers on the old build too.
- **Most warehouse reads are ungated, so curl is faster than the browser for setup and assertions.**
  `pullRequests`, `inventoryItems`, `inventoryHierarchy` and `auditLog` all answer unauthenticated;
  `shopAssemblyRequests`, `relayStatus` and the pick mutations are `require_user`. A partially-gated
  query returns HTTP 200 with `data.<field>: null` *and* an `errors` array - if a list looks
  mysteriously empty, print `errors` before concluding the data is missing.
- Allocator step (#378) specifics: the summary table is `Owed / Available / Allocated / Left to assign / Short`; each leaf card carries a `Fully covered` / `Not covered - auto-dropped` chip, an `N of M allocated` caption and an include/exclude toggle; the steppers have `aria-label`s `Add one <productCode>` / `Remove one <productCode>` and the `+` disables at `allocated === owed`. Driving a leaf's only line to 0 flips it to auto-dropped, greys the card, drops it out of the `Door leaves (N of M being sent)` count, removes its owed units from the summary, and shows an amber `N short` chip - **and Next stays enabled**, which is the whole point of the change.

## 2026-07-28 UI revamp - what changed for testers

An experimental aesthetic+motion revamp landed on master (single revertable PR). Business logic,
queries/mutations and every action are unchanged, but a lot of chrome moved:

- **Navigation is a persistent left rail on desktop** (collapsible via the panel icon in the app
  bar; state persists in localStorage `uc-nexus-rail-collapsed`). The hamburger-opens-drawer flow
  now exists only below the `md` breakpoint. Sub-items (incl. the new Pipeline entry) expand under
  the active module. The `<- Warehouse` / `<- Projects` back buttons are gone - breadcrumbs (now
  labelled "Purchase Orders", "Start a Task") are the way back.
- **Icons are lucide (stroke) not Material (filled)**; icon-only buttons gained aria-labels
  (e.g. `Open <PO> details`). Snapshot selectors keyed on Material icon `data-testid`s will miss.
- **Stat values animate** (count-up over ~0.5s on mount). A snapshot taken immediately after
  render can catch a mid-flight number - `wait_for` the final value or re-snapshot. With
  `prefers-reduced-motion`, values render instantly.
- **PO list**: the 7 stat tiles are now one status strip; segments are still the same filters
  (`aria-pressed`, `aria-label="Filter by <status>"`). The whole data row opens the detail modal;
  the leading chevron cell only toggles the line-item expand. Empty modal fields render an em-dash
  `—` (was `-`).
- **Escape behavior changed on purpose**: Pull Request detail modal now closes on Escape;
  Receive modal and Transfer dialog now *block* Escape once you have typed values into them
  (they used to discard silently). The assembly modal's close semantics are unchanged.
- **Shipping browse (Ship tab)** is no longer a chip wall: one row per opening (mono ref +
  per-leaf tags), with a text search on opening # and an All / Shippable / Shipped / Not ready
  filter. Long project groups window at 30 rows with a "Show N more of M" tail - enumerate via
  the search box or expand the tail. Selection/cart semantics unchanged. (The shop-assembly /
  warehouse shared chip panel caught up on 2026-07-29, PR #400: `OpeningLeafStatusPanel` windows
  each project group at 30 rows with a "Show N more of M" tail, adds a "Search opening #" box once
  there are more than 30 rows - searching expands across the window - and grouped project headers
  carry a "N of M leaves assembled/shipped" summary. On the Assemble List the panel now renders
  BELOW the Ready/Waiting/Pending work sections, so asserting on the top of that page means the
  work sections, not the chip wall.)
- **Import wizard**: step 1 shows a single success strip (the old second green alert is merged
  in); Purpose options are cards now but the radio semantics and the exact label strings
  ("Create Purchase Orders", "Pull Request for Shop Assembly", "Pull Request for Shipping Out")
  are unchanged.
- **Warehouse/Admin/Shop-Assembly landings**: the "Go to" cards now carry live counts (pending
  pulls, unlocated, deficient, etc.), driven by the same queries as before.
- **DevAction: drop and rebuild schema** is finally visible in light mode (it was ink-on-ink);
  same label, now to the right of the bar spacer, and its confirm button is red.
- Home's Recent Activity renders human sentences ("Staged door leaf ..."), never raw enums like
  `INSTALL_PROGRESS SHOP_ASSEMBLY_OPENING`. Since PR #396 the rows also carry a real identity mined
  from the audit `detail` payload - `Staged door leaf 62 · L1`, `Pulled inventory item 2× BB1068 ...
  · SA-E2E-367`, `Received ... · PO0000066` - with the shortened UUID only as a last resort.
- Every server timestamp in the app parses as UTC since PR #399 (`parseServerDate`; backend
  datetimes are naive-UTC with no zone suffix). Relative times reading "just now" for hours, or
  wall-clock times off by your UTC offset, are a regression of that fix, not server clock drift.
