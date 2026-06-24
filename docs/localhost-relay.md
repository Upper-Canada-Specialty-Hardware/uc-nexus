# Localhost Relay — POC Plan & Implementation Reference

**Status: design finalized — pure Python relay calling eConnect-registered stored procedures directly via `pyodbc`.**

The relay calls Microsoft-provided eConnect procs (`taGetPONextNumber`, `taPoHdr`, `taPoLine`) and WennSoft-provided eConnect-style procs (`wsiWSCreateUpdatePurchaseOrderIntegration`) via parameterized SQL EXEC, wrapped in a single transaction per PO. **No direct UPDATE/INSERT against GP tables** — only invocation of eConnect-registered procs, which is what enforces GP's business logic.

Earlier design iterations considered using Microsoft's `.NET` API (`eConnectMethods.CreateEntity()`) via pythonnet, but were dropped because:
- The .NET DLL is a thin XML-parsing + proc-routing wrapper; the business logic lives entirely in the SQL procs themselves
- Calling the same procs via `pyodbc.execute("{CALL dbo.taPoHdr ...}")` produces identical end-state on the database
- Avoiding the .NET DLL eliminates: .NET runtime dependency, pythonnet bridge, eConnect DLLs to ship, and the admin-one-time Windows Event Log source registration
- Stays in single-language Python tech stack matching UC Nexus

**Versions in scope** (verified against `DYNAMICS.WS_VHIST` and `DYNAMICS.DU000020`):
- **Microsoft Dynamics GP**: 2018 R2, build 18.00.0628 (eConnect API at version 18.0)
- **WennSoft Signature**: 2018 R3, build `18.00b03g0310`, modules `JC/SMS` (Job Cost + Service Management Suite)

