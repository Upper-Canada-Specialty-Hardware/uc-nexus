"""The eConnect orchestration: thin pyodbc wrappers around the eConnect-registered
stored procedures. NO direct INSERT/UPDATE/DELETE against GP tables — every write
goes through an EXEC of a Microsoft/WennSoft proc, which is what fires GP's business
logic. This is equivalent to Microsoft's .NET CreateEntity, minus the XML step.

Orchestration (all inside one BEGIN..COMMIT held by the caller's connection):
  1. taGetPONextNumber                          — reserve PO number
  2. taPoHdr (no SUBTOTAL)                       — create header
  3. taPoLine x N                                — create each line
  4. wsiWSCreateUpdatePurchaseOrderIntegration   — job-cost lines: PI=2/JOBNUMBR/COSTCODE + WS10101/JC00102/JC00701
  5. taPoHdr (UpdateIfExists=1, real SUBTOTAL)   — set header total
"""

import re
from datetime import date
from decimal import Decimal

_DB_NAME_RE = re.compile(r"^[A-Za-z0-9_]+$")  # custom_db comes from trusted config, but validate before interpolating


class EConnectError(Exception):
    def __init__(self, message: str, proc: str, error_state: int = 0):
        super().__init__(message)
        self.proc = proc
        self.error_state = error_state


def get_next_po_number(conn) -> str:
    """Reserve the next PO number. Advances POP40100.PONUMBER OUTSIDE the caller's
    transaction — a gap on rollback is normal and accepted in GP."""
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
        raise EConnectError("taGetPONextNumber failed", proc="taGetPONextNumber", error_state=row.error_state)
    return row.po_number.strip()


def assert_po_number_available(conn, po_number: str) -> None:
    """Guard for client-supplied PO numbers: refuse one already used by an active PO.
    (POC checks the live POP10100; production should also check history POP30100/POP30300.)"""
    row = conn.cursor().execute(
        "SELECT COUNT(*) AS n FROM dbo.POP10100 WHERE PONUMBER = ?", po_number
    ).fetchone()
    if row.n:
        raise EConnectError(
            f"PO number '{po_number}' already exists in GP (POP10100)",
            proc="assert_po_number_available", error_state=0,
        )


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
    po_status: int = 2,  # 2 = Released
    po_type: int = 1,
) -> None:
    """Create the PO header. SUBTOTAL is NOT passed here (no lines exist yet);
    it's set by update_po_header_subtotal() after the lines land."""
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
            f"taPoHdr failed: {row.err_string.strip()}", proc="taPoHdr", error_state=row.error_state
        )


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
    """Create one non-inventoried PO line. For job-cost lines, follow with
    apply_wennsoft_job_cost(). Do NOT pass ProjNum/CostCatID — they fail silently
    here (PA42201 absent; Project Accounting not configured)."""
    sql = """
    DECLARE @err int = 0;
    DECLARE @err_str varchar(255) = '';
    EXEC dbo.taPoLine
        @I_vPOTYPE         = ?,
        @I_vPONUMBER       = ?,
        @I_vDOCDATE        = ?,
        @I_vVENDORID       = ?,
        @I_vNONINVEN       = 1,
        @I_vPOLNESTA       = 2,
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
        location_code, item_number, item_description, quantity, uofm, unit_cost,
    ).fetchone()
    if row.error_state != 0:
        raise EConnectError(
            f"taPoLine failed for {item_number}: {row.err_string.strip()}",
            proc="taPoLine", error_state=row.error_state,
        )
    # Defensive read-back: taPoLine has a known err=0-but-no-row silent-failure mode.
    verify = conn.cursor().execute(
        "SELECT COUNT(*) AS n FROM dbo.POP10110 WHERE PONUMBER = ? AND ITEMNMBR = ?",
        po_number, item_number,
    ).fetchone()
    if verify.n == 0:
        raise EConnectError(
            f"taPoLine returned err=0 but no row inserted for {item_number} (silent failure)",
            proc="taPoLine", error_state=0,
        )


def apply_wennsoft_integration(
    conn,
    *,
    po_number: str,
    line_ord: int,  # GP line ordering: 16384 for line 1, 32768 for line 2, ...
    product_indicator: int,  # 1 = non-inventoried, 2 = job cost
    job_number: str | None = None,
    cost_code: str | None = None,  # 'phase-step-element' e.g. '210-200-2'
) -> None:
    """Run the WennSoft wsi proc for ONE PO line. This is how Product_Indicator gets set
    on POP10110 (taPoLine has no such parameter), so it's called for EVERY line to match
    the macro's behaviour:
      - PI=1 (non-inv): Product_Indicator=1, blank job/cost. Creates a WS10101 tracking row.
      - PI=2 (job cost): Product_Indicator=2 + JOBNUMBR + cost-code split + Cost_Element.
        The proc copies UNITCOST/QTYORDER from the POP10110 line into WS10101 and updates
        JC00102/JC00701 committed cost.

    Cost code 'phase-step-element' e.g. '210-200-2' (verified vs JC00701):
      Cost_Code_Number_1='210', Cost_Code_Number_2='200', Cost_Element=2 (the TRAILING digit).
      COSTTYPE stays 0 — every WS10101 row at this customer has COSTTYPE=0; the trailing digit
      is the Cost_Element, not the cost type (the localhost-relay.md doc mislabeled this).
    """
    if product_indicator == 2:
        segs = cost_code.split("-")
        cc1 = segs[0] if len(segs) > 0 else ""
        cc2 = segs[1] if len(segs) > 1 else ""
        try:
            cost_element = int(segs[2]) if len(segs) > 2 and segs[2] else 0
        except ValueError:
            cost_element = 0
        job = job_number or ""
    else:
        cc1 = cc2 = ""
        cost_element = 0
        job = ""
    cc3 = cc4 = ""

    sql = """
    DECLARE @err int = 0;
    DECLARE @err_str varchar(305) = '';
    EXEC dbo.wsiWSCreateUpdatePurchaseOrderIntegration
        @I_vPONUMBER           = ?,
        @I_vORD                = ?,
        @I_vProduct_Indicator  = ?,
        @I_vJOBNUMBR           = ?,
        @I_vCOSTTYPE           = 0,
        @I_vCost_Code_Number_1 = ?,
        @I_vCost_Code_Number_2 = ?,
        @I_vCost_Code_Number_3 = ?,
        @I_vCost_Code_Number_4 = ?,
        @I_vCost_Element       = ?,
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
        po_number, line_ord, product_indicator, job, cc1, cc2, cc3, cc4, cost_element,
    ).fetchone()
    if row.error_state != 0:
        raise EConnectError(
            f"wsiWSCreateUpdatePurchaseOrderIntegration failed for line ORD={line_ord} (PI={product_indicator}): "
            f"{row.err_string.strip()}",
            proc="wsiWSCreateUpdatePurchaseOrderIntegration", error_state=row.error_state,
        )


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
    """Re-call taPoHdr with UpdateIfExists=1 + the computed SUBTOTAL (validated now
    against the line totals from steps 3-4). May be droppable if the wsi proc sets
    SUBTOTAL itself — that's one of the two unknowns to resolve after the first create."""
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


