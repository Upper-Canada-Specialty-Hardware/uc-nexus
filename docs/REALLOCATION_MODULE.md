# Reallocation Module

## Problem

Inventory in UC Nexus is **fungible** — hardware items entering the warehouse are not dedicated to a specific opening. A hinge is a hinge, regardless of which opening's purchase order originally brought it in.

This creates a gap when openings ship out partially assembled. In urgent situations, the business will ship an opening to the job site with only some of its hardware installed, expecting field crews to install the rest on-site. The missing hardware may still be on order or may have arrived in the warehouse after the opening already went through shop assembly and shipped out.

Currently, there is no way to:
- Review what hardware is missing from shipped openings
- Allocate warehouse inventory to fulfill those shortfalls
- Track and ship the remaining items to the job site

## How Openings Ship Partially

A typical partial-shipment scenario:

1. Opening 101 needs 10 hardware items per the hardware schedule
2. A SAR is created — only 6 items are available (RECEIVED) in the warehouse
3. Shop assembly completes with 6 items → OpeningItem created
4. Timeline pressure forces the opening to ship immediately with 6 of 10 items
5. 2 more items arrive at the warehouse later (into general, fungible inventory)
6. 2 items are still on order

At this point, Opening 101 is at the job site missing 4 items. 2 of those items are sitting in the warehouse but have no association to Opening 101 — they're just inventory.

## Reallocation Module Concept

### Purpose

Allow users to review shipped openings, identify hardware shortfalls, and claim items from warehouse inventory to fulfill those gaps.

### Workflow

1. **Select Project** — User chooses a project to review
2. **Import Hardware Schedule** — User uploads the TITAN XML to define what each opening needs (the schedule is the source of truth for opening requirements)
3. **Review Shipped Openings** — For each Opening with SHIPPED_OUT status, show:
   - What hardware was shipped with it (from OpeningItemHardware records)
   - What the hardware schedule says the opening needs
   - The shortfall (needed minus shipped)
4. **Allocate from Inventory** — For each shortfall item, the user can claim available inventory:
   - Show what's currently in warehouse inventory (RECEIVED items, not already allocated)
   - User selects quantities to allocate to the shipped opening
   - Allocated items are "claimed" — reserved for that opening
5. **Ship Allocated Items** — Claimed items flow into a shipping workflow to be sent to the job site as loose hardware (not as an assembled opening)

### Key Principles

- **Hardware schedule is the source of truth** — The schedule defines what an opening needs. Without it, the system cannot compute shortfalls.
- **Inventory is fungible** — Any item of the right product code can fulfill any opening's shortfall, regardless of which PO originally brought it in.
- **Partial fulfillment is normal** — An opening may ship with 60% of its hardware today and get the rest over multiple shipments as items arrive.
- **Not urgent** — Everything in the warehouse is paid for by the client regardless. The reallocation module is about tracking and logistics, not financial exposure.

## Integration with Existing System

### Data Sources

| Existing Entity | How Reallocation Uses It |
|---|---|
| **OpeningItem** (state: SHIPPED_OUT) | Identifies which openings have shipped |
| **OpeningItemHardware** | Shows what hardware was included when the opening shipped |
| **Hardware Schedule XML** | Defines what each opening needs — used to compute shortfalls |
| **Warehouse Inventory** (HardwareItems with RECEIVED PO status, not yet pulled) | Pool of available items to allocate |
| **Project / Opening** | Scoping — reallocation operates per project |

### New Entities Needed

- **Reallocation** or **AllocationClaim** — Links a quantity of a product code from inventory to a specific shipped opening's shortfall
- Possible states: CLAIMED → SHIPPING → SHIPPED_TO_SITE

### Relationship to Existing Modules

- **Import Module**: Reallocation reuses the same TITAN XML parser to understand opening requirements. The hardware schedule import step is shared.
- **Warehouse Module**: Reallocation reads warehouse inventory to show what's available. Claimed items would need to be visible in the warehouse as "allocated" so they aren't double-claimed.
- **Shipping Module**: Allocated items eventually need to ship. This could create Shipping Out pull requests for loose hardware, integrating with the existing shipping PR workflow.
- **Shop Assembly Module**: Not directly involved. If an opening hasn't shipped yet and more items arrive, a new SAR can be created through the normal import flow. Reallocation only applies to already-shipped openings.
- **Reconciliation Step (Import Wizard)**: Independent. Reconciliation is pre-shipment state visibility. Reallocation is post-shipment gap-filling. They should not be conflated.
