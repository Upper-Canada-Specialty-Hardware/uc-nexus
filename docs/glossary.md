UC Nexus Glossary

These are the agreed names for this project's concepts. A term written in FULL CAPITALS is ratified; a lowercase label is not a name. Use these terms in conversation, docs, PR text, and issue text. Code identifiers keep their existing names, and each entry ends with the code it maps to. One entry per term, with a hard cap of sixty.

GP Sync

How UC Nexus and Dynamics GP exchange data through the relay.

Traffic types

- MIRRORED GP DATA - GP records that Nexus keeps a copy of on a schedule: jobs and purchase orders. GP is the authority. The copy is overwritten, never compared. Code: gp_job_sync, gp_po_sync
- LIVE GP LOOKUPS - GP data fetched at the moment a form opens or an action runs, and never stored: vendors, buyers, cost codes, customers, customer addresses, employees, tax codes, PO totals, vendor email. Code: the gp_* queries in app/schemas/relay.py
- NEXUS TO GP WRITES - Requests for GP to create or change a record when a person saves something in Nexus: PO REGISTRATION, GP RECEIVE ENTRY, create job, create buyer, add customer address, change job site. Code: relay ops create_po, create_receipt, create_job, create_buyer, create_customer_address, update_job_site
- NEXUS RELAY GP HANDSHAKE - What the relay tells Nexus about itself when it connects: the GP company list with names, its build, and the requests it supports. Code: the hello frame, relay_gateway.note_hello

MIRRORED GP DATA

- GP JOBS SYNC - Every 15 minutes per company, GP's job list is read and a project is created for every job Nexus lacks. Existing projects are left untouched. Code: gp_job_sync
- GP JOB HEALTH CHECK - The per-job check that its cost codes point at accounts the company owns. It is stamped on the project by GP JOBS SYNC and re-run live at PO REGISTRATION. Code: job_setup_health, check_job_setup_live
- FIRST TIME GP COMPANY NEXUS INITIALIZATION - The one-time copy of a company's entire PO history, 25 at a time, resumable after any stop, and allowed only in the OVERNIGHT INITIALIZATION WINDOW. Until it finishes, that company gets no OPEN-POS SYNC. Code: backfill (_run_backfill, backfill_cursor, backfill_done)
- OPEN-POS SYNC - The repeating pass, at least 15 minutes apart per company, that re-copies every PO still open in GP. Code: incremental / open-book walk (_run_incremental, open_only)
- NEW PO CHECK - Every two minutes per company, one page of the POs numbered above the newest one Nexus already holds, so a PO raised in GP appears in the register within minutes instead of after the next full OPEN-POS SYNC. Code: _new_po_check, GP_PO_SYNC_NEW_PO_CHECK_SECONDS
- OPEN-POS RECONCILIATION - The second half of an OPEN-POS SYNC. POs that Nexus still holds open but GP did not list as open are read by number to learn their final state. Code: closure sweep (_sweep_closed, read_pos_by_number, po_numbers_left_open)
- GP-DELETED PO RULE - A PO that GP has no record of, open or finished, is cancelled in Nexus only after two consecutive OPEN-POS SYNCS miss it. It is cancelled the same way as a GP void, and nothing in the UI says it was deleted. Code: note_missing_from_gp, gp_missing_since
- PO STATUS FROM QUANTITIES - A mirrored PO's status comes from its received and cancelled quantities plus which GP table it sits in, never from GP's status code. Nothing received means GP_REGISTERED. Some received means PARTIALLY_RECEIVED. All received, or sitting in GP's finished table, means CLOSED. Everything cancelled means CANCELLED. The status is never written below PARTIALLY_RECEIVED, so VENDOR_CONFIRMED survives. Code: derive_po_stage
- GP-OWNED FIELDS / NEXUS-ONLY FIELDS - The PO fields every OPEN-POS SYNC overwrites from GP (vendor, order date, cost code, shipping, line quantities, unit cost, received amount) versus the fields it never touches (notes, vendor quote number, creator, tariff, request number, the VENDOR_CONFIRMED step, the hardware category and product code on a NEXUS REGISTERED LINE, and the project on a Nexus-registered PO). Code: NEXUS_ONLY_FIELDS
- MIRROR PROGRESS - The saved per-company record of how far the initialization got, whether it finished, and where the current OPEN-POS SYNC is up to. It survives restarts and redeploys. Code: gp_po_sync_state

Protection of GP

