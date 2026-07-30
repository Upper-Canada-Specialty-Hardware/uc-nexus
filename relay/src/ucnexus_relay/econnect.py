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
    """proc_message: the proc's OWN error text (@oErrString), when that text is the thing the user needs
    to read rather than a GP error-code description. errors.econnect_error_body normally resolves
    error_state through DYNAMICS.taErrorCode and shows that description, which is right for the taXxx
    procs whose states ARE taErrorCode entries. The WennSoft job proc numbers its states independently,
    so a lookup there returns an unrelated GP description and buries the real reason ("Job cannot be
    created within a closed period"). Setting this pins the proc's text as the surfaced message."""

    def __init__(self, message: str, proc: str, error_state: int = 0, proc_message: str | None = None):
        super().__init__(message)
        self.proc = proc
        self.error_state = error_state
        self.proc_message = proc_message


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


def po_number_in_use(conn, po_number: str) -> str | None:
    """Read-only guard for a client-supplied PO number: is it already used ANYWHERE in GP, not just
    by an active PO? Returns a short human label of where it was found, or None if the number is free.
    A PO number can live in three places, and a collision in any of them makes GP reject (or, worse,
    silently reuse) the number, so /po pre-checks all three and returns a clean po_number_taken 400:
      - POP10100.PONUMBER - an active (open/work) PO
      - POP30100.PONUMBER - a historical (closed/posted/voided) PO
      - POP30300.VNDDOCNM - a posted PO receipt's vendor-doc number (= the PO it received against)
    Checked in that order and short-circuits on the first hit (active first, so no needless history
    reads on the common path). Table + column are compile-time constants; only po_number is bound."""
    for table, column, label in (
        ("POP10100", "PONUMBER", "an active PO"),
        ("POP30100", "PONUMBER", "a historical PO"),
        ("POP30300", "VNDDOCNM", "a posted PO receipt"),
    ):
        row = conn.cursor().execute(
            f"SELECT COUNT(*) AS n FROM dbo.{table} WHERE {column} = ?", po_number
        ).fetchone()
        if row.n:
            return f"{label} ({table}.{column})"
    return None


def _exec_tapohdr(conn, fields: dict) -> None:
    """Build + EXEC dbo.taPoHdr from an ordered {param: value} map (param name minus the @I_v prefix),
    always appending UpdateIfExists=1 + the OUTPUT error params. One place wires the header upsert so
    the create / subtotal / currency-rate / tax variants can't drift on parameter naming."""
    assignments = ",\n        ".join(f"@I_v{name} = ?" for name in fields)
    sql = f"""
    DECLARE @err int = 0;
    DECLARE @err_str varchar(255) = '';
    EXEC dbo.taPoHdr
        {assignments},
        @I_vUpdateIfExists = 1,
        @O_iErrorState     = @err OUTPUT,
        @oErrString        = @err_str OUTPUT;
    SELECT @err AS error_state, @err_str AS err_string;
    """
    row = conn.cursor().execute(sql, *fields.values()).fetchone()
    if row.error_state != 0:
        raise EConnectError(
            f"taPoHdr failed: {row.err_string.strip()}", proc="taPoHdr", error_state=row.error_state
        )


