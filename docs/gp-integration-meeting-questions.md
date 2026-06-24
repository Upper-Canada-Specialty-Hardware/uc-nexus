# Meeting prep: questions for the legacy GP-integration developer

## Why this meeting matters

UC Nexus needs to create purchase orders (POs) in Dynamics GP — the company's accounting/ERP system — and get back the PO number GP assigns. We've planned to do this via **eConnect**, which is Microsoft's official programmatic interface to GP (a set of SQL stored procedures that any application can call).

Through extensive read-only investigation of the GP database server, we've answered most technical questions ourselves. The remaining open questions need a **human who knows the business** — what the company is trying to do, why certain databases exist, how things were intended to work. The legacy GP-integration developer is the best person to answer these.

This document explains each question we plan to ask, the context behind it, and what the answer will let UC Nexus decide.

Companion documents:
- `gp-integration-briefing.md` — the full plain-English picture of the systems involved
- `gp-customizations-discovery.md` — read-only findings about customizations at this site

---

## What we've already answered ourselves (don't ask)

To respect the developer's time, here's what we've verified by reading the SQL Server directly. Skip these.

**About eConnect and stock GP behavior:**
- All the PO-related eConnect procedures (`taPoHdr`, `taPoLine`, `taGetPONextNumber`, etc.) are installed and our login can execute them.
- The full parameter set, error codes, and transaction semantics for stock eConnect are publicly documented by Microsoft.

**About customizations at this site:**
- The four eConnect customization hooks (`taPoHdrPre`, `taPoHdrPost`, `taPoLinePre`, `taPoLinePost`) are **stock empty**. We read the source. No custom validation runs. Microsoft's documented behavior applies verbatim.
- The custom database triggers on PO tables fire only on DELETE or UPDATE-with-cancel. **No trigger fires when a new PO line is created.** UC Nexus eConnect inserts will run through stock GP code paths with no interference.

**About WennSoft (the third-party service-business add-on installed on this server):**
- The WennSoft Service Management module is **installed but completely dormant**. We verified: zero service calls in `SVC00200`, zero work orders in `SVC06100`, zero contracts in `SV00300`, zero setup rows in `SVC00998`, and zero of the customer's 6,521 PO lines are linked to any WennSoft service call, work order, or RTV. The custom triggers we found would short-circuit even if WennSoft had INSERT triggers, because they all start with `if not exists(select * from SVC00998) return`.
- Only the WennSoft *Products* dictionary is active — it customizes the appearance of GP's PO Entry form (the visible UI), not the underlying data model.

**About the custom PMUBC database (the company's custom data store next to GP):**
- It contains ~40 tables. We've sampled row counts on every one. The actively-used parts are:
  - `UTPMMAINAWPROJ101` (45 rows) and `UTPMAWCONTRACTS101` (45 rows) — the project/job master
  - `UTPMBIDPROJ101` (85 rows) — the pre-award bid pipeline
  - `PMCHANGEHEADER101` / `PMCHANGELINE101` (29 / 254 rows) — change orders
  - `WHRECLINE101` (5,862 rows) — warehouse receipts (the largest, most-used table)
- Empty (zero rows) — i.e., either dormant features or data living elsewhere: `POUCSHHEADERCOMMENT101`, `POUCSHLINECOMMENT101`, `SOPPOPLINK101`, `HMSHOPDRAW101`, `PMSUBMITTAL*`, `PMREQUESTFORINFOS`, `PMPROGRESSBILL*`, `WHSHIP*`, `WHRECEIPTDEFICIENCY101`, and others.
- Job numbers used in POs (`POP10110.JOBNUMBR='22713'` etc.) match rows in `UTPMMAINAWPROJ101` — confirming that PMUBC is the job-master, not GP.
- There are no stored procedures or triggers in PMUBC at all — it's a pure data store for some external application that does its logic in its own code.

**About local data conventions (sampled from real production POs):**
- PO numbers always use the `'PO'` prefix from `POP40100.PO_Code`. UC Nexus should call `taGetPONextNumber` to get the next number, not invent its own format.
- Buyers are free-text human names ("Steve Faith", "Greg Sutton", etc.). No buyer-master enforcement.
- 100% of UBC POs are at the `VANCOUVER` location. 97% are CAD, 3% USD.
- **Strict invariant**: Product_Indicator=2 (Job Cost) lines ALL have a JOBNUMBR populated; Product_Indicator=1 (Non-Inventoried) lines ALL have empty JOBNUMBR. 6,521 lines, zero exceptions.
- Cost codes follow a three-segment `phase-step-type` format like `210-200-2`.
- Zero of 1,965 production POs are on hold — no auto-hold rules active.

**About authentication:**
- The current Windows account has full read/write access to all GP data through `DYNGRP` role membership inherited from an AD group. That's all the integration needs. Service-account provisioning for UC Nexus production is a DBA topic, not a developer topic.

---

## The open questions

Each question below comes with the context behind it: what we know, what we still need to know, and what the answer will let us decide.

---

### Section 1: The PMUBC custom application

The `PMUBC` database holds the customer's job-master, change orders, and warehouse receipts — and it's not part of stock GP. Some application is reading and writing to it from outside the database. UC Nexus needs to understand its place in the ecosystem before deciding how to coexist with it.

---

#### Q1. What application owns the `PMUBC` / `PMUCSH` databases?

**Context.** `PMUBC` has ~40 tables but no stored procedures or triggers. That pattern means an external application — running outside SQL Server — does all the logic and uses these databases purely as a data store. The Excel workbook we know about only *reads* from `WHRECLINE101` (one table out of 40), so the workbook is not the owner. There's clearly some larger application here that we haven't identified.

**Why we need to know.** UC Nexus has to coexist with this application in the short term. Without knowing what it is, we can't decide what risks UC Nexus poses to it (e.g., creating POs the other app doesn't expect to see), or whether UC Nexus will eventually replace it.

