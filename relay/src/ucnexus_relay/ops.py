"""Transport-agnostic relay operations - the GP-writing orchestration reachable via both the inbound
HTTP routes (main.py) and the outbound WS channel (channel.py). One implementation so the two
transports can't drift apart on what a create_po / create_receipt actually does.

Each function takes an already-open connection and raises RelayOpError for a validation-style
failure (the caller commits/rolls back and maps errors to its own shape) or lets econnect.EConnectError
propagate for a raw eConnect failure."""

import socket
from datetime import date
from decimal import Decimal

from . import buyers, econnect, models
from .config import get_settings


class RelayOpError(Exception):
    """A pre-check / validation failure, distinct from an eConnect error. The transport layer maps
    this to its own error shape (HTTPException for main.py, {ok: false, error: ...} for channel.py)."""

    def __init__(self, code: str, message: str, **context):
        super().__init__(message)
        self.code = code
        self.message = message
        self.context = context


def check_company_allowed(company: str) -> None:
    allowed = get_settings().gp.allowed_companies
    if company not in allowed:
        raise RelayOpError("company_not_allowed", f"{company} not in allowed_companies {allowed}")


def create_po_op(conn, *, company: str, request: models.CreatePoRequest) -> models.CreatePoResponse:
    h = request.header

    # 0. buyer: normally the Create PO dropdown sends a buyer_id picked from GP's registered buyers
    #    (POP00101, see list_buyers). If omitted, fall back to the [gp.buyers] config (by_host ->
    #    by_login -> default). The value MUST be a registered GP buyer.
    buyer_id = h.buyer_id
    if not buyer_id:
        bcfg = get_settings().gp.buyers
        login = None
        if bcfg.by_login:
            login = conn.cursor().execute("SELECT SUSER_NAME()").fetchone()[0]
        buyer_id = buyers.resolve_buyer(bcfg, socket.gethostname(), login)
        if not buyer_id:
            raise RelayOpError(
                "buyer_unresolved",
                "no buyer_id sent and none resolved from [gp.buyers]; pick a buyer from list_buyers",
            )

    # validate against GP's buyer master: eConnect taPoHdr rejects an unregistered BUYERID with
    # error 269, so give a clear error here instead.
    registered = econnect.list_buyers(conn)
    if buyer_id not in registered:
        raise RelayOpError(
            "buyer_not_registered",
            f"buyer '{buyer_id}' is not a registered GP buyer for {company} (registered: {registered})",
        )

    # 0c. currency + exchange rate: GP-first, the vendor master dictates the PO currency (issue #257),
    #     not the client. A foreign-currency PO (vendor currency != the company's functional currency)
    #     is priced with the company's default PURCHASING rate type; eConnect resolves the actual rate
    #     from GP's maintained exchange rate table (DYNAMICS.MC00100) itself. It must ALSO carry no tax
    #     schedule - GP would otherwise fill the company default - so a foreign PO blanks TAXSCHID and
    #     takes no tax detail. CAD (functional) needs no rate and keeps GP's default schedule.
    currency = econnect.get_vendor_currency(conn, h.vendor_id)
    mc = econnect.get_mc_setup(conn)
    is_foreign = currency != mc["functional"]
    rate_type = None
    if is_foreign:
        rate_type = mc["purchase_rate_type"]
        if not rate_type:
            raise RelayOpError(
                "rate_type_unresolved",
                f"no default purchasing rate type (MC40000.DEFPURTP) configured for {company}; "
                f"cannot price a {currency} PO",
            )
        if h.tax_detail_id:
            raise RelayOpError(
                "tax_detail_on_foreign_po",
                f"a {currency} PO carries no tax schedule (issue #257); tax_detail_id must be omitted",
            )
    exchange_date = h.doc_date if is_foreign else None

    # 0b. job + cost code: the wsi proc (step 4 below) rejects a made-up job or a cost code not set up
    #     on the job with a raw eConnect error mid-transaction, so pre-check job-cost lines here for
    #     clean job_not_registered / cost_code_not_on_job errors, mirroring the buyer check. Only PI=2
    #     lines carry a job/cost code (the model validator guarantees PI=2 has both, PI=1 has neither).
    job_ok: dict[str, bool] = {}  # cache: a PO can repeat a job across lines
    for line in request.lines:
        if line.product_indicator != 2:
            continue
        job = line.job_number
        if job not in job_ok:
            job_ok[job] = econnect.job_exists(conn, job)
        if not job_ok[job]:
            raise RelayOpError(
                "job_not_registered", f"job '{job}' is not a registered GP job (JC00102) for {company}"
            )
        if not econnect.cost_code_on_job(conn, job, line.cost_code):
            raise RelayOpError(
                "cost_code_not_on_job",
                f"cost code '{line.cost_code}' is not set up on job '{job}' (JC00701) for {company}",
            )

    # 1. PO number: use UC Nexus's own number if supplied, else reserve GP's next 'PO' number. A
    #    client-supplied number is rejected if it's already used anywhere in GP - active OR history.
    if request.po_number:
        po_number = request.po_number
        in_use = econnect.po_number_in_use(conn, po_number)
        if in_use:
            raise RelayOpError(
                "po_number_taken", f"PO number '{po_number}' is already in use in GP as {in_use}"
            )
    else:
        po_number = econnect.get_next_po_number(conn)

    # 2. header (no SUBTOTAL yet)
    econnect.create_po_header(
        conn,
        po_number=po_number,
        vendor_id=h.vendor_id,
        doc_date=h.doc_date,
        buyer_id=buyer_id,
        confirm_with=h.confirm_with,
        currency_id=currency,
        vendor_address_code=h.vendor_address_code,
        shipping_method=h.shipping_method,
        rate_type=rate_type,
        exchange_date=exchange_date,
        null_tax_schedule=is_foreign,
    )

    # 3. lines
    for line in request.lines:
        econnect.create_po_line(
            conn,
            po_number=po_number,
            doc_date=h.doc_date,
            vendor_id=h.vendor_id,
            item_number=line.item_number,
            item_description=line.item_description,
            quantity=line.quantity,
            unit_cost=line.unit_cost,
            location_code=line.location_code,
            uofm=line.uofm,
            manufacturer=line.manufacturer,
        )

    # 4. WennSoft integration for EVERY line - this is what sets Product_Indicator (1 non-inv / 2
    #    job cost); taPoLine can't.
    for idx, line in enumerate(request.lines, start=1):
        econnect.apply_wennsoft_integration(
            conn,
            po_number=po_number,
            line_ord=idx * 16384,
            product_indicator=line.product_indicator,
            job_number=line.job_number,
            cost_code=line.cost_code,
        )

    # 5. subtotal + order-time charges. GP does NOT compute PO tax under header-level taxes, so when a
    #    tax detail was picked the relay looks up its rate, computes the tax, inserts the detail
    #    (taPopIvcTaxInsert) BEFORE the final header, then sets USINGHEADERLEVELTAXES=1 + that TAXAMNT.
    subtotal = sum(line.quantity * line.unit_cost for line in request.lines)
    tax_amount = Decimal(0)
    if h.tax_detail_id:
        pct = econnect.get_tax_detail_percent(conn, h.tax_detail_id)
        if pct is None:
            raise RelayOpError(
                "tax_detail_not_found",
                f"tax detail '{h.tax_detail_id}' is not a GP purchase tax detail "
                f"(TX00201 TXDTLTYP=2) for {company}",
            )
        tax_amount = (subtotal * pct / Decimal(100)).quantize(Decimal("0.01"))
        econnect.insert_po_tax_detail(
            conn,
            po_number=po_number,
            vendor_id=h.vendor_id,
            tax_detail_id=h.tax_detail_id,
            tax_amount=tax_amount,
            taxable_purchase=subtotal,
        )
    econnect.update_po_header_subtotal(
        conn,
        po_number=po_number,
        vendor_id=h.vendor_id,
        doc_date=h.doc_date,
        buyer_id=buyer_id,
        confirm_with=h.confirm_with,
        currency_id=currency,
        vendor_address_code=h.vendor_address_code,
        shipping_method=h.shipping_method,
        subtotal=subtotal,
        trade_discount=h.trade_discount,
        freight_amount=h.freight_amount,
        misc_amount=h.misc_amount,
        tax_amount=tax_amount,
        using_header_taxes=bool(h.tax_detail_id),
        rate_type=rate_type,
        exchange_date=exchange_date,
        null_tax_schedule=is_foreign,
    )

    return models.CreatePoResponse(
        po_number=po_number,
        company=company,
        lines_created=len(request.lines),
        subtotal=subtotal,
        doc_date=h.doc_date,
        vendor_id=h.vendor_id,
        currency=currency,
        tax_amount=tax_amount,
    )


