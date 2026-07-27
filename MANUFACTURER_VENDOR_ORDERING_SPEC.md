manufacturer + vendor ordering (issue #228) - implementation spec

TITAN hardware schedules carry a manufacturer name per product. PO users order hardware from the manufacturer (buy direct) or a distributor/vendor.

ground truth (read-only TUBC exploration, full findings on #228)
- GP has no separate populated manufacturer entity. every orderable party is a vendor in PM00200.
- Allegion, ASSA ABLOY, Dormakaba exist in PM00200 as vendors, indistinguishable by class from distributors.
- a GP PO is cut to exactly one VENDORID. order-from-manufacturer vs order-from-vendor = same taPoHdr/taPoLine flow, different VENDORID.
- TITAN manufacturer name maps to GP only as a fuzzy match against PM00200 vendor names, only when that manufacturer is set up as a vendor. not exact (case, "INC.", ASSA ABLOY = 2 records, DORMAKABA = 2 records). manufacturers with no vendor record can't be matched.
- Nexus PO carries one gp_vendor_id + name snapshot.
- vendor list fetched live from relay /vendors (PM00200).
- vendor mirror dropped in migration 040.
- current parser drops TITAN manufacturer.
- HardwareItem stores vendor_no, no manufacturer field.
- eConnect public API can't set per-line manufacturer. taPoLine has 71 params, none for manufacturer. POP10140 (native per-line Manufacturer field) has only internal zDP_POP10140 helpers, no public taXxx entity proc.

locked decisions
1. capture TITAN manufacturer + use it to suggest/auto-pick the ordering vendor, user override.
2. write manufacturer into GP too.

open decision, settle before write-back phase

POP10140 (GP native per-line Manufacturer) is not writable through the sanctioned eConnect entity API. pick one:
- A. taPoLine @I_vUSRDEFND1 (char 50). no new proc. does NOT populate GP native manufacturer window. recommended default.
- B. taPoLine line comment @I_vCMMTTEXT (varchar 500). prints on the PO.
- C. call internal zDP_POP10140SI directly to populate native POP10140. conflicts with eConnect-only rule. needs explicit sign-off.
- D. Nexus-only, no GP write.

ship phases 1-2 first, settle A vs B vs C for phase 3. default A unless purchasing needs it on the printed PO (then B or A+B), or the native field is a hard requirement (then C, with sign-off).

part 1 - capture manufacturer from TITAN
- parser (frontend/src/workers/parserLogic.ts, extractHardwareItems) reads manufacturer from Material_List_Fields alongside Vendor_No, adds to ParsedHardwareItem.
  - confirm the XML element name against a real TITAN export. legacy UC Connects stored it as column "MFG" / property Manufacturer. test fixtures don't include it. likely mlf.Manufacturer or mlf.MFG.
- add manufacturer (String, nullable) to HardwareItem (backend/app/models/hardware.py) next to vendor_no.
- migration adds hardware_items.manufacturer (nullable, no backfill).
- import path persists manufacturer from parsed items (same path that persists vendor_no).
- GraphQL exposes HardwareItem.manufacturer on the type, adds it to the import input.

part 2 - manufacturer -> vendor suggestion (learned mapping + fuzzy fallback)
- new table manufacturer_vendor_map holds:
  - id
  - gp_company
  - manufacturer_key (normalized)
  - manufacturer_label (as seen)
  - gp_vendor_id (char 15)
  - gp_vendor_name (snapshot)
  - source (confirmed | imported)
  - created_at
  - updated_at
- unique (gp_company, manufacturer_key). one preferred vendor per manufacturer per company, user override at PO time updates it. multi-candidate mapping later if needed.
- normalize TITAN manufacturer + GP vendor name (both mapping key + fuzzy match):
  - uppercase
  - collapse whitespace
  - strip punctuation
  - strip trailing legal suffixes (INC, LTD, LTEE, CORP, CO, "OF CANADA", "CANADA")
- resolver suggestVendorForManufacturer(gpCompany, manufacturer):
  1. mapping-table hit on (company, normalized) -> return that gp_vendor as pre-selected suggestion (high confidence).
  2. else fuzzy-match normalized manufacturer against live PM00200 list (relay /vendors) -> return top N ranked candidates with scores.
  3. return { savedMapping: bool, candidates: [...] }.
- dependency rapidfuzz (backend) for token_set_ratio scoring, or hand-rolled ratio for no new dep.
- on PO create/register, upsert (company, manufacturer_key) -> chosen gp_vendor_id, source=confirmed.

part 3 - PO creation UX
- PO items share a manufacturer -> pre-select suggested vendor, label it ("suggested: manufacturer = X"). show fuzzy alternatives. user accepts or overrides with any vendor from the live list.
- selected items span manufacturers mapping to different vendors -> warn, require explicit vendor pick. don't silently pick one.
- manufacturer with no GP vendor record -> suggestion empty, user picks manually, soft note ("manufacturer not set up as a GP vendor").
- on confirm, persist the mapping (part 2 learn step).

part 4 - GP write-back (relay), default A
- add manufacturer (str | None, max 50) to relay models.POLine.
- relay econnect.create_po_line adds @I_vUSRDEFND1 = ? (RTRIM + truncate to 50).
- backend _prepare_create_po / _prepare_register_po include per-line manufacturer in the relay payload, derived from each line's hardware item.
- tests for the new param.
- confirm @I_vUSRDEFND1 at this customer is free + not read/printed anywhere before phase 3.
- B instead -> write @I_vCMMTTEXT and/or @I_vCOMMENT_1.
- C -> separate spike, validate zDP_POP10140SI against TUBC with sign-off, isolated from the proven taPoLine path.

sequencing
1. phase 1 - capture manufacturer (parser + model + migration + import + display). independent, shippable alone.
2. phase 2 - mapping table + suggestion query + PO UI suggestion/override + learn-on-confirm.
3. phase 3 - GP write-back, after A/B/C settled.

simulated user testing

Chrome DevTools MCP against Railway, after each phase deploys.

phase 1
- navigate to import module URL, import a hardware schedule containing manufacturers.
- verify each hardware item shows its manufacturer (list/detail view).
- verify an item whose product had no manufacturer shows blank, not an error.

phase 2
- navigate to the PO creation flow for a project with Allegion items.
- verify the vendor picker pre-selects the suggested vendor (mapping hit or top fuzzy candidate) and labels why.
- override to a different vendor, confirm the PO.
- start a second PO for another Allegion project, verify it now auto-picks the vendor learned from the override.
- select items spanning two manufacturers that map to different vendors, verify the mixed-manufacturer warning and that an explicit pick is required.
- select an item whose manufacturer is not a GP vendor, verify the empty-suggestion soft note.

phase 3
- create a PO through the relay, verify the GP PO line carries the manufacturer in the chosen field (read back via the relay PO read, or check TUBC POP10110 USRDEFND1 for option A / POP10140 for option C).