**What the answer enables.** We can identify the other system's stakeholders, understand its scope, and plan whether UC Nexus integrates with it, replaces parts of it, or sits alongside it.

---

#### Q2. What's the PMUBC application's relationship to UC Nexus's roadmap?

**Context.** UC Nexus is being built to handle hardware-management workflows (importing schedules, creating POs, receiving, shop assembly, shipping). The PMUBC database covers similar territory — project management, warehouse operations, change orders. There's clearly overlap.

**Why we need to know.** If the PMUBC app is being phased out in favour of UC Nexus, we need to plan migration. If it's staying, we need to plan coexistence (which tables UC Nexus reads vs. writes vs. ignores). If only certain features of it are being replaced, we need to know which.

**What the answer enables.** Concrete scope boundaries for UC Nexus. We can decide which PMUBC tables UC Nexus needs to read from (e.g., `UTPMMAINAWPROJ101` as job source), which to write to, and which to leave alone entirely.

---

#### Q3. When you create a PO via eConnect today, does the PMUBC-owning application need to be notified?

**Context.** We know that calling `taPoHdr` / `taPoLine` writes rows into `POP10100` / `POP10110` (GP's PO tables). What we don't know is whether the PMUBC application needs to *see* those rows downstream, and if so, how — does it poll GP, does it have its own triggers we haven't found, does it have a separate sync process, or does it learn about new POs through some other mechanism?

**Why we need to know.** If the PMUBC app expects to be notified when POs are created and UC Nexus skips that step, the customer's existing workflows (warehouse receiving, change orders, etc.) might silently break or get out of sync.

**What the answer enables.** UC Nexus can implement whatever notification step the PMUBC app needs — write to a "new PO" queue table, fire an HTTP webhook, schedule a sync, or nothing.

---

#### Q4. Why are so many PMUBC tables empty?

**Context.** We've counted rows in every PMUBC table. About a third are heavily used (`UTPMMAINAWPROJ101`, `WHRECLINE101`, `PMCHANGE*`), about a third are lightly used, and the rest are empty. Empty tables include: `POUCSHHEADERCOMMENT101`, `POUCSHLINECOMMENT101`, `SOPPOPLINK101`, `HMSHOPDRAW101`, `PMSUBMITTAL*`, `PMREQUESTFORINFOS`, `PMPROGRESSBILL*`, `WHSHIP*`, `WHRECEIPTDEFICIENCY101`.

There are several possible explanations:
- These features were built but never rolled out
- They were once used, then deprecated, then never cleaned up
- The data lives in a different system entirely and these tables are vestigial
- They're staged for a future rollout

**Why we need to know.** UC Nexus needs to decide whether to ignore these tables forever or whether they're features the company wants to enable. The answer changes UC Nexus's data model significantly.

**What the answer enables.** A clean decision per empty table: ignore, plan for future, or actively populate.

---

#### Q5. Should UC Nexus start writing to any of the currently-empty PMUBC tables?

**Context.** Building on Q4. Specifically:
- `POUCSHHEADERCOMMENT101` / `POUCSHLINECOMMENT101` are PO-comment tables, currently empty. GP itself has a single comment field per PO; these custom tables suggest someone once wanted richer comment data.
- `SOPPOPLINK101` is a sales-order ↔ PO link table, currently empty. This would matter if UC Nexus eventually handles sales orders.
- `HMSHOPDRAW101` is for hardware shop drawings, currently empty.

**Why we need to know.** These tables exist for a reason. If the company always wanted them populated but the existing tools never got around to it, UC Nexus is a chance to do it right. If they're abandoned ideas, UC Nexus should leave them alone.

**What the answer enables.** Explicit scope decisions about what UC Nexus's PO-creation flow writes beyond the standard GP tables.

---

#### Q6. Is `UTPMMAINAWPROJ101` the right source of truth for valid job numbers?

**Context.** The job number a user picks on a PO (e.g., `22713`) needs to refer to a real project. We've verified that `UTPMMAINAWPROJ101` contains a row for `22713`. GP itself has no row for it — GP's Project Accounting master table (`PA01201`) doesn't even exist in this database. So PMUBC is the project master, with no foreign key from GP enforcing the relationship.

**Why we need to know.** UC Nexus needs to validate job numbers before submitting a PO to eConnect. If `UTPMMAINAWPROJ101` is the canonical source, UC Nexus reads from there. If there's an even more authoritative source (a different system, a different table, a different lifecycle stage), we need to use that one instead.

**What the answer enables.** UC Nexus implements job-number lookup against the right table, avoiding "PO references a job that doesn't exist" errors.

---

#### Q7. Who's the contact for ongoing PMUBC questions?

**Context.** This is a big database with a lot of structure. Even if we get good answers in this meeting, we'll likely have follow-up questions during implementation.

**Why we need to know.** Self-explanatory — we need someone to call.

**What the answer enables.** Continuous unblocking during the build phase.

---

### Section 2: WennSoft

We've verified that WennSoft's Service Management module is installed but has zero data. Two open questions remain.

---

#### Q8. Is WennSoft Service Management being phased out, kept for future use, or just an unused install?

**Context.** WennSoft Service Management is a major add-on to GP, with ~1,400 database objects (procs, tables, triggers). It's installed here but completely dormant — zero service calls, work orders, contracts, or setup data. Installing WennSoft is not free and not casual; someone made a deliberate decision to put it on this server.

**Why we need to know.** If the company is planning to enable Service Management in the future, UC Nexus should design with that in mind (e.g., be ready to link POs to service calls eventually). If it's vestigial and being phased out, UC Nexus can completely ignore it.

**What the answer enables.** UC Nexus knows whether to design defensively for a future Service Management rollout or ignore it entirely.

---

#### Q9. Does the WennSoft Products PO Entry form customization add fields that eConnect doesn't write?

**Context.** The `.mac` files reference `dictionary 'WennSoft Products' form 'POP_PO_Entry'` — meaning the PO Entry screen in GP isn't stock GP's, it's been customized by WennSoft. UI customizations sometimes add new fields that get stored in extra tables, which an eConnect call wouldn't automatically populate.

**Why we need to know.** If WennSoft's PO Entry adds, say, a "Field Service Reference" field that gets stored in some `WS_*` table, and downstream reports or workflows expect that field populated, UC Nexus's eConnect-created POs would be incomplete from a business perspective.

**What the answer enables.** UC Nexus either populates the additional fields/tables, or confirms there's nothing extra to write.

---

### Section 3: Remaining data conventions

A few areas where our data sampling didn't fully answer the question.

---

#### Q10. What's the workflow for USD POs?

**Context.** 3% of PO lines (195 of 6,518) use USD instead of CAD. GP needs an exchange rate (`XCHGRATE`) at the time of PO creation. There are several common patterns: user picks the rate manually, the system pulls the current rate from `MC00100` automatically, a daily-import process keeps `MC00100` fresh, or the user picks a "rate type" that controls all this.

**Why we need to know.** UC Nexus's PO form needs to surface USD as an option and either ask the user for the rate or pull it programmatically. Either choice has consequences.

**What the answer enables.** UC Nexus's PO form design for currency handling.

---

#### Q11. How common are line-level tax schedule overrides?

**Context.** `POP40100.FRTSCHID = 'BC HST 5%'` is the default freight tax schedule. Each PO line in `POP10110` has its own `Purchase_Item_Tax_Schedu` field that can override. For out-of-province jobs, non-BC vendors, or special tax situations, this might be common.

**Why we need to know.** UC Nexus needs to decide whether the PO form needs a per-line tax-schedule control or whether it can rely on automatic defaults.

**What the answer enables.** UC Nexus PO form complexity — does it need a line-level tax control or not.

---

#### Q12. What's the job lifecycle, and when is a job "ready to receive PO lines"?

**Context.** We've seen the job tables in PMUBC: `UTPMBIDPROJ101` (bid pipeline, 85 rows), `UTPMMAINAWPROJ101` (active projects, 45 rows), `UTPMAWCONTRACTS101` (awarded contracts, 45 rows). This pattern suggests jobs move through stages — bid → awarded → in progress → maybe closed.

**Why we need to know.** UC Nexus might receive a PO request for a job that's still at bid stage, or for a closed-out job. Should UC Nexus block these, warn the user, or allow them?

**What the answer enables.** UC Nexus's job-lookup form can filter by lifecycle stage appropriately.

---

### Section 4: Known failure modes at this installation

This is where we want their hard-won institutional knowledge — things that *did* go wrong here that won't be in any documentation.

---

#### Q13. What's the most common eConnect error you've seen, and what causes it?

**Context.** The eConnect error catalogue (`DYNAMICS.taErrorCode`) has 9,407 distinct error codes. In practice, only a small subset are common at any given site, driven by the specific data conventions and reference-data hygiene at that customer.

**Why we need to know.** UC Nexus should specifically handle the errors users will actually hit, with friendly explanations and recovery paths. The remaining 9,400+ errors can be generic "talk to IT."

**What the answer enables.** UC Nexus's error-handling UX is tuned to the real top errors instead of guesswork.

---

#### Q14. Anything that broke after a past GP, SQL Server, or WennSoft upgrade?

**Context.** This GP installation is at SQL Server 2014 SP3 CU4 (vintage 2019). At some point, the server will get patched or upgraded. The customer has presumably been through past upgrades.

**Why we need to know.** If past upgrades broke specific integration patterns, UC Nexus should avoid those patterns from day one. Examples might include: a specific eConnect parameter that's been deprecated, a particular ODBC driver version that's required, a specific SQL feature to avoid.

**What the answer enables.** UC Nexus's relay implementation avoids known fragility points.

---

#### Q15. Are there windows where the integration has to pause — period close, year-end, backups?

**Context.** Accounting systems typically have periodic events (month-end close, fiscal year-end, payroll runs) where running integrations can interfere or fail.

**Why we need to know.** UC Nexus needs to handle the case where eConnect returns an error because the fiscal period is closed, or where SQL Server is briefly unavailable for a backup. The UX should differentiate "your PO failed validation" from "the system is in maintenance — try again later."

**What the answer enables.** UC Nexus's retry-and-display logic handles operational windows gracefully.

---

### Section 5: The catch-all

---

#### Q16. What surprised you about getting eConnect working at THIS site, that isn't in the Microsoft docs?

**Context.** This is the single most valuable question. The first three sections are structured because we know what we don't know. This one is for the things *we don't know that we don't know* — the surprises that come up only when someone has actually shipped an integration in this specific environment.

**Why we need to know.** Hard-won knowledge usually surfaces unprompted only when there's space for it. Without this question, we'll likely miss the most important learning.

**What the answer enables.** Avoiding a class of avoidable problems.

---

## "Show me" requests

Tangible artifacts that compress hours of meeting time:

- [ ] **The name of the PMUBC application and a current contact person.** Even just "it's our internal project-management app called X, written by Y team" unblocks Section 1 entirely.
- [ ] **A redacted code snippet** showing the legacy `taPoHdr` + `taPoLine` call pattern — specifically the **minimum parameter set** actually populated at this customer. Microsoft's spec for `taPoHdr` has 106 parameters; in practice most are defaulted. Knowing which ones are populated here collapses a significant research task.
- [ ] **Contact info** for ongoing questions during UC Nexus implementation.

---

## Out-of-meeting follow-ups (for DBA / GP admin, not this developer)

- A dedicated SQL service account for UC Nexus production, with narrow grants
- Access to the `TWO` (Fabrikam) demo company for baseline testing
- Refresh schedule for the `TUBC` / `TUCSH` test sandboxes (so we know whether test data is stable)
- GP / WennSoft / SQL Server upgrade roadmap
