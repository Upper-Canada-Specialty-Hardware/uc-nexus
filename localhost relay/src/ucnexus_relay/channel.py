"""Outbound WebSocket channel to the UC Nexus backend's relay-link endpoint.

The relay is the WS CLIENT here: it dials wss://<backend>/relay-link, authenticates with its
enrolled Bearer secret on the handshake, and services job frames the backend pushes down the
socket. There is no inbound HTTP surface for GP work anymore (see main.py, which now serves only
/health) - every GP read/write goes through an op dispatched off this channel.

Wire protocol (pinned to match the backend relay-gateway issue exactly):
  job in    <- {id, op, company, payload}
  reply out -> {id, ok: true, result} or {id, ok: false, error}

`op` maps to an eConnect proc wrapper in econnect.py for writes (create_po, create_receipt) or a
read-only SELECT for the list_* ops. Writes still go through eConnect procs only - never direct SQL
against GP tables.

Reconnection: `websockets.connect(...)` used as `async for ws in connect(...)` reconnects
automatically - immediately if an established connection drops, with exponential backoff if the
connection attempt itself keeps failing (see websockets.asyncio.client.backoff). In-flight job ids
are simply abandoned on a drop; the backend re-issues them to the next connection, so there is
nothing to persist across reconnects here. Keepalive pings are the WS-protocol pings `connect`
already sends every `ping_interval` seconds - no application-level ping frame is needed.
"""

import asyncio
import json
import socket
from collections.abc import Callable
from datetime import date

import pyodbc
import websockets
from pydantic import ValidationError

from . import buyers, db, econnect, errors, models
from .config import get_settings
from .logging_setup import get_logger

_KEEPALIVE_SECONDS = 20


class OpError(Exception):
    """A clean, client-facing failure for one job - reported back as {ok: false, error}, never
    raised past dispatch_job. Mirrors the shape errors.error_body used to give HTTPException."""

    def __init__(self, error: str, message: str, **context):
        super().__init__(message)
        self.error = error
        self.message = message
        self.context = context


def _check_company(company: str) -> None:
    allowed = get_settings().gp.allowed_companies
    if company not in allowed:
        raise OpError("company_not_allowed", f"{company} not in allowed_companies {allowed}")


def _econnect_op_error(conn, e: econnect.EConnectError) -> OpError:
    desc = errors.lookup_error_description(conn, e.error_state) if e.error_state else None
    return OpError(
        "econnect_error", desc or str(e), proc=e.proc, error_state=e.error_state, error_description=desc
    )


def _resolve_buyer(conn, requested: str | None) -> str:
    """See buyers.resolve_buyer: requested (from the create_po payload, picked from list_buyers)
    wins outright; otherwise fall back to [gp.buyers] (by_host -> by_login -> default)."""
    if requested:
        return requested
    bcfg = get_settings().gp.buyers
    login = None
    if bcfg.by_login:
        login = conn.cursor().execute("SELECT SUSER_NAME()").fetchone()[0]
    buyer_id = buyers.resolve_buyer(bcfg, socket.gethostname(), login)
    if not buyer_id:
        raise OpError(
            "buyer_unresolved",
            "no buyer_id sent and none resolved from [gp.buyers]; pick a buyer from list_buyers",
        )
    return buyer_id


# --- ops: each is (company, payload) -> JSON-safe result dict ----------------------------------


def _op_list_vendors(company: str, payload: dict) -> dict:
    with db.get_read_connection(company) as conn:
        rows = econnect.list_vendors(conn, active_only=True)
    return models.VendorsResponse(
        company=company, vendors=[models.VendorOut(**r) for r in rows]
    ).model_dump(mode="json")


def _op_list_buyers(company: str, payload: dict) -> dict:
    with db.get_read_connection(company) as conn:
        ids = econnect.list_buyers(conn)
    return models.BuyersResponse(company=company, buyers=ids).model_dump(mode="json")


def _op_list_cost_codes(company: str, payload: dict) -> dict:
    job = (payload.get("job") or "").strip()
    if not job:
        raise OpError("missing_job", "job is required")
    with db.get_read_connection(company) as conn:
        rows = econnect.list_cost_codes(conn, job)
    return models.CostCodesResponse(
        company=company, job=job, cost_codes=[models.CostCodeOut(**r) for r in rows]
    ).model_dump(mode="json")


