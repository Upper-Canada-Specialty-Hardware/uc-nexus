# Hardware Identity Lifecycle

How a piece of hardware gains, loses, and regains its association with a specific door leaf of a
specific opening. This is the domain rule the rest of the system is built on, and most of the
lifecycle bugs found so far have been a violation of it.

## The rule

**A pull request is the act of tagging hardware onto a door leaf.**

Hardware enters the system with an opening identity, loses it in the warehouse, and gets it back
when a pull request is created. That is true of both pull request sources: shop assembly and
shipping out. Neither is a special case.

## The three stages

### 1. Identity present: schedule and procurement

The TITAN hardware schedule is written per opening, and per door leaf within an opening. Import
preserves both:

- `openings.leaf_count` - 1 (single) or 2 (pair). The "N of M leaves" denominator.
- `hardware_items.opening_id` - which opening needs this item.
- `hardware_items.leaf` - which leaf of that opening, from the `Leaf` attribute on the TITAN
  Material_List (cross-checked against the material id token).

The PO module procures against these rows. A PO line item exists because some opening needs it.

### 2. Identity dropped: receiving into inventory

Receiving deliberately throws the opening away. `InventoryLocation` is keyed by
`(project_id, warehouse_id, hardware_category, product_code)` and has **no opening or leaf column**.
It keeps only an origin FK (PO line item, stock item, or shipment return item) for costing and audit.

Inventory is fungible: a hinge is a hinge. Hardware received against opening 101's PO can be used on
opening 205. This is intentional, not an oversight. It is also why
[REALLOCATION_MODULE.md](REALLOCATION_MODULE.md) exists: once an opening ships short, the hardware
that could fill the gap is sitting in general inventory with nothing tying it to that opening.

The only surviving identity at this stage is the project.

### 3. Identity restored: the pull request

Creating a shop assembly request or a shipping out request is what re-attaches identity. Each
`pull_request_items` row is a tag:

- `opening_number` - which opening the quantity is now committed to.
- `leaf` - which door leaf of it.
- `hardware_category` + `product_code` + `requested_quantity` - what is being claimed from fungible
  stock.

Approving the pull request deducts that quantity FIFO from `inventory_locations` rows. The physical
hardware never changed; what changed is that it now belongs to a leaf.

This is why both request types are created from the hardware schedule through **Start a Task**. The
schedule is the only thing that knows which leaf of which opening a quantity is owed to. Inventory
cannot answer that question, because it deliberately forgot.

#### 3a. The reservation: the tag's claim before the pull

The tag is written when the request is created, but the stock is not deducted until the warehouse
approves the pull - and that gap used to be a hole. Two requests could each be created against the
same hinges, both pass an accept-time check, and the second pull would then find the shelf empty.

Since #342 **creating a request reserves what it claims.** An `inventory_reservations` row is written
in the same transaction, and availability everywhere becomes

    available = on-hand - deficient - active reservations

A reservation is the claim half of the tag: it says "these units are spoken for by this request"
without yet saying *which* units, which is exactly right for fungible stock. Note what the table
deliberately does not have, for the same reason `InventoryLocation` does not have it:

- **no opening, no leaf** - a hinge is still a hinge; the reservation is aggregate, per
  `(project, hardware_category, product_code)`;
- **no `inventory_location_id`** - pinning a claim to specific rows would fight FIFO. The reservation
  governs *how much* is free, never *which* row. FIFO deduction at approval is unchanged.

The lifecycle of that claim, end to end:

| Path | Effect on the claim |
| --- | --- |
| Create a shop-assembly request | **Reserve** every checklist line, aggregated per combo |
| Create a shipping-out request, LOOSE line | **Reserve** - it claims fungible stock |
| Create a shipping-out request, OPENING_ITEM line | **Nothing** - the leaf claimed its hardware at assembly and ships as itself |
| Creation would exceed available | **Refused whole** - typed `InventoryShortfallError` naming every short combo; nothing is written and the creator refines the selection |
| Accept (either type) | **No change** - accept is a pure human gate and re-checks nothing |
| Reject (either type) | **Release** - the request is dead, the hardware goes back to the pool |
| Reopen an accepted request (#325) | **No change** - reopen undoes the *accept*, not the creation; the request returns to PENDING still holding its claim |
| Reject after a reopen | **Release** - the same reject path, and the only thing that finally lets go |
| Pull approval, sufficient | **Consume** - the claim becomes the FIFO deduction, atomically, under the same row locks |
| Pull approval, short | **No change** - the pull stays PENDING and keeps holding, so a blocked request does not hand its hardware to whoever asks next |
| PR-REPL replacement pull | **Never reserves** - a deficiency cannot be foreseen, so it keeps the reactive check and the PO-backfill loop. It still draws only from on-hand minus deficient minus *others'* reservations |
| Re-upload drops a PENDING request's openings | **Rebuilt** from what survived, which releases exactly what the vanished openings held |
| Re-upload empties a PENDING request | **Auto-reject**, which releases |

**Self-coverage** is the one subtlety worth naming. When the warehouse approves request R's pull, R's
own reservations are precisely what backs the deduction, so the availability check on that path
excludes them (`exclude_reservations_of`). Without the exclusion a request that reserved exactly what
it needs would read as competing with itself and could never be approved. Everyone else's claims
still count - which is also what stops an unreserved PR-REPL pull from eating stock another request
is holding.

A **deficiency reported at the bench** does not touch reservations, and cannot double-count against
them: `report_deficiency_at_assembly` raises the inventory row's `quantity` and `deficient_quantity`
together, so the pair nets to zero in `on-hand - deficient`. The unit is back in the building and is
not available - which is the truth.

#### 3b. Staging: the tag moves onto a cart, opening by opening

Approving the pull is one decision; *executing* it is a shift's work. The warehouse picks a pull cart
by cart, and before #343 the system only knew "pulled" or "not pulled" for the whole request, so an
opening whose hardware was on a cart at 9am was not assignable until the last opening was picked at
4pm.

**Staging is per opening.** `stage_pull_openings` flips one `ShopAssemblyOpening.pull_status` to
`PULLED` at a time, stamping `staged_at` / `staged_by`, and that opening becomes assignable and
workable immediately. Staging the last one calls `complete_pull_request`, so the completion
notification and the replacement-arrival application still fire exactly once, from one place.

Two state facts, deliberately kept apart:

- `ShopAssemblyOpening.pull_status` is only ever `NOT_PULLED` or `PULLED`. One cart is built or it is
  not; persisting a half-truth about a single cart would be a lie.
- `PullStatus.PARTIAL` is the **aggregate** reading over a set of openings, and it is **derived, not
  stored** (`warehouse.get_pull_staging_summaries`, one grouped aggregate for a whole page).
  `PullRequestStatus` therefore stays `PENDING -> IN_PROGRESS -> COMPLETED/CANCELLED` with no
  half-state wedged into it.

**Deduction timing does not move.** FIFO deduction and consumption of the source request's
reservation both stay at approval. Approval is where the pull is committed, and per-opening deduction
would break two things at once: an approved-but-unstaged opening would hold neither a reservation nor
a deduction, so its hardware would read as free to the next request (the hole §3a closed); and a
shortfall could then surface at staging time, where the only recovery is a half-deducted pull.
Staging is progress tracking. Cancellation is what reverses stock.

#### 3c. Cancelling a pull: the tag comes off

Once a pull was approved there was no way back - stock was deducted and `PullRequestStatus.CANCELLED`
was an enum value nothing ever set. `cancel_pull_request` is the way back, and it is
**all-or-nothing per pull**:

| Rule | Why |
| --- | --- |
| Blocked by any opening whose assembly is IN_PROGRESS or COMPLETED, naming every blocker | That is where the hardware stops being retrievable - it is on a leaf, and some of it may already have been condemned and replaced |
| Staged-but-unassembled openings **do** come back | Their hardware is on a cart in the shop, exactly as retrievable as hardware on the shelf. Restocking only the un-staged part would leave the staged part deducted with no leaf to show for it |
| No partial cancel | `PullStatus` has no cancelled value, and `complete_pull_request` flips *every* opening of a pull to PULLED - so a half-cancelled pull would resurrect its released openings the moment the rest was staged. Expressing it properly needs an opening-level cancelled state |
| Cancellable from IN_PROGRESS, and from COMPLETED for a shop-assembly pull with openings | Since staging is per opening, COMPLETED there means no more than "every cart is built". A completed shipping-out pull has already flipped leaves to SHIP_READY, and a completed PR-REPL pull has already restored expectations |
| Restock lands on the project's newest `InventoryLocation` row for the combo, not a row-by-row reversal | Which row a hinge sits on carries no identity (the rule at the top of this document). Landing on the newest row is also conservative for future FIFO: older stock still goes out first |
| Source request returns to **PENDING**, and its reservation is re-created after the restock, availability re-checked | The claim was consumed at approval, so re-creating it is a new claim competing with everyone else's. If it cannot be covered, the request is left **unreserved and flagged** via `integrity_note` rather than half-claimed - the same honest-and-flagged shape the #342 backfill uses |
| A PR-REPL replacement pull restocks and re-creates nothing | It never held a reservation. The leaf's `deficient_quantity` is untouched: the expectation stays on the checklist line and the replacement has to be requested again |

Cancelling keeps the pull row, which is why `pull_requests.request_number` is unique only among
**live** pulls (a partial unique index excluding `CANCELLED`): re-accepting the returned request
mints a fresh pull carrying the same number.

### 4. The tag materializes

The tag does not become physical all at once. Assembly happens over a shift, unit by unit, and since
#340 the system records it that way.

- **Assembly progress** - `shop_assembly_opening_items.installed_quantity` / `deficient_quantity`
  count what the assembler has actually fitted and what has been condemned. This is *work-tracking on
  the tag*, not a materialization: no `OpeningItem` exists yet, nothing has left or entered fungible
  inventory (the hardware was deducted when the pull was approved), and the leaf can be handed to
  another assembler without losing a unit of it. The opening sits at `IN_PROGRESS` while this is
  happening. Remaining is `quantity - installed - deficient`, derived, never stored.
- **A unit found defective** goes back the moment it is found, not at completion:
  `report_deficiency_at_assembly` returns it to project inventory flagged deficient and appends a
  PR-REPL replacement pull line carrying the leaf and the source `ShopAssemblyOpeningItem`. That is
  the identity round-trip in miniature - the unit loses its leaf on the way back into inventory, and
  the replacement line is what re-tags a fresh one.
- **Shop assembly complete** - *this* is where the tag becomes physical. An `OpeningItem` row is
  created per leaf (`opening_items.leaf`), with one `OpeningItemHardware` row per line that had units
  installed, at the **installed** quantity, not the planned one. Completion is refused while any unit
  is still unaccounted for (`installed + deficient < quantity`), and refused if nothing at all was
  installed - an assembled leaf with no hardware on it would read as ship-ready inventory. From here
  the leaf is a real object with its own state and warehouse location.
- **Shipping out complete** - the leaf moves to `SHIP_READY`, then a confirmed shipment writes a
  `PackingSlipItem` that snapshots the leaf permanently.

### 4b. The replacement loop closes

Since #341 the round-trip a deficiency starts actually finishes. When the PR-REPL pull completes,
`complete_pull_request` reads each line's `sa_opening_item_id` and gives the leaf its expectation
back - floored at what is genuinely still outstanding, so an over-delivery restores nothing extra.
Where the freed unit lands depends on whether the tag is still being worked:

- **Leaf still PENDING / IN_PROGRESS** - `deficient_quantity` simply drops, `remaining` goes back up,
  and the unit reappears as work in My Work. Completion stays blocked until somebody fits it.
- **Leaf already COMPLETED** - the unit moves into `replacement_pending_quantity`. This is the third
  bucket the line is partitioned into, and it exists because the alternative corrupts the model:
  lowering `deficient_quantity` alone would make a finished leaf read as un-dispositioned
  (`installed + deficient < quantity`). Moving it keeps the sum at `quantity` - the leaf is complete,
  with a known unit of work outstanding - and the check constraint
  `installed + deficient + replacement_pending <= quantity` is what makes that enforceable rather
  than merely intended. `install_replacement` then moves it `replacement_pending -> installed` and
  appends or increments the leaf's `OpeningItemHardware` row: **the one legitimate write to an
  assembled leaf's hardware after completion**, bounded by what the pull actually delivered.
- **Leaf already SHIPPED_OUT** - the hardware cannot be fitted to something that has left the
  building. The pending state is still recorded, so the unit stays queryable rather than silently
  stranded, and a `REPLACEMENT_AFTER_SHIPMENT` notification hands it to the reallocation /
  site-shipment world. `install_replacement` refuses it.

**A leaf with anything in `deficient_quantity` or `replacement_pending_quantity` is physically short
of the hardware list it would ship under.** That sum is `OpeningItem.awaiting_replacement_quantity`,
and it is what the shipping wizard flags as "incomplete - awaiting replacement". Shipping it anyway
is allowed and sometimes right - reallocation exists for exactly that - but the shipping-out creation
path refuses a flagged leaf unless the caller passes an explicit acknowledgment. Warn and confirm,
never silent, never a hard block.

## Corollary: LOOSE vs OPENING_ITEM pull lines

Both pull request sources use `pull_request_items`, but the two `item_type` values do fundamentally
different things:

- `LOOSE` - tags fungible inventory onto a leaf for the first time. Approving it deducts stock, so it
  is gated on inventory sufficiency - and since #342 it is also what *reserves* stock when the
  request is created.
- `OPENING_ITEM` - moves a leaf that was **already tagged** at shop assembly. The hardware left
  fungible inventory when it was installed. Approving it deducts nothing and locks the `OpeningItem`
  row instead; there is no stock to check, and nothing to reserve either.

Confusing the two is issue #335: the Shipping Out import emitted `LOOSE` lines for hardware that had
already been assembled onto a leaf, so the warehouse pull asked general inventory for hardware that
had left it, found zero, and blocked approval forever. An assembled leaf ships as an `OPENING_ITEM`
line naming its `OpeningItem`, never as loose hardware.

The same asymmetry explains the shipping wizard's selection UI: assembled leaves are listed per
`OpeningItem` (one row per leaf, because each leaf is its own physical object), while loose hardware
is listed leaf-agnostically per `(opening, category, product)` (because fungible stock carries no
leaf until a pull tags it onto one).

## Where this is enforced in code

| Stage | Code |
| --- | --- |
| Leaf parsed from TITAN | `frontend/src/workers/parserLogic.ts` (`leafFromMaterialId`, ML-level `Leaf` attribute) |
| Identity dropped | `backend/app/models/inventory.py` (`InventoryLocation`, no opening/leaf column) |
| Claim written at creation | `backend/app/repositories/import_repository.py` (`finalize_import_session` -> `_gate_on_available_inventory` + `create_reservations`) |
| Claim modelled | `backend/app/models/inventory_reservation.py` (aggregate; no opening, no leaf, no location) |
| Availability arithmetic | `backend/app/repositories/warehouse/reservations.py` (`get_reserved_quantities`, `get_project_availability`, grouped aggregates) |
| Claim respected / self-covered | `backend/app/repositories/warehouse/pull_requests.py` (`check_inventory_sufficiency`, `reservation_aware` + `exclude_reservations_of`) |
| Claim consumed at the pull | `backend/app/repositories/warehouse/pull_requests.py` (`approve_pull_request` -> `release_reservations` then FIFO deduction) |
| Claim released | `shop_assembly_repository.reject_shop_assembly_request` / `shipping_repository.reject_shipping_out_request` (reject only - reopen deliberately holds) |
| Duplicate / cross-type leaf guard | `shop_assembly_repository.find_in_flight_assembly_leaves`, `shipping_repository.find_live_shipping_claims` |
| Re-upload reconciliation | `backend/app/repositories/import_repository.py` (`_handle_schedule_replacement` -> rebuild, auto-reject, `integrity_note`) |
| Tag written, shop assembly | `backend/app/repositories/shop_assembly_repository.py` (`accept_shop_assembly_request`) |
| Tag written, shipping out | `backend/app/repositories/shipping_repository.py` (`accept_shipping_out_request`) |
| Tag consumes stock | `backend/app/repositories/warehouse/pull_requests.py` (`approve_pull_request`, FIFO deduction) |
| Tag staged, opening by opening | `backend/app/repositories/warehouse/pull_requests.py` (`stage_pull_openings` -> one `ShopAssemblyOpening.pull_status`, `staged_at` / `staged_by`; last one calls `complete_pull_request`) |
| PARTIAL derived, never stored | `backend/app/repositories/warehouse/pull_requests.py` (`get_pull_staging_summaries` / `StagingSummary.status`, one grouped aggregate per page) |
| Workability keyed on the opening, not the pull | `backend/app/repositories/shop_assembly_repository.py` (`_APPROVED_PULL_STATUSES` + `pull_status == PULLED` in `get_assemble_list`, `get_my_work`, `assign_openings`, `record_assembly_progress`, `complete_opening`) |
| Tag comes off, stock returned | `backend/app/repositories/warehouse/pull_requests.py` (`cancel_pull_request` -> `_return_units_to_project_inventory`, all-or-nothing, blockers named) |
| Claim re-created after a cancel | `backend/app/repositories/warehouse/pull_requests.py` (`cancel_pull_request` -> availability re-check then `create_reservations`, else `integrity_note`) |
| Pull number unique among live pulls only | `backend/app/models/pull_request.py` (`uq_pull_requests_request_number_live`, partial index excluding CANCELLED) |
| Tag worked, incrementally | `backend/app/repositories/shop_assembly_repository.py` (`record_assembly_progress` -> `installed_quantity` / `deficient_quantity`) |
| Deficient unit returned + replaced | `backend/app/repositories/stock/deficiency.py` (`report_deficiency_at_assembly` -> PR-REPL line) |
| Tag materialized | `backend/app/repositories/shop_assembly_repository.py` (`complete_opening` -> `OpeningItem`, quantities = installed) |
| Replacement arrives, expectation restored | `backend/app/repositories/warehouse/pull_requests.py` (`_apply_replacement_arrivals` -> `deficient_quantity` down, `replacement_pending_quantity` up on a completed leaf) |
| Replacement fitted to a finished leaf | `backend/app/repositories/shop_assembly_repository.py` (`install_replacement` -> `OpeningItemHardware`) |
| Leaf is short of its own list | `backend/app/repositories/shop_assembly_repository.py` (`get_awaiting_replacement_quantities`, one grouped aggregate) |
| Shipping a short leaf takes a decision | `backend/app/repositories/import_repository.py` (`finalize_import_session`, `acknowledge_incomplete_leaves`) |
| Replacement stranded after shipment | `backend/app/repositories/warehouse/pull_requests.py` (`REPLACEMENT_AFTER_SHIPMENT` notification) |
| Tag shipped | `backend/app/repositories/shipping_repository.py` (`confirm_shipment` -> `PackingSlipItem.leaf`) |
