# UC Connects - legacy documentation library

as-built reference for the legacy "UC Connects" application (the WPF desktop client whose
solution is `PM_Project_Tracking.sln`, internally called "PM10 - Project tracking program").

scope of this library is deliberately narrow - two workflows, documented exhaustively at the
code/field level:

1. purchase orders, end to end
2. hardware / inventory receiving, end to end

everything here describes what the legacy code actually does today. there are no opinions about
how to rebuild it. where the code is a dead stub or a dormant path, that is called out as such so
you don't copy a mechanism that was never actually wired up.

-------------------------------------------------------------------------------

files in this set

- `README.md` - this index, plus the single most important thing to understand before reading
  either workflow (where POs actually come from), and a glossary of the GP tables both workflows touch.
- `00 - shared foundations.md` - the infrastructure BOTH workflows sit on: the two-database model,
  the cross-database LINQ trick, the eConnect posting mechanism, the document-number reservation /
  rollback pattern, and the audit + manual-id conventions. read this first; the workflow docs assume it.
- `01 - purchase orders end to end.md` - the PO workflow: how POs are read from GP, the PO line/header
  read models field-by-field, the UC-only comment + do-not-ship + confirmation + deficiency overlays,
  and the dormant PO-creation stub.
- `02 - hardware inventory receiving end to end.md` - the receiving workflow: the four receipt types,
  the select-PO dialogs, the `WHRECLINE101` model field-by-field, the commit pipeline, the eConnect
  receipt push, rollback behaviour, and what happens to a receipt afterward.

-------------------------------------------------------------------------------

the one thing to understand first - POs are NOT created in this app

UC Connects does not create purchase orders. purchase orders are created directly inside Microsoft
Dynamics GP (Great Plains), the ERP. UC Connects READS them out of the GP company database and layers
its own extra data on top (warehouse rack locations, do-not-ship dates, free-text comments, deficiency
notes, confirmation tracking).

there IS a code path that pushes a new PO into GP via eConnect - `EConnect/PopTransaction.cs`,
`RunPoCreate()` - but it is a developer test stub: it builds two hardcoded dummy lines, targets the
TUCSH test database with a hardcoded connection string, and is only ever called from commented-out
lines in `MainWindow.xaml.cs` (1975, 3378). it is NOT part of any real workflow. see
`01 - purchase orders end to end.md` for the full breakdown.

the only thing UC Connects WRITES back to GP is purchase order RECEIPTS, via the receiving workflow.
that path (`EConnect/PopRcptLineInsert.cs`) is real, live, and the backbone of doc #2.

so the honest end-to-end shape is:

```
PO created in GP  ->  UC Connects reads it  ->  warehouse receives against it  ->  receipt posted back to GP via eConnect
   (not this app)        (doc #1)                  (doc #2)                            (doc #2)
```

-------------------------------------------------------------------------------

runtime facts (the app these workflows live in)

| thing | value |
|---|---|
| app type | WPF desktop, single WinExe |
| language / framework | C#, .NET Framework 4.7.2 |
| data access | LINQ-to-SQL (`System.Data.Linq`), hand-written entity classes with `[Table]`/`[Column]` attributes |
| ERP integration | Microsoft Dynamics GP via the eConnect 11.0 SDK (`Microsoft.Dynamics.GP.eConnect`, `...eConnect.Serialization`) |
| other API | a "Titan" REST API (`TitanApi/`, `DataClasses/TitanObjects/`) - NOT used by either of these two workflows |
| auth to SQL | Windows integrated security (SSPI); no SQL logins in code |
| SQL server | `UCSHSQL2\MSSQL2014` (hardcoded in the eConnect doc-number + verify code; the rest of the app reads the server name from app settings) |
| main UI shell | `MainWindow.xaml` / `MainWindow.xaml.cs` (a ~200k-line code-behind; both workflows are tabs in it) |

-------------------------------------------------------------------------------

the two database families

every query in both workflows hits one of two databases. knowing which is which is essential.

GP company database - the Dynamics GP data. holds all the `POP*` (purchasing), `SOP*` (sales),
`JC*` (job cost), `PM*` (payables/vendor), `RM*` (receivables), `WS*` tables. UC Connects only reads
these, except for posting receipts through eConnect (which GP itself writes).

| environment | GP db name | company |
|---|---|---|
| live - Markham/Ontario | `UCSH` | CompanyId 1 |
| live - BC/Vancouver | `UBC` | CompanyId 2 |
| test | `TUCSH` (a.k.a. `TEST` in old strings) | - |