# --- receiving (workflow 2) -------------------------------------------------
# Receive against a PO created in workflow 1. Mirrors the legacy app's live receipt path
# (UC Connects PopRcptLineInsert.cs): reserve a receipt number, insert the receipt header
# (VNDDOCNM = the PO number), then one receipt line per PO line being received with
# AUTOCOST=1 (GP pulls the cost from the PO line, so UNITCOST/EXTDCOST are passed as 0).
# The receipt lands in the receivings WORK tables; a user still posts the BACHNUMB batch
# inside GP to finalize it (that's a GP-side step).


def get_next_receipt_number(conn) -> str:
    """Reserve the next PO-receipt number via taGetPurchReceiptNextNumber. Like the PO number,
    the increment rolls back with the transaction on this pyodbc path."""
    sql = """
    DECLARE @rcpt varchar(17) = '';
    DECLARE @err int = 0;
    EXEC dbo.taGetPurchReceiptNextNumber
        @I_vInc_Dec    = 1,
        @O_vPOPRCTNM   = @rcpt OUTPUT,
        @O_iErrorState = @err OUTPUT;
    SELECT @rcpt AS rcpt, @err AS error_state;
    """
    row = conn.cursor().execute(sql).fetchone()
    if row.error_state != 0:
        raise EConnectError(
            "taGetPurchReceiptNextNumber failed", proc="taGetPurchReceiptNextNumber", error_state=row.error_state
        )
    return row.rcpt.strip()


