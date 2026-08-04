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

Confirming the pull's **pick** deducts that quantity from the `inventory_locations` rows the
warehouse user names (§3b). The physical hardware never changed; what changed is that it now belongs
to a leaf.

This is why both request types are created from the hardware schedule through **Start a Request**. The
schedule is the only thing that knows which leaf of which opening a quantity is owed to. Inventory
cannot answer that question, because it deliberately forgot.

#### 3a. The reservation: the tag's claim before the pull

The tag is written when the request is created, but the stock is not deducted until the warehouse
confirms the pick - and that gap used to be a hole. Two requests could each be created against the
same hinges, both pass an accept-time check, and the second pull would then find the shelf empty.

Since #342 **creating a request reserves what it claims.** An `inventory_reservations` row is written
in the same transaction, and availability everywhere becomes

    available = on-hand - deficient - active reservations

A reservation is the claim half of the tag: it says "these units are spoken for by this request"
without yet saying *which* units, which is exactly right for fungible stock. Note what the table
deliberately does not have, for the same reason `InventoryLocation` does not have it:

- **no opening, no leaf** - a hinge is still a hinge; the reservation is aggregate, per
  `(project, hardware_category, product_code)`;
- **no `inventory_location_id`** - pinning a claim to specific rows would decide something the claim
  has no business deciding. The reservation governs *how much* is free, never *which* row; which row
  is the picker's call at confirm time (§3b).

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
| Starting a pick | **No change** - opening a pull for picking moves nothing (§3b) |
| Pick confirmed, covered | **Consume** - the claim becomes the deduction of the rows the picker named, atomically, under the same row locks |
| Pick confirmed short | **Partial consume** - only what was picked comes off the book; the un-picked remainder stays claimed, so a part-filled request does not hand the rest to whoever asks next |
| PR-REPL replacement pull | **Reserves what it can at flag time** - `min(free stock, condemned)`, topped up as stock arrives. Being partly covered is its normal resting state, which is why a short pick on one is not an integrity error |
| Re-upload drops a PENDING request's openings | **Rebuilt** from what survived, which releases exactly what the vanished openings held |
| Re-upload empties a PENDING request | **Auto-reject**, which releases |

**Self-coverage** is the one subtlety worth naming. When request R's claim is being spent, R's own
reservations are precisely what backs the deduction, so any availability check on that path excludes
them (`exclude_reservations_of`). Without the exclusion a request that reserved exactly what it needs
would read as competing with itself and could never be satisfied. Everyone else's claims still count,
and since #367 the exclusion decides something at three moments rather than two: the creation gate,
the pick confirmation (§3b), and the cancel-time re-check.

A **deficiency reported at the bench** does not touch reservations, and cannot double-count against
them: `report_deficiency_at_assembly` raises the inventory row's `quantity` and `deficient_quantity`
together, so the pair nets to zero in `on-hand - deficient`. The unit is back in the building and is
not available - which is the truth.

#### 3b. The pick: which units, chosen by the person who can see them

Until #367 approving a pull did everything at once - it checked sufficiency against a project-wide
aggregate, deducted FIFO by `received_at`, consumed the claim, and recorded nothing about where the
hardware physically came from. The warehouse user, the only person standing in front of the racks,
never chose. Two consequences followed: the answer to "where did the hardware for pull X come from"
existed only as a scatter of audit rows nobody could reassemble, and a pull was refused before
anybody had looked at a shelf.

The moment splits in two:

| Step | What it does |
| --- | --- |
| `start_pull_request_pick` | Claims the pull for a picker and opens it: PENDING -> IN_PROGRESS, `assigned_to` and `approved_at` stamped. **Nothing moves in inventory, and there is no sufficiency gate.** |
| `save_pick_draft` | Saves the half-keyed sheet as DRAFT `pull_pick_lines`. A note, not a claim: shape is validated, availability deliberately is not, and a save replaces the pull's whole draft set rather than merging - the paper sheet is the authority being transcribed |
| `confirm_pick` | The atomic swap. Consumes the claim for what is being picked (per combo, partially) and deducts the exact rows named, in one transaction under the pull's lock and every named row's lock. Writes one APPLIED `pull_pick_lines` row and one `PULL_DEDUCTION` audit per row, and stamps `picked_at` / `picked_by` once every combo is covered |

