"""FastAPI app for the UC Nexus relay.

Endpoints:
  GET  /health           — liveness, no auth
  GET  /info             — config + read-only SQL identity probe (+ workstation hostname), auth required
  GET  /vendors          — PM00200 vendor list for the vendor sync, auth required
  GET  /buyers           — POP00101 registered buyers for the Create PO buyer dropdown, auth required
  GET  /cost-codes       — JC00701 per-job cost codes for the Create PO cost-code dropdown, auth required
  POST /po/next-number   — reserve a PO number (live taGetPONextNumber), auth required
  POST /po               — create a PO end-to-end (5-step orchestration), auth required
  POST /receipt          — receive against a PO, auth required
"""

import socket
import time
from datetime import date

import pyodbc
from fastapi import Depends, FastAPI, HTTPException

from . import auth, buyers, db, econnect, errors, models
from .config import get_settings
from .cors import configure_cors
from .logging_setup import configure_logging, get_logger

VERSION = "0.1.0"
_START = time.monotonic()


def _check_company(company: str) -> None:
    allowed = get_settings().gp.allowed_companies
    if company not in allowed:
        raise HTTPException(
            status_code=400,
            detail=errors.error_body("company_not_allowed", f"{company} not in allowed_companies {allowed}"),
        )


def _econnect_http(conn, e: econnect.EConnectError) -> HTTPException:
    desc = errors.lookup_error_description(conn, e.error_state) if e.error_state else None
    return HTTPException(
        status_code=502,
        detail=errors.error_body(
            "econnect_error",
            desc or str(e),
            proc=e.proc,
            error_state=e.error_state,
            error_description=desc,
        ),
    )


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.logging.level, settings.logging.file)
    logger = get_logger()

    app = FastAPI(title="UC Nexus Relay", version=VERSION)
    configure_cors(app)

    @app.middleware("http")
    async def add_pna_header(request, call_next):
        # Legacy Private Network Access answer, for stragglers on a pre-LNA Chrome. The browser hop
        # from the https Railway page to http://localhost is governed by Local Network Access (a
        # client-side permission prompt + targetAddressSpace:"loopback" on the fetch) on current
        # Chrome, NOT by this header. We echo it only when the browser asks (the PNA preflight sends
        # Access-Control-Request-Private-Network: true); it is harmless and not the mechanism.
        response = await call_next(request)
        if request.method == "OPTIONS" and request.headers.get("access-control-request-private-network") == "true":
            response.headers["Access-Control-Allow-Private-Network"] = "true"
        return response

    if not db.driver_available():
        logger.warning(
            "configured ODBC driver not found", extra={"driver": settings.sql.driver, "available": pyodbc.drivers()}
        )

    @app.middleware("http")
    async def log_requests(request, call_next):
        start = time.perf_counter()
        response = await call_next(request)
        dur = (time.perf_counter() - start) * 1000
        logger.info(
            "request",
            extra={
                "method": request.method,
                "path": request.url.path,
                "status": response.status_code,
                "duration_ms": round(dur, 1),
            },
        )
        return response

    @app.get("/health")
    def health():
        return {"status": "ok", "version": VERSION, "uptime_seconds": round(time.monotonic() - _START, 1)}

    @app.get("/info")
    def info(_=Depends(auth.verify_token)):
        s = get_settings()
        hostname = socket.gethostname()
        out = {
            "version": VERSION,
            "configured_companies": s.gp.allowed_companies,
            "default_company": s.gp.default_company,
            "sql_server": s.sql.server,
            "odbc_driver": s.sql.driver,
            "driver_installed": db.driver_available(),
            "hostname": hostname,  # the device name the relay maps to a GP buyer
        }
        try:
            out.update(db.connection_info(s.gp.default_company))
        except pyodbc.Error as e:
            out["connection_error"] = str(e)
        # which buyer this workstation resolves to (confirm hostname->BUYERID during deployment)
        out["resolved_buyer"] = buyers.resolve_buyer(s.gp.buyers, hostname, out.get("connected_as"))
        return out

    @app.get("/vendors", response_model=models.VendorsResponse)
    def vendors(company: str | None = None, _=Depends(auth.verify_token)):
        """Read PM00200 (active vendors) for the vendor sync. The frontend posts this list to UC
        Nexus's syncGpVendors, which fills Vendor.gp_vendor_id by matching on name."""
        company = company or get_settings().gp.default_company
        _check_company(company)
        try:
            with db.get_read_connection(company) as conn:
                rows = econnect.list_vendors(conn, active_only=True)
        except pyodbc.Error as e:
            raise HTTPException(status_code=502, detail=errors.error_body("sql_error", str(e)))
        return models.VendorsResponse(company=company, vendors=[models.VendorOut(**r) for r in rows])

    @app.get("/buyers", response_model=models.BuyersResponse)
    def gp_buyers(company: str | None = None, _=Depends(auth.verify_token)):
        """Registered GP buyers (POP00101) for the Create PO buyer dropdown. eConnect validates BUYERID
        against this, so the UI must pick from it (a device hostname is not a registered buyer)."""
        company = company or get_settings().gp.default_company
        _check_company(company)
        try:
            with db.get_read_connection(company) as conn:
                ids = econnect.list_buyers(conn)
        except pyodbc.Error as e:
            raise HTTPException(status_code=502, detail=errors.error_body("sql_error", str(e)))
        return models.BuyersResponse(company=company, buyers=ids)

    @app.get("/cost-codes", response_model=models.CostCodesResponse)
    def cost_codes(job: str, company: str | None = None, _=Depends(auth.verify_token)):
        """Active cost codes for one job (JC00701) for the Create PO cost-code dropdown. Cost codes
        are per-job and each carries its own Cost_Element, so the dropdown and the /po cost_code must
        come from here rather than a static list with a hardcoded element. `job` is the GP job number
        (UC Nexus project_id). A job with no cost codes returns an empty list (the UI shows that)."""
        company = company or get_settings().gp.default_company
        _check_company(company)
        job = job.strip()
        if not job:
            raise HTTPException(status_code=422, detail=errors.error_body("missing_job", "job is required"))
        try:
            with db.get_read_connection(company) as conn:
                rows = econnect.list_cost_codes(conn, job)
        except pyodbc.Error as e:
            raise HTTPException(status_code=502, detail=errors.error_body("sql_error", str(e)))
        return models.CostCodesResponse(
            company=company, job=job, cost_codes=[models.CostCodeOut(**r) for r in rows]
        )

    @app.post("/po/next-number")
    def next_number(request: models.NextNumberRequest, _=Depends(auth.verify_token)):
        _check_company(request.company)
        try:
            with db.get_connection(request.company) as conn:
                try:
                    po = econnect.get_next_po_number(conn)
                    conn.commit()
                    return {"po_number": po, "company": request.company}
                except econnect.EConnectError as e:
                    conn.rollback()
                    raise _econnect_http(conn, e)
                except Exception:
                    conn.rollback()
                    raise
        except pyodbc.Error as e:
            raise HTTPException(status_code=502, detail=errors.error_body("sql_error", str(e)))

    @app.post("/po", response_model=models.CreatePoResponse, status_code=201)
    def create_po(request: models.CreatePoRequest, _=Depends(auth.verify_token)):
        _check_company(request.company)
        h = request.header
        try:
            with db.get_connection(request.company) as conn:
                try:
                    # 0. buyer: the Create PO dropdown sends a buyer_id picked from GP's registered
                    #    buyers (POP00101, see GET /buyers). If omitted, fall back to the [gp.buyers]
                    #    config (by_host -> by_login -> default). The value MUST be a registered GP buyer.
                    buyer_id = h.buyer_id
                    if not buyer_id:
                        bcfg = get_settings().gp.buyers
                        login = None
                        if bcfg.by_login:
                            login = conn.cursor().execute("SELECT SUSER_NAME()").fetchone()[0]
                        buyer_id = buyers.resolve_buyer(bcfg, socket.gethostname(), login)
                        if not buyer_id:
                            raise HTTPException(
                                status_code=400,
                                detail=errors.error_body(
                                    "buyer_unresolved",
                                    "no buyer_id sent and none resolved from [gp.buyers]; "
                                    "pick a buyer from GET /buyers",
                                ),
                            )

                    # validate against GP's buyer master: eConnect taPoHdr rejects an unregistered BUYERID
                    # with error 269, so give a clear error here instead.
                    registered = econnect.list_buyers(conn)
                    if buyer_id not in registered:
                        raise HTTPException(
                            status_code=400,
                            detail=errors.error_body(
                                "buyer_not_registered",
                                f"buyer '{buyer_id}' is not a registered GP buyer for "
                                f"{request.company} (registered: {registered})",
                            ),
                        )

                    # 0b. job + cost code: GP has a job master (JC00102) and per-job cost codes
                    #     (JC00701). The wsi proc (step 4) rejects a made-up job or a cost code not
                    #     set up on the job with a raw eConnect error mid-transaction, so pre-check
                    #     job-cost lines here for clean job_not_registered / cost_code_not_on_job
                    #     400s, mirroring the buyer check. Only PI=2 lines carry a job/cost code
                    #     (the model validator guarantees PI=2 has both, PI=1 has neither).
                    job_ok: dict[str, bool] = {}  # cache: a PO can repeat a job across lines
                    for line in request.lines:
                        if line.product_indicator != 2:
                            continue
                        job = line.job_number
                        if job not in job_ok:
                            job_ok[job] = econnect.job_exists(conn, job)
                        if not job_ok[job]:
                            raise HTTPException(
                                status_code=400,
                                detail=errors.error_body(
                                    "job_not_registered",
                                    f"job '{job}' is not a registered GP job (JC00102) for {request.company}",
                                ),
                            )
                        if not econnect.cost_code_on_job(conn, job, line.cost_code):
                            raise HTTPException(
                                status_code=400,
                                detail=errors.error_body(
                                    "cost_code_not_on_job",
                                    f"cost code '{line.cost_code}' is not set up on job "
                                    f"'{job}' (JC00701) for {request.company}",
                                ),
                            )

                    # 1. PO number: use UC Nexus's own number (e.g. 'ucnexus...') if supplied,
                    #    else reserve GP's next 'PO' number via taGetPONextNumber. A client-supplied
                    #    number is rejected if it's already used anywhere in GP - active OR history
                    #    (POP10100 / POP30100 / POP30300) - so a reused number fails fast with a clean
                    #    po_number_taken instead of colliding mid-orchestration.
                    if request.po_number:
                        po_number = request.po_number
                        in_use = econnect.po_number_in_use(conn, po_number)
                        if in_use:
                            raise HTTPException(
                                status_code=400,
                                detail=errors.error_body(
                                    "po_number_taken",
                                    f"PO number '{po_number}' is already in use in GP as {in_use}",
                                ),
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
                        currency_id=h.currency_id,
                        vendor_address_code=h.vendor_address_code,
                        shipping_method=h.shipping_method,
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
                        )

                    # 4. WennSoft integration for EVERY line — this is what sets
                    #    Product_Indicator (1 non-inv / 2 job cost); taPoLine can't.
                    for idx, line in enumerate(request.lines, start=1):
                        econnect.apply_wennsoft_integration(
                            conn,
                            po_number=po_number,
                            line_ord=idx * 16384,
                            product_indicator=line.product_indicator,
                            job_number=line.job_number,
                            cost_code=line.cost_code,
                        )

                    # 5. header subtotal
                    subtotal = sum(line.quantity * line.unit_cost for line in request.lines)
                    econnect.update_po_header_subtotal(
                        conn,
                        po_number=po_number,
                        vendor_id=h.vendor_id,
                        doc_date=h.doc_date,
                        buyer_id=buyer_id,
                        confirm_with=h.confirm_with,
                        currency_id=h.currency_id,
                        vendor_address_code=h.vendor_address_code,
                        shipping_method=h.shipping_method,
                        subtotal=subtotal,
                    )

                    conn.commit()
                    return models.CreatePoResponse(
                        po_number=po_number,
                        company=request.company,
                        lines_created=len(request.lines),
                        subtotal=subtotal,
                        doc_date=h.doc_date,
                        vendor_id=h.vendor_id,
                    )
                except econnect.EConnectError as e:
                    conn.rollback()
                    raise _econnect_http(conn, e)
                except Exception:
                    conn.rollback()
                    raise
        except pyodbc.Error as e:
            raise HTTPException(status_code=502, detail=errors.error_body("sql_error", str(e)))

    @app.post("/receipt", response_model=models.ReceiptResponse, status_code=201)
    def create_receipt(request: models.ReceiptRequest, _=Depends(auth.verify_token)):
        """Receive against a PO. Reads the PO's lines from POP10110, then in ONE transaction:
        taGetPurchReceiptNextNumber -> taPopRcptLineInsert x N -> taPopRcptHdrInsert, and (for companies
        with a paired custom DB) inserts the matching WHRECLINE101 rows the dashboards read. The GP
        receipt lands in a batch a user posts inside GP."""
        _check_company(request.company)
        rdate = request.receipt_date or date.today()
        batch = f"{request.batch_prefix}-{rdate:%Y/%m/%d}"
        custom_db = get_settings().gp.custom_db.get(request.company)  # None for sandboxes / unmapped companies
        try:
            with db.get_connection(request.company) as conn:
                try:
                    vendor_id, vendor_name, po_lines = econnect.read_po_receipt_context(conn, request.po_number)
                    if vendor_id is None:
                        raise HTTPException(
                            status_code=404,
                            detail=errors.error_body(
                                "po_not_found", f"PO {request.po_number} not found in {request.company}"
                            ),
                        )
                    for rl in request.lines:
                        if rl.po_line_ord not in po_lines:
                            raise HTTPException(
                                status_code=400,
                                detail=errors.error_body(
                                    "po_line_not_found", f"PO {request.po_number} has no line ORD {rl.po_line_ord}"
                                ),
                            )
                        pl = po_lines[rl.po_line_ord]
                        if pl["polnesta"] >= 4:
                            raise HTTPException(
                                status_code=400,
                                detail=errors.error_body(
                                    "line_not_receivable",
                                    f"line ORD {rl.po_line_ord} is closed/cancelled (POLNESTA={pl['polnesta']})",
                                ),
                            )
                        # validate against REMAINING (ordered - already received), not just ordered, so
                        # cumulative over-receipt across multiple receives is blocked.
                        remaining = pl["qtyorder"] - pl["prev_received"]
                        if rl.quantity > remaining:
                            raise HTTPException(
                                status_code=400,
                                detail=errors.error_body(
                                    "qty_exceeds_remaining",
                                    f"line ORD {rl.po_line_ord}: qty {rl.quantity} exceeds remaining {remaining} "
                                    f"(ordered {pl['qtyorder']}, already received {pl['prev_received']})",
                                ),
                            )

                    receipt_number = econnect.get_next_receipt_number(conn)
                    # eConnect processes receipt LINES before the header (the line proc creates the
                    # receipt document; calling the header insert first makes the line a duplicate).
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

                    # header SUBTOTAL must equal the sum of the autocosted line totals
                    # (received qty x the PO line's unit cost)
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

                    # custom warehouse store (WHRECLINE101) - SAME transaction as the GP receipt, so a
                    # failure here rolls the GP receipt back too (no orphaned receipt). only runs for a
                    # company with a paired custom DB; sandboxes are GP-only.
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

                    conn.commit()
                    return models.ReceiptResponse(
                        receipt_number=receipt_number,
                        batch_number=batch,
                        po_number=request.po_number,
                        company=request.company,
                        lines_received=len(request.lines),
                        custom_db_written=bool(custom_db),
                    )
                except econnect.EConnectError as e:
                    conn.rollback()
                    raise _econnect_http(conn, e)
                except HTTPException:
                    conn.rollback()
                    raise
                except Exception:
                    conn.rollback()
                    raise
        except pyodbc.Error as e:
            raise HTTPException(status_code=502, detail=errors.error_body("sql_error", str(e)))

    return app


app = create_app()