def create_job_op(conn, *, company: str, request: models.CreateJobRequest) -> models.CreateJobResponse:
    """Create a GP job (issue #380): pre-check, dry run, real call. The caller commits.

    1. job_exists pre-check. wsiJCJobMaster would fail on a duplicate anyway, but it does so from inside
       the proc, and this turns that into a clean job_already_exists the dialog can show. It also makes a
       retry after an ambiguous failure safe: if the first attempt actually committed and the reply was
       lost, the retry says "already exists" instead of attempting a second create.
    2. OnlyValidate=1. The proc validates everything - division accounts, customer, both address codes,
       tax schedule, open fiscal period - and reports the FIRST problem in its own words. Running it
       first means a rejected create fails having written nothing, and the user reads GP's actual
       objection rather than a generic failure.
    3. The real call, same parameters.
    4. Read the row back from JC00102 and answer with GP's stored job number and name, NOT the request
       echoed back. The backend snapshots that name onto the project, and what GP kept is the honest
       thing to snapshot - WS_Job_Name is char(31), so a longer name is truncated on write and the
       request no longer describes the job. It also proves the row landed.

    Both passes raise econnect.EConnectError carrying the proc's message (see econnect.create_job)."""
    fields = request.model_dump(exclude={"company"})

    if econnect.job_exists(conn, request.job_number):
        raise RelayOpError(
            "job_already_exists",
            f"job '{request.job_number}' already exists in GP company {company} (JC00102)",
        )

    econnect.create_job(conn, only_validate=True, **fields)
    econnect.create_job(conn, only_validate=False, **fields)

    created = econnect.get_job(conn, request.job_number)
    if created is None:
        # err=0 with no row: the same silent-failure class create_po_line guards against.
        raise econnect.EConnectError(
            f"wsiJCJobMaster reported success but job {request.job_number} is not in JC00102",
            proc="wsiJCJobMaster",
        )

    return models.CreateJobResponse(
        job_number=created["job_number"],
        job_name=created["job_name"] or request.job_name,
        company=company,
    )


