# Hardware Identity Lifecycle

How a piece of hardware gains, loses, and regains its association with a specific opening. This is
the domain rule the rest of the system is built on, and most of the lifecycle bugs found so far have
been a violation of it.

## The rule

**A pull request is the act of tagging hardware onto an opening.**

Hardware enters the system with an opening identity, loses it in the warehouse, and gets it back
when a request is composed. That is true of both request sources: shop assembly and shipping out.
Neither is a special case.

**The door is a label, not an object.** v1 does not model a door. It models demand attributed to an
opening before receiving, and a text tag on a line after it. Nothing between those two points knows
what a door is - and nothing after a pull completes knows anything at all.

## The three stages

### 1. Identity present: schedule and procurement

The TITAN hardware schedule is written per opening, and per door leaf within an opening. Import
preserves both:

- `openings.leaf_count` - 1 (single) or 2 (pair).
- `hardware_items.opening_id` - which opening needs this item.
- `hardware_items.leaf` - which leaf of that opening, from the `Leaf` attribute on the TITAN
  Material_List (cross-checked against the material id token).

The PO module procures against these rows. A PO line item exists because some opening needs it.

**`leaf` stops here.** It is parsed demand data and nothing downstream carries it: the composer sums
it away, and no line table has a leaf column. It is kept because the schedule says it and a
re-upload has to round-trip faithfully, not because anything acts on it.

### 2. Identity dropped: receiving into inventory

Receiving deliberately throws the opening away. `InventoryLocation` is keyed by
`(project_id, warehouse_id, hardware_category, product_code)` and has **no opening column**. It keeps
only an origin FK (PO line item, stock item, or shipment return item) for costing and audit.

Inventory is fungible: a hinge is a hinge. Hardware received against opening 101's PO can be used on
opening 205. This is intentional, not an oversight. It is also why
[REALLOCATION_MODULE.md](REALLOCATION_MODULE.md) exists: once an opening ships short, the hardware
that could fill the gap is sitting in general inventory with nothing tying it to that opening.

The only surviving identity at this stage is the project.

### 3. Identity restored: the request, then the pull

Composing a shop-assembly or shipping-out request is what re-attaches identity. Each request line,
and each `pull_request_items` row the accept copies it onto, is a tag:

- `opening_number` - which opening the quantity is now committed to, as a **text tag**. Nothing keys
  off it and no row hangs beneath it; the pick sheet groups its carts by it, and that is all.
- `hardware_category` + `product_code` + `requested_quantity` - what is being claimed from fungible
  stock.

Confirming the pull's **pick** deducts that quantity from the `inventory_locations` rows the
warehouse user names (§3b). The physical hardware never changed; what changed is that it now belongs
to an opening.

Both request types are structurally identical - flat lines, an accept gate, one pull - and they are
composed by the same screen off the same query, because the question is the same one.

#### 3a. The composer: what an opening still has coming

The schedule is the only thing that knows what an opening is owed, and it never shrinks when hardware
goes out. Composing off it directly would re-offer everything that had already shipped, every time.

`request_composer.get_request_coverage` answers, per `(opening, category, product)`:

    suggested = max(owed - sent - claimed, 0)

| Term | What it reads |
| --- | --- |
| **owed** | The CURRENT schedule (`HardwareItem`), summed across the opening's leaves |
| **sent** | Hardware that has left. Two exits: a completed SHOP_ASSEMBLY pull, plus shipping out as `max(completed SHIPPING_OUT pull, packing slip)` |
| **claimed** | Lines on PENDING requests, plus lines on live (PENDING/IN_PROGRESS) pulls |

Three properties are worth stating because they are the point rather than accidents:

- **A completed shipping pull and the slip cut from it are one departure, not two.** The slip
  consumes what the pull fulfilled, so summing would charge the opening twice for one shipment;
  taking only the slip would re-offer everything picked and waiting for a truck. `max` folds them.
- **A request is counted once.** While it is PENDING it has no pull, so the request's own lines are
  the claim. Once accepted, the pull carries them and the request is not read - counting both would
  double it. When the pull completes it leaves `claimed` and enters `sent` in the same instant.
- **A lowered schedule reads zero, never negative and never a return.** A re-upload that drops an
  opening below what has already shipped does not auto-unwind anything; a human decides what to do
  about hardware already at site.