PM application database - UC Connects' OWN tables. holds everything GP can't store: rack locations,
do-not-ship dates, comments, deficiencies, shipment draw-downs.

| environment | PM db name |
|---|---|
| live - Markham/Ontario | `PMUCSH` |
| live - BC/Vancouver | `PMUBC` |
| test | `TESTPMUCSH` |
| users (always) | `UCUsers` |

the UC-owned tables that the two workflows touch:

| table | database | used by | what it stores |
|---|---|---|---|
| `WHRECLINE101` | PM | receiving | the canonical UC receiving-line record (rack location + revision + audit) |
| `WHRECEIPTDEFICIENCY101` | PM | both | per-PO warehouse deficiency notes (open/closed) |
| `WHRECLINEDRAWDOWNS101` | PM | receiving (downstream) | how much of a received rack quantity has been drawn down by shipments |
| `POUCSHHEADERCOMMENT101` | PM | PO | UC's PO-header comments + the do-not-ship-before date |
| `POUCSHLINECOMMENT101` | PM | PO | UC's PO-line comments |
| `PROCPOCONF101` | PM | PO | PO confirmation tracking (emailed-to-supplier, acknowledged, etc.) |

-------------------------------------------------------------------------------

GP table glossary (the tables both workflows read)

these are mirrored in code under `DataClasses/GpObjects/` as thin LINQ-to-SQL entity classes. column
names below are the real GP column names. victoriayudin.com/gp-tables is the reference the original
author leaned on (cited in code comments).

| GP table | code class | meaning | key columns the app uses |
|---|---|---|---|
| `POP10100` | `Pop10100` | purchase order header (work/open) | `PONUMBER`, `POSTATUS`, `BUYERID`, `ADDRESS3` (reused as change-order id), `DOCDATE` |
| `POP10110` | `Pop10110` | purchase order LINE (work/open) | `PONUMBER`, `ORD`, `JOBNUMBR`, `VENDORID`, `POLNESTA` (line status), `ITEMNMBR`, `ITEMDESC`, `QTYORDER`, `UNITCOST`, `NONINVEN`, `LOCNCODE`, `COSTCODE`, dates |
| `POP10500` | `Pop10500` | purchase order RECEIPT line (work/open) | `PONUMBER`, `POLNENUM`, `POPRCTNM`, `RCPTLNNM`, `QTYSHPPD` (qty received), `QTYMATCH`, `QTYINVCD` |
| `POP10150` | `Pop10150` | PO header comment text | `POPNUMBE`, `COMMNTID`, `CMMTTEXT`, `COMMENT_1..4` |
| `POP10550` | `Pop10550` | PO line comment text | `POPNUMBE`, `ORD`, `CMMTTEXT` |
| `POP30300` | `Pop30300` | PO receipt header HISTORY (posted) | `POPRCTNM`, `GLPOSTDT` (gl post date) |
| `SOP60100` | `Sop60100` | sales-order ⇄ PO link | `SOPNUMBE`, `SOPTYPE`, `PONUMBER`, `ORD`, `LOCNCODE` |
| `SOP10100` / `SOP30200` | `Sop10100` / `Sop30200` | sales order header work / history | `SOPNUMBE`, `CUSTNAME`, etc (for customer name on a PO) |
| `JC00102` | `Jc00102` | job cost - job master | `JOBNUMBR`, job name (project name) |
| `PM00200` | `Pm00200` | payables - vendor master | `VENDORID`, `VENDNAME` |

note: GP keeps "work/open" and "history" copies of most documents (e.g. POP10100 open vs POP30100
history; POP10500 open vs POP30300/POP30700 history). UC Connects mostly queries the open/work tables,
and reads POP30300 only to get the gl-post date of a posted receipt.

-------------------------------------------------------------------------------

two status code maps you will need constantly

PO line status - `POLNESTA` on POP10110 (decoded in `PurchaseOrderLineItem.Polnesta` setter):

| POLNESTA | meaning in UC Connects |
|---|---|
| 1 | New |
| 2 | Released |
| 3 | Change Order |
| 4 | Received |
| 5 | Closed |
| 6 | Cancelled |

both the PO-creation stub and the receipt push only ever include lines with `POLNESTA < 4` (i.e. not
yet received/closed/cancelled).

PO header status group - `STATGRP` (from code comments, not stored by UC's own classes but relevant
when reading GP):

| STATGRP | meaning |
|---|---|
| 0 | voided (not officially valid per the SDK, but seen on voided POs) |
| 1 | active (new, open, modified) |
| 2 | closed (cancelled, closed) |