def _op_list_jobs(company: str, payload: dict) -> dict:
    with db.get_read_connection(company) as conn:
        rows = econnect.list_jobs(conn)
    return models.JobsResponse(company=company, jobs=[models.JobOut(**r) for r in rows]).model_dump(mode="json")


def _op_create_po(company: str, payload: dict) -> dict:
    request = models.CreatePoRequest(**{**payload, "company": company})
    h = request.header
    with db.get_connection(company) as conn:
        try:
            # 0. buyer: validate against GP's buyer master; eConnect taPoHdr rejects an
            #    unregistered BUYERID (error 269), so pre-check for a clean 400-equivalent instead.
            buyer_id = _resolve_buyer(conn, h.buyer_id)
            registered = econnect.list_buyers(conn)
            if buyer_id not in registered:
                raise OpError(
                    "buyer_not_registered",
                    f"buyer '{buyer_id}' is not a registered GP buyer for {company} (registered: {registered})",
                )

            # 0b. job + cost code: pre-check every job-cost (PI=2) line against JC00102/JC00701 so a
            #     bad job or cost code fails clean instead of mid-orchestration.
            job_ok: dict[str, bool] = {}
            for line in request.lines:
                if line.product_indicator != 2:
                    continue
                job = line.job_number
                if job not in job_ok:
                    job_ok[job] = econnect.job_exists(conn, job)
                if not job_ok[job]:
                    raise OpError(
                        "job_not_registered", f"job '{job}' is not a registered GP job (JC00102) for {company}"
                    )
                if not econnect.cost_code_on_job(conn, job, line.cost_code):
                    raise OpError(
                        "cost_code_not_on_job",
                        f"cost code '{line.cost_code}' is not set up on job '{job}' (JC00701) for {company}",
                    )

            # 1. PO number: client-supplied (checked free across active/history/receipts) or reserved
            if request.po_number:
                po_number = request.po_number
                in_use = econnect.po_number_in_use(conn, po_number)
                if in_use:
                    raise OpError("po_number_taken", f"PO number '{po_number}' is already in use in GP as {in_use}")
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

            # 4. WennSoft integration for EVERY line - sets Product_Indicator (taPoLine can't)
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
                company=company,
                lines_created=len(request.lines),
                subtotal=subtotal,
                doc_date=h.doc_date,
                vendor_id=h.vendor_id,
            ).model_dump(mode="json")
        except econnect.EConnectError as e:
            conn.rollback()
            raise _econnect_op_error(conn, e) from e
        except Exception:
            conn.rollback()
            raise


def _op_create_receipt(company: str, payload: dict) -> dict:
    """Receive against a PO. Reads the PO's lines from POP10110, then in ONE transaction:
    taGetPurchReceiptNextNumber -> taPopRcptLineInsert x N -> taPopRcptHdrInsert, and (for
    companies with a paired custom DB) inserts the matching WHRECLINE101 rows."""
    request = models.ReceiptRequest(**{**payload, "company": company})
    rdate = request.receipt_date or date.today()
    batch = f"{request.batch_prefix}-{rdate:%Y/%m/%d}"
    custom_db = get_settings().gp.custom_db.get(company)  # None for sandboxes / unmapped companies
    with db.get_connection(company) as conn:
        try:
            vendor_id, vendor_name, po_lines = econnect.read_po_receipt_context(conn, request.po_number)
            if vendor_id is None:
                raise OpError("po_not_found", f"PO {request.po_number} not found in {company}")
            for rl in request.lines:
                if rl.po_line_ord not in po_lines:
                    raise OpError("po_line_not_found", f"PO {request.po_number} has no line ORD {rl.po_line_ord}")
                pl = po_lines[rl.po_line_ord]
                if pl["polnesta"] >= 4:
                    raise OpError(
                        "line_not_receivable",
                        f"line ORD {rl.po_line_ord} is closed/cancelled (POLNESTA={pl['polnesta']})",
                    )
                # validate against REMAINING (ordered - already received), so cumulative over-receipt
                # across multiple receives is blocked.
                remaining = pl["qtyorder"] - pl["prev_received"]
                if rl.quantity > remaining:
                    raise OpError(
                        "qty_exceeds_remaining",
                        f"line ORD {rl.po_line_ord}: qty {rl.quantity} exceeds remaining {remaining} "
                        f"(ordered {pl['qtyorder']}, already received {pl['prev_received']})",
                    )

            receipt_number = econnect.get_next_receipt_number(conn)
            # eConnect processes receipt LINES before the header (the line proc creates the receipt
            # document; calling the header insert first makes the line a duplicate).
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

            # custom warehouse store (WHRECLINE101) - SAME transaction as the GP receipt
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
                company=company,
                lines_received=len(request.lines),
                custom_db_written=bool(custom_db),
            ).model_dump(mode="json")
        except econnect.EConnectError as e:
            conn.rollback()
            raise _econnect_op_error(conn, e) from e
        except Exception:
            conn.rollback()
            raise