def read_po_receipt_context(conn, po_number: str):
    """Read-only: (vendor_id, vendor_name, {ord: line_dict}) for building a receipt against a PO.
    Returns (None, None, {}) if the PO header doesn't exist. The client only sends which line ORDs +
    quantities to receive; the per-line item/desc/vendor/job/jobname/location come from POP10110
    (+ JC00102 for the job name) here. The extra description fields feed WHRECLINE101."""
    hdr = conn.cursor().execute(
        "SELECT RTRIM(VENDORID) AS vendor, RTRIM(VENDNAME) AS vendname FROM dbo.POP10100 WHERE PONUMBER = ?",
        po_number,
    ).fetchone()
    if hdr is None:
        return None, None, {}
    lines: dict[int, dict] = {}
    rows = conn.cursor().execute(
        "SELECT l.ORD, RTRIM(l.ITEMNMBR) AS item, RTRIM(l.ITEMDESC) AS itemdesc, RTRIM(l.VENDORID) AS vendor, "
        "RTRIM(l.JOBNUMBR) AS job, RTRIM(j.WS_Job_Name) AS jobname, RTRIM(l.LOCNCODE) AS locn, "
        "l.NONINVEN, RTRIM(l.UOFM) AS uofm, RTRIM(l.VNDITNUM) AS vnditnum, l.QTYORDER, l.UNITCOST, "
        "l.POLNESTA, ISNULL(r.prev_received, 0) AS prev_received "
        "FROM dbo.POP10110 l "
        "LEFT JOIN dbo.JC00102 j ON j.WS_Job_Number = l.JOBNUMBR "
        "LEFT JOIN (SELECT POLNENUM, SUM(QTYSHPPD) AS prev_received FROM dbo.POP10500 "
        "           WHERE PONUMBER = ? GROUP BY POLNENUM) r ON r.POLNENUM = l.ORD "
        "WHERE l.PONUMBER = ? ORDER BY l.ORD",
        po_number, po_number,
    ).fetchall()
    for r in rows:
        lines[int(r.ORD)] = {
            "item": r.item,
            "itemdesc": r.itemdesc,
            "vendor": r.vendor,
            "job": r.job,
            "jobname": r.jobname,
            "locn": r.locn,
            "noninven": int(r.NONINVEN),
            "uofm": r.uofm,
            "vnditnum": r.vnditnum or r.item,  # legacy uses item number when VNDITNUM is blank
            "qtyorder": r.QTYORDER,
            "unitcost": r.UNITCOST,  # AUTOCOST pulls this onto the receipt line; header subtotal must match
            "polnesta": int(r.POLNESTA),  # PO line status; the legacy only receives lines with < 4
            "prev_received": r.prev_received,  # SUM(POP10500.QTYSHPPD) already received against this line
        }
    return hdr.vendor, hdr.vendname, lines


def list_vendors(conn, *, active_only: bool = True) -> list[dict]:
    """Read-only: PM00200 vendor list for the vendor sync (feeds UC Nexus's Vendor.gp_vendor_id).
    Returns VENDORID / VENDNAME / VNDCLSID (class) / VENDSTTS (status). VENDSTTS 1 = active; the
    sync only wants vendors usable on a new PO, so active_only filters to those."""
    sql = (
        "SELECT RTRIM(VENDORID) AS vendor_id, RTRIM(VENDNAME) AS vendor_name, "
        "RTRIM(VNDCLSID) AS vendor_class, VENDSTTS AS status FROM dbo.PM00200 "
    )
    if active_only:
        sql += "WHERE VENDSTTS = 1 "
    sql += "ORDER BY VENDNAME"
    rows = conn.cursor().execute(sql).fetchall()
    return [
        {
            "vendor_id": r.vendor_id,
            "vendor_name": r.vendor_name,
            "vendor_class": r.vendor_class or None,
            "status": int(r.status),
        }
        for r in rows
    ]


def create_receipt_header(conn, *, receipt_number, po_number, vendor_id, receipt_date, batch_number, subtotal) -> None:
    sql = """
    DECLARE @err int = 0;
    DECLARE @err_str varchar(255) = '';
    EXEC dbo.taPopRcptHdrInsert
        @I_vPOPRCTNM    = ?,
        @I_vPOPTYPE     = 1,
        @I_vVNDDOCNM    = ?,
        @I_vreceiptdate = ?,
        @I_vBACHNUMB    = ?,
        @I_vVENDORID    = ?,
        @I_vSUBTOTAL    = ?,
        @O_iErrorState  = @err OUTPUT,
        @oErrString     = @err_str OUTPUT;
    SELECT @err AS error_state, @err_str AS err_string;
    """
    row = conn.cursor().execute(
        sql, receipt_number, po_number, receipt_date, batch_number, vendor_id, subtotal
    ).fetchone()
    if row.error_state != 0:
        raise EConnectError(
            f"taPopRcptHdrInsert failed: {row.err_string.strip()}",
            proc="taPopRcptHdrInsert", error_state=row.error_state,
        )