There is deliberately **no duplicate-opening guard** on request creation. An opening genuinely may be
owed hardware twice, and what stops anybody raising the second request by accident is the `claimed`
term: it suggests zero rather than refusing.

Availability is deliberately **not** part of this answer. `projectInventoryAvailability` is the single
number the creation gate is applied against (§3b); a second figure computed here at a slightly
different instant is exactly the drift that would let the panel say 3 and the shortfall alert say 2.

#### 3b. The reservation: the tag's claim before the pull

The tag is written when the request is created, but the stock is not deducted until the warehouse
confirms the pick - and that gap used to be a hole. Two requests could each be created against the
same hinges, both pass an accept-time check, and the second pull would then find the shelf empty.

Since #342 **creating a request reserves what it claims.** An `inventory_reservations` row is written
in the same transaction, and availability everywhere becomes

    available = on-hand - deficient - active reservations

A reservation is the claim half of the tag: it says "these units are spoken for by this request"
without yet saying *which* units, which is exactly right for fungible stock. Note what the table
deliberately does not have, for the same reason `InventoryLocation` does not have it:

- **no opening** - a hinge is still a hinge; the reservation is aggregate, per
  `(project, hardware_category, product_code)`;
- **no `inventory_location_id`** - pinning a claim to specific rows would decide something the claim
  has no business deciding. The reservation governs *how much* is free, never *which* row; which row
  is the picker's call at confirm time (§3c).

A request is not all-or-nothing. Each line carries both `quantity` (what it was offered) and
`allocated_quantity` (what the composer could actually claim out of free stock); the reservation and
the pull are built from the allocation, so **the pull asks for exactly what is reserved**. Short is
derived, never stored, and a line with nothing allocated mints no pull line at all.

The lifecycle of that claim, end to end:

| Path | Effect on the claim |
| --- | --- |
| Create a request, either type | **Reserve** the allocated quantity, aggregated per combo |
| Creation would exceed available | **Refused whole** - typed `InventoryShortfallError` naming every short combo. This is a *race* gate, not a shortfall gate: the composer never asks for more than was free when it built its numbers, so a refusal means availability moved underneath it |
| Accept (either type) | **No change** - accept is a pure human gate and re-checks nothing |
| Reject (either type) | **Release** - the request is dead, the hardware goes back to the pool |
| Reopen an accepted request (#325) | **No change** - reopen undoes the *accept*, not the creation; the request returns to PENDING still holding its claim |
| Reject after a reopen | **Release** - the same reject path, and the only thing that finally lets go |
| Starting a pick | **No change** - opening a pull for picking moves nothing (§3c) |
| Pick confirmed, covered | **Consume** - the claim becomes the deduction of the rows the picker named, atomically, under the same row locks |
| Pick confirmed short | **Partial consume** - only what was picked comes off the book; the un-picked remainder stays claimed, so a part-filled request does not hand the rest to whoever asks next |
| Re-upload drops a PENDING request's lines | **Rebuilt** from what survived, which releases exactly what the vanished openings held |
| Re-upload empties a PENDING request | **Auto-reject**, which releases |

**Self-coverage** is the one subtlety worth naming. When request R's claim is being spent, R's own
reservations are precisely what backs the deduction, so any availability check on that path excludes
them (`exclude_reservations_of`). Without the exclusion a request that reserved exactly what it needs
would read as competing with itself and could never be satisfied. Everyone else's claims still count,
and the exclusion decides something at three moments: the creation gate, the pick confirmation (§3c),
and the cancel-time re-check.

Every claim has a request behind it. There is no reservation held by a pull directly - the
replacement pull that used to hold one is gone with the bench (§4).

#### 3c. The pick: which units, chosen by the person who can see them

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
product_code, inventory_location_id, quantity, state)`. It is the one place a location and an
opening's hardware are recorded together, and it is not a violation of the rule at the top of this
document - it is *history* ("these units came off that bin"), not identity ("this bin belongs to that
opening"). The FK is `ON DELETE SET NULL`, so a location merged or deleted later degrades the row to
"came from somewhere that no longer exists" rather than blocking the delete.

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

**The third ceiling is what keeps §3b intact.** Without it a pull holding no claim of its own - one
whose source request was rejected after the accept, or a legacy pull - could walk off with stock
another request had already been promised, and that request would discover the loss as a short pick
on its own pull. A claim that holds only until somebody physically reaches the shelf first is not a
claim.

It has a real cost: a picker can be refused with hardware in their hand, which the per-row Available
column cannot explain. Two things make that survivable. The refusal is a `CONFLICT` naming the combo
and how much is claimable, so it is actionable rather than mysterious; and the same number rides on
the sheet as `PickSheetSection.claimable_quantity`, on screen and in print, so contention is visible
*before* the walk rather than after it.

Every line is picked by quantity. There is no second line type and nothing is fetched off a rack:
the assembled unit that used to be collected that way does not exist.

#### 3d. Cancelling a pull: the tag comes off

Once a pull was started there was no way back - stock was deducted and `PullRequestStatus.CANCELLED`
was an enum value nothing ever set. `cancel_pull_request` is the way back:

| Rule | Why |
| --- | --- |
| Cancellable from IN_PROGRESS only | A completed pull has handed its hardware over - to the bench or to a shipping desk - and v1 does not follow it past that point, so there is nothing left to reverse |
| How much comes back is how much went out | A fully picked pull returns everything; a short-picked one returns only what was picked; a pull cancelled before its pick returns nothing, because nothing left. Its drafts are discarded with it - a draft is a note about hardware, not a hold on it |
| Restock returns each unit to the **exact `InventoryLocation` it came off**, from the APPLIED `pull_pick_lines` | The picker recorded where each handful came from (§3c), so there is nothing to guess: a bin that gave up twelve hinges gets twelve hinges back, which is what makes a physical recount agree with the system |
| Two fallbacks to the old per-combo return | A pull picked under the pre-#367 model has no pick lines to reverse (the migration's backfill population), and a pick line whose location was deleted since has a null FK. Both land on the project's newest row for the combo - defensible because which row a hinge sits on carries no identity, and conservative for future FIFO |
| Any claim the pull still holds is **released before** the request's is re-created | Since the claim is consumed *as the pick is confirmed*, a pull cancelled before its pick still holds all of it and a short-picked one holds the remainder. Re-creating the request's full need on top of either would double-claim the same units |
| Source request returns to **PENDING** with `pull_request_id` cleared, and its reservation is re-created from what it will need on re-acceptance, availability re-checked after the restock | Re-creating it is a new claim competing with everyone else's. If it cannot be covered, the request is left **unreserved and flagged** via `integrity_note` rather than half-claimed - the same honest-and-flagged shape the #342 backfill uses |

Cancelling keeps the pull row, which is why `pull_requests.request_number` is unique only among
**live** pulls (a partial unique index excluding `CANCELLED`): re-accepting the returned request
mints a fresh pull carrying the same number.

### 4. The exit: where the system stops looking

A completed pull is where v1 stops following the hardware. There are exactly two exits and they are
the same event seen from two sides:

- **Shop assembly** - the completed pull is terminal. The shop takes its cart to the bench, and what
  happens there is untracked. No assembled unit is materialized, no per-leaf progress is recorded,
  and "which doors can we build / ship / are complete" is not answerable in v1. That is the v2
  boundary, stated as a boundary rather than approximated.
- **Shipping out** - the completed pull stages the hardware, and `confirm_shipment` cuts the packing
  slip against that staged pool. The slip is the permanent record of what left; from there the
  Delivery Request lifecycle (SCHEDULED -> PICKED_UP -> DELIVERED) documents the truck's journey and
  moves no inventory.

Both feed the composer's `sent` term (§3a), which is the only way an exit is ever read back.

**Deficiency is stock-level only.** A unit found defective is flagged on the inventory location or
stock item it sits on, and resolved through destock / deficient swap / overage. There is no
auto-minted replacement pull and no `PR-REPL` numbering: a replacement is an ordinary new request
line, composed like any other, and the composer offers it because the deficient units never counted
as `sent`.

### 5. Reading the lifecycle back

Every stage above is written by a different screen. What a reader wants is one answer, and there are
two of them:

- **Where is this request?** `REQUESTED -> ACCEPTED -> PULLING -> DONE`, with `REJECTED` off the
  ladder rather than at the end of it. Derived from the request's own status and the state of the
  pull it minted - there is deliberately no `stage` column, because a denormalised copy is a fifth
  thing that can disagree with the four facts it is derived from. `get_request_stages` resolves it in
  one query for a whole page (CLAUDE.md perf rules); the requests list draws it as columns.
- **What does this opening still have coming?** The composer (§3a), which is the only place the
  question is answered and is read by both wizards.

## Where this is enforced in code

| Stage | Code |
| --- | --- |
| Leaf parsed from TITAN | `frontend/src/workers/parserLogic.ts` (`leafFromMaterialId`, ML-level `Leaf` attribute) |
| Identity dropped | `backend/app/models/inventory.py` (`InventoryLocation`, no opening column) |
| What an opening still has coming | `backend/app/repositories/request_composer.py` (`get_request_coverage`; owed / sent / claimed, fixed eight statements at any scale) |
| The offer turned into lines | `frontend/src/modules/import/composer.ts` (`composableRows`, `autoAllocate`, `buildRequestLines`) |
| Claim written at creation | `backend/app/repositories/shop_assembly_repository.py` (`create_shop_assembly_request`) / `shipping_requests.create_shipping_out_requests` |
| Claim modelled | `backend/app/models/inventory_reservation.py` (aggregate; no opening, no location; exactly one request FK) |
| Availability arithmetic | `backend/app/repositories/warehouse/reservations.py` (`get_reserved_quantities`, `get_project_availability`, grouped aggregates) |
| Claim respected / self-covered | `backend/app/repositories/warehouse/pull_requests.py` (`check_inventory_sufficiency`, `reservation_aware` + `exclude_reservations_of`) |
| Claim consumed at the pick | `backend/app/repositories/warehouse/pull_requests.py` (`confirm_pick` -> `reservations.consume_reservations` then the dictated deduction) |
| Claim released | `shop_assembly_repository.reject_shop_assembly_request` / `shipping_repository.reject_shipping_out_request` (reject only - reopen deliberately holds) |
| Re-upload reconciliation | `backend/app/repositories/import_repository.py` (`_handle_schedule_replacement` -> rebuild, auto-reject, `integrity_note`) |
| Tag written, shop assembly | `backend/app/repositories/shop_assembly_repository.py` (`accept_shop_assembly_request`) |
| Tag written, shipping out | `backend/app/repositories/shipping_repository.py` (`accept_shipping_out_request`) |
| Pull opened for picking, nothing moved | `backend/app/repositories/warehouse/pull_requests.py` (`start_pull_request_pick`) |
| Pick sheet, fixed query count | `backend/app/repositories/warehouse/pull_requests.py` (`get_pick_sheet` -> sections, per-location rows, openings owed) |
| Tag consumes stock, per location | `backend/app/repositories/warehouse/pull_requests.py` (`confirm_pick`; three hard ceilings) |
| Where each unit came off, recorded | `backend/app/models/pull_pick_line.py` (`PullPickLine`, DRAFT/APPLIED, `inventory_location_id` ON DELETE SET NULL) |
| Completion gated on the pick | `backend/app/repositories/warehouse/pull_requests.py` (`_require_picked`, called by `complete_pull_request`) |
| The terminal exit | `backend/app/repositories/warehouse/pull_requests.py` (`complete_pull_request`; no source-specific side effects) |
| Tag comes off, stock returned to source rows | `backend/app/repositories/warehouse/pull_requests.py` (`cancel_pull_request` -> `_restock_cancelled_pull`; per-combo `_return_units_to_project_inventory` only as the legacy / null-FK fallback) |
| Claim re-created after a cancel | `backend/app/repositories/warehouse/pull_requests.py` (`cancel_pull_request` -> availability re-check then `create_reservations`, else `integrity_note`) |
| Pull number unique among live pulls only | `backend/app/models/pull_request.py` (`uq_pull_requests_request_number_live`, partial index excluding CANCELLED) |
| Deficiency, stock level only | `backend/app/repositories/stock/deficiency.py` (`report_inventory_deficiency`, `report_stock_deficiency`, `resolve_deficiency`) |
| Tag shipped | `backend/app/repositories/shipping_repository.py` (`confirm_shipment` -> `PackingSlipItem`) |
| Request stage derived, never stored | `backend/app/repositories/shop_assembly_repository.py` (`get_request_stages`, one query per page; `app/schemas/enums.RequestStage`) |
| Notification dedupe key | `backend/app/models/notification.py` (`pull_request_id` + partial unread index) / `app/services/notification_service.has_unread_notification_for_pull` |
