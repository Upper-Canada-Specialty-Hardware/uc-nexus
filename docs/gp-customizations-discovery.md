# GP customizations & local conventions — discovery findings

Everything below was discovered read-only from the SQL Server. No writes, no tampering. The raw source code of each customization is saved in `docs/gp-customizations/`.

This document partially answers the questions in `gp-integration-meeting-questions.md` — we can now go into the meeting with concrete observations rather than open questions.

---

## TL;DR

Three big findings, all good news:

1. **The eConnect Pre/Post hooks are EMPTY at this site.** All four (`taPoHdrPre`, `taPoHdrPost`, `taPoLinePre`, `taPoLinePost`) are stock Microsoft defaults — they just return success. The 4–7 KB body size that looked alarming was 99% parameter declarations; the actual logic is one line. **Microsoft's eConnect documentation applies verbatim with no local customization to worry about.**

2. **The WennSoft Service Mgmt triggers DON'T fire on new PO creation.** WennSoft has triggers on `POP10110` for DELETE and UPDATE only (not INSERT), and on `POP30310` for INSERT (receipts, not POs). UC Nexus creating new POs via `taPoHdr`/`taPoLine` will insert rows, and **no WennSoft logic runs on those inserts.**

3. **`PMUBC` / `PMUCSH` are a large custom application data store**, not a stock GP component. 40+ tables span project management, warehouse operations, shipping, RFIs, change orders, submittals, bid management, custom user/role tables — clearly a custom-built business application that runs alongside GP. **There are zero stored procedures or triggers in PMUBC**, meaning the application logic lives in whatever app owns this database (likely the legacy app, or a similar custom system). UC Nexus won't need to write here to create POs.

---

## Detailed findings

### 1. eConnect Pre/Post hook procs — all stock empty

| Proc | Size | Logic |
|---|---|---|
| `taPoHdrPre` | 3,780 bytes | Empty — `select @O_iErrorState = 0; return @O_iErrorState` |
| `taPoHdrPost` | 3,055 bytes | Empty — same |
| `taPoLinePre` | 2,589 bytes | Empty — same |
| `taPoLinePost` | 2,100 bytes | Empty — same |

These are Microsoft's stock-shipped versions. No custom validation, no transformations, no field defaulting, no rejection logic. **Microsoft's published eConnect parameter requirements apply exactly.**

Saved as raw SQL in `docs/gp-customizations/taPoHdr*.sql` and `taPoLine*.sql`.

### 2. Triggers on PO tables

| Trigger | On Table | Fires On | What it does | Relevant to new-PO creation? |
|---|---|---|---|---|
| `tr_SVC_POP10110_D` | `POP10110` | DELETE | When a PO line is deleted and was linked to a WennSoft service call / work order / RTV, releases that service call back to backorder status. Unlinks the PO reference. | **No** — UC Nexus inserts, doesn't delete |
| `tr_SVC_POP10110_U` | `POP10110` | UPDATE | When a PO line is updated AND either canceled (`POLNESTA=6`) or has a cancel quantity, updates linked service calls and work orders. | **No** — only fires on update/cancel, not initial insert |
| `tr_SVC_POP30310_I` | `POP30310` | INSERT | When a receipt line is created, notifies the linked WennSoft service call/work order that the item was received. | **No for PO creation. Yes if UC Nexus ever records receipts.** |
| `zDT_POP10100U` | `POP10100` | UPDATE | Stock GP "data tracking" — just updates `DEX_ROW_TS` timestamp | Stock GP, harmless |
| `zDT_POP10110U` | `POP10110` | UPDATE | Stock GP `DEX_ROW_TS` updater | Stock GP, harmless |
| `zDT_POP30100U` | `POP30100` | UPDATE | Stock GP `DEX_ROW_TS` updater | Stock GP, harmless |
| `zDT_POP30110U` | `POP30110` | UPDATE | Stock GP `DEX_ROW_TS` updater | Stock GP, harmless |

**Net**: when UC Nexus calls `taPoHdr` + `taPoLine` via eConnect, **no custom triggers fire**. The path through the database is exactly what Microsoft's stock eConnect does.