def _foreign_currency_fields(rate_type: str | None, exchange_date: date | None, null_tax_schedule: bool) -> dict:
    """The taPoHdr fields that differ for a foreign-currency PO (issue #257). rate_type set -> pass
    RATETPID + EXCHDATE and let eConnect auto-resolve XCHGRATE from GP's maintained exchange rate table
    (DYNAMICS.MC00100). null_tax_schedule -> blank TAXSCHID: a USD PO must carry no tax schedule, and GP
    would otherwise fill the company default (verified live - it does NOT auto-null for a foreign PO)."""
    fields: dict = {}
    if rate_type:
        fields["RATETPID"] = rate_type
        fields["EXCHDATE"] = exchange_date
    if null_tax_schedule:
        fields["TAXSCHID"] = ""
    return fields


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
    rate_type: str | None = None,
    exchange_date: date | None = None,
    null_tax_schedule: bool = False,
) -> None:
    """Create the PO header. SUBTOTAL is NOT passed here (no lines exist yet); update_po_header_subtotal
    sets it after the lines land. For a foreign-currency PO (issue #257), rate_type/exchange_date let
    eConnect resolve the exchange rate and null_tax_schedule blanks TAXSCHID."""
    fields = {
        "POTYPE": po_type,
        "PONUMBER": po_number,
        "VENDORID": vendor_id,
        "DOCDATE": doc_date,
        "BUYERID": buyer_id,
        "CURNCYID": currency_id,
        "POSTATUS": po_status,
        "CONFIRM1": confirm_with,
        "VADCDPAD": vendor_address_code,
        "SHIPMTHD": shipping_method,
    }
    fields.update(_foreign_currency_fields(rate_type, exchange_date, null_tax_schedule))
    _exec_tapohdr(conn, fields)


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
    manufacturer: str | None = None,
    po_type: int = 1,
) -> None:
    """Create one non-inventoried PO line. For job-cost lines, follow with
    apply_wennsoft_job_cost(). Do NOT pass ProjNum/CostCatID — they fail silently
    here (PA42201 absent; Project Accounting not configured).

    manufacturer (when captured) is written to USRDEFND1 on POP10110 - the free user-defined
    line field this customer uses for it (issue #233)."""
    # USRDEFND1 is char(50) in GP: RTRIM (trailing pad is meaningless there) + cap at 50 so an
    # over-length value can't overflow the column. None/blank -> '' leaves the field blank.
    usrdefnd1 = (manufacturer or "").rstrip()[:50]
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
        @I_vUSRDEFND1      = ?,
        @O_iErrorState     = @err OUTPUT,
        @oErrString        = @err_str OUTPUT;
    SELECT @err AS error_state, @err_str AS err_string;
    """
    row = conn.cursor().execute(
        sql,
        po_type, po_number, doc_date, vendor_id,
        location_code, item_number, item_description, quantity, uofm, unit_cost, usrdefnd1,
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


def split_cost_code(cost_code: str) -> tuple[str, str, str, str, int]:
    """Split a 'phase-step-element' cost code (e.g. '210-200-2') into the JC00701 key columns
    (Cost_Code_Number_1, _2, _3, _4, Cost_Element). cc3/cc4 are always blank at this customer;
    Cost_Element is the TRAILING segment as int (the doc once mislabeled it COSTTYPE - it's not).
    Used by BOTH apply_wennsoft_integration (the wsi call) and cost_code_on_job (the pre-check),
    so the validated split and the applied split can never drift."""
    segs = cost_code.split("-")
    cc1 = segs[0] if len(segs) > 0 else ""
    cc2 = segs[1] if len(segs) > 1 else ""
    try:
        cost_element = int(segs[2]) if len(segs) > 2 and segs[2] else 0
    except ValueError:
        cost_element = 0
    return cc1, cc2, "", "", cost_element


def job_exists(conn, job_number: str) -> bool:
    """Read-only: is job_number a real GP job in the job master JC00102? The wsi proc rejects an
    unknown JOBNUMBR, so /po pre-checks here to return a clean job_not_registered instead of a raw
    eConnect error (mirrors the buyer pre-check against POP00101). RTRIM the column and strip the
    arg so this normalizes the job the SAME way the /cost-codes dropdown (list_cost_codes) does -
    a job the dropdown loads can't then fail the pre-check on surrounding whitespace."""
    row = conn.cursor().execute(
        "SELECT COUNT(*) AS n FROM dbo.JC00102 WHERE RTRIM(WS_Job_Number) = ?", job_number.strip()
    ).fetchone()
    return row.n > 0


def cost_code_on_job(conn, job_number: str, cost_code: str) -> bool:
    """Read-only: is cost_code an ACTIVE cost code on job_number in the cost-code detail master
    JC00701? Matches the same six-column key the WennSoft proc uses (WS_Job_Number +
    Cost_Code_Number_1..4 + Cost_Element), splitting cost_code with the identical split_cost_code
    the wsi call uses, and filtering WS_Inactive = 0 so it accepts exactly the codes the /cost-codes
    dropdown (list_cost_codes) offers - an inactive code the dropdown hides must not slip past this
    pre-check and then fail mid-orchestration with the raw eConnect error the pre-check exists to
    prevent. /po pre-checks this so a code not on the job returns a clean cost_code_not_on_job."""
    cc1, cc2, cc3, cc4, cost_element = split_cost_code(cost_code)
    row = conn.cursor().execute(
        "SELECT COUNT(*) AS n FROM dbo.JC00701 "
        "WHERE RTRIM(WS_Job_Number) = ? AND Cost_Code_Number_1 = ? AND Cost_Code_Number_2 = ? "
        "AND Cost_Code_Number_3 = ? AND Cost_Code_Number_4 = ? AND Cost_Element = ? AND WS_Inactive = 0",
        job_number.strip(), cc1, cc2, cc3, cc4, cost_element,
    ).fetchone()
    return row.n > 0


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
        cc1, cc2, cc3, cc4, cost_element = split_cost_code(cost_code)
        job = job_number or ""
    else:
        cc1 = cc2 = cc3 = cc4 = ""
        cost_element = 0
        job = ""

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
    trade_discount: Decimal = Decimal(0),
    freight_amount: Decimal = Decimal(0),
    misc_amount: Decimal = Decimal(0),
    tax_amount: Decimal = Decimal(0),
    using_header_taxes: bool = False,
    rate_type: str | None = None,
    exchange_date: date | None = None,
    null_tax_schedule: bool = False,
) -> None:
    """Re-call taPoHdr with UpdateIfExists=1 + the computed SUBTOTAL (validated now against the line
    totals from steps 3-4) and the order-time GP charges (issue #257): trade discount, freight, misc,
    and the header-level tax amount.

    Freight/misc go on non-taxable (Purchase_Freight_Taxable/Purchase_Misc_Taxable=0), so no
    FRTSCHID/MSCSCHID is needed. When a tax detail was inserted (via insert_po_tax_detail),
    using_header_taxes=1 tells GP to use the passed TAXAMNT rather than compute one - GP does NOT
    calculate PO tax under header-level taxes (verified live). rate_type/exchange_date/null_tax_schedule
    carry the foreign-currency handling (re-sent here so the UpdateIfExists upsert can't revert the
    rate or re-default a blanked TAXSCHID)."""
    fields = {
        "POTYPE": po_type,
        "PONUMBER": po_number,
        "VENDORID": vendor_id,
        "DOCDATE": doc_date,
        "BUYERID": buyer_id,
        "CURNCYID": currency_id,
        "POSTATUS": po_status,
        "CONFIRM1": confirm_with,
        "VADCDPAD": vendor_address_code,
        "SHIPMTHD": shipping_method,
        "SUBTOTAL": subtotal,
        "TRDISAMT": trade_discount,
        "FRTAMNT": freight_amount,
        "MSCCHAMT": misc_amount,
        "TAXAMNT": tax_amount,
        "Purchase_Freight_Taxable": 0,
        "Purchase_Misc_Taxable": 0,
        "USINGHEADERLEVELTAXES": 1 if using_header_taxes else 0,
    }
    fields.update(_foreign_currency_fields(rate_type, exchange_date, null_tax_schedule))
    _exec_tapohdr(conn, fields)