`pull_pick_lines` is the record the FIFO deduction never kept: `(pull, hardware_category,
product_code, inventory_location_id, quantity, state)`. It is the one place a location and a leaf's
hardware are recorded together, and it is not a violation of the rule at the top of this document -
it is *history* ("these units came off that bin"), not identity ("this bin belongs to that leaf").
The FK is `ON DELETE SET NULL`, so a location merged or deleted later degrades the row to "came from
somewhere that no longer exists" rather than blocking the delete.

Three ceilings, all hard and none negotiable from the client. No row may give up more than its own
`quantity - deficient_quantity`; no product code may exceed what the pull asked for once what is
already picked is counted; and no product code may exceed what is genuinely **free for this pull**,
`on-hand - deficient - other requests' reservations`, with this pull's own holder excluded.
**No over-pull, ever.**

**Short is a first-class outcome, not a failure.** A confirmation that does not cover everything
deducts what was entered, leaves the pull IN_PROGRESS and un-picked, notifies purchasing once
(deduped on `notifications.pull_request_id`), and lets a later confirmation enter the remainder. The
alternative - refusing the whole confirmation - would mean a picker who found nine of twelve hinges
has to put the nine back on the shelf. Nobody does that; they mark the pull complete anyway and the
system starts lying.

**The third ceiling is what keeps §3a intact.** Without it a pull holding no claim of its own - a
replacement that could only partly reserve, or a request from the #342 backfill population - could
walk off with stock another request had already been promised, and that request would discover the
loss as a short pick on its own pull. A claim that holds only until somebody physically reaches the
shelf first is not a claim.

It has a real cost: a picker can be refused with hardware in their hand, which the per-row Available
column cannot explain. Two things make that survivable. The refusal is a `CONFLICT` naming the combo
and how much is claimable, so it is actionable rather than mysterious; and the same number rides on
the sheet as `PickSheetSection.claimable_quantity`, on screen and in print, so contention is visible
*before* the walk rather than after it.

An **OPENING_ITEM line is fetched, not picked**: the leaf was tagged at assembly and its hardware left
fungible inventory then, so there is nothing to deduct - only to walk to the rack and collect it.
`pull_request_items.fetched_at` / `fetched_by` persist that check-off so it survives a reload or a
shift change, and a pull whose lines are all OPENING_ITEM is picked the moment it is confirmed with
nothing entered.

#### 3c. Staging: the tag moves onto a cart, opening by opening

Confirming the pick is one decision; *executing* the rest is a shift's work. The warehouse builds a
pull cart by cart, and before #343 the system only knew "pulled" or "not pulled" for the whole
request, so an opening whose hardware was on a cart at 9am was not assignable until the last opening
was picked at 4pm.

**Staging is per opening.** `stage_pull_openings` flips one `ShopAssemblyOpening.pull_status` to
`PULLED` at a time, stamping `staged_at` / `staged_by`, and that opening becomes assignable and
workable immediately. Staging the last one calls `complete_pull_request`, so the completion
notification and the replacement-arrival application still fire exactly once, from one place.

Two state facts, deliberately kept apart:

- `ShopAssemblyOpening.pull_status` is only ever `NOT_PULLED` or `PULLED`. One cart is built or it is
  not; persisting a half-truth about a single cart would be a lie. Since #345 that is a CHECK
  constraint on the column rather than a convention, so a bad write cannot express it either.
- `PullStatus.PARTIAL` is the **aggregate** reading over a set of openings, and it is **derived, not
  stored** (`warehouse.get_pull_staging_summaries`, one grouped aggregate for a whole page).
  `PullRequestStatus` therefore stays `PENDING -> IN_PROGRESS -> COMPLETED/CANCELLED` with no
  half-state wedged into it.

**Deduction timing does not move to staging.** The deduction and the consumption of the source
request's reservation both stay at the pick confirmation (§3b), which is where the pull is committed.
Per-opening deduction would break two things at once: a picked-but-unstaged opening would hold
neither a reservation nor a deduction, so its hardware would read as free to the next request (the
hole §3a closed); and a shortfall could then surface at staging time, where the only recovery is a
half-deducted pull. Staging is progress tracking. Cancellation is what reverses stock.

