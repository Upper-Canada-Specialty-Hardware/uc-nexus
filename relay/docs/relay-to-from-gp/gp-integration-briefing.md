# GP Integration Briefing

A plain-English walkthrough of what we've learned about the Excel PO workbook, the SQL Server it talks to, and the integration options available to UC Nexus. Written so you can verify the mental model matches yours.

Companion docs in this folder:
- `gp-integration-meeting-questions.md` — focused question list for the legacy developer meeting
- `gp-customizations-discovery.md` — what we found read-only on the server (custom code, conventions)
- `gp-table-structure.md` — full schema of the tables the workbook reads from
- `gp-customizations/` — raw SQL source code of every customization we extracted

---

## TL;DR

1. The Excel file `UCH PO Tracking.xlsm` does two jobs: (a) **looks up** existing PO info from your company's accounting system, and (b) **helps create new POs** by generating a script that automates the GP application's screens.
2. Your company's accounting system is **Microsoft Dynamics GP** ("GP"), running on a SQL Server called `UCSHSQL2`. The Excel file talks to this SQL Server directly — read-only.
3. New POs do NOT get created from the Excel file directly. The Excel file produces a **script of clicks and keystrokes** that someone manually plays inside the GP application. GP creates the PO and assigns the PO number itself.
4. There's a modern, supported way for software to create POs in GP — called **eConnect**. It's already installed and working on your SQL Server. **We've verified its customization hooks are empty** (stock Microsoft behavior), which makes integration much cleaner than initially feared.
5. The main remaining unknown is a **custom application data layer** called `PMUBC` (and `PMUCSH`). It's where this customer's job/project master, change orders, and warehouse receipts actually live. We don't yet know what application owns it or whether UC Nexus needs to coexist with it.
6. **Bonus finding**: WennSoft Service Management is installed but completely dormant at this customer — zero service calls, zero work orders, zero usage. The Service Mgmt module concerns we initially worried about don't apply.

---

## Part 1: The Excel file

### What it really is

The file is named `UCH PO Tracking.xlsm`. Despite the name, it's more than a tracking spreadsheet. It has 11 worksheets and about 2,400 lines of Visual Basic code (macros) behind the scenes. Most users only see two or three of those worksheets — the rest are hidden helpers.

The two real jobs it does:

**Job 1 — Look up purchase order information**

The user enters search criteria (vendor, item, PO number, date range) into a `SearchDetails` sheet, clicks a button, and the file:

- Connects to the SQL Server using the logged-in user's Windows credentials
- Runs a query against the PO tables to find matching records
- Optionally also queries a custom warehouse-receiving table to show what's been received
- Pastes the results back into the worksheet

This is a **read-only** operation. It doesn't change anything on the server.

**Job 2 — Help create a new PO**

The user fills out a `POInputToGP` sheet with vendor, buyer name, job number, items, quantities, unit costs, location, etc. Then they click a button that:

- Pulls the values they typed
- Plugs those values into pre-recorded **templates** that live in hidden worksheets (`GPPOTemplates` and `GPPOMacro`)
- Assembles the completed templates into a single text file
- Saves that text file to a network folder: `\\ucshdc19\BC Company\BC Warehouse\Purchasing\PO\Making\GPPOmacro.mac`

That `.mac` file is what actually drives PO creation — see Part 3 below.

### What the file does NOT do

Despite having read AND write access to all GP company databases (we verified this), the Excel file **never writes to the SQL Server**. Every database operation in its code is read-only. The only writing it does is to that `.mac` text file on the network share.

It also does NOT generate PO numbers. The PO number that ends up in the `.mac` file is either typed by the user manually (after they grab it from GP first using a separate "PO number grabber" macro) or left blank for GP to assign on its own.

---

## Part 2: The SQL Server

### Server identity

- Name: `UCSHSQL2\MSSQL2014`
- Reachable from any device on your corporate network at IP `10.0.0.246`, TCP port `1435`
- Software: Microsoft SQL Server 2014, with Service Pack 3 and Cumulative Update 4 (vintage 2019)
- This is the database engine where Dynamics GP stores everything

### What's on it

Dynamics GP organizes data into one database per **company** (one legal entity = one set of books). On this server:

| Database | What it is |
|---|---|
| `UBC` | UC Hardware Inc. — production |
| `UCSH` | Upper Canada Specialty Hardware — production |
| `UCA` | UC Access Inc. — production |
| `UCI` | Upper Canada Installations — production |
| `UHOLD` | UCSH Holding — production |
| `KEYMA` | Keymaster — production |
| `TUBC` | Test version of UBC — sandbox |
| `TUCSH` | Test version of UCSH — sandbox |
| `TUCA` | Test version of UCA — sandbox |
| `TUCI` | Test version of UCI — sandbox |
| `TWO` | Fabrikam, Ltd. — Microsoft's standard demo company |
| `TEM` | Template company |
| `DYNAMICS` | GP's "system" database (settings, error codes, company list) |
| **`PMUBC`** | **Custom application data store paired with UBC — 40+ tables, no procs/triggers. See below.** |
| **`PMUCSH`** | **Custom application data store paired with UCSH — same shape as PMUBC** |
| `master`, `model`, `msdb`, `tempdb` | SQL Server's built-in administrative databases |

### The `PMUBC` / `PMUCSH` custom application layer

These databases are not part of stock GP. They contain ~40 tables and zero stored procedures or triggers — a pure data store for some external application that does the actual logic in its own code.

**Which parts are actually used (sampled by row count):**

| Tables | Rows | Role |
|---|---|---|
| `UTPMMAINAWPROJ101` | 45 | **Active project/job master** |
| `UTPMAWCONTRACTS101` | 45 | Awarded contracts (1:1 with projects) |
| `UTPMBIDPROJ101` | 85 | Pre-award bid pipeline |
| `PMCHANGEHEADER101` / `PMCHANGELINE101` | 29 / 254 | Change orders (active) |
| `PMTASKITEMLIST001` | 34 | Task items |
| `WHRECLINE101` | **5,862** | Warehouse receipts (most active table) |
| `WHTAGGINGLINE101` | 2 | Inventory tagging |
| `SYSUCUSERS` | 1 | Custom user list (minimal use) |

**Which parts are empty (zero rows):**

`HMSHOPDRAW101`, `PMPROGRESSBILLING*`, `PMREQUESTFORINFOS`, `PMSUBMITTAL*`, `PMTASKSCHEDULER101`, `POUCSHHEADERCOMMENT101`, `POUCSHLINECOMMENT101`, `PSDRIVEPATH`, `PSJOBPATHROOT`, `QUOSOP_USERS`, `SOPPOPLINK101`, `WHRECEIPTDEFICIENCY101`, `WHSHIP*`

**Key insight: this customer's job/project master lives in `UTPMMAINAWPROJ101`, not in GP.** When a PO has `JOBNUMBR='22713'`, it's referencing a row in PMUBC, not anywhere in stock GP. The link is by string convention with no foreign key enforcing it.

For UC Nexus, this means: the PMUBC integration concern is much smaller than the 40-table count suggested. Most of those tables are dormant. The two real questions are: (a) what application owns PMUBC, and (b) when UC Nexus creates a PO, does that app need to be notified?

### Key GP tables we care about

These are stock GP tables, used by both the Excel file and any future integration:

| Table | Lives in | What it stores |
|---|---|---|
| `POP10100` | UBC, UCSH | PO header — vendor, dates, totals, status |
| `POP10110` | UBC, UCSH | PO line items — items, quantities, costs, jobs |
| `POP30100` | UBC, UCSH | PO history header (closed/posted POs) |
| `POP30300` | UBC, UCSH | Receipt history header |
| `POP30310` | UBC, UCSH | Receipt history lines |
| `POP40100` | UBC, UCSH | PO setup — *includes the "next PO number"* |
| `WHRECLINE101` | PMUBC, PMUCSH | Warehouse receipt lines — **custom, not stock GP** |

### Third-party add-on: WennSoft (installed but mostly dormant)

This server has **WennSoft** installed (a service-industry add-on for GP). We can see ~1,400 add-in objects: 176 `SMS_*` procs, 575 `SV*` tables, 545 `WS_*`/`WSMobile*` objects, 116 `WENN*`/`WSI*` objects.

**However, WennSoft Service Management is completely unused at this customer.** Verified by querying the actual data:

| WennSoft table | Row count | Meaning |
|---|---|---|
| `SVC00200` (service calls) | 0 | No service calls exist |
| `SVC06100` (work orders) | 0 | No work orders exist |
| `SV00300` (service contracts) | 0 | No contracts |
| `SVC00998` (setup) | 0 | Module not configured |
| % of POs linked to WennSoft | 0% | No PO has ever been linked |

The WennSoft Service Management triggers we initially worried about wouldn't fire even if they were INSERT triggers — they short-circuit on `if not exists(select * from SVC00998) return`.

**What IS active from WennSoft**: the *Products* dictionary, which customizes the appearance of GP's PO Entry form. That's what the macro targets (`dictionary 'WennSoft Products' form 'POP_PO_Entry'`). But this is purely a UI/display customization — it doesn't add data fields that eConnect bypasses.