- GP READ LIMIT - Everything scheduled may ask GP for at most 100 POs or jobs per minute in total, across all companies, and never more than 25 in one request. Code: gp_load budget, READS_PER_MINUTE, READ_BATCH
- GP CPU PAUSE - Scheduled reads stop when GP's SQL CPU is at or above 40 percent and continue only when it is below 40. The relay applies the same line on its side and refuses scheduled requests. Code: SERVER_CPU_PAUSE_PCT, SERVER_CPU_RESUME_PCT, relay load_ceiling_pct
- OVERNIGHT INITIALIZATION WINDOW - 8pm to 5am Toronto time, the only hours a FIRST TIME GP COMPANY NEXUS INITIALIZATION may run. Nothing else is gated by it. Code: GP_PO_SYNC_BACKFILL_WINDOW, gp_window

NEXUS TO GP WRITES

- PO REGISTRATION - A PO drafted in Nexus is sent to GP. GP assigns the number and books the job cost, and Nexus stores the number. The register shows it as GP-Registered. Code: register_po_in_gp, relay create_po
- GP-PROCESSING - Right after GP confirms a PO REGISTRATION, Nexus reads that one PO back from GP by number and overwrites the GP-OWNED FIELDS from GP's copy, so the PO opens complete instead of half filled until the next sync. The person waits on it in the register dialog and lands on the PO's detail when it is done. A queued registration gets the same read when PENDING GP WRITES drain. Code: run_gp_processing, runGpProcessing, relay read_pos_by_number
- GP RECEIVE ENTRY - The warehouse receives against a PO and Nexus writes the receipt into GP, where it waits in a batch for someone to post inside GP. Code: relay create_receipt
- PENDING GP WRITES - NEXUS TO GP WRITES held while the relay is unreachable, or while GP has not confirmed a PO REGISTRATION in time, and sent automatically when they can be. A write that may already have reached GP is retried only when the relay can recognise it: PO REGISTRATION can, GP RECEIVE ENTRY cannot. Code: gp_outbox

Inventory Value

- INVENTORY VALUE - The admin page and its three figures (OSSA, NON-OSSA, GENERAL STOCK): hardware on the shelves plus hardware staged for shipping plus doors, in dollars, per GP company. Code: inventory_value_repository.get_inventory_value
- DOORS ON HAND - The per-company table of door quantities in the building: one row per project plus one general row. Code: doors_on_hand
- AVERAGE DOOR COST - The single per-company dollar value that every DOORS ON HAND row is multiplied by. Code: inventory_value_settings.average_door_cost
- OSSA - Off Site Storage Agreement, a flag on a project. Code: projects.off_site_storage_agreement

Monitoring

- NEXUS GP TRAFFIC - The dashboard: the relay window tab and the Nexus admin page showing what is crossing between Nexus and GP right now and what has already crossed. Code: route `/app/admin/nexus-gp-traffic`, `NexusGpTrafficPage`, relay tab `traffic`
- GP SYNC STATE - The backend's account of its own sync work: per company, whether the FIRST TIME GP COMPANY NEXUS INITIALIZATION is done or where it is up to, the OPEN-POS SYNC in progress and the last one finished, the last NEW PO CHECK, the last GP JOBS SYNC, plus the GP READ LIMIT balance, whether the GP CPU PAUSE is on, and PENDING GP WRITES counts. One thing served two ways: the `gpSyncState` GraphQL query and the `gp_sync_state` frame pushed to the relay. Code: `app/services/gp_sync_state.py`, `gpSyncState`, frame type `gp_sync_state`
- RELAY TRAFFIC - The relay's own in-memory record of the jobs it is running now and the jobs it has finished since it started. Code: `channel.traffic_snapshot`, relay health block `traffic`

Purchase Orders

- GP PO LINE ITEM - One line on a purchase order in GP: item number, item description, ordered quantity, unit cost, received quantity and job number. On every PO not made by Nexus the item number is a cost bucket and the description is the part number. On a Nexus-made PO the item number is the hardware category and the description is the product code. Nexus's own line record mirrors it by line ordinal. Code: POP10110 / POP30110 row, POLineItem.gp_line_ord; item number = po_line_items.hardware_category, description = po_line_items.product_code, cost code = po_line_items.cost_code
- NEXUS REGISTERED LINE - A GP PO LINE ITEM whose Nexus copy carries the schedule's hardware category and product code, so the OPEN-POS SYNC leaves those two fields alone. A PO is Nexus-registered when every line is a NEXUS REGISTERED LINE. Code: po_line_items.nexus_registered

Tenancy

- GP COMPANY NEXUS TENANT - The separation of everything in Nexus into one tenant per GP company. Every project, PO, request, inventory row, pull and user scope belongs to exactly one GP company, and nothing is read or written across that line. Code: projects.company, auth.tenant_scope, repositories/tenancy.py