**Staging is gated on `picked_at`**, not on the pull merely being IN_PROGRESS. Since starting a pick
no longer moves anything, without that gate a cart could be declared built - and its opening handed
to the assembly floor - off hardware still sitting on the shelf. `complete_pull_request` gates the
same way.

#### 3d. Cancelling a pull: the tag comes off

Once a pull was started there was no way back - stock was deducted and `PullRequestStatus.CANCELLED`
was an enum value nothing ever set. `cancel_pull_request` is the way back, and it is
**all-or-nothing per pull**:

| Rule | Why |
| --- | --- |
| Blocked by any opening whose assembly is IN_PROGRESS or COMPLETED, naming every blocker | That is where the hardware stops being retrievable - it is on a leaf, and some of it may already have been condemned and replaced |
| Staged-but-unassembled openings **do** come back | Their hardware is on a cart in the shop, exactly as retrievable as hardware on the shelf. Restocking only the un-staged part would leave the staged part deducted with no leaf to show for it |
| No partial cancel | `PullStatus` has no cancelled value, and `complete_pull_request` flips *every* opening of a pull to PULLED - so a half-cancelled pull would resurrect its released openings the moment the rest was staged. Expressing it properly needs an opening-level cancelled state |
| Cancellable from IN_PROGRESS, and from COMPLETED for a shop-assembly pull with openings | Since staging is per opening, COMPLETED there means no more than "every cart is built". A completed shipping-out pull has already flipped leaves to SHIP_READY, and a completed PR-REPL pull has already restored expectations |
| How much comes back is how much went out | A fully picked pull returns everything; a short-picked one returns only what was picked; a pull cancelled before its pick returns nothing, because nothing left. Its drafts are discarded with it - a draft is a note about hardware, not a hold on it |
| Restock returns each unit to the **exact `InventoryLocation` it came off**, from the APPLIED `pull_pick_lines` | The picker recorded where each handful came from (§3b), so there is nothing to guess: a bin that gave up twelve hinges gets twelve hinges back, which is what makes a physical recount agree with the system |
| Two fallbacks to the old per-combo return | A pull picked under the pre-#367 model has no pick lines to reverse (the migration's backfill population), and a pick line whose location was deleted since has a null FK. Both land on the project's newest row for the combo - defensible because which row a hinge sits on carries no identity, and conservative for future FIFO |
| Any claim the pull still holds is **released before** the request's is re-created | Since the claim is consumed *as the pick is confirmed*, a pull cancelled before its pick still holds all of it and a short-picked one holds the remainder. Re-creating the request's full need on top of either would double-claim the same units |
| Source request returns to **PENDING**, and its reservation is re-created from what it will need on re-acceptance, availability re-checked after the restock | Re-creating it is a new claim competing with everyone else's. If it cannot be covered, the request is left **unreserved and flagged** via `integrity_note` rather than half-claimed - the same honest-and-flagged shape the #342 backfill uses |
| A PR-REPL replacement pull restocks whatever it picked and re-creates nothing | It has no source request to hand back to. Its own claim is released, spent or not. The leaf's `deficient_quantity` is untouched: the expectation stays on the checklist line and the replacement has to be requested again |

Cancelling keeps the pull row, which is why `pull_requests.request_number` is unique only among
**live** pulls (a partial unique index excluding `CANCELLED`): re-accepting the returned request
mints a fresh pull carrying the same number.

### 4. The tag materializes

The tag does not become physical all at once. Assembly happens over a shift, unit by unit, and since
#340 the system records it that way.

- **Assembly progress** - `shop_assembly_opening_items.installed_quantity` / `deficient_quantity`
  count what the assembler has actually fitted and what has been condemned. This is *work-tracking on
  the tag*, not a materialization: no `OpeningItem` exists yet, nothing has left or entered fungible
  inventory (the hardware was deducted when the pick was confirmed), and the leaf can be handed to
  another assembler without losing a unit of it. The opening sits at `IN_PROGRESS` while this is
  happening. Remaining is `quantity - installed - deficient`, derived, never stored.
