# Product

## Register

product

## Users

Internal UCSH (Upper Canada Specialty Hardware) staff run UC Nexus across the full door-hardware fulfillment lifecycle. Distinct roles live in distinct modules:

- Purchasing / buyers: import hardware schedules from TITAN, create and register POs (pushed into Great Plains via a local relay), generate supplier PO documents.
- Warehouse staff: receive POs, put away and stock inventory, manage bin/locations, work pull requests.
- Shop assembly staff: assemble hardware for openings against pull requests.
- Shipping staff: ship completed work out to job sites.

Context is a mix of desk and warehouse floor, on desktop screens, usually working through long lists of openings, line items, and inventory under time pressure. The job to be done: move every hardware item accurately through each stage with full traceability, minimal clicks, and nothing lost.

## Product Purpose

UC Nexus tracks door installation hardware from a TITAN hardware-schedule import through purchase orders, warehouse receiving, shop assembly, and shipping out. It is the system of record tying schedules, POs (kept in sync with Great Plains / GP through a local relay), inventory, and shipments together. Success looks like: every hardware item is accounted for at every stage, each role completes its step fast without fighting the UI, and the data stays consistent with GP.

## Brand Personality

Efficient, precise, industrial. The voice is direct and unembellished - it states status and lets the operator act. The interface should feel like a dependable shop tool: fast, dense with the right information, quietly confident, never decorative. The emotional goal is trust - the operator believes the numbers and never has to wonder where something is.

## Anti-references

- Consumer / playful SaaS: no rounded-everything, no colorful marketing gloss, no oversized empty hero sections.
- Sprawly, wasted space: no short values stretched across empty columns, no panel sprawling vertically while starved horizontally. Every region must earn its space.
- Legacy enterprise clutter: not gray-on-gray, cramped, inconsistent old-ERP density with no hierarchy.
- Flashy / heavy motion: no gradients-as-decoration, no bouncy or attention-grabbing animation that slows real work.

## Design Principles

1. Space earns its keep. Every region is sized to its content and one flexible element absorbs the slack; if a region renders mostly empty, the layout is wrong. This is the highest-priority value in this product.
2. Information before ornament. Show the operator the status, number, or next action first. Decoration never competes with data.
3. Fast for daily hands. Optimize the common path - fewest clicks, keyboard-reachable, predictable. These are people repeating the same task dozens of times a day.
4. Trustworthy state. The screen always reflects true system state, including GP sync and relay connectivity. Never imply done when it is not; surface errors and connection state honestly.
5. Consistency across the lifecycle. Import, PO, warehouse, shop, and shipping share the same nouns, verbs, and interaction shapes - a modal in one module behaves like a modal in another.

## Accessibility & Inclusion

WCAG 2.1 AA. Body text at least 4.5:1 contrast and large text at least 3:1, full keyboard navigation across tables, modals, and forms, visible focus indicators, and respect for prefers-reduced-motion (motion is minimal by design). Must hold in both the app's light and dark themes.
