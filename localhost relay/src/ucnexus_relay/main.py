"""FastAPI app for the UC Nexus relay.

Endpoints:
  GET  /health           — liveness, no auth
  GET  /info             — config + read-only SQL identity probe, auth required
  POST /po/next-number   — reserve a PO number (live taGetPONextNumber), auth required
  POST /po               — create a PO end-to-end (5-step orchestration), auth required
"""

import time
from datetime import date

import pyodbc
from fastapi import Depends, FastAPI, HTTPException

from . import auth, db, econnect, errors, models
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
            detail={"error": "company_not_allowed", "message": f"{company} not in allowed_companies {allowed}"},
        )


def _econnect_http(conn, e: econnect.EConnectError) -> HTTPException:
    desc = errors.lookup_error_description(conn, e.error_state) if e.error_state else None
    return HTTPException(
        status_code=502,
        detail={
            "error": "econnect_error",
            "proc": e.proc,
            "error_state": e.error_state,
            "error_description": desc or str(e),
        },
    )


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.logging.level, settings.logging.file)
    logger = get_logger()

    app = FastAPI(title="UC Nexus Relay", version=VERSION)
    configure_cors(app)

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
        out = {
            "version": VERSION,
            "configured_companies": s.gp.allowed_companies,
            "default_company": s.gp.default_company,
            "sql_server": s.sql.server,
            "odbc_driver": s.sql.driver,
            "driver_installed": db.driver_available(),
        }
        try:
            out.update(db.connection_info(s.gp.default_company))
        except pyodbc.Error as e:
            out["connection_error"] = str(e)
        return out

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
            raise HTTPException(status_code=502, detail={"error": "sql_error", "message": str(e)})

    @app.post("/po", response_model=models.CreatePoResponse, status_code=201)
    def create_po(request: models.CreatePoRequest, _=Depends(auth.verify_token)):
        _check_company(request.company)
        h = request.header
        try:
            with db.get_connection(request.company) as conn:
                try:
                    # 1. PO number: use UC Nexus's own number (e.g. 'ucnexus...') if supplied,
                    #    else reserve GP's next 'PO' number via taGetPONextNumber.
                    if request.po_number:
                        po_number = request.po_number
                        econnect.assert_po_number_available(conn, po_number)
                    else:
                        po_number = econnect.get_next_po_number(conn)

                    # 2. header (no SUBTOTAL yet)
                    econnect.create_po_header(
                        conn,
                        po_number=po_number,
                        vendor_id=h.vendor_id,
                        doc_date=h.doc_date,
                        buyer_id=h.buyer_id,
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
                        buyer_id=h.buyer_id,
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
            raise HTTPException(status_code=502, detail={"error": "sql_error", "message": str(e)})

    @app.post("/receipt", response_model=models.ReceiptResponse, status_code=201)
    def create_receipt(request: models.ReceiptRequest, _=Depends(auth.verify_token)):
        """Receive against a PO created in workflow 1. Reads the PO's lines from POP10110,
        then runs taGetPurchReceiptNextNumber -> taPopRcptHdrInsert -> taPopRcptLineInsert x N
        in one transaction. The receipt lands in a GP batch a user posts inside GP."""
        _check_company(request.company)
        rdate = request.receipt_date or date.today()
        batch = f"{request.batch_prefix}-{rdate:%Y/%m/%d}"
        try:
            with db.get_connection(request.company) as conn:
                try:
                    vendor_id, po_lines = econnect.read_po_receipt_context(conn, request.po_number)
                    if vendor_id is None:
                        raise HTTPException(
                            status_code=404,
                            detail={"error": "po_not_found",
                                    "message": f"PO {request.po_number} not found in {request.company}"},
                        )
                    for rl in request.lines:
                        if rl.po_line_ord not in po_lines:
                            raise HTTPException(
                                status_code=400,
                                detail={"error": "po_line_not_found",
                                        "message": f"PO {request.po_number} has no line ORD {rl.po_line_ord}"},
                            )
                        ordered = po_lines[rl.po_line_ord]["qtyorder"]
                        if rl.quantity > ordered:
                            raise HTTPException(
                                status_code=400,
                                detail={"error": "qty_exceeds_ordered",
                                        "message": f"line ORD {rl.po_line_ord}: qty {rl.quantity} exceeds ordered {ordered}"},
                            )

                    receipt_number = econnect.get_next_receipt_number(conn)
                    # eConnect processes receipt LINES before the header (the line proc creates the
                    # receipt document; calling the header insert first makes the line a duplicate).
                    rcpt_ln = 16384
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

                    conn.commit()
                    return models.ReceiptResponse(
                        receipt_number=receipt_number,
                        batch_number=batch,
                        po_number=request.po_number,
                        company=request.company,
                        lines_received=len(request.lines),
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
            raise HTTPException(status_code=502, detail={"error": "sql_error", "message": str(e)})

    return app


app = create_app()