- **A unit found defective** goes back the moment it is found, not at completion:
  `report_deficiency_at_assembly` returns it to project inventory flagged deficient and appends a
  PR-REPL replacement pull line carrying the leaf and the source `ShopAssemblyOpeningItem`. That is
  the identity round-trip in miniature - the unit loses its leaf on the way back into inventory, and
  the replacement line is what re-tags a fresh one.

  **One replacement pull per open round of deficiencies**, numbered `PR-REPL-{source pull number}`,
  then `-2`, `-3` on collision (truncating the basis, never the suffix, to stay inside
  `request_number`'s varchar(50)). A flag reuses the existing replacement pull only while it is
  **PENDING**, and merges into that pull's existing line for the same checklist item and product
  rather than stacking one-unit rows. Once the pull has been started it is closed to new lines, and
  the reason is the same rule the rest of this document is about: the pick is where the claim on
  stock is settled. A line appended afterwards was never picked and never deducted, yet
  `_apply_replacement_arrivals` would count it as delivered and `cancel_pull_request` would restock
  it - inventory conjured from a row that had no hardware behind it. The next deficiency therefore
  starts a pull of its own.
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
- **Leaf already SHIPPED_OUT, or staged at the dock as SHIP_READY** - the hardware cannot be fitted.
  A shipped leaf has left the building; a SHIP_READY one has been picked and checked against a
  confirmed pull, and `confirm_shipment` snapshots its hardware onto the `PackingSlipItem`, so a late
  write here would put hardware on a packing slip for a unit that shipped without it. The pending
  state is still recorded in both cases, so the unit stays queryable rather than silently stranded,
  and for the shipped case a `REPLACEMENT_AFTER_SHIPMENT` notification hands it to the reallocation /
  site-shipment world. `install_replacement` refuses both.

**A leaf with anything in `deficient_quantity` or `replacement_pending_quantity` is physically short
of the hardware list it would ship under.** That sum is `OpeningItem.awaiting_replacement_quantity`,
and it is what the shipping wizard flags as "incomplete - awaiting replacement". Shipping it anyway
is allowed and sometimes right - reallocation exists for exactly that - but the shipping-out creation
path refuses a flagged leaf unless the caller passes an explicit acknowledgment. Warn and confirm,
never silent, never a hard block.

### 5. Reading the lifecycle back

Every stage above is written by a different screen, and until #344 it could only be *read* from the
screen that wrote it. A request holds a reservation (§3a), its pull is part-staged (§3c), one leaf is
half-built (§4), another is finished but owed a replacement (§4b) - and answering **"where is opening
A01 leaf 2?"** meant opening four views and joining them by eye.

The pipeline is that join, done once and **derived from the same state**. There is deliberately no
`pipeline_stage` column: a denormalised stage would be a fifth thing that can disagree with the four
above, and this whole slice exists because the four already disagreed on screen.

The ladder is per door leaf, and the stage of a *request* is the stage of its **least-advanced**
opening - what is holding it up, not its best news:

    REQUESTED -> ACCEPTED -> PULLING -> STAGED -> ASSIGNED -> IN_PROGRESS -> COMPLETED -> SHIPPED

`REJECTED` and `CANCELLED` sit off the ladder rather than at the end of it. They are the two ways a
leaf leaves the pipeline unassembled, and reading them as "further along than IN_PROGRESS" would be
nonsense. `CANCELLED` is also how a cancelled pull stays visible at all: cancellation detaches the
openings and returns the request to PENDING (§3d), so without the cancelled pull in view the request
would read as though it had never been accepted.

Two constraints shaped the implementation, both from CLAUDE.md's performance rules:

- **Scalar aggregates only.** Every count is `count`/`sum` with `FILTER`, grouped by request, one
  statement for the whole result set. `get_assembly_pipeline_summaries` runs a fixed **five**
  statements whether it covers one project or all of them; `get_assembly_pipeline` a fixed **eight**
  however many openings a request has. Both numbers are asserted by tests, because a per-row lookup
  here is exactly what an innocent-looking edit reaches for.
- **One implementation per reading.** The request's stage is derived from the aggregates (the list
  needs it on every row); each leaf's stage from its own columns. A test pins them together by
  asserting the first equals the minimum of the second.

The same view is where the flags earlier slices introduced finally meet the eye: the `integrity_note`
from §3a, `deficient + replacement_pending` from §4b as "awaiting replacement", and the
arrived-after-shipping case that `install_replacement` refuses.

### 5a. Being told, rather than looking

Three states slices 1-5 created had nobody watching them, and #344 gave each one a signal:

| Event | Audience | Why it could not be inferred |
| --- | --- | --- |
| Openings became workable - carts staged (§3c), or a pull completed with openings still un-staged | Shop-assembly manager | Per-opening staging made an opening assignable the moment its cart was built; the assignment board only found out when somebody reloaded it |
| A replacement arrived for a leaf that has **not** shipped (§4b) | The assembler holding the leaf | #341 notified only the *shipped* case. The ordinary case - the one somebody can act on - was silent |
| A blocked PR-REPL pull became coverable because a receive landed the stock | Warehouse | A replacement pull holds **no reservation** by design (§3a), so nothing was tracking its demand. The picker confirmed short, the PO backfilled, and nothing said the remainder could now be keyed in |

The staged/completed pair needs no dedupe logic at all, because each call announces only the openings
*it* made workable: staging the last cart calls `complete_pull_request`, which then finds nothing left
to flip and stays silent. The unblocked signal does need one, and it is three rules - only pulls
wanting a combo this receive landed; only when coverage crosses from insufficient to sufficient; and
only one **unread** notification per pull, keyed on `notifications.pull_request_id` rather than on
text inside the message.

## Corollary: LOOSE vs OPENING_ITEM pull lines

Both pull request sources use `pull_request_items`, but the two `item_type` values do fundamentally
different things:

- `LOOSE` - tags fungible inventory onto a leaf for the first time. It is **picked**: the warehouse
  user names a quantity per location and confirming that deducts stock (§3b). Since #342 it is also
  what *reserves* stock when the request is created.
- `OPENING_ITEM` - moves a leaf that was **already tagged** at shop assembly. The hardware left
  fungible inventory when it was installed, so it is **fetched**, not picked: a check-off, no
  quantity, nothing deducted, nothing to reserve.

