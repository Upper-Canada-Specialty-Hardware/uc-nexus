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

### 4. The tag materializes

- **Shop assembly complete** - the tag becomes physical. An `OpeningItem` row is created per leaf
  (`opening_items.leaf`), with `OpeningItemHardware` recording what was actually installed on it.
  From here the leaf is a real object with its own state and warehouse location.
- **Shipping out complete** - the leaf moves to `SHIP_READY`, then a confirmed shipment writes a
  `PackingSlipItem` that snapshots the leaf permanently.

## Corollary: LOOSE vs OPENING_ITEM pull lines

Both pull request sources use `pull_request_items`, but the two `item_type` values do fundamentally
different things:

- `LOOSE` - tags fungible inventory onto a leaf for the first time. Approving it deducts stock, so it
  is gated on inventory sufficiency.
- `OPENING_ITEM` - moves a leaf that was **already tagged** at shop assembly. The hardware left
  fungible inventory when it was installed. Approving it deducts nothing and locks the `OpeningItem`
  row instead; there is no stock to check.

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
| Tag written, shop assembly | `backend/app/repositories/shop_assembly_repository.py` (`accept_shop_assembly_request`) |
| Tag written, shipping out | `backend/app/repositories/shipping_repository.py` (`accept_shipping_out_request`) |
| Tag consumes stock | `backend/app/repositories/warehouse/pull_requests.py` (`approve_pull_request`, FIFO deduction) |
| Tag materialized | `backend/app/repositories/shop_assembly_repository.py` (`complete_opening` -> `OpeningItem`) |
| Tag shipped | `backend/app/repositories/shipping_repository.py` (`confirm_shipment` -> `PackingSlipItem.leaf`) |