→ **UC Nexus does not need to populate any WennSoft tables or worry about WennSoft business logic when creating POs.**

### Permissions situation

Your Windows account (`UPPERCANADA\jayp`) is in an AD group called `UPPERCANADA\wennsoft`, which is in turn a member of GP's `DYNGRP` role. `DYNGRP` is the "master key" role for GP — having it means full read/write access on every GP company database. The Excel file uses that same access for its read-only queries.

For UC Nexus production, we'd want a more restricted dedicated service account — that's a conversation for the DBA, not the legacy developer.

---

## Part 3: How POs actually get created today

This is the part most often misunderstood. The Excel file looks like it creates POs, but it doesn't directly. Here's the actual sequence:

### Step-by-step

1. **User opens GP** (the Dynamics GP desktop application)
2. **User runs a "PO number grabber" macro** (`multiplePOGet.mac`) that opens GP's PO Entry window, tabs through the PO Number field (which causes GP to reveal what the next PO number will be), and then cancels. GP has now "shown" the next number but not committed anything.
3. **User reads that PO number off the screen** and types it into the Excel workbook's `POInputToGP` sheet, cell `J2`
4. **User fills out the rest of the PO** in the Excel sheet — vendor, buyer, job, items, etc.
5. **User clicks the "make PO" button** in Excel. VBA code grabs the data, plugs it into templates, and writes out a complete `.mac` file (a script of clicks and keystrokes) to a network folder
6. **User goes back to GP**, opens Tools → Macro → Play, and selects that `.mac` file
7. **GP replays the script** — opening the PO Entry window, typing the PO number, typing the buyer, clicking through to the vendor detail screen, typing the vendor, going back to the main window, adding each line item with quantity/cost/job, etc.
8. **GP commits the PO** when the script reaches the Save action. The PO is now real in the GP database.

### What "`.mac` file" means

`.mac` files are **Dexterity macro files** — Dexterity is the framework GP is built in. A `.mac` file is a plain text script of UI commands. Sample lines:

```
MoveTo field 'Vendor ID'              ← put cursor in the Vendor ID field
TypeTo field 'Vendor ID' , 'BRA101'   ← type BRA101 into it
ClickHit field 'Expansion Button 4'   ← click the button
```

The macros target *specific named windows and fields in specific dictionaries* (`'WennSoft Products'`, `'default'`). If GP's screens change, or if WennSoft is upgraded, or if the user has the wrong window open, the script can break in subtle ways.

### Why this approach is brittle

- Requires the GP application running on a Windows desktop
- Requires a user to be sitting there, opening files, playing macros
- Breaks if anyone re-arranges fields, renames buttons, or installs a GP update
- No real error handling — failures pop up as modal dialogs the user has to click through
- Two users running it at the same time can collide
- No way for software in the cloud (like UC Nexus on Railway) to drive it

This is why the existing process is "Excel writes a script, human plays the script in GP."

---

## Part 4: eConnect — the modern, supported way

### What eConnect is

Microsoft ships an integration layer with GP called **eConnect**. The simplest way to think about it: **eConnect is GP's API**. Instead of automating GP's screens, you call procedures in the database that GP itself uses internally for its business logic.

For purchase orders, the relevant procedures are:

| Procedure | What it does |
|---|---|
| `taGetPONextNumber` | Returns the next available PO number and reserves it |
| `taPoHdr` | Creates the PO header row (vendor, dates, totals) |
| `taPoLine` | Creates one PO line item (called once per line) |
| `taPopDistribution*` | Creates the GL distributions |
| `taPoHdrPre` / `taPoHdrPost` | Empty hook procedures that customers can customize |
| `taPoLinePre` / `taPoLinePost` | Same, but for line items |

You call them with the same Windows credentials you'd use to connect to the database, pass parameters describing the PO, and get back either success (and a new PO number) or an error code.

### Why eConnect is much better than the `.mac` approach

| Concern | `.mac` UI replay | eConnect |
|---|---|---|
| Needs GP application running | Yes | No — just the SQL Server |
| Needs a user to play the file | Yes | No |
| Works from cloud-hosted software | No | Yes |
| Breaks when GP UI changes | Yes | Rarely |
| Two users at once safe? | No | Yes |
| Errors come back as data, not popups | No | Yes |
| Microsoft supports it | Officially, kind of | Officially, fully |
| All-or-nothing transactions | No | Yes |

### What we've verified about eConnect on YOUR server

