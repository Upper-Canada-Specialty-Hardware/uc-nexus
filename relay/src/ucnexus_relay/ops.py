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


# GP's POP10100.PONUMBER is char(17). Anything longer is silently truncated by SQL Server, which
# would produce a PO nobody can match back to the number Nexus recorded (#488).
_MAX_PO_NUMBER = 17


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
        # Issue #425: the cost code exists on the job, but the GL account index it carries may not
        # exist in this company's chart. That is the pre-2023 UCSH -> UBC job copy's legacy - 1504
        # JC00701 rows across 62 UBC jobs point at UCSH indexes - and the WennSoft integration copies
        # the index onto POP10110.INVINDX at step 4 below. Nothing objects at that point; the PO
        # registers cleanly and then fails FOREVER at receipt with eConnect 4612 "Invalid Account
        # Index", by which time the hardware is on a truck. Refusing it here costs one SELECT and
        # turns an unreceivable PO into a message naming the code and the index.
        account_index = econnect.cost_code_account_index(conn, job, line.cost_code)
        if account_index is not None and not econnect.account_index_exists(conn, account_index):
            raise RelayOpError(
                "cost_code_account_invalid",
                f"cost code '{line.cost_code}' on job '{job}' points at GL account index "
                f"{account_index}, which does not exist in {company} (GL00105). A PO on this cost "
                f"code would register but could never be received; the job's GP setup needs fixing "
                f"in accounting first.",
                job=job,
                cost_code=line.cost_code,
                account_index=account_index,
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
        # #488: GP still owns and reserves the number; the suffix only makes it traceable. GP's
        # PONUMBER is char(17), so a long project number can overflow - refuse here rather than let
        # SQL Server truncate silently into a number nobody can match back to the job.
        if request.po_number_suffix:
            composed = f"{po_number.strip()}-{request.po_number_suffix}"
            if len(composed) > _MAX_PO_NUMBER:
                raise RelayOpError(
                    "invalid_payload",
                    f"PO number '{composed}' is {len(composed)} characters; GP's PONUMBER holds "
                    f"{_MAX_PO_NUMBER}. Shorten the project number suffix.",
                    po_number=composed,
                )
            po_number = composed

        # The composed number is a different string from the one GP reserved, so it gets the same
        # collision check an explicit number does.
        in_use = econnect.po_number_in_use(conn, po_number)
        if in_use:
            raise RelayOpError(
                "po_number_taken", f"PO number '{po_number}' is already in use in GP as {in_use}"
            )

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


def _resolve_cost_code_selection(conn, *, company: str, request: models.CreateJobRequest) -> list[dict]:
    """Resolve the requested cost codes against the company master (issue #448) and return the master
    rows the write step will provision from. Writes nothing.

    Runs BEFORE the job proc, not after it. The selection is checked against GP's own tables, so a
    stale picker or a made-up code is a refusal that must cost nothing - and it only costs nothing if
    it happens before wsiJCJobMaster has created anything. Rolling the job back afterwards would work,
    but "the create failed and nothing was written" is a promise the ordering keeps rather than one the
    transaction has to rescue.

    Every value provisioned comes from the company master, never from the request. The selection names
    which codes the job gets; the alias, description, profit type, transaction type and above all the
    GL account index are read out of JC40202/JC40302 here. That is the same provenance rule #427 and
    #430 settled for actors and accounts elsewhere: GP's configuration decides, and a caller that could
    send an account index could post a job's costs anywhere in the chart.

    Two refusals:
      - a code that is not in JC40202 at all. The picker is fed from that table, so this is a stale
        client or a made-up code, and the proc would take it and create a cost code the company's own
        setup has never heard of.
      - a code JC40302 has no usable account for in this job's division. Provisioning it would
        manufacture exactly the dangling JC00701 row #425 is about - the job would register POs and
        then fail forever at receipt with eConnect 4612.

    An empty selection short-circuits without reading the master at all: that is what every pre-#448
    caller sends, and for them the create path has to be exactly what it was."""
    if not request.cost_codes:
        return []

    master = {
        (row["cost_code"], row["cost_element"]): row
        for row in econnect.list_cost_code_master(conn, request.division)
    }

    chosen = []
    for selection in request.cost_codes:
        row = master.get((selection.cost_code, selection.cost_element))
        if row is None:
            raise RelayOpError(
                "cost_code_not_in_master",
                f"cost code '{selection.cost_code}' element {selection.cost_element} is not in the "
                f"cost-code master (JC40202) for GP company {company}",
                cost_code=selection.cost_code,
                cost_element=selection.cost_element,
            )
        if not row["mapped"]:
            raise RelayOpError(
                "cost_code_unmapped",
                f"cost code '{selection.cost_code}' element {selection.cost_element} has no usable GL "
                f"account for division '{request.division}' in {company}: JC40302 maps no account index "
                f"for that cost element, or the one it maps does not exist in the chart (GL00105). A job "
                f"provisioned with it could register POs and never receive them.",
                cost_code=selection.cost_code,
                cost_element=selection.cost_element,
                division=request.division,
            )
        chosen.append(row)
    return chosen


def _write_cost_codes(conn, *, request: models.CreateJobRequest, chosen: list[dict]) -> int:
    """Write the resolved cost codes onto the job just created (issue #448) and return how many landed.
    Runs inside the caller's transaction, so the job and its cost structure commit together or neither
    does - a job that exists with half its codes is the state this whole feature exists to avoid, since
    #425's quarantine would hold it and nobody would know why.

    The rows come from _resolve_cost_code_selection, which already refused anything the master does not
    know or cannot account for, so by here there is nothing left to reject on our side.

    Validate ALL of them before writing ANY of them, the same reason create_job_op dry-runs the job
    proc: the eleventh code failing after ten were written leaves a partially provisioned job that only
    a rollback saves, and the rollback is what the dry run makes unnecessary.

    The segments are bound straight off the master row (cost_code_number_1 / _2) rather than re-split
    out of the joined 'cc1-cc2' form. Re-splitting a segment that itself contains a '-' would provision
    a different row than the one the picker named, and the master already hands over exactly what GP
    stores.

    Then verify EACH code through econnect.cost_code_on_job - the same lookup /po runs before it lets a
    line reference a cost code. taPoLine has a known err=0-but-no-row silent-failure mode and this is
    the same class of proc, so a success report is not evidence a row landed. Checking per code through
    the PO path's own lookup means "provisioned" and "reachable by a PO" cannot drift apart: a row that
    landed but that lookup cannot find is a row no PO could ever use, and that is a failure whether or
    not JC00701 has something in it. It also needs no assumption about rows this call did not write,
    which a COUNT of the job's whole active set does - that count is only correct while nothing else
    ever seeds JC00701 for a new job."""
    if not chosen:
        return 0

    for only_validate in (True, False):
        for row in chosen:
            econnect.create_job_cost_code(
                conn,
                only_validate=only_validate,
                job_number=request.job_number,
                cost_code_number_1=row["cost_code_number_1"],
                cost_code_number_2=row["cost_code_number_2"],
                alias=row["alias"] or "",
                description=row["description"] or "",
                cost_element=row["cost_element"],
                account_index=row["account_index"],
                profit_type_number=row["profit_type_number"],
                type_of_transaction=row["type_of_transaction"],
            )

    for row in chosen:
        # 'phase-step-element', the shape the register-PO dropdown (list_cost_codes) and the /po
        # cost_code speak, so this asks the question a PO will ask, in the words a PO will ask it in.
        cost_code = f"{row['cost_code']}-{row['cost_element']}"
        if not econnect.cost_code_on_job(conn, request.job_number, cost_code):
            raise econnect.EConnectError(
                f"wsiJCJobDetailMSTR reported success but cost code {cost_code} is not on job "
                f"{request.job_number} in JC00701",
                proc="wsiJCJobDetailMSTR",
            )
    return len(chosen)


def create_job_op(conn, *, company: str, request: models.CreateJobRequest) -> models.CreateJobResponse:
    """Create a GP job (issue #380): pre-check, dry run, real call. The caller commits.

    1. job_exists pre-check. wsiJCJobMaster would fail on a duplicate anyway, but it does so from inside
       the proc, and this turns that into a clean job_already_exists the dialog can show. It also makes a
       retry after an ambiguous failure safe: if the first attempt actually committed and the reply was
       lost, the retry says "already exists" instead of attempting a second create.
    2. Resolve the cost-code selection against JC40202/JC40302 (issue #448, see
       _resolve_cost_code_selection). Read-only, and deliberately ahead of the job proc: a selection GP's
       own master does not recognise is a stale picker, and refusing it here means the create fails
       having written nothing at all - which is what step 3's dry run promises for the job's own fields
       and what the selection deserves for the same reason. A no-op when no cost codes were selected,
       which is what every pre-#448 caller sends.
    3. OnlyValidate=1. The proc validates everything - division accounts, customer, both address codes,
       tax schedule, open fiscal period - and reports the FIRST problem in its own words. Running it
       first means a rejected create fails having written nothing, and the user reads GP's actual
       objection rather than a generic failure.
    4. The real call, same parameters.
    5. Read the row back from JC00102 and answer with GP's stored job number and name, NOT the request
       echoed back. The backend snapshots that name onto the project, and what GP kept is the honest
       thing to snapshot - WS_Job_Name is char(31), so a longer name is truncated on write and the
       request no longer describes the job. It also proves the row landed.
    6. Write the resolved cost codes onto it (see _write_cost_codes). wsiJCJobMaster writes the JC00102
       row and nothing else, so without this the job is created into #425's quarantine - no active cost
       codes - and its register-PO dropdown is empty. Inside the SAME transaction the caller commits, so
       the job and its cost structure land together or not at all.

    Both passes raise econnect.EConnectError carrying the proc's message (see econnect.create_job)."""
    # cost_codes is a provisioning instruction for steps 2 and 6, not a wsiJCJobMaster field - leaving
    # it in would trip create_job's unknown-field guard on every call (#448).
    fields = request.model_dump(exclude={"company", "cost_codes"})

    if econnect.job_exists(conn, request.job_number):
        raise RelayOpError(
            "job_already_exists",
            f"job '{request.job_number}' already exists in GP company {company} (JC00102)",
        )

    chosen_cost_codes = _resolve_cost_code_selection(conn, company=company, request=request)

    econnect.create_job(conn, only_validate=True, **fields)
    econnect.create_job(conn, only_validate=False, **fields)

    created = econnect.get_job(conn, request.job_number)
    if created is None:
        # err=0 with no row: the same silent-failure class create_po_line guards against.
        raise econnect.EConnectError(
            f"wsiJCJobMaster reported success but job {request.job_number} is not in JC00102",
            proc="wsiJCJobMaster",
        )

    provisioned = _write_cost_codes(conn, request=request, chosen=chosen_cost_codes)

    return models.CreateJobResponse(
        job_number=created["job_number"],
        job_name=created["job_name"] or request.job_name,
        company=company,
        cost_codes_provisioned=provisioned,
    )


def _address_code_already_exists(company: str, request: models.CreateCustomerAddressRequest) -> RelayOpError:
    """The one sentence a duplicate address code is reported with, wherever it is detected. Both halves
    of create_customer_address_op's duplicate guard raise it, so a race loser reads identically to a
    caller who lost the race by a full second - the user is looking at the same situation either way."""
    return RelayOpError(
        "address_code_already_exists",
        f"customer '{request.customer_number}' already has address code '{request.address_code}' "
        f"in GP company {company} (RM00102)",
    )


def create_customer_address_op(
    conn, *, company: str, request: models.CreateCustomerAddressRequest
) -> models.CreateCustomerAddressResponse:
    """Add an address code to a GP customer (issue #444): pre-check, create, read back. The caller
    commits.

    The same three beats as create_buyer_op, and here they carry more weight. taCreateCustomerAddress
    has NO OnlyValidate parameter, so there is no dry-run pass to fall back on the way create_job_op
    has - the duplicate guard is ours to build, and it is what lets econnect.create_customer_address
    pin UpdateIfExists to 0 (see that docstring: overwriting an address accounting already maintains is
    the one outcome this feature must never produce).

    That guard is in two parts, because the pre-check alone is check-then-act. It is the first line and
    answers almost every duplicate, including the important one: if a first attempt committed and the
    reply was lost, pressing Create again reads as "that customer already has this address code" rather
    than as a raw eConnect state for something that already worked. But between that SELECT and the
    EXEC, a second Nexus caller or somebody in GP's own Customer Address Maintenance window can save the
    same code, and then the proc is what refuses it. So an eConnect failure re-runs the check on the way
    out: if the row is there now, the race is what happened, and it is worded the same as if the
    pre-check had caught it. Anything else re-raises untouched.

    The read-back guards the err=0-but-nothing-landed case create_po_line has a known mode for, and
    answers with GP's stored row - which is exactly what list_customer_addresses will serve the picker
    on its next refetch, so answering with anything else could hand the dialog an address that differs
    from the one everything else is about to see."""
    if econnect.customer_address_exists(conn, request.customer_number, request.address_code):
        raise _address_code_already_exists(company, request)

    try:
        econnect.create_customer_address(conn, request.model_dump(exclude={"company"}))
    except econnect.EConnectError as e:
        # One extra SELECT on a path that has already failed, and it is what turns "eConnect state 350"
        # into a sentence naming the customer and the code. Chained from the original so the raw GP
        # failure is still in the traceback for anyone reading relay.log.
        if econnect.customer_address_exists(conn, request.customer_number, request.address_code):
            raise _address_code_already_exists(company, request) from e
        raise

    created = econnect.get_customer_address(conn, request.customer_number, request.address_code)
    if created is None:
        raise econnect.EConnectError(
            f"taCreateCustomerAddress reported success but address '{request.address_code}' is not in "
            f"RM00102 for customer '{request.customer_number}'",
            proc="taCreateCustomerAddress",
        )

    return models.CreateCustomerAddressResponse(
        company=company,
        customer=request.customer_number,
        address=models.CustomerAddressOut(**created),
    )


def create_buyer_op(conn, *, company: str, request: models.CreateBuyerRequest) -> models.CreateBuyerResponse:
    """Register a GP buyer (issue #409): pre-check, create, read back. The caller commits.

    Same three-beat shape as create_job_op, for the same reasons. taCreateBuyer does reject a
    duplicate on its own (error state 2684), but it does so from inside the proc, and this turns that
    into a clean buyer_already_exists the dialog can show. It also makes a retry after an ambiguous
    failure safe: if the first attempt committed and the reply was lost, the retry says "already
    registered" instead of surfacing a raw eConnect state for something that already worked.

    The read-back guards the err=0-but-nothing-landed case and answers with GP's stored row, which is
    what the buyer dropdowns will show on their next refetch. It goes through econnect.get_buyer, so
    it normalizes the id exactly as the buyer_exists pre-check does - a Python match against the whole
    buyer master would disagree with the pre-check on case and roll back a create that worked."""
    if econnect.buyer_exists(conn, request.buyer_id):
        raise RelayOpError(
            "buyer_already_exists",
            f"buyer '{request.buyer_id}' is already registered in GP company {company} (POP00101)",
        )

    econnect.create_buyer(conn, buyer_id=request.buyer_id, description=request.description)

    created = econnect.get_buyer(conn, request.buyer_id)
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

    # Issue #425: pre-flight the account index each line was stamped with at registration.
    # taPopRcptLineInsert reads POP10110.INVINDX and rejects an index that is not in GL00105 with
    # eConnect 4612 "Invalid Account Index" - the failure that started this issue. Raised as a
    # RelayOpError rather than left to the proc for two reasons: 4612 says nothing about which line or
    # which account, and the whole receipt has already been half-built by the time the proc gets there.
    # Only the lines being received are checked; an unrelated broken line on the same PO is somebody
    # else's problem on the day they try to receive it.
    receiving_ords = {rl.po_line_ord for rl in request.lines}
    broken = [b for b in econnect.po_lines_with_dangling_account(conn, request.po_number) if b["ord"] in receiving_ords]
    if broken:
        first = broken[0]
        raise RelayOpError(
            "po_line_account_invalid",
            f"PO {request.po_number} line {first['ord']} ({first['item']}) is stamped with GL account "
            f"index {first['account_index']}, which does not exist in {company} (GL00105). This came "
            f"from job '{first['job'] or 'unknown'}' cost-code setup when the PO was registered, so "
            f"the receipt cannot be posted until accounting fixes the job's GP setup.",
            po_number=request.po_number,
            lines=broken,
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
