# Simulated User Testing Guide

This is a tester's knowledge journal for UC Nexus. It documents how the app works from a front-end user's perspective and how to drive it via Chrome DevTools MCP.

**Maintain this file:** Update it when you discover new behaviors, gotchas, or workflows during testing. This is a living document that grows with each testing session.

---

## Environment

**Railway is the default** for simulated user testing (issue #182 pivot - the localdev runtime was dropped for UC Nexus e2e; zero local setup needed).

- **Railway production (default)**: frontend `https://frontend-production-34fc.up.railway.app/`, backend `https://backend-production-7866.up.railway.app/`. Deploys from master after CI passes.
- **Railway PR environments** (once enabled in Project Settings → Environments): every PR gets a full ephemeral replica (frontend + backend + fresh empty Postgres, migrated on boot). The Railway GitHub bot comments the environment's URLs on the PR - test there BEFORE merge, substituting those URLs into the sign-in flow below. Data starts empty; seed via the import fixture. `VITE_GRAPHQL_URL` is a reference variable (`https://${{backend.RAILWAY_PUBLIC_DOMAIN}}/graphql`) so each environment self-wires; `TESTING_ENABLED` and Clerk keys inherit from production.
- **Local (manual fallback)**: frontend `http://localhost:5173`, backend `http://localhost:8000`. Run the backend with `poetry run uvicorn main:app --reload` (from `backend/`) and the frontend with `npm run dev` (from `frontend/`). Needs a local Postgres (not provided; the worktree-localdev adoption was dropped).
- **Auth**: Clerk sign-in, automated via one-time sign-in tokens (no manual password/verification needed).
  - Backend endpoint `GET /testing/clerk-sign-in` generates the token (requires `TESTING_ENABLED=true`).
  - Navigate to the frontend URL with `?__clerk_ticket=TOKEN` to auto-authenticate.
  - Tokens are one-time use; fetch a fresh one each session. Works on any runtime with the same Clerk dev instance.
- **Test XML file**: `testing/fixtures/contracterp-74.xml` - TITAN hardware schedule export, use for Import wizard testing (upload via `upload_file`)

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
/app/shop-assembly         -> Shop Assembly (manager vs user views)
/app/shipping              -> Shipping Out (ship-ready items, packing slips)
/app/admin                 -> Admin (reports, vendors, projects, users, cleanup)
```

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
- Documents section with upload capability
- Receiving history
- Actions: Edit (header fields + line item Order As/costs), Mark as Ordered, Cancel PO

**PO Lifecycle**:
```
DRAFT -> ORDERED -> VENDOR_CONFIRMED -> PARTIALLY_RECEIVED -> CLOSED
                                    \-> PARTIALLY_RECEIVED -> CLOSED
  \-> CANCELLED (from DRAFT, ORDERED, or VENDOR_CONFIRMED)
```
- **Mark as Ordered** requires: PO number + vendor name
- **VENDOR_CONFIRMED** auto-triggers when ORDERED PO has both vendor quote number and vendor acknowledgement document; auto-reverts if either is removed
- **Receiving** a PO without a project will show error: "PO must be associated with a project before receiving"

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

**Approving a pull request consumes its source request's reservation.** A pull whose request reserved
exactly what it needs still approves - the check excludes the request's own claim (self-coverage). A
`PR-REPL-*` replacement pull holds no reservation at all, so it keeps the old reactive behaviour: it
can come up INSUFFICIENT and notify the PO, and it can only draw from what nobody else has claimed.


**Entry**: `/app/warehouse` -> Warehouse landing page with stat cards and "Go to" card buttons for: Inventory, Locations, Deliveries, Receiving, Put Away, Pull Requests, Stock Pool, Deficient Items, Shipments. (No longer "three tabs" - this has evolved to a full landing page.)

**Inventory tab default**: Navigating directly to `/app/warehouse/inventory` defaults to "All Projects" view — shows the "Projects" back button, "All Projects" heading, and Hardware Items / Opening Items sub-tabs immediately. The ProjectLandingPage is NOT shown on initial load. Clicking "Projects" brings up the ProjectLandingPage where you can filter to a specific project or click "All Projects" to return to the all-projects view.

**Receiving** (wizard):
1. Select POs to receive (shows ORDERED/VENDOR_CONFIRMED/PARTIALLY_RECEIVED POs)
2. Enter quantities received per line item — line items grid shows: Product Code, Ordered As, Hardware Category, Ordered Qty, Already Received, Pending, Receive Now
3. Assign storage locations (aisle/bay/bin)
- Receiving auto-transitions PO status (ORDERED -> PARTIALLY_RECEIVED -> CLOSED)

**Inventory**: Browse by hardware category and product code, see storage locations.

**Pull Requests**: Queue of pull requests from shop assembly or shipping modules.

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

**Entry**: `/app/shop-assembly` -> Manager view (SAR list) or user view (my work)

- Manager creates/approves Shop Assembly Requests (SARs)
- Approved SARs generate pull requests for warehouse
- Users get assigned openings, pull hardware, assemble, mark complete

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
  spinbutton-append gotcha on the quantity field - clear it before typing.
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
- A card whose leaf already shipped shows a "Leaf already shipped" chip and a warning alert instead
  of the button - it cannot be installed, only reallocated. A `REPLACEMENT_AFTER_SHIPMENT`
  notification was also raised for the SHIPPING role when the pull completed.

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
- Import wizard Classification step columns: Opening #, Product Code, Hardware Category, Vendor, List Price, Discount, Unit Cost, Qty, Classification. Each row has two toggle buttons: "By UCSH" and "By Others". Also has "Add group level" button and a header checkbox to select all rows. Counter shows "X of Y items classified".
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
- Issue #198: free-form project creation is gone. A project is now adopted from a live GP job - `createProject`/`CreateProjectInput` no longer exist. The ungated mutation is `adoptGpJob(input: AdoptGpJobInput!)` (`jobNumber`, optional `jobName`), which sets `projectId` = `jobNumber` and `description` = `jobName` snapshotted at adopt time (`client` starts null). It does NOT call the relay itself - it trusts whatever the caller passes, so seeding a project via `evaluate_script` fetch still works without a relay connection: `mutation { adoptGpJob(input: {jobNumber: "X", jobName: "..."}) { id } }`. The UI dialog (`AdoptGpJobDialog`, "Adopt GP Job" button on the Import landing page) DOES require a connected relay - it picks from the live `gpJobs` query - so driving that dialog through the UI needs the relay running and enrolled. New projects default `offSiteStorageAgreement` to false and the GC/address fields to null — handy for testing the Projects edit flow.
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