def insert_po_tax_detail(
    conn,
    *,
    po_number: str,
    vendor_id: str,
    tax_detail_id: str,
    tax_amount: Decimal,
    taxable_purchase: Decimal,
) -> None:
    """taPopIvcTaxInsert: attach ONE purchase tax detail to a PO (issue #257). TAXTYPE=0 = the PO item
    tax. GP does not compute PO tax under header-level taxes, so the caller passes the computed TAXAMNT
    (= detail rate x taxable purchase) plus the taxable/total purchase base. Called BEFORE the final
    update_po_header_subtotal, which sets USINGHEADERLEVELTAXES=1 + the matching TAXAMNT."""
    sql = """
    DECLARE @err int = 0;
    DECLARE @err_str varchar(255) = '';
    EXEC dbo.taPopIvcTaxInsert
        @I_vPONUMBER   = ?,
        @I_vTAXTYPE    = 0,
        @I_vORD        = 0,
        @I_vTAXDTLID   = ?,
        @I_vBKOUTTAX   = 0,
        @I_vTAXAMNT    = ?,
        @I_vTAXPURCH   = ?,
        @I_vTOTPURCH   = ?,
        @I_vVENDORID   = ?,
        @O_iErrorState = @err OUTPUT,
        @oErrString    = @err_str OUTPUT;
    SELECT @err AS error_state, @err_str AS err_string;
    """
    row = conn.cursor().execute(
        sql, po_number, tax_detail_id, tax_amount, taxable_purchase, taxable_purchase, vendor_id
    ).fetchone()
    if row.error_state != 0:
        raise EConnectError(
            f"taPopIvcTaxInsert failed for detail {tax_detail_id}: {row.err_string.strip()}",
            proc="taPopIvcTaxInsert", error_state=row.error_state,
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
    Returns VENDORID / VENDNAME / VNDCLSID (class) / VENDSTTS (status) / CURNCYID (currency). VENDSTTS
    1 = active; the sync only wants vendors usable on a new PO, so active_only filters to those.
    currency (issue #257) is the vendor's GP currency the PO inherits; blank -> functional 'CAD'."""
    sql = (
        "SELECT RTRIM(VENDORID) AS vendor_id, RTRIM(VENDNAME) AS vendor_name, "
        "RTRIM(VNDCLSID) AS vendor_class, VENDSTTS AS status, RTRIM(CURNCYID) AS currency FROM dbo.PM00200 "
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
            "currency": (r.currency or "").strip().upper() or "CAD",
        }
        for r in rows
    ]


def get_vendor_currency(conn, vendor_id: str) -> str:
    """Read-only: a vendor's GP currency (PM00200.CURNCYID), for GP-first currency resolution at PO
    create (issue #257: the vendor dictates PO currency). Blank -> functional currency 'CAD'. Returns
    an uppercased currency id, or 'CAD' if the vendor row is missing (create_po_header would then fail
    on VENDORID with a clear eConnect error anyway)."""
    row = conn.cursor().execute(
        "SELECT RTRIM(CURNCYID) AS cur FROM dbo.PM00200 WHERE VENDORID = ?", vendor_id
    ).fetchone()
    return ((row.cur if row else "") or "").strip().upper() or "CAD"


def get_mc_setup(conn) -> dict:
    """Read-only: the company's multicurrency setup (MC40000) - functional currency + the default
    PURCHASING rate type (issue #257). A foreign-currency PO (vendor currency != functional) is priced
    with that rate type; eConnect then resolves the actual XCHGRATE from GP's maintained exchange rate
    table (DYNAMICS.MC00100) itself. Returns {'functional': <id>, 'purchase_rate_type': <id or None>};
    a company with no MC setup (single-currency) yields functional 'CAD' and no rate type."""
    row = conn.cursor().execute(
        "SELECT RTRIM(FUNLCURR) AS functional, RTRIM(DEFPURTP) AS purchase_rate_type FROM dbo.MC40000"
    ).fetchone()
    if row is None:
        return {"functional": "CAD", "purchase_rate_type": None}
    return {
        "functional": ((row.functional or "").strip().upper() or "CAD"),
        "purchase_rate_type": ((row.purchase_rate_type or "").strip() or None),
    }


def list_tax_details(conn) -> list[dict]:
    """Read-only: PURCHASE tax details (TX00201 WHERE TXDTLTYP = 2) for the register-PO tax-detail
    dropdown (issue #257). TXDTLTYP 1 = Sales, 2 = Purchases. TXDTLPCT is the percent the relay uses
    to compute the PO tax. GP-first: the options are whatever the company defines (e.g. BC HST P /
    ON HST - P / PST 7% in production), never a hardcoded list.

    The percent column is aliased AS pct, NOT `AS percent`: PERCENT is a reserved SQL Server keyword
    (TOP n PERCENT), so a bare `AS percent` throws "Incorrect syntax near the keyword 'percent'" and the
    dropdown never loads (issue #315 follow-up). Matches get_tax_detail_percent below, which aliases pct."""
    rows = conn.cursor().execute(
        "SELECT RTRIM(TAXDTLID) AS tax_detail_id, RTRIM(TXDTLDSC) AS description, TXDTLPCT AS pct "
        "FROM dbo.TX00201 WHERE TXDTLTYP = 2 ORDER BY TAXDTLID"
    ).fetchall()
    return [
        {"tax_detail_id": r.tax_detail_id, "description": r.description or None, "percent": float(r.pct)}
        for r in rows
    ]


def get_tax_detail_percent(conn, tax_detail_id: str) -> Decimal | None:
    """Read-only: the percent rate of a PURCHASE tax detail (TX00201.TXDTLPCT WHERE TXDTLTYP = 2), for
    computing the PO tax amount. Returns None if the id isn't a purchase tax detail (caller raises a
    clean tax_detail_not_found instead of letting taPopIvcTaxInsert reject it mid-transaction)."""
    row = conn.cursor().execute(
        "SELECT TXDTLPCT AS pct FROM dbo.TX00201 WHERE TAXDTLID = ? AND TXDTLTYP = 2", tax_detail_id
    ).fetchone()
    return Decimal(str(row.pct)) if row is not None else None


def list_buyers(conn) -> list[str]:
    """Registered GP buyer IDs from the buyer master POP00101. eConnect taPoHdr validates BUYERID against
    this and rejects an unregistered buyer (error 269), so /po pre-checks against this list and the
    Create PO buyer dropdown is populated from it. (A device hostname is NOT a registered buyer.)"""
    rows = conn.cursor().execute(
        "SELECT RTRIM(BUYERID) AS b FROM dbo.POP00101 WHERE BUYERID <> '' ORDER BY BUYERID"
    ).fetchall()
    return [r.b for r in rows]


def list_buyers_detailed(conn) -> list[dict]:
    """The same POP00101 buyer master as list_buyers, with each buyer's description (#409).

    list_buyers returns bare ids because that is all the Create PO dropdown needs. The admin screens
    that assign a buyer identity to a Nexus account need the description too: an id like 'donr' or
    'mira' says nothing on its own about who or what it is, and picking the wrong one silently
    mis-attributes every PO that account creates. Kept separate rather than widening list_buyers so
    the PO path's payload doesn't grow a field it never reads."""
    rows = conn.cursor().execute(
        "SELECT RTRIM(BUYERID) AS buyer_id, RTRIM(DSCRIPTN) AS description "
        "FROM dbo.POP00101 WHERE BUYERID <> '' ORDER BY BUYERID"
    ).fetchall()
    return [{"buyer_id": r.buyer_id, "description": r.description or None} for r in rows]


def buyer_exists(conn, buyer_id: str) -> bool:
    """Read-only: is buyer_id already in the buyer master POP00101? BUYERID is char(15), so the column
    is RTRIM'd and the argument stripped - the same normalization list_buyers/list_buyers_detailed
    apply, so an id read out of either dropdown compares equal here."""
    row = conn.cursor().execute(
        "SELECT COUNT(*) AS n FROM dbo.POP00101 WHERE RTRIM(BUYERID) = ?", buyer_id.strip()
    ).fetchone()
    return row.n > 0


def get_buyer(conn, buyer_id: str) -> dict | None:
    """Read-only: one buyer's stored row from POP00101, or None. Used as the read-back after a create
    (#409) so the response carries GP's OWN id and description rather than the request echoed back -
    DSCRIPTN is char(31) on the table and char(30) on the proc, so a longer description is truncated
    on write and the request no longer describes the row. Doubles as proof the row actually landed.

    Matched the same way buyer_exists matches (RTRIM'd column, stripped argument, SQL comparison) so
    the pre-check and the read-back agree about what counts as the same buyer - a Python `==` against
    list_buyers_detailed would disagree with the pre-check on case, and would roll back a create that
    actually succeeded."""
    row = conn.cursor().execute(
        "SELECT RTRIM(BUYERID) AS buyer_id, RTRIM(DSCRIPTN) AS description "
        "FROM dbo.POP00101 WHERE RTRIM(BUYERID) = ?",
        buyer_id.strip(),
    ).fetchone()
    if row is None:
        return None
    return {"buyer_id": row.buyer_id, "description": row.description or None}


def create_buyer(conn, *, buyer_id: str, description: str = "") -> None:
    """Register a GP buyer through eConnect's taCreateBuyer (#409) - the same thing GP's Buyer
    Maintenance window does, so an admin no longer has to open GP just to add one.

    Only BUYERID and DSCRIPTN are sent. The proc's other inputs (RequesterTrx, USRDEFND1-5) are
    defaulted, matching what _exec_tapohdr does with taPoHdr's ~100: an unset optional is absent from
    the EXEC, not an explicit NULL.

    Error states worth recognizing, from DYNAMICS.taErrorCode: 2681 (BUYERID empty), 2684 (duplicate
    in POP00101), 2683 (insert failed), 2679 (a null input). create_buyer_op pre-empts 2684 with its
    own check so the dialog gets a sentence rather than a code."""
    sql = """
    DECLARE @err int = 0;
    DECLARE @err_str varchar(255) = '';
    EXEC dbo.taCreateBuyer
        @I_vBUYERID    = ?,
        @I_vDSCRIPTN   = ?,
        @O_iErrorState = @err OUTPUT,
        @oErrString    = @err_str OUTPUT;
    SELECT @err AS error_state, @err_str AS err_string;
    """
    row = conn.cursor().execute(sql, buyer_id, description).fetchone()
    if row.error_state != 0:
        message = (row.err_string or "").strip()
        raise EConnectError(
            f"taCreateBuyer failed for buyer {buyer_id}: {message}",
            proc="taCreateBuyer",
            error_state=row.error_state,
        )


def list_jobs(conn) -> list[dict]:
    """Read-only: the job master JC00102 (WennSoft Job Cost). Feeds the outbound-channel list_jobs
    op - there's no existing HTTP route for this (nothing reads it via the browser hop today)."""
    rows = conn.cursor().execute(
        "SELECT RTRIM(WS_Job_Number) AS job_number, RTRIM(WS_Job_Name) AS job_name "
        "FROM dbo.JC00102 ORDER BY WS_Job_Name"
    ).fetchall()
    return [{"job_number": r.job_number, "job_name": r.job_name or None} for r in rows]


def read_po_totals(conn, po_number: str) -> dict | None:
    """Read-only: a PO's GP-computed header totals, to auto-fill the generated PO document (issue
    #230). Reads the open-PO work table POP10100 first, then the history table POP30100 (a fully
    processed PO moves there). Columns (verified against the live TUBC POP10100 schema): SUBTOTAL,
    FRTAMNT (freight), MSCCHAMT (misc charges), TAXAMNT (tax). Returns None if the PO isn't in GP."""
    cur = conn.cursor()
    for table in ("POP10100", "POP30100"):
        row = cur.execute(
            f"SELECT RTRIM(PONUMBER) AS po, SUBTOTAL AS subtotal, FRTAMNT AS freight, "
            f"MSCCHAMT AS misc, TAXAMNT AS tax FROM dbo.{table} WHERE PONUMBER = ?",
            po_number,
        ).fetchone()
        if row is not None:
            return {
                "po_number": row.po,
                "subtotal": float(row.subtotal or 0),
                "freight": float(row.freight or 0),
                "miscellaneous": float(row.misc or 0),
                "tax_amount": float(row.tax or 0),
            }
    return None


def list_cost_codes(conn, job_number: str) -> list[dict]:
    """Read-only: the active cost codes defined for ONE job in JC00701 (WennSoft Job Cost).
    Cost codes are per-job, and the real Cost_Element varies by code (210-200 is element 2,
    310-000 is element 3, 510-000 is element 5, ...). The Create PO dropdown is populated from
    this and the /po cost_code is assembled as 'phase-step-element' (e.g. '310-000-3') from the
    code's own element - NOT a hardcoded 2.

    Returns one dict per code: cost_code = the two-segment number 'cc1-cc2' (segments 3/4 are
    blank for every code at this customer), description (Cost_Code_Description), and the integer
    cost_element. WS_Inactive = 0 filters to codes usable on a new PO."""
    rows = conn.cursor().execute(
        "SELECT RTRIM(Cost_Code_Number_1) AS cc1, RTRIM(Cost_Code_Number_2) AS cc2, "
        "Cost_Element AS elem, RTRIM(Cost_Code_Description) AS descr "
        "FROM dbo.JC00701 WHERE RTRIM(WS_Job_Number) = ? AND WS_Inactive = 0 "
        "ORDER BY Cost_Code_Number_1, Cost_Code_Number_2",
        job_number,
    ).fetchall()
    return [
        {
            "cost_code": f"{r.cc1}-{r.cc2}",
            "description": r.descr or None,
            "cost_element": int(r.elem),
        }
        for r in rows
    ]


# --- GP job setup health (issue #425) --------------------------------------
# Receiving PO0000070 in TUBC failed with eConnect 4612 "Invalid Account Index" from
# taPopRcptLineInsert. The PO line had been stamped INVINDX=1617 at registration by the WennSoft PO
# integration, copied straight out of JC00701 (job 23093, cost code 210-200-2). 1617 is not in
# UBC/TUBC's account index master GL00105 at all - it is a UCSH index, left behind by the pre-2023
# UCSH -> UBC job replication which copied JC00701 account indexes raw. Production UBC carries 1504
# such rows across 62 jobs and TUBC, being a clone, mirrors them.
#
# The damage is invisible until receipt time: a job-cost PO against one of those jobs registers
# perfectly and can then never be received. Repairing the data is accounting's job; the relay's job is
# to make the breakage visible BEFORE somebody spends a PO on it, which is what these three reads do.
#
# Rule for "this job is set up": it has at least one active cost code, and every active cost code's
# WS_Account_Index_1 is either 0 or present in GL00105. Index 0 passes deliberately - eConnect defaults
# the account at receipt time, so only a non-zero dangling index is the proven failure mode.
#
# GL00105 is GP's account index master; ACTINDX is the surrogate key JC00701.WS_Account_Index_1 and
# POP10110.INVINDX both point at.

_ACTIVE_COST_CODE = "WS_Inactive = 0"


def job_setup_health(conn, job_number: str | None = None) -> list[dict]:
    """Read-only: the per-job GP setup verdict for EVERY job in the company (#425), or for one job
    when `job_number` is given.

    Two queries regardless of how many jobs there are, because the loop is a sync pass over the whole
    job master and a per-job round trip over the relay socket would make it unusable:

      1. the verdict: JC00102 left-joined to its active JC00701 rows, each left-joined to GL00105,
         grouped by job. Driven off the JOB master rather than off JC00701 so a job with zero active
         cost codes still comes back (it would simply be absent from a JC00701-driven grouping) - that
         is rule one, and it is a real state: a job nobody has set a cost structure on yet.
      2. the detail: the individual broken cost codes, so the quarantine banner can name what is wrong
         rather than saying "something is". Only unhealthy jobs contribute rows, so on a healthy
         company this returns nothing.

    Returns one dict per job: job_number, ok, active_cost_code_count, and issues (a list of
    {cost_code, account_index} for the dangling ones, empty when the job is healthy).

    The single-job filter exists for the live re-check register_po_in_gp runs at submit time: reading
    900 jobs to answer a question about one is the difference between a gate somebody keeps and a gate
    somebody turns off."""
    job = (job_number or "").strip() or None
    cur = conn.cursor()

    verdict_sql = (
        "SELECT RTRIM(j.WS_Job_Number) AS job_number, "
        "COUNT(c.WS_Job_Number) AS active_cost_codes, "
        "SUM(CASE WHEN c.WS_Account_Index_1 <> 0 AND a.ACTINDX IS NULL THEN 1 ELSE 0 END) AS broken_cost_codes "
        "FROM dbo.JC00102 j "
        f"LEFT JOIN dbo.JC00701 c ON RTRIM(c.WS_Job_Number) = RTRIM(j.WS_Job_Number) AND c.{_ACTIVE_COST_CODE} "
        "LEFT JOIN dbo.GL00105 a ON a.ACTINDX = c.WS_Account_Index_1 "
    )
    detail_sql = (
        "SELECT RTRIM(c.WS_Job_Number) AS job_number, RTRIM(c.Cost_Code_Number_1) AS cc1, "
        "RTRIM(c.Cost_Code_Number_2) AS cc2, c.Cost_Element AS elem, c.WS_Account_Index_1 AS account_index "
        "FROM dbo.JC00701 c "
        "LEFT JOIN dbo.GL00105 a ON a.ACTINDX = c.WS_Account_Index_1 "
        f"WHERE c.{_ACTIVE_COST_CODE} AND c.WS_Account_Index_1 <> 0 AND a.ACTINDX IS NULL "
    )
    if job is None:
        verdict_rows = cur.execute(verdict_sql + "GROUP BY RTRIM(j.WS_Job_Number) ORDER BY 1").fetchall()
        detail_rows = cur.execute(detail_sql + "ORDER BY 1, 2, 3").fetchall()
    else:
        verdict_rows = cur.execute(
            verdict_sql + "WHERE RTRIM(j.WS_Job_Number) = ? GROUP BY RTRIM(j.WS_Job_Number) ORDER BY 1", job
        ).fetchall()
        detail_rows = cur.execute(
            detail_sql + "AND RTRIM(c.WS_Job_Number) = ? ORDER BY 1, 2, 3", job
        ).fetchall()

    issues_by_job: dict[str, list[dict]] = {}
    for r in detail_rows:
        # 'phase-step-element', the same shape list_cost_codes / the PO cost_code use, so the banner
        # names a code the user can recognise from the register-PO dropdown.
        cost_code = f"{r.cc1}-{r.cc2}-{int(r.elem)}"
        issues_by_job.setdefault(r.job_number, []).append(
            {"cost_code": cost_code, "account_index": int(r.account_index)}
        )

    out = []
    for r in verdict_rows:
        active = int(r.active_cost_codes or 0)
        broken = int(r.broken_cost_codes or 0)
        out.append(
            {
                "job_number": r.job_number,
                "ok": active > 0 and broken == 0,
                "active_cost_code_count": active,
                "issues": issues_by_job.get(r.job_number, []),
            }
        )
    return out


def cost_code_account_index(conn, job_number: str, cost_code: str) -> int | None:
    """Read-only: the GL account index (JC00701.WS_Account_Index_1) one active cost code on one job
    carries (#425). None when there is no such active row - cost_code_on_job is the check for that and
    runs first, so None here means the code went inactive between the two reads.

    Split from the account_index_exists lookup below rather than answered by one join, because the
    caller has to name the offending index in its error: "cost code 210-200-2 points at GL account
    index 1617" is actionable in GP, "that cost code is broken" is not."""
    cc1, cc2, cc3, cc4, cost_element = split_cost_code(cost_code)
    row = conn.cursor().execute(
        "SELECT WS_Account_Index_1 AS account_index FROM dbo.JC00701 "
        "WHERE RTRIM(WS_Job_Number) = ? AND Cost_Code_Number_1 = ? AND Cost_Code_Number_2 = ? "
        f"AND Cost_Code_Number_3 = ? AND Cost_Code_Number_4 = ? AND Cost_Element = ? AND {_ACTIVE_COST_CODE}",
        job_number.strip(), cc1, cc2, cc3, cc4, cost_element,
    ).fetchone()
    if row is None or row.account_index is None:
        return None
    return int(row.account_index)


def account_index_exists(conn, account_index: int) -> bool:
    """Read-only: is account_index a real row in GP's account index master GL00105 (#425)?

    Index 0 is answered True without a query. It is not an account - it is "GP, pick the account
    yourself at posting time" - and eConnect honours that, so treating it as dangling would quarantine
    every job that simply leaves the default in place."""
    if not account_index:
        return True
    row = conn.cursor().execute(
        "SELECT COUNT(*) AS n FROM dbo.GL00105 WHERE ACTINDX = ?", int(account_index)
    ).fetchone()
    return row.n > 0


def po_lines_with_dangling_account(conn, po_number: str) -> list[dict]:
    """Read-only: the PO's lines whose stamped POP10110.INVINDX is not in GL00105 (#425).

    This is the exact condition taPopRcptLineInsert rejects with eConnect 4612 "Invalid Account
    Index", read before the receipt is attempted so the warehouse user gets "this job's GP setup is
    broken" instead of a bare error state. INVINDX was copied onto the line from JC00701 at
    registration, so the account is already wrong by the time anyone opens the receive form - nothing
    the receiver did causes this and nothing they can do fixes it.

    Returns {ord, item, account_index, job} per broken line, empty when the PO is clean. The caller
    narrows to the lines actually being received."""
    rows = conn.cursor().execute(
        "SELECT l.ORD AS ord, RTRIM(l.ITEMNMBR) AS item, l.INVINDX AS account_index, "
        "RTRIM(l.JOBNUMBR) AS job FROM dbo.POP10110 l "
        "LEFT JOIN dbo.GL00105 a ON a.ACTINDX = l.INVINDX "
        "WHERE l.PONUMBER = ? AND l.INVINDX <> 0 AND a.ACTINDX IS NULL ORDER BY l.ORD",
        po_number,
    ).fetchall()
    return [
        {
            "ord": int(r.ord),
            "item": r.item,
            "account_index": int(r.account_index),
            "job": r.job or None,
        }
        for r in rows
    ]


# --- create a GP job (issue #380) ------------------------------------------
# Nexus can adopt an existing GP job as a project; these originate one. The create-job form cannot be
# composed from anything Nexus stores - customer, address codes, tax schedule, division and the
# estimator/manager payroll ids all live in GP - so the five reads below feed its dropdowns and
# create_job runs the WennSoft job proc.


def list_customers(conn, *, active_only: bool = True) -> list[dict]:
    """Read-only: the customer master RM00101, for the create-job customer picker. GP-first, same as
    every other picker in this file: the options are whatever the company has set up.

    INACTIVE = 0 by default, mirroring list_vendors' VENDSTTS filter and list_divisions' accounts
    filter: a dropdown must not offer a choice that can only produce a job nobody can invoice. TUBC
    has no inactive customers, so this changes nothing in the sandbox and everything in production."""
    sql = (
        "SELECT RTRIM(CUSTNMBR) AS customer_number, RTRIM(CUSTNAME) AS customer_name FROM dbo.RM00101 "
    )
    if active_only:
        sql += "WHERE INACTIVE = 0 "
    sql += "ORDER BY CUSTNAME"
    rows = conn.cursor().execute(sql).fetchall()
    return [{"customer_number": r.customer_number, "customer_name": r.customer_name or None} for r in rows]


def list_employees(conn, *, active_only: bool = True) -> list[dict]:
    """Read-only: the payroll employee master UPR00100, for the create-job estimator and WS manager
    pickers (#392).

    wsiJCJobMaster validates both against this table - a made-up EstimatorID comes back as "The
    estimator does not exist in the payroll master table." (error state 51117) - so #380's free-text
    fields could only ever be guessed right. EMPLOYID is char(15), the same width as JC00102's
    Estimator_ID and WS_Manager_ID.

    INACTIVE = 0 by DEFAULT, the same rule as list_customers / list_vendors / list_divisions: never
    offer a choice that can only fail validation. It is a default rather than a rule because the proc
    validates against the whole of UPR00100 - an inactive employee is still a legal estimator - so
    active_only=False stays reachable through the op for backdating or recreating an older job.

    There is no WennSoft-specific estimator master; JC90102 carries WS_Estimator_Name and
    WS_Manager_Name, but that is denormalized reporting output."""
    sql = (
        "SELECT RTRIM(EMPLOYID) AS employee_id, RTRIM(FRSTNAME) AS first_name, "
        "RTRIM(LASTNAME) AS last_name FROM dbo.UPR00100 "
    )
    if active_only:
        sql += "WHERE INACTIVE = 0 "
    sql += "ORDER BY LASTNAME, FRSTNAME"
    rows = conn.cursor().execute(sql).fetchall()
    return [
        {
            "employee_id": r.employee_id,
            "first_name": r.first_name or None,
            "last_name": r.last_name or None,
        }
        for r in rows
    ]


def get_job(conn, job_number: str) -> dict | None:
    """Read-only: one job's stored record from JC00102, or None. Used as the read-back after a create
    (issue #380) so the response carries GP's OWN job number and name rather than the request echoed
    back - WS_Job_Name is char(31), and what GP stored is the honest thing to snapshot onto the Nexus
    project. Doubles as proof the row actually landed."""
    row = conn.cursor().execute(
        "SELECT RTRIM(WS_Job_Number) AS job_number, RTRIM(WS_Job_Name) AS job_name "
        "FROM dbo.JC00102 WHERE RTRIM(WS_Job_Number) = ?",
        job_number.strip(),
    ).fetchone()
    if row is None:
        return None
    return {"job_number": row.job_number, "job_name": row.job_name or None}


def list_customer_addresses(conn, customer_number: str) -> list[dict]:
    """Read-only: one customer's address codes from the customer address master RM00102, for the job
    address / bill-to address pickers. wsiJCJobMaster validates both codes against this table FOR THAT
    CUSTOMER, so the list is scoped to CUSTNMBR rather than offering every address in GP - an address
    code that exists under a different customer is not valid on this job.

    city/address1 ride along because an address code alone ('MAIN', 'PRIMARY', 'RIH') doesn't tell the
    user which site it is."""
    rows = conn.cursor().execute(
        "SELECT RTRIM(ADRSCODE) AS address_code, RTRIM(ADDRESS1) AS address1, RTRIM(CITY) AS city, "
        "RTRIM(STATE) AS state FROM dbo.RM00102 WHERE RTRIM(CUSTNMBR) = ? ORDER BY ADRSCODE",
        customer_number.strip(),
    ).fetchall()
    return [
        {
            "address_code": r.address_code,
            "address1": r.address1 or None,
            "city": r.city or None,
            "state": r.state or None,
        }
        for r in rows
    ]


def list_tax_schedules(conn) -> list[dict]:
    """Read-only: the tax SCHEDULE master TX00101, for the create-job tax-schedule picker (and the
    optional use-tax schedule, which is the same kind of id - JC00102.USETAXSCHID is char(15) like
    TAXSCHID). Distinct from list_tax_details above, which reads the tax DETAIL table TX00201: a
    schedule groups details, and wsiJCJobMaster wants the schedule."""
    rows = conn.cursor().execute(
        "SELECT RTRIM(TAXSCHID) AS tax_schedule_id, RTRIM(TXSCHDSC) AS description "
        "FROM dbo.TX00101 ORDER BY TAXSCHID"
    ).fetchall()
    return [{"tax_schedule_id": r.tax_schedule_id, "description": r.description or None} for r in rows]


def list_divisions(conn) -> list[str]:
    """Read-only: WennSoft divisions that have division ACCOUNTS set up (JCDivisionSETP joined to
    JCDivisionAccountsSETP), for the create-job division picker.

    The accounts filter is the whole point: wsiJCJobMaster rejects a division with no division accounts
    ("division accounts have not been set up"), so offering every JCDivisionSETP row would put choices in
    the dropdown that can only ever fail validation. TUBC has exactly one qualifying division, VANCOUVER.
    There is no description column on either table - the division code IS the label."""
    rows = conn.cursor().execute(
        "SELECT RTRIM(d.Divisions) AS division FROM dbo.JCDivisionSETP d "
        "WHERE EXISTS (SELECT 1 FROM dbo.JCDivisionAccountsSETP a WHERE a.Divisions = d.Divisions) "
        "ORDER BY d.Divisions"
    ).fetchall()
    return [r.division for r in rows]


# request field -> wsiJCJobMaster parameter name (minus the @I_v prefix), in the order they're sent.
# Required first, then the optional ones. Verified against sys.parameters on the live proc: char(17) for
# the job/project numbers, char(31) for the job name, char(15) for the rest, datetime for the dates.
_CREATE_JOB_PARAMS = (
    ("job_number", "WSJobNumber"),
    ("job_name", "WSJobName"),
    ("division", "Divisions"),
    ("customer_number", "CustomerNumber"),
    ("job_address_code", "JobAddressCode"),
    ("billto_address_code", "JobBilltoAddressCode"),
    ("tax_schedule_id", "TaxScheduleID"),
    ("created_date", "CreatedDate"),
    ("estimator_id", "EstimatorID"),
    ("ws_manager_id", "WSManagerID"),
    ("ws_project_number", "WSProjectNumber"),
    ("bill_customer_number", "BillCustomerNumber"),
    ("use_tax_schedule", "UseTaxSchedule"),
    ("schedule_start_date", "ScheduleStartDate"),
    ("scheduled_completion_date", "ScheduledCompletionDate"),
    ("bid_due_date", "BidDueDate"),
)

# The 8 the proc actually demands (established by validating clean, then dropping each in turn).
_CREATE_JOB_REQUIRED = (
    "job_number",
    "job_name",
    "division",
    "customer_number",
    "job_address_code",
    "billto_address_code",
    "tax_schedule_id",
    "created_date",
)


def create_job(conn, *, only_validate: bool = False, **fields) -> None:
    """Create a GP job through the WennSoft job proc wsiJCJobMaster. Same shape as
    apply_wennsoft_integration: DECLARE the two OUTPUT locals, EXEC, then SELECT them back.

    The proc takes 217 parameters and ALL 215 inputs carry defaults, so the EXEC is assembled from only
    the fields the caller actually set - passing the other 199 as explicit NULLs is not the same thing as
    leaving them defaulted, and there is no reason to find out which ones differ. Unset optional fields
    are simply absent from the statement.

    only_validate drives @I_vOnlyValidate, so the caller's dry run and the real create go through this one
    function and cannot drift on how the parameters are built - the dry run has to exercise the exact
    statement the real call will make, or it validates something else.

    @I_vReturnErrorText=1 makes the proc fill @oErrString; that text is carried on the raised error as
    proc_message so it survives to the user verbatim (see EConnectError)."""
    unknown = set(fields) - {field for field, _ in _CREATE_JOB_PARAMS}
    if unknown:
        raise EConnectError(f"unknown create_job field(s): {sorted(unknown)}", proc="wsiJCJobMaster")
    # A required field arriving as None would otherwise be quietly dropped from the EXEC and the proc
    # would run on its own default for it - validating and then creating something other than what was
    # asked for. CreateJobRequest already rejects these, so reaching here means a caller bypassed it.
    missing = [field for field in _CREATE_JOB_REQUIRED if fields.get(field) is None]
    if missing:
        raise EConnectError(f"create_job is missing required field(s): {missing}", proc="wsiJCJobMaster")

    # Non-empty by construction now that the required 8 are checked above, which is what keeps the
    # f-string below from emitting `EXEC dbo.wsiJCJobMaster\n        ,\n ...` - a bare syntax error.
    supplied = {param: fields[field] for field, param in _CREATE_JOB_PARAMS if fields.get(field) is not None}

    assignments = ",\n        ".join(f"@I_v{param} = ?" for param in supplied)
    sql = f"""
    DECLARE @err int = 0;
    DECLARE @err_str varchar(255) = '';
    EXEC dbo.wsiJCJobMaster
        {assignments},
        @I_vOnlyValidate    = ?,
        @I_vReturnErrorText = 1,
        @O_iErrorState      = @err OUTPUT,
        @oErrString         = @err_str OUTPUT;
    SELECT @err AS error_state, @err_str AS err_string;
    """
    row = conn.cursor().execute(sql, *supplied.values(), 1 if only_validate else 0).fetchone()
    if row.error_state != 0:
        message = (row.err_string or "").strip()
        pass_label = "validation" if only_validate else "create"
        raise EConnectError(
            f"wsiJCJobMaster {pass_label} failed for job {fields.get('job_number')}: {message}",
            proc="wsiJCJobMaster",
            error_state=row.error_state,
            proc_message=message or None,
        )


# --- create a GP customer address (issue #444) ------------------------------
# The create-job form picks its job address and bill-to address out of RM00102 (list_customer_addresses
# above), so a site that was never entered in GP meant stopping the job creation, opening GP, adding the
# address, and starting over. This is the write half of that picker.
#
# taCreateCustomerAddress is a stock eConnect proc, present with DYNGRP EXECUTE in every company DB. It
# has NO OnlyValidate parameter, unlike wsiJCJobMaster, so there is no dry-run pass to lean on here -
# the duplicate guard is entirely ours (customer_address_exists, called by create_customer_address_op).


def customer_address_exists(conn, customer_number: str, address_code: str) -> bool:
    """Read-only: does this customer already have this address code (RM00102)?

    Scoped to BOTH columns because ADRSCODE is unique per customer, not globally - 'MAIN' exists under
    nearly every customer in GP, so a global probe would refuse almost every legitimate create. Both
    columns are char(15), so they are RTRIM'd and the arguments stripped, which is the same
    normalization list_customer_addresses applies - a code read out of that dropdown compares equal
    here.

    This is the whole duplicate guard for the create (the proc offers no validate-only pass), and it is
    what lets create_customer_address hardcode UpdateIfExists=0 without a re-run of the dialog turning
    into a raw eConnect error state."""
    row = conn.cursor().execute(
        "SELECT COUNT(*) AS n FROM dbo.RM00102 WHERE RTRIM(CUSTNMBR) = ? AND RTRIM(ADRSCODE) = ?",
        customer_number.strip(),
        address_code.strip(),
    ).fetchone()
    return row.n > 0


def get_customer_address(conn, customer_number: str, address_code: str) -> dict | None:
    """Read-only: one stored address row from RM00102, or None. Used as the read-back after a create
    (#444), so the response reports what GP ACTUALLY STORED rather than the request echoed back - the
    same honesty rule get_job follows for the job name.

    RM00102 is fixed-width char throughout (ADDRESS1 char(60), CITY char(35), STATE char(29)) and SQL
    Server truncates on the way in without a word. CreateCustomerAddressRequest rejects an over-length
    value before it ever gets here, so a truncation should be unreachable - reading the row back is what
    makes that a guarantee instead of an assumption, and it doubles as proof the row landed at all.

    Returns the same shape as a list_customer_addresses row, so the address just created and the ones
    the picker fetched are the same kind of thing to everything downstream.

    Matched the way customer_address_exists matches (RTRIM'd columns, stripped arguments, comparison
    left to SQL) so the pre-check and the read-back agree on what counts as the same address - a Python
    match would disagree on case and roll back a create that actually worked."""
    row = conn.cursor().execute(
        "SELECT RTRIM(ADRSCODE) AS address_code, RTRIM(ADDRESS1) AS address1, RTRIM(CITY) AS city, "
        "RTRIM(STATE) AS state FROM dbo.RM00102 WHERE RTRIM(CUSTNMBR) = ? AND RTRIM(ADRSCODE) = ?",
        customer_number.strip(),
        address_code.strip(),
    ).fetchone()
    if row is None:
        return None
    return {
        "address_code": row.address_code,
        "address1": row.address1 or None,
        "city": row.city or None,
        "state": row.state or None,
    }


# request field -> taCreateCustomerAddress parameter name (minus the @I_v prefix), in the proc's own
# parameter order. The proc takes more than these (ADDRESS3, the phone/fax numbers, the shipping
# method, the user-defined fields); those are left defaulted, the same treatment _exec_tapohdr gives
# taPoHdr's ~100 - an unset optional is absent from the EXEC, not an explicit NULL.
_CREATE_CUSTOMER_ADDRESS_PARAMS = (
    ("customer_number", "CUSTNMBR"),
    ("address_code", "ADRSCODE"),
    ("address1", "ADDRESS1"),
    ("address2", "ADDRESS2"),
    ("city", "CITY"),
    ("state", "STATE"),
    ("zip_code", "ZIPCODE"),
    ("country", "COUNTRY"),
)

# The four without which the row is not an address anyone could ship to. CreateCustomerAddressRequest
# rejects them first; this is the same defence in depth _CREATE_JOB_REQUIRED provides for the job proc.
_CREATE_CUSTOMER_ADDRESS_REQUIRED = ("customer_number", "address_code", "address1", "city")


def create_customer_address(conn, fields: dict) -> None:
    """Create an address code under a GP customer through eConnect's taCreateCustomerAddress (#444) -
    the same thing GP's Customer Address Maintenance window does. Same DECLARE / EXEC / SELECT shape as
    _exec_tapohdr, built from the ordered {field: parameter} map above.

    @I_vUpdateIfExists = 0 is a LITERAL in the statement, deliberately not a parameter the caller can
    set. With 1 the proc overwrites an existing address code in place, and Nexus must never do that:
    RM00102 is master data accounting maintains in GP, an address code is already referenced by every
    job and posted invoice that used it, and the business here is adding a site nobody has entered yet -
    never re-pointing one. Pinned to 0, the worst a duplicate can do is fail, and
    create_customer_address_op pre-empts even that.

    Every parameter is sent on every call, unset optionals as blanks. That is the opposite of
    create_job's "absent means leave GP's default", and right for the same reason create_buyer sends a
    blank DSCRIPTN: this row does not exist yet, so there is no GP default to preserve - a blank STATE
    is simply an address with no state.

    No proc_message on the raised error, unlike wsiJCJobMaster: taCreateCustomerAddress is a taXxx proc,
    so its error states ARE taErrorCode entries and errors.econnect_error_body resolves a real GP
    description for them. GP's own errString still rides in the message."""
    unknown = set(fields) - {field for field, _ in _CREATE_CUSTOMER_ADDRESS_PARAMS}
    if unknown:
        raise EConnectError(
            f"unknown create_customer_address field(s): {sorted(unknown)}", proc="taCreateCustomerAddress"
        )
    missing = [field for field in _CREATE_CUSTOMER_ADDRESS_REQUIRED if not (fields.get(field) or "").strip()]
    if missing:
        raise EConnectError(
            f"create_customer_address is missing required field(s): {missing}", proc="taCreateCustomerAddress"
        )

    values = [fields.get(field) or "" for field, _ in _CREATE_CUSTOMER_ADDRESS_PARAMS]
    assignments = ",\n        ".join(f"@I_v{param} = ?" for _, param in _CREATE_CUSTOMER_ADDRESS_PARAMS)
    sql = f"""
    DECLARE @err int = 0;
    DECLARE @err_str varchar(255) = '';
    EXEC dbo.taCreateCustomerAddress
        {assignments},
        @I_vUpdateIfExists = 0,
        @O_iErrorState     = @err OUTPUT,
        @oErrString        = @err_str OUTPUT;
    SELECT @err AS error_state, @err_str AS err_string;
    """
    row = conn.cursor().execute(sql, *values).fetchone()
    if row.error_state != 0:
        message = (row.err_string or "").strip()
        raise EConnectError(
            f"taCreateCustomerAddress failed for customer {fields.get('customer_number')} "
            f"address {fields.get('address_code')}: {message}",
            proc="taCreateCustomerAddress",
            error_state=row.error_state,
        )


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