Raw trigger source saved in `docs/gp-customizations/trigger_*.sql`.

### 3. The `PMUBC` / `PMUCSH` custom layer

**`PMUBC` contains 40+ tables, zero procs, zero triggers.** It's a pure data store for an external application. Tables grouped by theme:

#### Project Management ("PM*", "UTPM*")
- `PMCHANGEHEADER101`, `PMCHANGEINDEX101`, `PMCHANGELINE101`, `PMCHANGELINEDRAWDOWNS101`, `PMCHANGELINESESSION` — change orders
- `PMPROGRESSBILLINGHEADER101`, `PMPROGRESSBILLINGLINE101`, `PMPROGRESSBILLSESSION` — progress billing
- `PMREQUESTFORINFOS` — RFIs
- `PMSUBMITTALLINES101`, `PMSUBMITTALSHEADERS101` — submittals
- `PMTASKITEMLIST001`, `PMTASKSCHEDULER101` — task management
- `UTPMAWCONTRACTS101`, `UTPMBIDPROJ101`, `UTPMMAINAWPROJ101`, `UTPMOFFERTOTENDER101`, `UTPMPURSUIT101`, `UTPMQUOTESUMMARY101` — bid/contract pipeline

#### Warehouse operations ("WH*")
- `WHRECEIPTDEFICIENCY101` — receipt deficiencies
- `WHRECLINE101` — receipt lines (the one the Excel macro reads)
- `WHRECLINEDRAWDOWNS101` — partial draws against PO lines
- `WHSHIPHEADER101`, `WHSHIPHEADERSESSION` — shipping headers
- `WHSHIPLINE101` — shipping lines
- `WHTAGGINGLINE101` — tagging (inventory marking)

#### PO extensions ("PO*", "SOPPOPLINK*")
- `POUCSHHEADERCOMMENT101`, `POUCSHLINECOMMENT101` — extra PO comments beyond what GP supports natively
- `SOPPOPLINK101`, `SOPPOPLINK101NEW` — sales-order ↔ PO links

#### Custom user/role system ("SYSUC*")
- `SYSUCUSERS`, `SYSUCUSERSASSOC`, `SYSUCUSERSOVERRIDES`, `SYSUCUSERSROLEASSIGN`, `SYSUCUSERSROLELIST` — looks like a custom auth/permission layer separate from GP's

#### Other
- `HMSHOPDRAW101` — hardware/metal shop drawing records
- `QUOSOP_USERS` — quoting users
- `PSDRIVEPATH`, `PSJOBPATHROOT` — file system path config

**Key takeaway**: PMUBC is the database for what looks like a major custom-built business app — project/job lifecycle, warehouse, shipping, document management, and a custom auth system. Whatever app owns this database is doing real work alongside GP. UC Nexus needs to know what that app is, who maintains it, and whether UC Nexus is going to coexist with it, replace parts of it, or integrate with it.

**The most pressing meeting question**: *what application owns PMUBC, and what's its relationship to UC Nexus's roadmap?* This is bigger than just PO creation.

---

## Local data conventions (sampled from real POs in UBC)

These are observed patterns, not enforced rules — but they tell us what's "normal" at this customer.

### PO numbers
- **Format**: 100% of POs start with `'PO'` prefix (1,964 of 1,964 sampled)
- **Setup-driven**: GP's `POP40100.PO_Code = 'PO'` — this is the customer's chosen prefix
- **Implication for UC Nexus**: just call `taGetPONextNumber` — don't try to invent a custom prefix

### Buyer IDs
Sampled top buyers — they're **real human names typed as free text**, not codes:

| Buyer | PO count |
|---|---|
| Shane Robertson | 375 |
| Raz Cojocariu | 282 |
| Darren Watson | 252 |
| Eduardo DS | 160 |
| Steve Faith | 150 |
| Greg Sutton | 138 |
| John Stearman | 97 |
| Jana Giuranno | 71 |
| Sarthak Anand | 70 |
| Jordan Savage | 70 |