_OPS: dict[str, Callable[[str, dict], dict]] = {
    "list_vendors": _op_list_vendors,
    "list_buyers": _op_list_buyers,
    "list_cost_codes": _op_list_cost_codes,
    "list_jobs": _op_list_jobs,
    "create_po": _op_create_po,
    "create_receipt": _op_create_receipt,
}


async def dispatch_job(frame: dict) -> dict:
    """{id, op, company, payload} -> {id, ok: true, result} or {id, ok: false, error}. Never
    raises - every failure mode (unknown op, bad payload, company gate, eConnect error, SQL error,
    anything else) is caught here and turned into the uniform error envelope. The blocking pyodbc
    call runs off the event loop thread so one slow GP call doesn't stall keepalive pings or other
    concurrently in-flight jobs."""
    job_id = frame.get("id")
    op = frame.get("op")
    company = frame.get("company")
    payload = frame.get("payload") or {}
    try:
        handler = _OPS.get(op)
        if handler is None:
            raise OpError("unknown_op", f"unknown op {op!r}")
        if not company:
            raise OpError("missing_company", "company is required")
        _check_company(company)
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(None, handler, company, payload)
        return {"id": job_id, "ok": True, "result": result}
    except OpError as e:
        return {"id": job_id, "ok": False, "error": errors.error_body(e.error, e.message, **e.context)}
    except ValidationError as e:
        return {"id": job_id, "ok": False, "error": errors.error_body("invalid_payload", str(e))}
    except pyodbc.Error as e:
        return {"id": job_id, "ok": False, "error": errors.error_body("sql_error", str(e))}
    except Exception as e:  # last-resort guard: one bad job must never kill the channel
        get_logger().exception("relay op failed", extra={"op": op, "job_id": job_id})
        return {"id": job_id, "ok": False, "error": errors.error_body("internal_error", str(e))}


async def _serve(ws) -> None:
    """Service jobs on one open connection until it closes. Each frame is dispatched as its own
    task so a slow job never blocks reading (or replying to) the next one."""
    logger = get_logger()

    async def _handle(raw: str) -> None:
        try:
            frame = json.loads(raw)
        except json.JSONDecodeError:
            logger.warning("relay channel received malformed frame", extra={"raw": raw[:200]})
            return
        reply = await dispatch_job(frame)
        try:
            await ws.send(json.dumps(reply, default=str))
        except websockets.exceptions.ConnectionClosed:
            logger.warning("relay channel closed before reply could be sent", extra={"job_id": reply.get("id")})

    async for raw in ws:
        asyncio.ensure_future(_handle(raw))


async def run_channel() -> None:
    """Dial the backend relay-link socket and service jobs until cancelled. `websockets.connect`
    used as an async iterator reconnects automatically: immediately after an established connection
    drops, with exponential backoff if the connect attempt itself keeps failing. In-flight job ids
    are simply abandoned on a drop - the wire protocol has the backend re-issue them."""
    logger = get_logger()
    settings = get_settings()
    url = settings.backend.url
    headers = {"Authorization": f"Bearer {settings.auth.shared_secret}"}
    async for ws in websockets.connect(url, additional_headers=headers, ping_interval=_KEEPALIVE_SECONDS):
        logger.info("relay channel connected", extra={"url": url})
        try:
            await _serve(ws)
            logger.info("relay channel closed cleanly, reconnecting")
        except websockets.exceptions.ConnectionClosed as exc:
            logger.warning("relay channel dropped, reconnecting", extra={"error": str(exc)})