- ✅ The eConnect procedures (`taPoHdr`, `taPoLine`, `taGetPONextNumber`, etc.) are installed in both production companies (`UBC`, `UCSH`) and in the test sandboxes (`TUBC`, `TUCSH`)
- ✅ Your account has permission to execute them
- ✅ The error-lookup table (`DYNAMICS.taErrorCode`, 9,407 rows of error definitions) is in place
- ✅ The current "next PO number" in UBC is `PO501927`; in TUBC it's `PO0000036` — independent sequences
- ✅ **The Pre/Post hook procedures are stock empty** — we read their source code. No custom validation, no transformations, no field-defaulting. Microsoft's documented behavior applies verbatim with no local customization.
- ✅ **No custom triggers fire when new PO lines are inserted** — WennSoft's triggers only fire on DELETE, UPDATE-with-cancel, or receipt insert.

That removes most of the "what custom logic might break our integration?" worry. The eConnect path through this customer's database is essentially identical to a stock GP install.

---

## Part 5: Sandbox situation

For testing eConnect-based PO creation without risk to production:

- **`TUBC` and `TUCSH`** are the test versions of UBC and UCSH. They have identical schemas, all the WennSoft customizations, the same custom triggers, and independent PO numbering sequences. They're the most accurate test environments available. You have access to both.
- **`TWO`** is GP's standard demo company. Your account currently can't open it. Even if you could, it wouldn't have your WennSoft customizations or your real vendor/item/job data, so it'd be a much weaker sandbox than TUBC.
- A **dry-run technique** also exists: in production, you can wrap eConnect calls in `BEGIN TRANSACTION ... ROLLBACK`. The database does all the validation, returns any errors, and then un-does the changes before they're committed. Lets you safely test against real production data and find issues without ever committing a fake PO. Caveat: side effects that escape the SQL transaction (e.g., a trigger sending email — although we've verified none exist for PO inserts) wouldn't roll back.

---

## Part 6: Local data conventions (sampled from real POs)

We sampled real PO data in UBC to learn what's "normal" at this customer. These aren't enforced rules — they're observed patterns that tell UC Nexus what the defaults should be:

| Convention | Observed pattern |
|---|---|
| **PO number prefix** | 100% start with `'PO'` (`PO501920`, etc.). Governed by `POP40100.PO_Code='PO'`. UC Nexus should always use `taGetPONextNumber`, not generate its own prefix. |
| **Buyer ID** | Free-text human names — "Shane Robertson", "Steve Faith", "Greg Sutton". No buyer-master enforcement visible. |
| **Location** | 100% `'VANCOUVER'` in UBC (out of 6,518 line items sampled). |
| **Currency** | 97% CAD, 3% USD. Need to support both, default CAD. |
| **Cost code format** | Three segments: `phase-step-type` like `210-200-2`. First two are user-entered; third (cost type) likely auto-derived from phase. |
| **Product Indicator** | 87% Job Cost (PI=2), 13% Non-Inventoried (PI=1). Zero inventory POs. This is a job-cost-only shop. |
| **PI ↔ JOBNUMBR rule** | **Strict invariant**: PI=2 lines (5,653) ALL have a JOBNUMBR populated; PI=1 lines (868) ALL have empty JOBNUMBR. Zero exceptions. UC Nexus rule: line has a job → PI=2 + JOBNUMBR; else → PI=1 + blank JOBNUMBR. |
| **PO hold** | Zero of 1,965 POs are on hold. No auto-hold rules active. |
| **PO lifecycle** | Most POs reach `POSTATUS=5 (Closed)` after receipt; healthy normal flow |
| **Tax schedule (freight)** | `POP40100.FRTSCHID='BC HST 5%'` is the default; line-level overrides likely. |

---

## Part 7: What this means for UC Nexus

The plan is for UC Nexus to create POs in GP without anyone touching the GP application. The proposed shape:

```
┌──────────────────────────────────────────────────────────────┐
│  UC Nexus (Railway cloud)                                    │
│  ─ user fills out PO form in the web app                     │
│  ─ web app sends PO data to a small "relay" service          │
└──────────────────────────────────────────────────────────────┘
                       │
                       │  HTTPS over a private tunnel
                       │  (Tailscale, Cloudflare Tunnel, etc.)
                       ▼
┌──────────────────────────────────────────────────────────────┐
│  Localhost Relay (small program on the corporate network)    │
│  ─ Receives PO data from UC Nexus                            │
│  ─ Opens a SQL connection to UCSHSQL2 using a dedicated      │
│    service account (NOT a personal Windows account)          │
│  ─ Calls taGetPONextNumber → gets new PO number              │
│  ─ Calls taPoHdr → creates header                            │
│  ─ Calls taPoLine once per line → creates lines              │
│  ─ Wrapped in a transaction; commits on success              │
│  ─ Returns the PO number back to UC Nexus                    │
└──────────────────────────────────────────────────────────────┘
                       │
                       ▼
                  UCSHSQL2\MSSQL2014
                  (GP company databases)
```