**Implication**: UC Nexus probably needs a buyer-name field, free text, capturing first + last name. There's no apparent buyer-master being enforced.

### Location codes
- **100% `'VANCOUVER'`** (6,518 of 6,518 line items sampled in UBC)
- **Implication**: hardcoding `LOCNCODE='VANCOUVER'` for UBC is safe for now; verify UCSH separately

### Currency
| CURNCYID | Lines | % |
|---|---:|---:|
| CAD | 6,323 | 97.0% |
| USD | 195 | 3.0% |

- **Implication**: default to CAD, but support USD as an explicit option. UC Nexus will need to pull exchange rate (XCHGRATE) from `MC00100` for USD POs.

### Cost codes
Real cost codes follow a **three-segment format** `phase-step-type`:

| Cost code | Lines |
|---|---:|
| `210-200-2` | 3,526 |
| `220-000-2` | 727 |
| `320-000-3` | 470 |
| `310-000-3` | 249 |
| `410-000-4` | 176 |
| `630-000-6` | 127 |
| `330-000-3` | 95 |
| `590-000-5` | 83 |
| `620-000-6` | 48 |
| `340-000-3` | 27 |

- The Excel macros use `CC_Phase` and `CC_Step` as separate fields when typing into GP — so the *first two* segments are user-entered, the third (cost type) likely auto-derives in GP from the phase number
- **Implication**: UC Nexus collects phase + step as separate inputs; GP fills in the rest

### Product Indicator (what kind of line item)
| Product_Indicator | Lines | Meaning |
|---|---:|---|
| 2 | 5,650 | Job Cost |
| 1 | 868 | Non-Inventoried |
| (others) | 0 | — |

**This is a job-cost-only shop.** No inventory-tracked PO lines, no drop ships, no service drop ships. ~87% of lines are billed to jobs.

- **Implication**: UC Nexus should default `Product_Indicator = 2 (Job Cost)`. The "non-inventoried" cases are likely shop-supplies POs without a specific job link.

### Tax schedules
- `POP40100.FRTSCHID = 'BC HST 5%'` — freight defaults to BC HST 5%
- Per-PO `TAXSCHID` overrides are presumably common (we didn't sample but the column exists)

---

## What this lets us drop from the meeting agenda

These questions can be removed from `gp-integration-meeting-questions.md` — we've answered them:

- ~~Section 2 (Pre/Post hook customizations)~~ — they're empty, stock
- ~~Section 1 question 2 (do `tr_SVC_POP10110_*` triggers cause issues on eConnect insert?)~~ — they don't fire on insert
- ~~Section 4 questions 12, 13 (PO number prefix, cost code format)~~ — sampled directly

The remaining high-value meeting questions are now mostly about **`PMUBC`** and **WennSoft's behavior at the application/business-process level** (auto-hold, approval flow, what fields WennSoft business users expect populated, etc.).

---

## Refined meeting question priorities (post-discovery)

Going into the meeting, the highest-value questions are now:

1. **What application owns the `PMUBC` / `PMUCSH` databases?** Is it the legacy app you wrote, or someone else's? What does it do at a business level?
2. **Does that PMUBC application need to know when a new PO is created in GP?** If so, what's the mechanism today (polling, triggers, app-level integration)? Will UC Nexus need to replicate that handoff?
3. **Are there PMUBC tables UC Nexus needs to write to when creating a PO** (e.g., `POUCSHHEADERCOMMENT101` for header-level comments, `SOPPOPLINK101` for linking back to a sales order, `HMSHOPDRAW101` for hardware shop drawings, anything PM-related)? Or are those purely a downstream concern populated by other workflows?
4. **WennSoft business behavior**: with the eConnect inserts not triggering WennSoft triggers, does WennSoft still need to "see" new POs through some other mechanism (a scheduled sync, manual reconciliation, a service call link)?
5. **Job-cost-only shop confirmation**: are inventory POs ever created here, or is Job Cost (PI=2) the right universal default?
6. **The "wish I'd known" question** — still the best catch-all.

The auth, generic eConnect, generic GP, and hook-customization questions are all answered.