Confusing the two is issue #335: the Shipping Out import emitted `LOOSE` lines for hardware that had
already been assembled onto a leaf, so the warehouse pull asked general inventory for hardware that
had left it, found zero, and could never be picked. An assembled leaf ships as an `OPENING_ITEM`
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
| Claim consumed at the pick | `backend/app/repositories/warehouse/pull_requests.py` (`confirm_pick` -> `reservations.consume_reservations` then the dictated deduction) |
| Claim released | `shop_assembly_repository.reject_shop_assembly_request` / `shipping_repository.reject_shipping_out_request` (reject only - reopen deliberately holds) |
| Duplicate / cross-type leaf guard | `shop_assembly_repository.find_in_flight_assembly_leaves`, `shipping_repository.find_live_shipping_claims` |
| Re-upload reconciliation | `backend/app/repositories/import_repository.py` (`_handle_schedule_replacement` -> rebuild, auto-reject, `integrity_note`) |
| Tag written, shop assembly | `backend/app/repositories/shop_assembly_repository.py` (`accept_shop_assembly_request`) |
| Tag written, shipping out | `backend/app/repositories/shipping_repository.py` (`accept_shipping_out_request`) |
| Pull opened for picking, nothing moved | `backend/app/repositories/warehouse/pull_requests.py` (`start_pull_request_pick`) |
| Pick sheet, fixed query count | `backend/app/repositories/warehouse/pull_requests.py` (`get_pick_sheet` -> sections, per-location rows, fetch list) |
| Tag consumes stock, per location | `backend/app/repositories/warehouse/pull_requests.py` (`confirm_pick`; two hard ceilings - the row's available units, and what the pull asked for) |
| Where each unit came off, recorded | `backend/app/models/pull_pick_line.py` (`PullPickLine`, DRAFT/APPLIED, `inventory_location_id` ON DELETE SET NULL) |
| Assembled leaf fetched, not picked | `backend/app/repositories/warehouse/pull_requests.py` (`set_pull_item_fetched` -> `pull_request_items.fetched_at` / `fetched_by`) |
| Staging and completion gated on the pick | `backend/app/repositories/warehouse/pull_requests.py` (`_require_picked`, called by `stage_pull_openings` and `complete_pull_request`) |
| Tag staged, opening by opening | `backend/app/repositories/warehouse/pull_requests.py` (`stage_pull_openings` -> one `ShopAssemblyOpening.pull_status`, `staged_at` / `staged_by`; last one calls `complete_pull_request`) |
| PARTIAL derived, never stored | `backend/app/repositories/warehouse/pull_requests.py` (`get_pull_staging_summaries` / `StagingSummary.status`, one grouped aggregate per page) |
| Workability keyed on the opening, not the pull | `backend/app/repositories/shop_assembly_repository.py` (`_APPROVED_PULL_STATUSES` + `pull_status == PULLED` in `get_assemble_list`, `get_my_work`, `assign_openings`, `record_assembly_progress`, `complete_opening`) |
| Tag comes off, stock returned to source rows | `backend/app/repositories/warehouse/pull_requests.py` (`cancel_pull_request` -> `_restock_cancelled_pull`; per-combo `_return_units_to_project_inventory` only as the legacy / null-FK fallback) |
| Claim re-created after a cancel | `backend/app/repositories/warehouse/pull_requests.py` (`cancel_pull_request` -> availability re-check then `create_reservations`, else `integrity_note`) |
| Pull number unique among live pulls only | `backend/app/models/pull_request.py` (`uq_pull_requests_request_number_live`, partial index excluding CANCELLED) |
| Tag worked, incrementally | `backend/app/repositories/shop_assembly_repository.py` (`record_assembly_progress` -> `installed_quantity` / `deficient_quantity`) |
| Deficient unit returned + replaced | `backend/app/repositories/stock/deficiency.py` (`report_deficiency_at_assembly` -> PR-REPL line) |
| Tag materialized | `backend/app/repositories/shop_assembly_repository.py` (`complete_opening` -> `OpeningItem`, quantities = installed) |
| One live assembled unit per leaf | `backend/app/models/opening_item.py` (`uq_opening_items_live_leaf`, partial unique index on `(project, opening, coalesce(leaf,0))` excluding shipped units); `complete_opening` translates the violation into the same `ConflictError` its read-then-write guard raises |
| Replacement pull numbering | `backend/app/repositories/stock/deficiency.py` (`_replacement_number` / `_is_replacement_number`: reuse only a PENDING pull, otherwise mint `PR-REPL-{basis}-{n}`) |
| Replacement arrives, expectation restored | `backend/app/repositories/warehouse/pull_requests.py` (`_apply_replacement_arrivals` -> `deficient_quantity` down, `replacement_pending_quantity` up on a completed leaf) |
| Replacement fitted to a finished leaf | `backend/app/repositories/shop_assembly_repository.py` (`install_replacement` -> `OpeningItemHardware`) |
| Leaf is short of its own list | `backend/app/repositories/shop_assembly_repository.py` (`get_awaiting_replacement_quantities`, one grouped aggregate) |
| Shipping a short leaf takes a decision | `backend/app/repositories/import_repository.py` (`finalize_import_session`, `acknowledge_incomplete_leaves`) |
| Replacement stranded after shipment | `backend/app/repositories/warehouse/pull_requests.py` (`REPLACEMENT_AFTER_SHIPMENT` notification) |
| Tag shipped | `backend/app/repositories/shipping_repository.py` (`confirm_shipment` -> `PackingSlipItem.leaf`) |
| Lifecycle read back, per request | `backend/app/repositories/shop_assembly_repository.py` (`get_assembly_pipeline_summaries`, fixed five statements at any scale) |
| Lifecycle read back, per door leaf | `backend/app/repositories/shop_assembly_repository.py` (`get_assembly_pipeline` + `_opening_stage`, fixed eight statements however many openings) |
| Stage derived, never stored | `backend/app/repositories/shop_assembly_repository.py` (`PIPELINE_STAGE_RANK`, `_opening_stage`, `_request_stage`; `app/schemas/enums.PipelineStage`) |
| Board told there is work | `backend/app/repositories/warehouse/pull_requests.py` (`notify_assembly_work_available`, called with only the openings that call made workable) |
| Assembler told a replacement landed | `backend/app/repositories/warehouse/pull_requests.py` (`_apply_replacement_arrivals` -> `REPLACEMENT_ARRIVED`, addressed to `assigned_to_user_id`) |
| Warehouse told a blocked replacement is coverable | `backend/app/repositories/warehouse/receiving.py` (`notify_unblocked_replacement_pulls` -> `find_pending_replacement_pulls`, structural `sa_opening_item_id` test) |
| Notification dedupe key | `backend/app/models/notification.py` (`pull_request_id` + partial unread index) / `app/services/notification_service.has_unread_notification_for_pull` |