def create_buyer_op(conn, *, company: str, request: models.CreateBuyerRequest) -> models.CreateBuyerResponse:
    """Register a GP buyer (issue #409): pre-check, create, read back. The caller commits.

    Same three-beat shape as create_job_op, for the same reasons. The pre-check matters more here
    because taCreateBuyer's body is encrypted: whether it errors on a duplicate or quietly overwrites
    the existing description is not knowable from the proc, and overwriting one would rename a buyer
    that live POs are already attributed to. Checking POP00101 first makes the answer ours.

    The read-back guards the err=0-but-nothing-landed case and returns GP's stored description - the
    column is char(30) on the proc, so a longer one is truncated on write and the request no longer
    describes the row."""
    if econnect.buyer_exists(conn, request.buyer_id):
        raise RelayOpError(
            "buyer_already_exists",
            f"buyer '{request.buyer_id}' is already registered in GP company {company} (POP00101)",
        )

    econnect.create_buyer(conn, buyer_id=request.buyer_id, description=request.description)

    created = next(
        (b for b in econnect.list_buyers_detailed(conn) if b["buyer_id"] == request.buyer_id),
        None,
    )
    if created is None:
        raise econnect.EConnectError(
            f"taCreateBuyer reported success but buyer {request.buyer_id} is not in POP00101",
            proc="taCreateBuyer",
        )

    return models.CreateBuyerResponse(
        company=company,
        buyer_id=created["buyer_id"],
        description=created["description"],
    )


