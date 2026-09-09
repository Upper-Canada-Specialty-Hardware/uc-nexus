uc nexus glossary

the agreed names for this project's concepts. a term written in FULL CAPITALS is ratified; a lowercase label is not a name. use these terms in conversation, docs, PR text and issue text. code identifiers keep their existing names; each entry ends with the code it maps to. one entry per term, hard cap of sixty.

gp sync

how UC Nexus and Dynamics GP exchange data through the relay.

traffic types

- MIRRORED GP DATA - GP records Nexus keeps a copy of on a schedule: jobs and purchase orders. GP is the authority. the copy is overwritten, never compared. code: gp_job_sync, gp_po_sync
- LIVE GP LOOKUPS - GP data fetched at the moment a form opens or an action runs, never stored: vendors, buyers, cost codes, customers, customer addresses, employees, tax codes, PO totals, vendor email. code: the gp_* queries in app/schemas/relay.py
- NEXUS TO GP WRITES - requests for GP to create or change a record when a person saves something in Nexus: PO REGISTRATION, GP RECEIVE ENTRY, create job, create buyer, add customer address, change job site. code: relay ops create_po, create_receipt, create_job, create_buyer, create_customer_address, update_job_site
- NEXUS RELAY GP HANDSHAKE - what the relay tells Nexus about itself when it connects: the GP company list with names, its build, and the requests it supports. code: the hello frame, relay_gateway.note_hello

MIRRORED GP DATA

- GP JOBS SYNC - every 15 minutes per company, GP's job list is read and a project is created for every job Nexus lacks. existing projects are left untouched. code: gp_job_sync
- GP JOB HEALTH CHECK - the per-job check that its cost codes point at accounts the company owns, stamped on the project by GP JOBS SYNC and re-run live at PO REGISTRATION. code: job_setup_health, check_job_setup_live
- FIRST TIME GP COMPANY NEXUS INITIALIZATION - the one-time copy of a company's entire PO history, 25 at a time, resumable after any stop, allowed only in the OVERNIGHT INITIALIZATION WINDOW. until it finishes, that company gets no OPEN-POS SYNC. code: backfill (_run_backfill, backfill_cursor, backfill_done)
- OPEN-POS SYNC - the repeating pass, at least 15 minutes apart per company, that re-copies every PO still open in GP. code: incremental / open-book walk (_run_incremental, open_only)
- OPEN-POS RECONCILIATION - the second half of an OPEN-POS SYNC: POs Nexus still holds open that GP did not list as open are read by number to learn their final state. code: closure sweep (_sweep_closed, read_pos_by_number, po_numbers_left_open)
- GP-DELETED PO RULE - a PO GP has no record of, open or finished, is cancelled in Nexus only after two consecutive OPEN-POS SYNCS miss it. it is cancelled the same way as a GP void; nothing in the UI says it was deleted. code: note_missing_from_gp, gp_missing_since
- PO STATUS FROM QUANTITIES - a mirrored PO's status comes from received and cancelled quantities plus which GP table it sits in, never from GP's status code. nothing received: GP_REGISTERED. some: PARTIALLY_RECEIVED. all, or in GP's finished table: CLOSED. everything cancelled: CANCELLED. never written below PARTIALLY_RECEIVED, so VENDOR_CONFIRMED survives. code: derive_po_stage
- GP-OWNED FIELDS / NEXUS-ONLY FIELDS - the PO fields every OPEN-POS SYNC overwrites from GP (vendor, order date, line quantities, unit cost, received amount) versus the fields it never touches (notes, vendor quote number, cost code, creator, shipping, tariff, request number, the VENDOR_CONFIRMED step, and the project on a Nexus-registered PO). code: NEXUS_ONLY_FIELDS
- MIRROR PROGRESS - the saved per-company record of how far the initialization got, whether it finished, and where the current OPEN-POS SYNC is up to. survives restarts and redeploys. code: gp_po_sync_state

protection of GP

- GP READ LIMIT - everything scheduled may ask GP for at most 100 POs or jobs per minute in total, across all companies, and never more than 25 in one request. code: gp_load budget, READS_PER_MINUTE, READ_BATCH
- GP CPU PAUSE - scheduled reads stop when GP's SQL CPU is at or above 40 percent and continue only when below 40. the relay applies the same line on its side and refuses scheduled requests. code: SERVER_CPU_PAUSE_PCT, SERVER_CPU_RESUME_PCT, relay load_ceiling_pct
- OVERNIGHT INITIALIZATION WINDOW - 8pm to 5am Toronto time, the only hours a FIRST TIME GP COMPANY NEXUS INITIALIZATION may run. nothing else is gated by it. code: GP_PO_SYNC_BACKFILL_WINDOW, gp_window

NEXUS TO GP WRITES

- PO REGISTRATION - a PO drafted in Nexus is sent to GP, GP assigns the number and books the job cost, Nexus stores the number. the register shows it as GP-Registered. code: register_po_in_gp, relay create_po
- GP RECEIVE ENTRY - the warehouse receives against a PO and Nexus writes the receipt into GP, where it waits in a batch for someone to post inside GP. code: relay create_receipt
- PENDING GP WRITES - NEXUS TO GP WRITES held while the relay is unreachable and sent automatically when it returns. a write that may already have reached GP is never retried blindly. code: gp_outbox

inventory value

- INVENTORY VALUE - the admin page and its three figures (OSSA, NON-OSSA, GENERAL STOCK): hardware on the shelves plus hardware staged for shipping plus doors, in dollars, per GP company. code: inventory_value_repository.get_inventory_value
- DOORS ON HAND - the per-company table of door quantities in the building: one row per project plus one general row. code: doors_on_hand
- AVERAGE DOOR COST - the single per-company dollar value every DOORS ON HAND row is multiplied by. code: inventory_value_settings.average_door_cost
- OSSA - Off Site Storage Agreement; a flag on a project. code: projects.off_site_storage_agreement