The relay is needed because UC Nexus runs in the cloud (Railway) and your SQL Server is on the corporate network. The relay bridges the gap, runs inside your network, and only that machine needs the SQL credentials.

End-to-end user experience: fill out PO in UC Nexus → click Submit → 1–2 seconds later, UC Nexus shows them the new PO number GP assigned. No GP application running. No `.mac` files. No manual replay.

---

## Part 8: Why we're asking what we're asking

After the read-only discovery, the meeting questions are mostly about **business intent and future direction** — things data can't tell us:

- **The `PMUBC` mystery**: Who owns the application? Does it need to be told when UC Nexus creates a PO? Will UC Nexus eventually replace parts of it?
- **Why WennSoft is installed if dormant**: Is it being phased out, kept for a future rollout, or just vestigial?
- **Which currently-empty PMUBC tables UC Nexus should start populating** (PO comments, sales-order links, etc.) — they're empty today but the business may want them populated going forward
- **USD workflow** (3% of POs)
- **Job lifecycle stages** — when's a job "ready to receive PO lines"
- **Known failure modes** at this installation
- **The "wish I'd known" catch-all**

What we're NOT asking (already answered by data):
- Anything about the legacy app's architecture or tech stack
- Anything documented in Microsoft Learn
- Authentication / permissions (DBA conversation)
- Whether eConnect hooks have custom logic (verified empty)
- Whether custom triggers interfere with new PO inserts (verified they don't)
- Whether WennSoft Service Mgmt affects PO creation (verified zero usage)
- PO numbering convention, cost code format, location, currency mix, PI↔JOBNUMBR rule (sampled)
- Whether the customer uses PMUBC's PO comment / sales-link / shop-drawing tables today (verified empty)

---

## Glossary

| Term | What it means |
|---|---|
| **GP** | Microsoft Dynamics GP — the accounting/ERP application your business runs on |
| **Dynamics GP** | Same as GP |
| **SQL Server** | The database engine GP stores its data in |
| **Company / Company DB** | One database per legal entity. `UBC`, `UCSH`, etc. |
| **eConnect** | Microsoft's official programmatic interface to GP, made of SQL stored procedures starting with `ta` |
| **WennSoft** | A third-party add-on installed on top of GP, focused on service business workflows |
| **`.mac` file** | A Dexterity macro file — a text script of UI commands replayed by GP's macro player |
| **Dexterity** | The development framework GP is built in. Dexterity macros automate GP's UI |
| **POP table** | "Purchase Order Processing" — stock GP tables for purchasing, named with `POP` prefix |
| **DYNGRP** | The standard GP database role that gives full data access. Most GP users are in it |
| **DYNAMICS** | The shared "system" database that holds settings and the master list of companies |
| **PMUBC / PMUCSH** | Custom application databases paired with UBC/UCSH. 40+ tables, no procs. Unknown owning application |
| **WHRECLINE101** | A custom table in PMUBC/PMUCSH that tracks warehouse receipt lines |
| **POP10100 / 10110** | Stock GP: PO header and PO line items |
| **POP40100** | Stock GP table holding the PO setup, including the next PO number to be assigned |
| **`taPoHdr` / `taPoLine`** | eConnect stored procedures for creating a PO header and PO line |
| **`taGetPONextNumber`** | eConnect stored procedure that returns and reserves the next PO number |
| **Pre / Post hooks** | eConnect's customization points — empty at this site, verified |
| **AD / Active Directory** | The Windows network's identity system. `UPPERCANADA\jayp` is an AD account |
| **SSPI** | "Integrated Security" — connecting to SQL using your Windows login automatically |
| **Transaction (database)** | A group of changes that either all succeed or all roll back |

---

## Anything I have wrong?

The whole point of this doc is for you to flag mismatches. A few specific spots:

- **Part 3 step 2-3**: my read is that users manually grab a PO number from GP via `multiplePOGet.mac` and paste it into Excel before generating the `.mac`. Is that actually what people do?
- **Part 6 architecture**: Is "small program on the corporate network" workable? Is there an existing always-on machine where it could live?
- **`PMUBC`**: Is the owning app something you recognize? Is this an internal-built app, or a third-party purchase? This is the meeting's biggest open question.