def create_receipt_line(
    conn,
    *,
    receipt_number: str,
    po_number: str,
    rcpt_line_num: int,   # RCPTLNNM, GP line scaling: 16384, 32768, ...
    po_line_ord: int,     # POLNENUM = the POP10110.ORD being received
    item_number: str,
    vendor_id: str,
    vnditnum: str,
    uofm: str,
    job_number: str,
    location_code: str,
    noninven: int,
    quantity,
    receipt_date,
) -> None:
    """AUTOCOST=1 -> GP pulls the line cost from the PO, so UNITCOST/EXTDCOST go in as 0."""
    sql = """
    DECLARE @err int = 0;
    DECLARE @err_str varchar(255) = '';
    EXEC dbo.taPopRcptLineInsert
        @I_vPOPTYPE      = 1,
        @I_vPOPRCTNM     = ?,
        @I_vPONUMBER     = ?,
        @I_vRCPTLNNM     = ?,
        @I_vPOLNENUM     = ?,
        @I_vITEMNMBR     = ?,
        @I_vVENDORID     = ?,
        @I_vVNDITNUM     = ?,
        @I_vUOFM         = ?,
        @I_vJOBNUMBR     = ?,
        @I_vLOCNCODE     = ?,
        @I_vNONINVEN     = ?,
        @I_vQTYSHPPD     = ?,
        @I_vAUTOCOST     = 1,
        @I_vUNITCOST     = 0,
        @I_vEXTDCOST     = 0,
        @I_vreceiptdate  = ?,
        @I_vRequesterTrx = 1,
        @O_iErrorState   = @err OUTPUT,
        @oErrString      = @err_str OUTPUT;
    SELECT @err AS error_state, @err_str AS err_string;
    """
    row = conn.cursor().execute(
        sql,
        receipt_number, po_number, rcpt_line_num, po_line_ord,
        item_number, vendor_id, vnditnum, uofm, job_number, location_code,
        noninven, quantity, receipt_date,
    ).fetchone()
    if row.error_state != 0:
        raise EConnectError(
            f"taPopRcptLineInsert failed for ORD={po_line_ord}: {row.err_string.strip()}",
            proc="taPopRcptLineInsert", error_state=row.error_state,
        )


def insert_whrecline_row(
    conn,
    *,
    custom_db: str,       # e.g. 'PMUBC' / 'PMUCSH' (the paired custom warehouse DB)
    po_number: str,
    polnenum: int,        # = the POP10110.ORD being received
    poprctnm: str,        # GP receipt number from this receive
    rcptlnnm: int,        # receipt line number (16384 steps)
    qty_ordered: int,
    qty_received: int,
    item: str,
    itemdesc: str | None,
    vendor_id: str,
    vendname: str | None,
    job: str | None,
    jobname: str | None,
    location: str,        # the RACK location - the whole reason this table exists
    revision: str | None,
    comments: str | None,
    date_received: date,
    received_by: str | None,
) -> None:
    """Insert one row into <custom_db>.dbo.WHRECLINE101 - the custom warehouse-receipt store the
    company dashboards (and the shipping/tagging chain) read. NOT a GP table and has NO eConnect proc;
    the legacy app wrote it with a plain INSERT, same as here. Called inside the SAME transaction as the
    GP receipt so a failure rolls the whole receive back (no orphaned GP receipt - the legacy's hazard).

    QuantityRemainingOnRack starts equal to QuantityReceived (full received qty is on the rack until
    later drawn down by shipping). DateReceived/UpdatingUser/UpdatingMachine mirror the legacy stamps;
    TimeReceived + machine are taken from the SQL server/connection so they're consistent."""
    if not _DB_NAME_RE.match(custom_db):
        raise EConnectError(f"invalid custom_db name {custom_db!r}", proc="insert_whrecline_row", error_state=0)
    sql = f"""
    INSERT INTO {custom_db}.dbo.WHRECLINE101
        (PONUMBER, POLNENUM, POPRCTNM, RCPTLNNM,
         QuantityOrdered, QuantityReceived, QuantityRemainingOnRack, SopNumber,
         ITEMNMBR, ITEMDESC, VENDORID, VENDNAME, JobNumber, JobName,
         RevisionNumber, Location, Comments,
         DateReceived, TimeReceived, UpdatingUser, UpdatingMachine)
    VALUES (?, ?, ?, ?,
            ?, ?, ?, ?,
            ?, ?, ?, ?, ?, ?,
            ?, ?, ?,
            ?, CAST(GETDATE() AS time), COALESCE(?, SUSER_SNAME()), HOST_NAME());
    """
    conn.cursor().execute(
        sql,
        po_number, polnenum, poprctnm, rcptlnnm,
        qty_ordered, qty_received, qty_received, None,  # SopNumber null for plain job POs
        item, itemdesc, vendor_id, vendname, job, jobname,
        revision, location, comments,
        date_received, received_by,
    )
