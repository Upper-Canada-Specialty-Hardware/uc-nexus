# Relay POC - next steps

what we have to prove, and how, before scaffolding the localhost relay. companion to `localhost-relay.md` (the full design) and the `UC Connects source code/UC Connects code review/` library (the deprecated app's as-built behaviour).

where the relay POC stands today

- discovery and planning are complete. the design is `localhost-relay.md`. decided with the user: pure-python relay, pyodbc-direct EXEC of the eConnect procs (not the .NET SDK), PO-creation first.
- the deprecated app (`docs/UC Connects source code`, solution PM_Project_Tracking) is confirmed owner of PMUCSH/PMUBC and is what UC Nexus replaces. its only live GP writeback is receipts; its PO-create path is a dead developer test stub. so the relay's PO-create path - and especially the job-cost path that 87% of real lines use - has no working reference and must be proven live.
- the gate before any scaffolding: a tested POC proving two workflows against the TUBC sandbox, chained -
  1. PO creation end to end
  2. receiving end to end (receive against the PO created in #1)

auth is the blocker, not the network

- the GP SQL server (`UCSHSQL2\MSSQL2014`, `10.0.0.246:1435`) is reachable from this dev machine over wifi - tcp 1435 is open.
- this machine is not domain-joined (`LEGION7I\jaymi`). windows/SSPI auth fails before the server evaluates anything: `Cannot generate SSPI context (1312)`. that is a client-side credential failure (no domain logon session to build a token from), not a network limit and not an eConnect limit.
- eConnect is not a separate network service - it is stored procedures inside the SQL database. talking to it = authenticating to SQL and running EXEC. so auth is the whole gate, including for read-only discovery.

three ways past the auth blocker

1. a SQL login (cleanest for letting the agent run and iterate here). a DBA creates a SQL Server login, maps it as a user in TUBC, and adds it to DYNGRP (the same access the windows account already inherits). requires the server to be in mixed mode - unverified; the first connection attempt reveals it. connect with `SERVER=10.0.0.246,1435` + uid/pwd.
2. `runas /netonly` as `UPPERCANADA\jayp`. reuses existing domain access, no DBA, no new login - but the process must be launched with jayp's domain password interactively, so the user drives each run.
3. move development to a domain-joined machine on that network. matches the relay's real auth (`Trusted_Connection` as jayp, already in DYNGRP), nothing to manage; the user runs the scripts there.

lean toward option 1 if a SQL login can be obtained, since it keeps the agent in the run/verify loop. otherwise option 3.

local prerequisites if running on this machine

- pyodbc: installed.
- ODBC Driver 18 for SQL Server: not installed. needed (admin MSI, `winget install Microsoft.msodbcsql.18`). the ancient built-in `SQL Server` driver connects but defaults to old TLS, so it is only good for a smoke test.
- connection uses `SERVER=10.0.0.246,1435` because the hostname `UCSHSQL2` does not resolve off-domain. database `TUBC`.
- credentials and connection details live in a gitignored config or env var, never in the repo or logs.

workflow 1, PO creation (the five-step eConnect orchestration)

- `taGetPONextNumber` reserves the PO number. it advances `POP40100.PONUMBER` outside the caller's transaction, so a gap on failure is normal.
- `taPoHdr` (no SUBTOTAL) creates the header.
- `taPoLine` x N creates lines, mixing non-inventoried (PI=1) and job-cost (PI=2). read back each line against `POP10110` to catch eConnect's silent-failure mode (err=0 but no row).
- `wsiWSCreateUpdatePurchaseOrderIntegration` x M for job-cost lines: sets `Product_Indicator=2` / `JOBNUMBR` / `COSTCODE` and writes `WS10101` / `JC00102` / `JC00701`. cost code `210-200-2` splits to `Cost_Code_Number_1=210`, `Cost_Code_Number_2=200`, `COSTTYPE=2`.
- `taPoHdr` again (`UpdateIfExists=1`, computed SUBTOTAL) sets the header total.
- everything wraps in one transaction; roll back on any failure.
- TUBC test values: vendor `ING100`, buyer `mira`, item `HARDWARE-PO03` (PI=1), job `80003` + cost code `210-200-2` (PI=2), location `VANCOUVER`, uofm `Each`, currency `CAD`.
- two load-bearing unknowns resolvable only after the first live create: does the wsi proc set `POPCONTNUM`, and does it set `SUBTOTAL` (which would make step five redundant). resolution queries are in `localhost-relay.md`; record the outcome there.

workflow 2, receiving (receive against the PO from workflow 1)

- the reference is the deprecated app's live path, `UC Connects source code/PM_Project_Tracking/DataClasses/EConnect/PopRcptLineInsert.cs`.
- reserve a receipt number. the legacy app uses the SDK `GetNextPOPReceiptNumber`; the equivalent eConnect proc to call directly via pyodbc is still to be confirmed read-only against the server (search `sys.procedures` for `taGet%` / `%Rcpt%` / `%Receipt%`).
- `taPopRcptHdrInsert` creates the receipt header: `POPTYPE=1`, `VNDDOCNM`=the PO number, `receiptdate`, `BACHNUMB` (the legacy convention is `EC-yyyy/MM/dd`), `VENDORID`, `SUBTOTAL=0`.
- `taPopRcptLineInsert` x N creates receipt lines: `POPTYPE=1`, `POPRCTNM`, `POLNENUM` (= the `POP10110.ORD` being received), `LOCNCODE`, `JOBNUMBR`, `PONUMBER`, `ITEMNMBR`, `VENDORID`, `VNDITNUM`, `AUTOCOST=1`, `UNITCOST=0`, `QTYSHPPD`=qty received, `NONINVEN`, `receiptdate`. `RCPTLNNM` steps by 16384.
- verify `POP10500` has the receipt; roll back the reserved receipt number if it did not land.
- receipts post into a GP batch (`BACHNUMB`) that a user posts inside GP. the PO line's `LSTRCPTDT` only populates after that batch posts.

sequencing and safety gates

- read-only first: connect, confirm identity and database, discover the receipt-number proc and the receipt proc param sets, sample reference data. no writes.
- pause for explicit user authorization before the first `taGetPONextNumber` (advances the PO sequence), before the first PO create, and before the first receipt. TUBC is a sandbox and safe to manipulate, but each first write still gets an explicit OK.
- after the first authorized create, resolve the two unknowns with the read-only queries and write the outcome into `localhost-relay.md`.

what the POC must prove before we scaffold

- a real PO in TUBC: header released with correct SUBTOTAL and CONFIRM1/VADCDPAD/SHIPMTHD, non-inv and job-cost lines with correct PI/NONINVEN/JOBNUMBR/COSTCODE, and `WS10101` + `JC00102`/`JC00701` updated.
- a real receipt in TUBC against that PO, verified in `POP10500`, with received quantities correct.
- pyodbc-direct confirmed equivalent to the SDK path, with no transaction-nesting or silent-failure surprises. if it is not equivalent, fall back to the .NET eConnect SDK (the proven legacy mechanism).

after the POC

- scaffold the relay at `relay/` per `localhost-relay.md` phases 1-4, porting the proven proc-call code from the POC.
- production hardening (dedicated service account, distribution, auto-start) stays as the follow-ups already listed at the end of `localhost-relay.md`.
