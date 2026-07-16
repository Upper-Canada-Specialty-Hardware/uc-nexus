# Relay POC - next steps

what we have to prove, and how, before scaffolding the relay. companion to `localhost-relay.md` (the full design) and the `UC Connects source code/UC Connects code review/` library (the deprecated app's as-built behaviour).

where the relay POC stands today

- the relay is scaffolded and running at `relay/` (FastAPI + pyodbc, package `ucnexus_relay`). this `docs/` folder now lives under it.
- workflow 1 (PO creation) is PROVEN end to end against TUBC as of 2026-06-24, including the WennSoft job-cost commitment and custom `ucnexus`-prefixed PO numbers. the design plus the corrections found while proving it are in `localhost-relay.md` ("what the live POC proved").
- the deprecated app (`UC Connects source code`, solution PM_Project_Tracking) is confirmed owner of PMUCSH/PMUBC and is what UC Nexus replaces. its only live GP writeback is receipts; its PO-create path was a dead developer test stub, so workflow 1 had no working reference and had to be proven live - which it now is.
- workflow 2 (receiving) is also PROVEN against TUBC as of 2026-06-24: RC0000038 received PO0000044 end to end. both POC workflows are done.

auth - resolved on this machine (it was the blocker on the old one)

- the original plan was written on a non-domain box (`LEGION7I\jaymi`) where windows/SSPI auth failed with `Cannot generate SSPI context (1312)`. that does NOT apply here.
- this dev machine is `TAGGING3W10`, logged in as `UPPERCANADA\jayp` (domain `UPPERCANADA.CORP`). it is domain-joined, reaches the GP SQL server (`UCSHSQL2\MSSQL2014`, `10.0.0.246:1435`) over tcp 1435, and authenticates via windows SSPI (`Trusted_Connection=yes`) with `IS_MEMBER('DYNGRP')=1`. no SQL login, no runas - this is the relay's real auth path.
- eConnect is stored procedures inside the SQL database, so authenticating to SQL and running EXEC is the whole game; confirmed working for both read and write.

local prerequisites on this machine

- python 3.11, poetry, pyodbc 5.3.0: installed.
- ODBC Driver 17 for SQL Server: installed and used. Driver 18 is NOT installed and not needed - 17 handles TLS 1.2 fine against SQL 2014. the config `[sql] driver` switches between them.
- connection uses `SERVER=10.0.0.246,1435` + `Trusted_Connection=yes`. allowed databases: TUBC and TUCSH only - the relay's allowlist hard-blocks production UBC/UCSH. TUBC is the primary testing ground.
- the shared secret lives in a gitignored `config.toml`, never in the repo or logs.

workflow 1, PO creation - PROVEN (the eConnect orchestration, as actually built)

- PO number: UC Nexus supplies its own (e.g. `ucnexus0000001`, which GP stores uppercase) and the relay passes it through; or omit it and the relay reserves GP's next `PO` number via `taGetPONextNumber`. a rolled-back create leaks no number - the increment rolls back with the transaction.
- session needs `SET NOCOUNT ON` first, or `taPoHdr` / the wsi proc fail at the pyodbc layer ("No results. Previous SQL was not a query.").
- `taPoHdr` (no SUBTOTAL) creates the header (POSTATUS=2, Released).
- `taPoLine` x N creates lines with `@I_vPOLNESTA=2` (Released - load-bearing) and `NONINVEN=1`. read back each line against `POP10110` to catch the silent-failure mode (err=0 but no row).
- `wsiWSCreateUpdatePurchaseOrderIntegration` x N for EVERY line (taPoLine can't set Product_Indicator): PI=1 on non-inv lines, PI=2 + `JOBNUMBR` + cost-code split + `Cost_Element` on job lines, and commits cost to `WS10101` / `JC00102` / `JC00701`. cost code `210-200-2` splits to `Cost_Code_Number_1=210`, `Cost_Code_Number_2=200`, `Cost_Element=2` - the trailing digit is the cost ELEMENT, not COSTTYPE (which stays 0). job cost only commits when the line is POLNESTA=2.
- `taPoHdr` again (`UpdateIfExists=1`, computed SUBTOTAL) sets the header total.
- everything wraps in one transaction; roll back on any failure.
- TUBC test values: vendor `ING100`, buyer `mira`, item `HARDWARE-PO03` (PI=1) or any non-inv string, job `80003` + a cost code like `210-200-2` / `510-000-5` / `610-000-6` (PI=2), location `VANCOUVER`, uofm `Each`, currency `CAD`.
- the two unknowns are resolved: the wsi proc does NOT set `POPCONTNUM` (stays blank); SUBTOTAL is set correctly by the second `taPoHdr` (step five, kept). details in `localhost-relay.md`.

workflow 2, receiving - PROVEN (receive against the PO from workflow 1, as actually built)

- reference: the deprecated app's live path, `UC Connects source code/PM_Project_Tracking/DataClasses/EConnect/PopRcptLineInsert.cs`.
- reserve a receipt number via `taGetPurchReceiptNextNumber` (Inc_Dec=1) - the eConnect equivalent of the SDK `GetNextPOPReceiptNumber`. like the PO number, the increment rolls back with the transaction (no manual decrement needed).
- ORDER MATTERS: call `taPopRcptLineInsert` for each line BEFORE `taPopRcptHdrInsert`. eConnect processes receipt lines first; header-first makes the line a duplicate (error 8053 "duplicate document"). this is the OPPOSITE of PO create, which is header-first.
- `taPopRcptLineInsert` x N: `POPTYPE=1`, `POPRCTNM`, `PONUMBER`, `POLNENUM` (= the `POP10110.ORD` being received), `ITEMNMBR`, `VENDORID`, `VNDITNUM`, `UOFM`, `JOBNUMBR`, `LOCNCODE`, `NONINVEN`, `QTYSHPPD`=qty received, `AUTOCOST=1`, `UNITCOST=0`/`EXTDCOST=0` (GP autocosts from the PO line). `RCPTLNNM` steps by 16384.
- `taPopRcptHdrInsert` LAST: `POPTYPE=1`, `VNDDOCNM`=the PO number, `receiptdate`, `BACHNUMB` (`EC-yyyy/MM/dd`), `VENDORID`, and `SUBTOTAL` = the sum of the autocosted line totals (received qty x PO unit cost). `SUBTOTAL=0` fails with error 2006 "Subtotal does not match the line item totals" on direct proc calls (the legacy's 0 worked only because eConnect's XML envelope recomputes it).
- everything in one transaction. verify the receipt landed in `POP10300`/`POP10310` and `POP10500`.
- the receipt sits in a GP batch (`BACHNUMB`) that a user posts inside GP. the PO line's `LSTRCPTDT` only populates after that batch posts.

sequencing and safety gates

- read-only first: connect, confirm identity and database, discover the receipt-number proc and the receipt proc param sets, sample reference data. no writes.
- pause for explicit user authorization before the first `taGetPONextNumber` (advances the PO sequence), before the first PO create, and before the first receipt. TUBC is a sandbox and safe to manipulate, but each first write still gets an explicit OK.
- after the first authorized create, resolve the two unknowns with the read-only queries and write the outcome into `localhost-relay.md`.

what the POC must prove

- [DONE] a real PO in TUBC: header released with correct SUBTOTAL and CONFIRM1/VADCDPAD/SHIPMTHD, non-inv and job-cost lines with correct PI/NONINVEN/JOBNUMBR/COSTCODE, and `WS10101` + `JC00102`/`JC00701` committed. proven on PO0000044 and UCNEXUS0000001 (still wants a human GP-side eyeball once TUBC access is granted).
- [DONE] a real receipt in TUBC against that PO, verified in `POP10500`, with received quantities correct. RC0000038 received PO0000044 (both lines, qty 1 each), autocosted 33.00/555.00, in batch EC-2026/06/24 awaiting a GP-side post.
- [DONE] pyodbc-direct confirmed equivalent for PO create AND receiving - no transaction-nesting or silent-failure surprises once `SET NOCOUNT ON` / `POLNESTA=2` (create) and lines-before-header / matching SUBTOTAL (receiving) were in place. no need to fall back to the .NET SDK.

after the POC

- the relay is scaffolded at `relay/`; the proven proc-call code lives in `src/ucnexus_relay/`. both POC workflows (PO create + receiving) are proven; what remains is the human GP-side eyeball (pending TUBC access) and production hardening.
- production hardening (dedicated service account, distribution, auto-start) stays as the follow-ups already listed at the end of `localhost-relay.md`.