**Reference documentation:**
- [WennSoft Signature Integration Technical Reference](https://docs.wennsoft.com/1803b05/signature-integration-technical-reference) — closest published version (Signature 2020); wsi proc parameter sets match our installed 2018 R3 build
- [`wsiWSCreateUpdatePurchaseOrderIntegration` proc page](https://docs.wennsoft.com/1803b05/wsiwscreateupdatepurchaseorderintegration) — official parameter list, affected tables, error codes
- [WennSoft Signature Nodes Reference (SmartConnect)](https://docs.wennsoft.com/1803b05/signature-nodes-reference) — lists "WS Purchase Orders" as the SmartConnect-friendly node name
- [WennSoft Customer Portal](https://www.wennsoft.com/wsportal/home) — login required; deeper SmartConnect Integration Manager guides live behind it
- Microsoft eConnect XSD + XML samples at `docs/econnect-reference/` — extracted locally; useful for confirming parameter sets per proc
- WennSoft proc signatures saved at `docs/wennsoft-procs/` for offline reference

## Contents

1. [What we're building (POC scope)](#what-were-building-poc-scope)
2. [How the relay talks to GP](#how-the-relay-talks-to-gp)
3. [Architecture decisions](#architecture-decisions)
4. [API surface](#api-surface-poc)
5. [The eConnect orchestration](#the-econnect-orchestration)
6. [Configuration](#configuration)
7. [Project layout](#project-layout-poc)
8. [Implementation phases](#implementation-phases)
9. [What this POC unblocks for UC Nexus](#what-this-poc-unblocks-for-uc-nexus)
10. [Open questions / decisions before coding](#open-questions--decisions-before-coding)
11. [Risks and mitigations](#risks-and-mitigations)
12. [Definition of done](#definition-of-done-poc)
13. [Appendix: Concrete handoff](#appendix-concrete-handoff)

---

## What we're building (POC scope)

A small Windows application that runs on the user's machine, listens for HTTP requests from UC Nexus (in their browser), and forwards them to GP via SQL EXEC calls against the eConnect-registered stored procedures. For the POC, the relay supports one operation end-to-end: **create a PO and return the assigned PO number**.

```
┌──────────────────────────┐
│  UC Nexus (browser)      │
│  https://ucnexus.app     │
└──────────────────────────┘
          │
          │  fetch('http://localhost:7321/po', {...})
          ▼
┌──────────────────────────┐
│  Localhost Relay         │
│  http://localhost:7321   │   ◄── Python + FastAPI, single process
│                          │
│  Calls eConnect procs    │
│  via pyodbc EXEC:        │
│   • taGetPONextNumber    │
│   • taPoHdr              │
│   • taPoLine             │
│   • wsiWSCreateUpdate... │
│                          │
│  All within one BEGIN    │
│  TRAN / COMMIT scope     │
└──────────────────────────┘
          │
          │  TDS / SSPI / TLS over TCP 1435 (via pyodbc + ODBC Driver 18)
          ▼
┌──────────────────────────┐
│  UCSHSQL2\MSSQL2014      │
│  eConnect procs execute  │
│  with full business      │
│  logic firing:           │
│   POP10100, POP10110,    │
│   WS10101, JC00102,      │
│   JC00701, etc.          │
└──────────────────────────┘
          │
          ▼
   PO created, number returned to UC Nexus
```

### What's in scope for POC
- Single Windows machine
- Single GP company (start with `TUBC` for testing, swappable to UBC/UCSH later)
- eConnect calls: `taGetPONextNumber`, `taPoHdr`, `taPoLine`, `wsiWSCreateUpdatePurchaseOrderIntegration`
- Simple shared-secret auth between UC Nexus and the relay
- CORS configured for the UC Nexus origin
- Basic structured logging
- Manual start/stop (no Windows service yet)

### What's out of scope for POC
- Real UC Nexus UI integration (just expose the API contract; UC Nexus calls it later)
- Production-grade authentication (no token rotation, no pairing flow yet)
- Installer / auto-start / Windows service registration
- Multi-user / multi-company logic
- Receipt creation, PO updates, anything beyond create-PO
- Retry logic beyond basic try/catch
- Health monitoring / telemetry

### Hard rules

1. **All GP writes go through eConnect-registered stored procedures** — `taPo*`, `taGetPONextNumber`, `wsiWS*`. No direct `UPDATE`/`INSERT`/`DELETE` against any GP table. The procs are what fire GP's business logic (validation, hooks, triggers, downstream updates). Calling the procs via pyodbc EXEC is equivalent to calling them via Microsoft's .NET API — same procs, same business logic, same end state.
2. **Read-only against the SQL Server during development** until the user explicitly authorizes a write. Each first live proc call against TUBC needs explicit OK before the agent runs it.

---

## How the relay talks to GP

Standard SQL Server client/server communication, no .NET in the call chain.

```
Python relay code
   ↓
pyodbc                          (Python wrapper around the ODBC API)
   ↓
ODBC Driver 18 for SQL Server   (msodbcsql18.dll — Microsoft's ODBC driver)
   ↓
TDS protocol over TCP           (port 1435 — the MSSQL2014 named instance)
   ↓ wrapped in TLS 1.2
   ↓ authenticated via Windows SSPI (Kerberos preferred, NTLM fallback)
   ↓
SQL Server engine
   ↓
EXEC dbo.taPoHdr / dbo.taPoLine / dbo.wsiWSCreateUpdatePurchaseOrderIntegration
   ↓
GP business logic fires:
  • The procs' own validation
  • Pre/Post hooks (stock empty at this customer)
  • Triggers on POP10100/POP10110 (verified: zero fire on insert at this customer)
  • Downstream table updates: WS10101, JC00102, JC00701, SV000810 (per WennSoft docs)
```

**Key facts:**
- **Protocol on the wire**: TDS 7.4. Stored proc calls are sent as TDS RPC requests with typed parameters — not text SQL strings — so there's no SQL injection risk from the parameter values.
- **Port**: TCP 1435 (named-instance port we discovered via SQL Browser service).
- **Encryption**: TLS 1.2 — ODBC Driver 18 defaults to `Encrypt=yes`.
- **Authentication**: Windows Integrated Auth via SSPI. The relay process runs as a Windows user, and SQL Server inherits that user's identity via Kerberos/NTLM. **No password is stored anywhere.**

**Why this is equivalent to Microsoft's .NET eConnect API:**

The Microsoft .NET DLL (`Microsoft.Dynamics.GP.eConnect.dll`) internally does the following when you call `CreateEntity(connStr, xml)`:
1. Parses the XML
2. Opens a SqlConnection using `connStr`
3. For each `<taXxx>` element: builds an `EXEC dbo.taXxx @I_v... = ?, ...` command and executes it
4. Wraps everything in a transaction
5. Translates output param errors to `eConnectException`
6. Logs to Windows Event Log

The relay does steps 2-5 directly via pyodbc, skips step 1 (we build params from our typed Python models), and skips step 6 (we use structured logging instead). The actual SQL procs invoked are identical. Business logic fires identically. **The .NET DLL is a convenience wrapper — not a business-logic boundary.**

---

## Architecture decisions

### Why pure Python (no .NET dependency)

The relay needs to:
1. Receive HTTP requests from UC Nexus (browser)
2. Validate request shape
3. Call eConnect-registered stored procedures with the right parameters
4. Return the result

Pure Python with pyodbc accomplishes all four. We considered three alternatives and rejected them:

| Approach | Why we didn't pick it |
|---|---|
| **C# / .NET relay** using `eConnectMethods.CreateEntity()` natively | Diverges from UC Nexus's Python stack; team would need to maintain two language ecosystems for one component |
| **Python + pythonnet** loading the eConnect DLL | Adds .NET runtime dependency, pythonnet bridge, eConnect DLLs to ship, and a Windows Event Log source registration requiring admin one-time per machine. All overhead for zero functional benefit — the DLL is plumbing, not business logic. |
| **Direct UPDATE on POP tables** (the earlier abandoned spike) | Bypasses the procs, which means bypassing GP's business logic. The procs are what enforce validation, fire triggers, and update downstream tables (WS10101, JC00102, etc.). |

Pure Python via pyodbc: calls the same procs as the .NET API, satisfies the "use eConnect" requirement (eConnect is the procs, not the DLL), keeps the team in one language, and minimizes deployment dependencies (just `pyodbc` + ODBC Driver 18 — the latter is a single MSI from Microsoft).

### Why HTTP-on-localhost (not WebSocket, not custom protocol)
- Simplest possible model for a browser to talk to a local app
- Modern browsers treat `http://localhost` as a secure context — no mixed-content warnings even when called from `https://`
- Standard tooling, easy to debug with curl / Postman / browser devtools
- Maps cleanly to a stateless request/response

### Why a fixed port (`7321`)
- UC Nexus needs to know the URL ahead of time
- 4-digit, non-system, not in IANA's well-known list, mnemonic ("seven-three-twenty-one")
- If the port is in use on a given machine, the relay should fail loudly at startup

### Authentication model

Two layers:

**Layer 1 — Shared secret (Bearer token)**
- A random secret is generated at install
- The same secret is configured in UC Nexus per user
- Every request from UC Nexus includes `Authorization: Bearer <secret>`
- For POC: secret in `config.toml`. Production would use Windows DPAPI.

**Layer 2 — Origin restriction via CORS**
- The relay only accepts cross-origin requests from configured UC Nexus URLs
- Browsers enforce this — non-UC-Nexus pages can't make authenticated requests even if they know the token

For POC this is sufficient. Production would add token rotation, pairing flow, etc.

---

## API surface (POC)

All endpoints under `http://localhost:7321/`. JSON request/response. Bearer token required (except `/health`).

### `GET /health`
Liveness probe. No auth.

```json
{
  "status": "ok",
  "version": "0.1.0",
  "uptime_seconds": 3421
}
```

### `GET /info`
Configuration introspection. Auth required.

```json
{
  "version": "0.1.0",
  "configured_companies": ["TUBC"],
  "sql_server": "UCSHSQL2\\MSSQL2014",
  "connected_as": "UPPERCANADA\\jayp",
  "default_company": "TUBC",
  "odbc_driver": "ODBC Driver 18 for SQL Server"
}
```

### `POST /po/next-number`
Reserve and return the next PO number. Auth required.

Internally executes `EXEC dbo.taGetPONextNumber @I_vInc_Dec=1, @O_vPONUMBER=? OUTPUT, @O_iErrorState=? OUTPUT` via pyodbc.

```json
// Request
{ "company": "TUBC" }

// Response 200
{ "po_number": "PO0000041", "company": "TUBC" }
```

### `POST /po`
Create a PO end-to-end. Auth required.

```json
// Request
{
  "company": "TUBC",
  "header": {
    "vendor_id": "ING100",
    "buyer_id": "mira",
    "confirm_with": "Greg Sutton",
    "doc_date": "2026-05-20",
    "currency_id": "CAD",
    "vendor_address_code": "PRIMARY",
    "shipping_method": "LOCAL DELIVERY"
  },
  "lines": [
    {
      "item_number": "HARDWARE-PO03",
      "item_description": "Painted 2670 HMD - Alpaca",
      "quantity": 1,
      "unit_cost": 50.87,
      "location_code": "VANCOUVER",
      "uofm": "Each",
      "product_indicator": 1
    },
    {
      "item_number": "JOB-LINE-TEST",
      "item_description": "Job-cost item",
      "quantity": 1,
      "unit_cost": 1.00,
      "location_code": "VANCOUVER",
      "uofm": "Each",
      "product_indicator": 2,
      "job_number": "80003",
      "cost_code": "210-200-2"
    }
  ]
}

// Response 201
{
  "po_number": "PO0000041",
  "company": "TUBC",
  "lines_created": 2,
  "subtotal": 51.87,
  "doc_date": "2026-05-20",
  "vendor_id": "ING100"
}

// Response 400 — Pydantic validation error (caught before any SQL)
{
  "error": "validation_error",
  "message": "Job-cost lines (product_indicator=2) require both job_number and cost_code",
  "field": "lines[0]"
}

// Response 502 — eConnect proc returned a non-zero error_state
{
  "error": "econnect_error",
  "proc": "taPoLine",
  "error_state": 9127,
  "error_description": "Duplicate Order"
}

// Response 401
{ "error": "unauthorized" }
```

---

## The eConnect orchestration

The relay performs a sequence of eConnect proc calls per PO, all wrapped in a single transaction:

| Step | Proc | Purpose |
|---|---|---|
| 1 | `taGetPONextNumber` | Reserve next PO number |
| 2 | `taPoHdr` | Create PO header (without SUBTOTAL on first call) |
| 3 | `taPoLine` (× N) | Create each line item |
| 4 | `wsiWSCreateUpdatePurchaseOrderIntegration` (× M) | For each job-cost line, populate the WennSoft job-cost fields on POP10110 + write to WS10101, JC00102, JC00701 |
| 5 | `taPoHdr` (with `UpdateIfExists=1`) | Re-call with computed SUBTOTAL to update the header total |

All five steps happen inside one `BEGIN TRAN` / `COMMIT` (or `ROLLBACK` on any failure).

**Why two calls to `taPoHdr`?** eConnect's `taPoHdr` validates `@I_vSUBTOTAL` against the current sum of line totals in `POP10110`. On the first call, no lines exist yet, so we must pass `SUBTOTAL=0` (or omit it). After all lines are inserted (steps 3-4), we re-call `taPoHdr` with `UpdateIfExists=1` and the real subtotal. This is how the .NET `CreateEntity` ultimately handles it too — by sequencing the proc calls correctly internally.

### Connection setup (`db.py`)

```python
import pyodbc
from contextlib import contextmanager

def build_conn_string(company: str) -> str:
    return (
        "DRIVER={ODBC Driver 18 for SQL Server};"
        "SERVER=UCSHSQL2\\MSSQL2014;"
        f"DATABASE={company};"
        "Trusted_Connection=yes;"      # Windows auth via SSPI
        "Encrypt=yes;"
        "TrustServerCertificate=yes;"  # internal CA — fine for POC
        "Connection Timeout=10;"
    )

@contextmanager
def get_connection(company: str):
    conn = pyodbc.connect(build_conn_string(company), autocommit=False)
    conn.timeout = 30  # query timeout in seconds
    try:
        yield conn
    finally:
        conn.close()
```

`autocommit=False` is critical — we want explicit transaction control so we can roll back if any proc call fails.

### Step 1: `taGetPONextNumber`

```python
class EConnectError(Exception):
    def __init__(self, message: str, proc: str, error_state: int = 0):
        super().__init__(message)
        self.proc = proc
        self.error_state = error_state

def get_next_po_number(conn) -> str:
    """Reserve the next PO number. Increments POP40100.PONUMBER as a side effect.
    Note: this increment is OUTSIDE the caller's transaction — gaps in the PO sequence
    on rollback are normal and expected in GP."""
    sql = """
    DECLARE @po_number varchar(17) = '';
    DECLARE @error_state int = 0;
    EXEC dbo.taGetPONextNumber
        @I_vInc_Dec    = 1,
        @O_vPONUMBER   = @po_number OUTPUT,
        @O_iErrorState = @error_state OUTPUT;
    SELECT @po_number AS po_number, @error_state AS error_state;
    """
    row = conn.cursor().execute(sql).fetchone()
    if row.error_state != 0:
        raise EConnectError("taGetPONextNumber failed", proc="taGetPONextNumber",
                            error_state=row.error_state)
    return row.po_number.strip()
```

### Step 2: `taPoHdr` (initial create, no SUBTOTAL)

```python
from datetime import date

def create_po_header(
    conn,
    *,
    po_number: str,
    vendor_id: str,
    doc_date: date,
    buyer_id: str,
    confirm_with: str,
    currency_id: str = "CAD",
    vendor_address_code: str = "PRIMARY",
    shipping_method: str = "LOCAL DELIVERY",
    po_status: int = 2,         # 2=Released
    po_type: int = 1,
) -> None:
    """Create PO header via taPoHdr. SUBTOTAL is NOT passed here — eConnect would
    validate it against line totals (which are zero pre-insert). It's set in Step 5
    via a second taPoHdr call with UpdateIfExists=1."""
    sql = """
    DECLARE @err int = 0;
    DECLARE @err_str varchar(255) = '';
    EXEC dbo.taPoHdr
        @I_vPOTYPE         = ?,
        @I_vPONUMBER       = ?,
        @I_vVENDORID       = ?,
        @I_vDOCDATE        = ?,
        @I_vBUYERID        = ?,
        @I_vCURNCYID       = ?,
        @I_vPOSTATUS       = ?,
        @I_vCONFIRM1       = ?,
        @I_vVADCDPAD       = ?,
        @I_vSHIPMTHD       = ?,
        @I_vUpdateIfExists = 1,
        @O_iErrorState     = @err OUTPUT,
        @oErrString        = @err_str OUTPUT;
    SELECT @err AS error_state, @err_str AS err_string;
    """
    row = conn.cursor().execute(
        sql,
        po_type, po_number, vendor_id, doc_date, buyer_id, currency_id,
        po_status, confirm_with, vendor_address_code, shipping_method,
    ).fetchone()
    if row.error_state != 0:
        raise EConnectError(
            f"taPoHdr failed: {row.err_string.strip()}",
            proc="taPoHdr", error_state=row.error_state,
        )
```

### Step 3: `taPoLine` (× N)

```python
from decimal import Decimal

def create_po_line(
    conn,
    *,
    po_number: str,
    doc_date: date,
    vendor_id: str,
    item_number: str,
    item_description: str,
    quantity: Decimal,
    unit_cost: Decimal,
    location_code: str = "VANCOUVER",
    uofm: str = "Each",
    po_type: int = 1,
) -> None:
    """Create one PO line via taPoLine.

    Note: this creates a basic non-inventoried line. For job-cost lines,
    follow up with apply_wennsoft_job_cost() to set JOBNUMBR/COSTCODE/Product_Indicator
    via the wsi proc. Do NOT pass ProjNum/CostCatID — they fail silently at this
    customer because PA42201 doesn't exist (Project Accounting module not configured)."""
    sql = """
    DECLARE @err int = 0;
    DECLARE @err_str varchar(255) = '';
    EXEC dbo.taPoLine
        @I_vPOTYPE         = ?,
        @I_vPONUMBER       = ?,
        @I_vDOCDATE        = ?,
        @I_vVENDORID       = ?,
        @I_vNONINVEN       = 1,
        @I_vUpdateIfExists = 1,
        @I_vLOCNCODE       = ?,
        @I_vITEMNMBR       = ?,
        @I_vITEMDESC       = ?,
        @I_vQUANTITY       = ?,
        @I_vUOFM           = ?,
        @I_vUNITCOST       = ?,
        @O_iErrorState     = @err OUTPUT,
        @oErrString        = @err_str OUTPUT;
    SELECT @err AS error_state, @err_str AS err_string;
    """
    row = conn.cursor().execute(
        sql,
        po_type, po_number, doc_date, vendor_id,
        location_code, item_number, item_description,
        quantity, uofm, unit_cost,
    ).fetchone()
    if row.error_state != 0:
        raise EConnectError(
            f"taPoLine failed for {item_number}: {row.err_string.strip()}",
            proc="taPoLine", error_state=row.error_state,
        )
    # Defensive read-back: taPoLine has known silent-failure modes
    # (e.g., passing ProjNum/CostCatID against missing PA42201 returns err=0
    # but doesn't insert). Verify the row landed.
    verify = conn.cursor().execute(
        "SELECT COUNT(*) AS n FROM dbo.POP10110 WHERE PONUMBER = ? AND ITEMNMBR = ?",
        po_number, item_number,
    ).fetchone()
    if verify.n == 0:
        raise EConnectError(
            f"taPoLine returned err=0 but no row inserted for {item_number} (silent failure)",
            proc="taPoLine", error_state=0,
        )
```

### Step 4: `wsiWSCreateUpdatePurchaseOrderIntegration` (× M, only for job-cost lines)

Reference: [official docs page](https://docs.wennsoft.com/1803b05/wsiwscreateupdatepurchaseorderintegration). Affected tables (per docs): `WS10101, SV00300, JC00102, JC00701, PM00200, IV00101, POP10100, POP10110`.

This proc sets `Product_Indicator=2`, `JOBNUMBR`, and `COSTCODE` on the POP10110 line, plus updates the WennSoft tables (WS10101 for integration tracking, JC00102/JC00701 for Job Cost commitments).

```python
def apply_wennsoft_job_cost(
    conn,
    *,
    po_number: str,
    line_ord: int,        # GP's line ordering value (16384 for line 1, 32768 for line 2, ...)
    job_number: str,
    cost_code: str,       # format: 'phase-step-type', e.g. '210-200-2'
) -> None:
    """Apply WennSoft Job Cost fields to a PO line via the wsi eConnect-style proc.

    Cost code parsing for this customer (verified against JC00701):
      '210-200-2' splits into:
        Cost_Code_Number_1 = '210' (Phase, 3 chars)
        Cost_Code_Number_2 = '200' (Step, 3 chars)
        Cost_Code_Number_3 = ''    (unused at this customer)
        Cost_Code_Number_4 = ''    (unused at this customer)
        COSTTYPE = 2               (the trailing digit — smallint)
    """
    segments = cost_code.split("-") + ["", "", "", ""]
    cc1, cc2, cc3, cc_type_str = segments[0], segments[1], segments[2], segments[2]
    # The third hyphen-segment is COSTTYPE (smallint), not Cost_Code_Number_3
    try:
        cost_type = int(cc_type_str) if cc_type_str else 0
    except ValueError:
        cost_type = 0
    cc3_val = ""  # this customer only uses 2 segments
    cc4_val = ""

    sql = """
    DECLARE @err int = 0;
    DECLARE @err_str varchar(305) = '';
    EXEC dbo.wsiWSCreateUpdatePurchaseOrderIntegration
        @I_vPONUMBER           = ?,
        @I_vORD                = ?,
        @I_vProduct_Indicator  = 2,
        @I_vJOBNUMBR           = ?,
        @I_vCOSTTYPE           = ?,
        @I_vCost_Code_Number_1 = ?,
        @I_vCost_Code_Number_2 = ?,
        @I_vCost_Code_Number_3 = ?,
        @I_vCost_Code_Number_4 = ?,
        @I_vWennSoftTablesOnly = 0,
        @I_vUpdateIfExists     = 1,
        @I_vOnlyValidate       = 0,
        @I_vReturnErrorText    = 1,
        @O_iErrorState         = @err OUTPUT,
        @oErrString            = @err_str OUTPUT;
    SELECT @err AS error_state, @err_str AS err_string;
    """
    row = conn.cursor().execute(
        sql,
        po_number, line_ord, job_number, cost_type,
        cc1, cc2, cc3_val, cc4_val,
    ).fetchone()
    if row.error_state != 0:
        raise EConnectError(
            f"wsiWSCreateUpdatePurchaseOrderIntegration failed for line ORD={line_ord}: {row.err_string.strip()}",
            proc="wsiWSCreateUpdatePurchaseOrderIntegration",
            error_state=row.error_state,
        )
```

**Documented error codes** for this proc (from public docs):

| Code | Meaning |
|---|---|
| 51013, 51016 | Service call missing |
| 51018 | Cost code absent |
| 51052 | Integration table insert failure |
| 51054 | Retention >100% |
| 51094 | Inactive job |
| 51098 | PO doesn't exist (would fire if called before taPoHdr/taPoLine inserts the line) |
| 52017 | Job missing |

### Step 5: Re-call `taPoHdr` with computed SUBTOTAL

```python
def update_po_header_subtotal(
    conn,
    *,
    po_number: str,
    vendor_id: str,
    doc_date: date,
    buyer_id: str,
    confirm_with: str,
    subtotal: Decimal,
    currency_id: str = "CAD",
    vendor_address_code: str = "PRIMARY",
    shipping_method: str = "LOCAL DELIVERY",
    po_status: int = 2,
    po_type: int = 1,
) -> None:
    """Re-call taPoHdr with UpdateIfExists=1 and the computed SUBTOTAL.
    eConnect now validates SUBTOTAL against the line totals that exist
    (inserted in steps 3-4); they should match."""
    sql = """
    DECLARE @err int = 0;
    DECLARE @err_str varchar(255) = '';
    EXEC dbo.taPoHdr
        @I_vPOTYPE         = ?,
        @I_vPONUMBER       = ?,
        @I_vVENDORID       = ?,
        @I_vDOCDATE        = ?,
        @I_vBUYERID        = ?,
        @I_vCURNCYID       = ?,
        @I_vPOSTATUS       = ?,
        @I_vCONFIRM1       = ?,
        @I_vVADCDPAD       = ?,
        @I_vSHIPMTHD       = ?,
        @I_vSUBTOTAL       = ?,
        @I_vUpdateIfExists = 1,
        @O_iErrorState     = @err OUTPUT,
        @oErrString        = @err_str OUTPUT;
    SELECT @err AS error_state, @err_str AS err_string;
    """
    row = conn.cursor().execute(
        sql,
        po_type, po_number, vendor_id, doc_date, buyer_id, currency_id,
        po_status, confirm_with, vendor_address_code, shipping_method, subtotal,
    ).fetchone()
    if row.error_state != 0:
        raise EConnectError(
            f"taPoHdr (subtotal update) failed: {row.err_string.strip()}",
            proc="taPoHdr", error_state=row.error_state,
        )
```

### Error code translation (`errors.py`)

The relay should translate eConnect numeric error codes to human-readable text using `DYNAMICS.dbo.taErrorCode`:

```python
def lookup_error_description(conn, error_code: int) -> str | None:
    """DYNAMICS.taErrorCode is the central error lookup (9,407 entries)."""
    row = conn.cursor().execute(
        "SELECT ErrorDesc FROM DYNAMICS.dbo.taErrorCode WHERE ErrorCode = ?",
        error_code,
    ).fetchone()
    return row.ErrorDesc.strip() if row else None
```

### Full orchestration: `POST /po` handler (`main.py`)

```python
from fastapi import Depends, FastAPI, HTTPException
import pyodbc
from . import db, econnect, models, auth, errors

app = FastAPI()

@app.post("/po", response_model=models.CreatePoResponse, status_code=201)
def create_po(
    request: models.CreatePoRequest,
    _=Depends(auth.verify_token),
):
    """Create a complete PO via eConnect-registered stored procedures.
    All-or-nothing transaction."""
    try:
        with db.get_connection(request.company) as conn:
            try:
                # Step 1: reserve PO number
                po_number = econnect.get_next_po_number(conn)

                # Step 2: create header (no SUBTOTAL — see Step 5)
                econnect.create_po_header(
                    conn,
                    po_number=po_number,
                    vendor_id=request.header.vendor_id,
                    doc_date=request.header.doc_date,
                    buyer_id=request.header.buyer_id,
                    confirm_with=request.header.confirm_with,
                    currency_id=request.header.currency_id,
                    vendor_address_code=request.header.vendor_address_code,
                    shipping_method=request.header.shipping_method,
                )

                # Step 3: create each line
                for line in request.lines:
                    econnect.create_po_line(
                        conn,
                        po_number=po_number,
                        doc_date=request.header.doc_date,
                        vendor_id=request.header.vendor_id,
                        item_number=line.item_number,
                        item_description=line.item_description,
                        quantity=line.quantity,
                        unit_cost=line.unit_cost,
                        location_code=line.location_code,
                        uofm=line.uofm,
                    )

                # Step 4: for each job-cost line, apply WennSoft Job Cost data
                for line_index, line in enumerate(request.lines, start=1):
                    if line.product_indicator == 2:
                        econnect.apply_wennsoft_job_cost(
                            conn,
                            po_number=po_number,
                            line_ord=line_index * 16384,
                            job_number=line.job_number,
                            cost_code=line.cost_code,
                        )

                # Step 5: re-call taPoHdr with the computed SUBTOTAL
                subtotal = sum(line.quantity * line.unit_cost for line in request.lines)
                econnect.update_po_header_subtotal(
                    conn,
                    po_number=po_number,
                    vendor_id=request.header.vendor_id,
                    doc_date=request.header.doc_date,
                    buyer_id=request.header.buyer_id,
                    confirm_with=request.header.confirm_with,
                    currency_id=request.header.currency_id,
                    vendor_address_code=request.header.vendor_address_code,
                    shipping_method=request.header.shipping_method,
                    subtotal=subtotal,
                )

                # All good — commit the whole transaction
                conn.commit()

                return models.CreatePoResponse(
                    po_number=po_number,
                    company=request.company,
                    lines_created=len(request.lines),
                    subtotal=subtotal,
                    doc_date=request.header.doc_date,
                    vendor_id=request.header.vendor_id,
                )

            except econnect.EConnectError as e:
                conn.rollback()
                # Translate the error code to a readable description if possible
                desc = errors.lookup_error_description(conn, e.error_state) if e.error_state else None
                raise HTTPException(
                    status_code=502,
                    detail={
                        "error": "econnect_error",
                        "proc": e.proc,
                        "error_state": e.error_state,
                        "error_description": desc or str(e),
                    },
                )
            except Exception:
                conn.rollback()
                raise
    except pyodbc.Error as e:
        raise HTTPException(
            status_code=502,
            detail={"error": "sql_error", "message": str(e)},
        )
```

### Pydantic models for the API contract (`models.py`)

```python
from datetime import date
from decimal import Decimal
from pydantic import BaseModel, Field, model_validator

class POLine(BaseModel):
    item_number: str = Field(..., max_length=30)
    item_description: str = Field(..., max_length=100)
    quantity: Decimal
    unit_cost: Decimal
    location_code: str = "VANCOUVER"
    uofm: str = "Each"
    product_indicator: int = 1   # 1=Non-Inventoried, 2=Job Cost
    job_number: str | None = None
    cost_code: str | None = None  # format: 'phase-step-type' e.g. '210-200-2'

    @model_validator(mode="after")
    def check_job_cost_consistency(self):
        if self.product_indicator == 2:
            if not self.job_number or not self.cost_code:
                raise ValueError("Job-cost lines (product_indicator=2) require both job_number and cost_code")
        elif self.product_indicator == 1:
            if self.job_number or self.cost_code:
                raise ValueError("Non-inventoried lines (product_indicator=1) must not have job_number or cost_code")
        else:
            raise ValueError(f"product_indicator must be 1 or 2 (got {self.product_indicator})")
        return self

class POHeader(BaseModel):
    vendor_id: str = Field(..., max_length=15)
    buyer_id: str = Field(..., max_length=15)
    confirm_with: str = Field(..., max_length=20)
    doc_date: date
    currency_id: str = "CAD"
    vendor_address_code: str = "PRIMARY"
    shipping_method: str = "LOCAL DELIVERY"

class CreatePoRequest(BaseModel):
    company: str
    header: POHeader
    lines: list[POLine] = Field(..., min_length=1)

class CreatePoResponse(BaseModel):
    po_number: str
    company: str
    lines_created: int
    subtotal: Decimal
    doc_date: date
    vendor_id: str
```

---

## Configuration

### `config.toml`

```toml
[server]
host = "127.0.0.1"
port = 7321

[auth]
shared_secret = "REPLACE_ME_RANDOM_TOKEN"

[cors]
allowed_origins = [
  "https://ucnexus-frontend-production.up.railway.app",
  "http://localhost:5173"
]

[sql]
server = "UCSHSQL2\\MSSQL2014"
driver = "ODBC Driver 18 for SQL Server"
trusted_connection = true
encrypt = "yes"
trust_server_certificate = true
connection_timeout = 10
command_timeout = 30

[gp]
default_company = "TUBC"
allowed_companies = ["TUBC"]

[logging]
level = "INFO"
file = "relay.log"
```

### Where the config file lives
- POC: same directory as the executable, e.g., `relay/config.toml`
- Production later: `%LOCALAPPDATA%\UCNexusRelay\config.toml`

---

## Project layout (POC)

```
ucnexus-relay/
├── pyproject.toml              # Poetry project file
├── README.md                   # how to run it
├── config.toml                 # actual runtime config (gitignored)
├── config.example.toml         # template checked into git
├── relay.log                   # runtime log file (gitignored)
├── src/
│   ├── ucnexus_relay/
│   │   ├── __init__.py
│   │   ├── main.py             # FastAPI app, route definitions
│   │   ├── config.py           # config loading + validation (Pydantic Settings)
│   │   ├── auth.py             # bearer-token check
│   │   ├── cors.py             # CORS middleware setup
│   │   ├── db.py               # pyodbc connection factory
│   │   ├── econnect.py         # the 5 proc wrappers (taGetPONextNumber, taPoHdr,
│   │   │                       # taPoLine, wsiWSCreate..., taPoHdr subtotal update)
│   │   ├── errors.py           # error code lookup against DYNAMICS.taErrorCode
│   │   ├── models.py           # Pydantic request/response models
│   │   └── logging_setup.py    # structured logging config
└── tests/
    ├── test_health.py
    ├── test_auth.py
    └── test_econnect_smoke.py  # smoke test against TUBC
```

No `lib/` folder — no .NET DLLs to ship.

---

## Implementation phases

### Phase 1 — Skeleton + auth + health (≤ 1 day)
1. `pyproject.toml` with dependencies: `fastapi`, `uvicorn`, `pyodbc`, `pydantic`, `pydantic-settings`, `python-json-logger`
2. `main.py` with a FastAPI app, `/health` endpoint
3. `auth.py` with a Bearer-token dependency
4. `cors.py` with FastAPI's built-in `CORSMiddleware`
5. `config.py` loading from `config.toml`
6. Run with `uvicorn src.ucnexus_relay.main:app --host 127.0.0.1 --port 7321`
7. Verify with curl from another shell

### Phase 2 — `taGetPONextNumber` end-to-end (≤ 1 day)
1. Install ODBC Driver 18 for SQL Server (one-time MSI from Microsoft)
2. `db.py` with `get_connection(company)` factory using pyodbc + Windows auth
3. Sanity test: open a connection, run `SELECT @@VERSION` (read-only — no auth needed)
4. `econnect.py` with `get_next_po_number(conn)` calling the proc
5. `POST /po/next-number` endpoint
6. **End-to-end test (requires user authorization for the first live eConnect call)**: hit `/po/next-number`, verify it returns a PO number, verify in TUBC that `POP40100.PONUMBER` advanced (read-only check)

### Phase 3 — `POST /po` end-to-end (≤ 2 days)
1. Pydantic models for request/response in `models.py`, including the strict PI↔JOBNUMBR invariant
2. `econnect.py` adds the 4 remaining proc wrappers (`create_po_header`, `create_po_line`, `apply_wennsoft_job_cost`, `update_po_header_subtotal`)
3. `errors.py` to translate eConnect error codes via `DYNAMICS.taErrorCode`
4. `POST /po` endpoint orchestrating the 5 steps in a single transaction
5. **End-to-end test (requires user authorization for the first live PO create)**: post a valid PO with both non-inv and job-cost lines; verify field-by-field parity against an existing TUBC PO using the read-only verification queries in the appendix
6. **Phase 3 verification gate** — the resulting PO must match what a macro-produced PO looks like:
   - `POP10100`: POSTATUS=2 (Released), SUBTOTAL populated correctly, CONFIRM1/VADCDPAD/SHIPMTHD set
   - `POP10110` job-cost lines: Product_Indicator=2, NONINVEN=1, JOBNUMBR populated, COSTCODE populated
   - `WS10101`: rows inserted linking PO line to WennSoft integration
   - `JC00102`/`JC00701`: committed cost updated for the job
7. **Resolve the known unknowns** — see "Resolving the two known unknowns in Phase 3" below.

### Resolving the two known unknowns in Phase 3

The plan has two open questions that can only be answered by inspecting the database after the first successful Phase 3 create. Both are simple read-only checks. Do them right after your first authorized PO create, before declaring Phase 3 done.

#### Unknown #1: Does the wsi proc populate `POPCONTNUM` automatically?

**Why it matters**: stock `taPoHdr` has no parameter for `POPCONTNUM`. The wsi proc updates `POP10100` as one of its affected tables (per WennSoft docs), so it MIGHT set `POPCONTNUM = JOBNUMBR` as a side effect. If yes, we don't need a separate mechanism. If no, we need to decide whether the customer requires this field (the macro-produced reference PO0000025 had `POPCONTNUM='RTLORD-000007'` — different value pattern, possibly customer convention rather than required).

**How to verify** (after your first authorized job-cost PO create — substitute your new PO number):

```sql
SELECT RTRIM(PONUMBER) AS po, RTRIM(POPCONTNUM) AS pop_contract
FROM TUBC.dbo.POP10100
WHERE PONUMBER = '<your_new_PO>';
```

**Interpret the result**:

| `POPCONTNUM` value | Conclusion | Action |
|---|---|---|
| Equals the JOBNUMBR we sent (e.g., `80003`) | wsi proc sets it as side effect | Document this. Relay needs no extra logic. |
| Empty / blank | wsi proc doesn't touch it | Defer to the customer: do they need POPCONTNUM populated for their downstream workflows? If yes, escalate as a follow-up (no eConnect-registered proc exposes it; would need WennSoft support to identify the right mechanism). If no, leave it. |
| Some other value | Unexpected — investigate | Read WennSoft docs / customer portal; may indicate a customer-specific configuration setting. |

#### Unknown #2: Does the wsi proc set `POP10100.SUBTOTAL` automatically?

**Why it matters**: Step 5 in our orchestration re-calls `taPoHdr` with `UpdateIfExists=1` and computed SUBTOTAL. If the wsi proc already updates SUBTOTAL as a side effect, Step 5 is redundant and can be dropped from the orchestration (saving one proc call per PO).

**How to verify** (after your first authorized job-cost PO create — substitute your new PO number):

Run this query in two phases of the test:
1. **Before Step 5**: temporarily comment out the `update_po_header_subtotal()` call in `main.py`, run a fresh PO create, then query:
```sql
SELECT RTRIM(PONUMBER) AS po, SUBTOTAL, REMSUBTO
FROM TUBC.dbo.POP10100
WHERE PONUMBER = '<your_new_PO>';
```
2. **Compare to expected**: SUBTOTAL should equal `SUM(EXTDCOST) FROM POP10110 WHERE PONUMBER = <new_PO>`.

**Interpret the result**:

| `SUBTOTAL` after Step 4 (no Step 5) | Conclusion | Action |
|---|---|---|
| Matches sum of line ext-costs | wsi proc updates SUBTOTAL | **Drop Step 5** from the orchestration. Update `main.py` to remove `update_po_header_subtotal()` call. Update doc to reflect 4-step orchestration. |
| Stays at 0 (or original taPoHdr value) | wsi proc doesn't touch SUBTOTAL | **Keep Step 5** as-is. Document that the second `taPoHdr` call is required. Restore the `update_po_header_subtotal()` call. |
| Some other value | Unexpected — investigate | Likely a partial update; inspect what fields changed vs didn't, may indicate the wsi proc has a different update mode. |

**Either way, document the outcome in this file** (in the "Verified facts" section) so future maintainers don't have to re-derive it.

### Phase 4 — Polish (≤ 1 day)
1. Structured logging — every request logged with timestamp, endpoint, status, duration
2. Better error responses (consistent shape across endpoints)
3. README with run instructions
4. Optional: PyInstaller spec to produce `ucnexus-relay.exe` for one-machine install demo

**Total POC time estimate: ~4-5 working days** including testing.

---

## What this POC unblocks for UC Nexus

Once Phase 3 is working, UC Nexus's PO-creation feature can:
1. POST PO data to the relay
2. Get back a real GP PO number in 1-2 seconds
3. Show that number in the UI
4. Save it to UC Nexus's own database for tracking

UC Nexus only needs to know:
- The relay's URL (`http://localhost:7321`)
- The user's shared-secret token
- The request schema for `POST /po`

The user's experience: fill out a PO in UC Nexus → click Submit → done.

---

## Open questions / decisions before coding

Two known unknowns are **load-bearing for the implementation** but answerable only by inspecting the database after a Phase 3 test:
- Does the wsi proc set `POPCONTNUM` automatically?
- Does the wsi proc set `POP10100.SUBTOTAL` automatically (which would make Step 5 unnecessary)?

Both have their resolution protocols (specific queries + decision tables) in "Resolving the two known unknowns in Phase 3" above. The agent should run these checks immediately after the first authorized PO create and document the outcomes.

Beyond those, here are the design decisions that don't need investigation — defaults are in parentheses:

1. **Sandbox company**: TUBC. (Confirmed accessible to your account; eConnect procs verified present; sequence runs independently from production UBC/UCSH.)
2. **Auth pairing flow**: For POC, static shared secret in `config.toml`? (Recommended.)
3. **Partial-failure handling**: If Step 4 (wsi) fails after Step 3 (taPoLine) succeeded, the `BEGIN TRAN`/`ROLLBACK` reverses POP10100/POP10110 inserts. The only thing that persists is the consumed PO number from `taGetPONextNumber` (which advances outside the transaction — gaps are normal in GP).
4. **How does UC Nexus know whether the relay is installed?** Background `fetch('http://localhost:7321/health')` on the PO page, banner if missing. POC can skip.
5. **Relay distribution**: For POC, `git clone + poetry install + python -m uvicorn ...` on one dev machine. PyInstaller `.exe` is Phase 4. Real installer (MSI) is post-POC.

---

## Risks and mitigations

| Risk | Mitigation |
|---|---|
| Browser blocks the cross-origin request to localhost | Configure CORS correctly; test from a deployed UC Nexus URL early in Phase 1 |
| Windows Defender / corporate firewall blocks the relay's port | Document that port 7321 needs to be allowed for inbound localhost; run as user-mode (no admin) |
| ODBC Driver 18 not installed on the user's machine | One-time install per machine (free MSI from Microsoft); document as a prerequisite. Detect at startup via `pyodbc.drivers()` and fail with a clear error. |
| User's Windows credentials don't have GP access | Surface a clear error from `/info` like `"connection_failed: <message>"` so UC Nexus can show "ask your DBA for GP access" |
| Two relays on the same machine collide on port 7321 | Detect at startup, fail with clear "port in use" message; let user override port via config |
| eConnect proc returns `err=0` but row never inserts (silent failure — verified for `taPoLine` with `ProjNum`/`CostCatID` against missing `PA42201`) | Defensive read-back: after each `taPoLine`, query `POP10110` to confirm the row exists. The wrapper includes this check. |
| `taPoHdr` rejects SUBTOTAL because it doesn't match lines | Split into two calls: initial taPoHdr without SUBTOTAL → lines → re-call taPoHdr with `UpdateIfExists=1` and correct SUBTOTAL (Step 5 in the orchestration) |
| Partial failure: PO header created but job-cost wsi call fails | Wrapped in single `BEGIN TRAN`; `ROLLBACK` undoes the inserts. Only side effect is the consumed PO number from `taGetPONextNumber` (which is outside the transaction — leaves a gap, which is normal in GP). |
| Decimal precision drift between Python and SQL | pyodbc auto-converts Python `Decimal` to SQL `decimal(19,5)` correctly. Use `Decimal(str(value))` rather than `Decimal(float)` when constructing values from JSON to avoid float intermediate precision loss. |

---

## Definition of done (POC)

- [ ] `python -m ucnexus_relay` starts the relay on `http://localhost:7321`
- [ ] `GET /health` returns 200 with version info
- [ ] `GET /info` returns the configured company list, authenticated user, and ODBC driver version
- [ ] `POST /po/next-number` returns the next PO number from TUBC via `taGetPONextNumber`
- [ ] `POST /po` creates a real PO in TUBC with header + 1-3 lines (mix of non-inv and job-cost) via the 5-step orchestration
- [ ] `POP40100.PONUMBER` in TUBC has advanced after a successful create
- [ ] `POP10100` / `POP10110` in TUBC contain the new PO when queried directly, with all parity fields populated (subtotal, status=Released, JOBNUMBR/COSTCODE/Product_Indicator on job-cost lines)
- [ ] `WS10101` has new rows linking the new PO to WennSoft integration (verifies the wsi proc fired correctly)
- [ ] `JC00102` / `JC00701` reflect updated committed cost for any jobs the new PO is attached to
- [ ] An invalid request (bad vendor, missing job number, etc.) returns a clean 4xx with a useful error message; the transaction is rolled back so no partial PO remains
- [ ] Auth: requests without a valid bearer token return 401
- [ ] CORS: requests from a non-allowed origin are rejected
- [ ] Basic structured log file shows every request with status and duration
- [ ] **NO direct `UPDATE`/`INSERT`/`DELETE` anywhere in the codebase against any GP table.** Every GP write goes through an EXEC of an eConnect-registered proc (`taPo*`, `taGetPONextNumber`, `wsiWS*`).
- [ ] A short README explains how to run it locally

---

# Appendix: Concrete handoff

## Hard rule for the implementing agent

**Read-only against the SQL Server until the user explicitly authorizes a write.** The agent can:
- Build the entire relay code base
- Run unit tests that mock pyodbc
- Manually test against `/health`, `/info` (these don't touch GP)
- Sample TUBC data via `SELECT` queries for fixtures and verification

The agent **must not**:
- Run `EXEC dbo.taGetPONextNumber` against TUBC without explicit user authorization (it increments `POP40100.PONUMBER`)
- Run `EXEC dbo.taPoHdr` / `EXEC dbo.taPoLine` / `EXEC dbo.wsiWSCreateUpdatePurchaseOrderIntegration` without authorization
- Use `BEGIN TRAN / EXEC / ROLLBACK` patterns to "test without writing" — even rolled-back transactions advance the PO sequence and can fire triggers
- Perform any `INSERT` / `UPDATE` / `DELETE` / DDL against any GP database

When the agent reaches Phase 2 (first live `taGetPONextNumber` call) or Phase 3 (first live PO create), they pause for user authorization. After validation, the user can grant standing authorization for further TUBC iteration.

See `feedback_econnect_only_no_direct_sql.md` and `feedback_gp_readonly_discovery.md` in memory for the full rules.

## Repo location

Recommend a **new sibling folder at the top of the UC Nexus monorepo**:

```
UC Nexus/
├── backend/                  ← existing FastAPI service
├── frontend/                 ← existing React app
├── relay/                    ← NEW — the localhost relay
│   ├── pyproject.toml
│   ├── src/ucnexus_relay/
│   └── ...
├── docs/                     ← existing docs
└── ...
```

## Tooling and versions

| Tool | Pinned version | Notes |
|---|---|---|
| Python | **3.11.x** | Matches `backend/`. |
| Package manager | **Poetry 1.8+** | Matches `backend/`. |
| FastAPI | `^0.115` | |
| Uvicorn | `^0.32` | |
| Pydantic | `^2.9` | v2 is current. Uses `model_validator` and `str \| None`. |
| pydantic-settings | `^2.6` | For TOML/env-based config. |
| **pyodbc** | `^5.2` | SQL Server driver. |
| python-json-logger | `^2.0` | Structured logging. |

`pyproject.toml`:

```toml
[tool.poetry]
name = "ucnexus-relay"
version = "0.1.0"
description = "Localhost relay bridging UC Nexus (cloud) to GP via eConnect stored procedures"
authors = ["UC Nexus Team"]
package-mode = false

[tool.poetry.dependencies]
python = "^3.11"
fastapi = "^0.115"
uvicorn = {extras = ["standard"], version = "^0.32"}
pydantic = "^2.9"
pydantic-settings = "^2.6"
pyodbc = "^5.2"
python-json-logger = "^2.0"

[tool.poetry.group.dev.dependencies]
pytest = "^8.3"
httpx = "^0.27"
ruff = "^0.7"

[build-system]
requires = ["poetry-core"]
build-backend = "poetry.core.masonry.api"
```

## ODBC Driver 18 for SQL Server

Required on every machine where the relay runs.

**Download**: https://learn.microsoft.com/en-us/sql/connect/odbc/download-odbc-driver-for-sql-server

Pick "ODBC Driver 18 for SQL Server" — the x64 MSI installer. Install with defaults. No reboot needed.

**Verification** (from PowerShell):
```powershell
Get-OdbcDriver -Name "ODBC Driver 18 for SQL Server"
```
Should print one row with `Platform: 64-bit`.

**Detect from Python at startup**:
```python
import pyodbc
if not any("ODBC Driver 18 for SQL Server" in d for d in pyodbc.drivers()):
    raise RuntimeError("ODBC Driver 18 for SQL Server is required — install from Microsoft")
```

**Connection sanity test** (still read-only — no eConnect calls):
```python
import pyodbc
conn = pyodbc.connect(
    "DRIVER={ODBC Driver 18 for SQL Server};"
    "SERVER=UCSHSQL2\\MSSQL2014;"
    "DATABASE=TUBC;"
    "Trusted_Connection=yes;"
    "Encrypt=yes;"
    "TrustServerCertificate=yes;"
)
print(conn.cursor().execute("SELECT @@VERSION, SUSER_NAME(), DB_NAME()").fetchone())
conn.close()
```

If this fails, every later step will too — fix the driver / network / auth before continuing.

## Reference materials (in this repo)

- `docs/econnect-reference/POPTransaction.xsd` — Microsoft's official eConnect schema. Lists ALL parameters available for `taPoHdr` and `taPoLine` (we only use a subset). Useful when extending the relay to handle additional fields.
- `docs/econnect-reference/POP_Purchase_Order-Multi_Line.xml` — sample 2-line PO XML envelope. Shows the shape Microsoft's .NET API would build internally. The procs we call directly handle the same parameters.
- `docs/econnect-reference/csharp_console_sample.cs` — Microsoft's official C# sample for `CreateEntity`. Reference for understanding the documented pattern. Our Python implementation calls the same procs with the same parameters but skips the .NET XML-serialization step.
- `docs/econnect-reference/csharp_GetNextDocumentNumber/` — Microsoft's official C# sample for `GetNextDocNumbers.GetNextPONumber`. The underlying SQL proc is `taGetPONextNumber` which is what we call directly.
- `docs/wennsoft-procs/wsiWSCreateUpdatePurchaseOrderIntegrationPre.sql` and `Post.sql` — the WennSoft Pre/Post hook bodies (the main proc itself is encrypted but the hooks are stock empty at this customer).
- `docs/wennsoft-procs/SVC_POP_Make_PO.sql` — readable WennSoft PO-create proc body (different code path, but informative for understanding patterns).

## CORS configuration

```python
ALLOWED_ORIGINS = [
    "https://ucnexus-frontend-production.up.railway.app",
    "http://localhost:5173",
    "http://localhost:8000",
]
```

```python
from fastapi.middleware.cors import CORSMiddleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Authorization", "Content-Type"],
)
```

## Shared secret generation

```python
import secrets
print(secrets.token_urlsafe(32))
```

Paste the output into both `relay/config.toml` (under `[auth]`) and UC Nexus's config.

## Logging setup

```python
import logging
from pythonjsonlogger import jsonlogger

def configure_logging(level: str = "INFO", file_path: str = "relay.log"):
    handler = logging.FileHandler(file_path)
    handler.setFormatter(jsonlogger.JsonFormatter(
        "%(asctime)s %(levelname)s %(name)s %(message)s"
    ))
    root = logging.getLogger()
    root.setLevel(level)
    root.addHandler(handler)
    console = logging.StreamHandler()
    console.setFormatter(jsonlogger.JsonFormatter(
        "%(asctime)s %(levelname)s %(name)s %(message)s"
    ))
    root.addHandler(console)
```

Use FastAPI middleware for per-request logging:
```python
import time
@app.middleware("http")
async def log_requests(request, call_next):
    start = time.perf_counter()
    response = await call_next(request)
    duration_ms = (time.perf_counter() - start) * 1000
    logger.info("request", extra={
        "method": request.method,
        "path": request.url.path,
        "status": response.status_code,
        "duration_ms": round(duration_ms, 1),
    })
    return response
```

## Concrete test values for TUBC

All values verified read-only against `TUBC` on 2026-05-07.

| Field | Verified values | Source |
|---|---|---|
| Vendor IDs (`VENDORID`) | `DAY200`, `ING100`, `ASS102`, `BOB100`, `GAL100` | `TUBC.dbo.PM00200` |
| Buyer ID (`BUYERID`) | `mira` | `TUBC.dbo.POP10100.BUYERID` |
| Location code (`LOCNCODE`) | `VANCOUVER` | `TUBC.dbo.IV40700` |
| Currency ID (`CURNCYID`) | `CAD` | `TUBC.dbo.POP10110.CURNCYID` |
| Unit of measure (`UOFM`) | `Each` | `TUBC.dbo.POP10110.UOFM` |
| Item number (`ITEMNMBR`) — for PI=1 | `HARDWARE-PO03`, `ABC TEST ITEM`, `STOCK-PO02`, `NONSTOCK-HD` | `TUBC.dbo.POP10110.ITEMNMBR` |
| Vendor address code (`VADCDPAD`) | `PRIMARY` | `TUBC.dbo.PM00300` |
| Shipping method (`SHIPMTHD`) | `LOCAL DELIVERY` | observed |
| Confirm With (`CONFIRM1`) | free text — observed: `MARY`, `Greg Sutton` | observed |
| Job number (`JOBNUMBR`) — for PI=2 | `80003` | observed in PI=2 rows |
| Cost code — for PI=2 | `210-200-2` (parses to: cc1='210', cc2='200', cc3='', cc4='', COSTTYPE=2) | observed; verified split via `JC00701` |
| Next PO number | as of 2026-05-07: `PO0000041` (advances on each `taGetPONextNumber` call) | `TUBC.dbo.POP40100` |

## Verified working test PO request

```json
{
  "company": "TUBC",
  "header": {
    "vendor_id": "ING100",
    "buyer_id": "mira",
    "confirm_with": "Greg Sutton",
    "doc_date": "2026-05-20",
    "currency_id": "CAD",
    "vendor_address_code": "PRIMARY",
    "shipping_method": "LOCAL DELIVERY"
  },
  "lines": [
    {
      "item_number": "HARDWARE-PO03",
      "item_description": "*** UC NEXUS POC TEST - line 1 non-inv ***",
      "quantity": 1,
      "unit_cost": 50.87,
      "location_code": "VANCOUVER",
      "uofm": "Each",
      "product_indicator": 1
    },
    {
      "item_number": "JOB-LINE-TEST",
      "item_description": "*** UC NEXUS POC TEST - line 2 job cost ***",
      "quantity": 1,
      "unit_cost": 1.00,
      "location_code": "VANCOUVER",
      "uofm": "Each",
      "product_indicator": 2,
      "job_number": "80003",
      "cost_code": "210-200-2"
    }
  ]
}
```

Expected outcome on success: new rows in `POP10100` (header, status=Released, subtotal=51.87), `POP10110` (two lines — line 1 at ORD=16384 non-inventoried, line 2 at ORD=32768 job-cost with Product_Indicator=2, JOBNUMBR='80003', COSTCODE='210-200-2'), `WS10101` (Signature integration tracking for both lines), `JC00102`/`JC00701` (committed cost updated for job 80003).

## Sample curl commands

```bash
# Health
curl http://localhost:7321/health

# Info
curl -H "Authorization: Bearer $TOKEN" http://localhost:7321/info

# Get next PO number (Phase 2)
# AGENT: requires user authorization for the first run
curl -X POST -H "Authorization: Bearer $TOKEN" \
     -H "Content-Type: application/json" \
     -d '{"company":"TUBC"}' \
     http://localhost:7321/po/next-number

# Create a PO (Phase 3)
# AGENT: requires user authorization for the first run
curl -X POST -H "Authorization: Bearer $TOKEN" \
     -H "Content-Type: application/json" \
     -d @test-po.json \
     http://localhost:7321/po
```

## Verification queries (read-only)

After a successful create, the agent can confirm what landed in the database:

```sql
-- Did the next-PO-number advance?
SELECT RTRIM(PONUMBER) AS next_po, RTRIM(PO_Code) AS prefix
FROM TUBC.dbo.POP40100;

-- Header check
SELECT TOP 5 RTRIM(PONUMBER) AS po, POSTATUS, SUBTOTAL,
       RTRIM(CONFIRM1) AS confirm_with, RTRIM(POPCONTNUM) AS pop_contract,
       RTRIM(VADCDPAD) AS vendor_addr, RTRIM(SHIPMTHD) AS ship_method,
       RTRIM(BUYERID) AS buyer, HOLD, RTRIM(CURNCYID) AS cur, DEX_ROW_TS
FROM TUBC.dbo.POP10100
ORDER BY DEX_ROW_TS DESC;

-- Lines check (including WennSoft job-cost fields)
SELECT ORD, RTRIM(ITEMNMBR) AS item, QTYORDER, UNITCOST, EXTDCOST,
       Product_Indicator, NONINVEN, RTRIM(JOBNUMBR) AS job, RTRIM(COSTCODE) AS cc
FROM TUBC.dbo.POP10110
WHERE PONUMBER = '<your_new_PO>'
ORDER BY ORD;

-- WennSoft integration table — should have rows for the new PO (this is the
-- proof that the wsi proc fired, since direct UPDATE wouldn't populate this)
SELECT TOP 5 * FROM TUBC.dbo.WS10101 WHERE WS_PO_Number = '<your_new_PO>'
ORDER BY DEX_ROW_TS DESC;

-- After a failed/rolled-back create, confirm no orphan rows remain
SELECT COUNT(*) FROM TUBC.dbo.POP10100 WHERE PONUMBER = '<failed_PO>';
SELECT COUNT(*) FROM TUBC.dbo.POP10110 WHERE PONUMBER = '<failed_PO>';
SELECT COUNT(*) FROM TUBC.dbo.WS10101 WHERE WS_PO_Number = '<failed_PO>';
```

Run via pyodbc from a Python REPL, or via Azure Data Studio if you have it.

## How the agent should sequence work

| Phase | What's safe to do | What needs user auth |
|---|---|---|
| 1 — Skeleton, auth, health | All of Phase 1 — no GP interaction | None |
| 2 — pyodbc + `taGetPONextNumber` | Code, unit tests, ODBC driver install, read-only connection test | **First live `taGetPONextNumber` call against TUBC** |
| 3 — Full `POST /po` | Code, unit tests, request validation | **First live PO create against TUBC** |
| 4 — Polish | Logging, README — no GP interaction | None |

When the agent reaches a "first live call" gate, agent stops and asks: *"Phase X code is complete and tested with mocks. Authorizing one live eConnect call against TUBC will [advance POP40100.PONUMBER by 1 / create one PO]. OK to proceed?"*

After the first authorized run, the user can grant standing approval for further TUBC iteration.

## Verified facts (carry forward from earlier discovery)

These were established read-only and remain valid:

1. **eConnect Pre/Post hooks at this site are stock empty** (verified by reading `sys.sql_modules` for `taPoHdrPre`, `taPoHdrPost`, `taPoLinePre`, `taPoLinePost`). Microsoft's documented eConnect behavior applies verbatim.

2. **WennSoft Service Management module is unused** at this customer (zero rows in SVC00200 / SVC06100 / SV00300 / SVC00998). The Service Management triggers (`tr_SVC_POP10110_*`) wouldn't fire on inserts even if they were INSERT triggers, because they short-circuit on `if not exists(select * from SVC00998) return`.

3. **WennSoft is actively used for Job/Project Cost** (the project-entity layer GP doesn't natively support). The `wsiWSCreateUpdatePurchaseOrderIntegration` proc is the eConnect-style entry point for setting Product_Indicator/JOBNUMBR/COSTCODE on PO lines, plus updating WS10101/JC00102/JC00701. We have EXECUTE permission. Body is encrypted (proprietary WennSoft IP) but parameter signature matches the public docs.

4. **The PO sequence (POP40100.PONUMBER) increments outside the caller's transaction** — gaps from failed creates are normal and accepted in GP. The relay should not try to "undo" a consumed number on failure.

5. **PI ↔ JOBNUMBR invariant in production data**: PI=2 lines (Job Cost) ALL have JOBNUMBR populated; PI=1 lines (Non-Inventoried) ALL have empty JOBNUMBR. Pydantic models enforce this before we even open a SQL connection.

6. **The 2 macro-driven `.mac` files** correspond to: (a) `multiplePOGet.mac` reserves a PO number by tabbing through GP's UI then cancelling — the eConnect equivalent is `taGetPONextNumber`. (b) `GPPOmacro.mac` fills out the full PO including project linkage — the eConnect equivalent is `taPoHdr` + `taPoLine` + `wsiWSCreateUpdatePurchaseOrderIntegration` per job-cost line.

7. **Cost code structure at this customer**: `'phase-step-type'` like `'210-200-2'`. Splits to wsi proc params as: `Cost_Code_Number_1='210'`, `Cost_Code_Number_2='200'`, `Cost_Code_Number_3=''`, `Cost_Code_Number_4=''`, `COSTTYPE=2`. Confirmed by reading `JC00701` directly for job 80003 — segments 3 and 4 are blank for every cost code at this customer.

## Open follow-ups for the user (not the agent)

1. **Production service account** — the relay should NOT use personal AD credentials in production. A dedicated SQL login with EXECUTE on the eConnect surface (`taPo*`, `taGetPONextNumber`, `wsiWS*`) and SELECT on `DYNAMICS.taErrorCode` is the right shape. DBA conversation.
2. **Distribution mechanism** — PyInstaller `.exe` for early adopters; MSI installer or Group Policy for wider rollout. Includes ODBC Driver 18 as a prerequisite.
3. **Auto-start** — should the relay launch on user logon? Recommended for usability.
4. **WennSoft customer portal access** — request login at [www.wennsoft.com/wsportal/home](https://www.wennsoft.com/wsportal/home). Useful for deeper integration docs if questions come up during Phase 3.
5. **If Unknown #1 (POPCONTNUM) resolves to "not set automatically"** — escalate to the customer: do they need POPCONTNUM populated for their downstream workflows? If yes, this requires further WennSoft-side investigation (no eConnect-registered proc directly exposes this field). The agent should NOT add direct UPDATE as a workaround.