def create_receipt_op(conn, *, company: str, request: models.ReceiptRequest) -> models.ReceiptResponse:
    """Receive against a PO. Reads the PO's lines from POP10110, then: taGetPurchReceiptNextNumber ->
    taPopRcptLineInsert x N -> taPopRcptHdrInsert, and (for companies with a paired custom DB) inserts
    the matching WHRECLINE101 rows the dashboards read. The caller commits the whole thing as one
    transaction; the GP receipt lands in a batch a user posts inside GP."""
    rdate = request.receipt_date or date.today()
    batch = f"{request.batch_prefix}-{rdate:%Y/%m/%d}"
    custom_db = get_settings().gp.custom_db.get(company)  # None for sandboxes / unmapped companies

    vendor_id, vendor_name, po_lines = econnect.read_po_receipt_context(conn, request.po_number)
    if vendor_id is None:
        raise RelayOpError("po_not_found", f"PO {request.po_number} not found in {company}")
    for rl in request.lines:
        if rl.po_line_ord not in po_lines:
            raise RelayOpError(
                "po_line_not_found", f"PO {request.po_number} has no line ORD {rl.po_line_ord}"
            )
        pl = po_lines[rl.po_line_ord]
        if pl["polnesta"] >= 4:
            raise RelayOpError(
                "line_not_receivable",
                f"line ORD {rl.po_line_ord} is closed/cancelled (POLNESTA={pl['polnesta']})",
            )
        # validate against REMAINING (ordered - already received), not just ordered, so cumulative
        # over-receipt across multiple receives is blocked.
        remaining = pl["qtyorder"] - pl["prev_received"]
        if rl.quantity > remaining:
            raise RelayOpError(
                "qty_exceeds_remaining",
                f"line ORD {rl.po_line_ord}: qty {rl.quantity} exceeds remaining {remaining} "
                f"(ordered {pl['qtyorder']}, already received {pl['prev_received']})",
            )

    receipt_number = econnect.get_next_receipt_number(conn)
    # eConnect processes receipt LINES before the header (the line proc creates the receipt document;
    # calling the header insert first makes the line a duplicate).
    rcpt_ln = 16384
    received = []  # (request line, PO line dict, RCPTLNNM) for the WHRECLINE101 write below
    for rl in request.lines:
        pl = po_lines[rl.po_line_ord]
        econnect.create_receipt_line(
            conn,
            receipt_number=receipt_number,
            po_number=request.po_number,
            rcpt_line_num=rcpt_ln,
            po_line_ord=rl.po_line_ord,
            item_number=pl["item"],
            vendor_id=pl["vendor"] or vendor_id,
            vnditnum=pl["vnditnum"],
            uofm=pl["uofm"],
            job_number=pl["job"],
            location_code=pl["locn"],
            noninven=pl["noninven"],
            quantity=rl.quantity,
            receipt_date=rdate,
        )
        received.append((rl, pl, rcpt_ln))
        rcpt_ln += 16384

    # header SUBTOTAL must equal the sum of the autocosted line totals (received qty x the PO line's
    # unit cost)
    subtotal = sum(rl.quantity * po_lines[rl.po_line_ord]["unitcost"] for rl in request.lines)
    econnect.create_receipt_header(
        conn,
        receipt_number=receipt_number,
        po_number=request.po_number,
        vendor_id=vendor_id,
        receipt_date=rdate,
        batch_number=batch,
        subtotal=subtotal,
    )

    # custom warehouse store (WHRECLINE101) - SAME transaction as the GP receipt, so a failure here
    # rolls the GP receipt back too. only runs for a company with a paired custom DB; sandboxes are
    # GP-only.
    if custom_db:
        for rl, pl, rln in received:
            econnect.insert_whrecline_row(
                conn,
                custom_db=custom_db,
                po_number=request.po_number,
                polnenum=rl.po_line_ord,
                poprctnm=receipt_number,
                rcptlnnm=rln,
                qty_ordered=int(pl["qtyorder"]),
                qty_received=int(rl.quantity),
                item=pl["item"],
                itemdesc=pl["itemdesc"],
                vendor_id=vendor_id,
                vendname=vendor_name,
                job=pl["job"],
                jobname=pl["jobname"],
                location=rl.rack_location,
                revision=rl.revision_number,
                comments=rl.comments,
                date_received=rdate,
                received_by=request.received_by,
            )

    return models.ReceiptResponse(
        receipt_number=receipt_number,
        batch_number=batch,
        po_number=request.po_number,
        company=company,
        lines_received=len(request.lines),
        custom_db_written=bool(custom_db),
    )
