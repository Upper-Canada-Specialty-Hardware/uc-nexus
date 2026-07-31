"""FastAPI app for the UC Nexus relay.

Endpoints:
  GET  /health           — liveness, no auth
  GET  /info             — config + read-only SQL identity probe (+ workstation hostname), auth required
  GET  /vendors          — PM00200 vendor list for the vendor sync, auth required
  GET  /buyers           — POP00101 registered buyers for the Create PO buyer dropdown, auth required
  GET  /tax-details      — TX00201 purchase tax details for the register-PO tax-detail dropdown, auth required
  GET  /cost-codes       — JC00701 per-job cost codes for the Create PO cost-code dropdown, auth required
  POST /po/next-number   — reserve a PO number (live taGetPONextNumber), auth required
  POST /po               — create a PO end-to-end (5-step orchestration), auth required
  POST /receipt          — receive against a PO, auth required
"""

import socket
import time

import pyodbc
from fastapi import Depends, FastAPI, HTTPException

from . import __version__ as VERSION
from . import auth, buyers, channel, db, econnect, errors, models, ops
from .config import get_settings
from .cors import configure_cors
from .logging_setup import configure_logging, get_logger

_START = time.monotonic()


def _check_company(company: str) -> None:
    allowed = get_settings().gp.allowed_companies
    if company not in allowed:
        raise HTTPException(
            status_code=400,
            detail=errors.error_body("company_not_allowed", f"{company} not in allowed_companies {allowed}"),
        )


def _econnect_http(conn, e: econnect.EConnectError) -> HTTPException:
    return HTTPException(status_code=502, detail=errors.econnect_error_body(conn, e))


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
        # /health is a liveness probe the UI window polls every few seconds; logging every hit floods
        # relay.log and the UI's own event-log view. Skip it - real GP ops and errors are still logged.
        if request.url.path == "/health":
            return response
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
        return {
            "status": "ok",
            "version": VERSION,
            "uptime_seconds": round(time.monotonic() - _START, 1),
            "channel": channel.channel_state_snapshot(),  # the REAL backend-channel state, for the app UI
        }

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

    @app.get("/tax-details", response_model=models.TaxDetailsResponse)
    def tax_details(company: str | None = None, _=Depends(auth.verify_token)):
        """Purchase tax details (TX00201, TXDTLTYP=2) for the register-PO tax-detail dropdown (issue
        #257). GP-first: the options are whatever the company defines, read live, not a hardcoded list."""
        company = company or get_settings().gp.default_company
        _check_company(company)
        try:
            with db.get_read_connection(company) as conn:
                rows = econnect.list_tax_details(conn)
        except pyodbc.Error as e:
            raise HTTPException(status_code=502, detail=errors.error_body("sql_error", str(e)))
        return models.TaxDetailsResponse(company=company, tax_details=[models.TaxDetailOut(**r) for r in rows])

    @app.get("/cost-codes", response_model=models.CostCodesResponse)
    def cost_codes(job: str, company: str | None = None, _=Depends(auth.verify_token)):
        """Active, account-usable cost codes for one job (JC00701) for the Create PO cost-code
        dropdown. Cost codes are per-job and each carries its own Cost_Element, so the dropdown and
        the /po cost_code must come from here rather than a static list with a hardcoded element.
        Codes whose account index dangles (#425) are excluded - the create_po guard would refuse
        them, so they must not be selectable. `job` is the GP job number (UC Nexus project_id). A
        job with no usable cost codes returns an empty list (the UI shows that)."""
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
        try:
            with db.get_connection(request.company) as conn:
                try:
                    response = ops.create_po_op(conn, company=request.company, request=request)
                    conn.commit()
                    return response
                except ops.RelayOpError as e:
                    conn.rollback()
                    raise HTTPException(
                        status_code=400, detail=errors.error_body(e.code, e.message, **e.context)
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
        """Receive against a PO - see ops.create_receipt_op for the orchestration."""
        _check_company(request.company)
        try:
            with db.get_connection(request.company) as conn:
                try:
                    response = ops.create_receipt_op(conn, company=request.company, request=request)
                    conn.commit()
                    return response
                except ops.RelayOpError as e:
                    conn.rollback()
                    status_code = 404 if e.code == "po_not_found" else 400
                    raise HTTPException(
                        status_code=status_code, detail=errors.error_body(e.code, e.message, **e.context)
                    )
                except econnect.EConnectError as e:
                    conn.rollback()
                    raise _econnect_http(conn, e)
                except Exception:
                    conn.rollback()
                    raise
        except pyodbc.Error as e:
            raise HTTPException(status_code=502, detail=errors.error_body("sql_error", str(e)))

    return app


app = create_app()
