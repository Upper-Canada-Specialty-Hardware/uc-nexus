class AppError(Exception):
    def __init__(self, message: str, code: str, field: str | None = None):
        self.message = message
        self.code = code
        self.field = field
        super().__init__(message)


class ValidationError(AppError):
    def __init__(self, message: str, field: str | None = None):
        super().__init__(message, "VALIDATION_ERROR", field)


class NotFoundError(AppError):
    def __init__(self, message: str):
        super().__init__(message, "NOT_FOUND")


class ConflictError(AppError):
    def __init__(self, message: str, field: str | None = None, code: str = "CONFLICT"):
        super().__init__(message, code, field)


class GpSetupInvalidError(ConflictError):
    """This project's GP job is not set up well enough to act on (#425).

    Its JC00701 cost codes point at GL account indexes that do not exist in the company's chart - the
    residue of the pre-2023 UCSH -> UBC job copy, 1504 rows across 62 production jobs. A job-cost PO
    on such a code registers cleanly and then fails FOREVER at receipt with eConnect 4612 "Invalid
    Account Index", so the hardware arrives, gets counted, and cannot be booked in.

    A conflict rather than a validation failure: nothing about the request is wrong. The state of the
    world is, and no amount of re-entering the form fixes it - accounting has to repair GP. The
    distinct code lets the frontend recognise a quarantine and show the banner naming the codes,
    instead of rendering it as one more red toast the user is expected to act on.

    `issues` carries the parsed {cost_code, account_index} pairs so a caller can reformat them; the
    message already names them, because a raw GraphQL error is what most callers will show."""

    def __init__(self, message: str, issues: list[dict] | None = None):
        super().__init__(message, code="GP_SETUP_INVALID")
        self.issues = issues or []


class InsufficientInventoryError(AppError):
    def __init__(self, message: str):
        super().__init__(message, "INSUFFICIENT_INVENTORY")


class InventoryShortfallError(AppError):
    """A hard inventory-sufficiency gate (#224) refused an operation because available units can't
    cover the request. Carries the per-combo shortfall so the resolver can surface it inline to the
    caller and notify the PO for backfill. `project_id` / `request_number` let the resolver mint that
    PO notification in a fresh session after the refused work rolls back."""

    def __init__(self, message: str, shortfalls: list, project_id=None, request_number: str | None = None):
        super().__init__(message, "INSUFFICIENT_INVENTORY")
        self.shortfalls = shortfalls
        self.project_id = project_id
        self.request_number = request_number


class InvalidStateTransitionError(AppError):
    def __init__(self, message: str):
        super().__init__(message, "INVALID_STATE_TRANSITION")


class LockedError(AppError):
    def __init__(self, message: str):
        super().__init__(message, "LOCKED")


class RelayUnavailableError(AppError):
    """No usable relay connection for this call.

    `dispatched` is the single most important bit in the GP write path (#353 PR E). It is False when
    the job never left the backend - no socket, wrong company, send failure - which means GP cannot
    possibly have run it, so the write is safe to queue and retry. It is True when the job WAS on the
    wire and the socket then died (`RelayGateway._fail_all`): GP may have committed and the reply was
    simply lost, so a blind retry could post a second receipt or reserve a second PO number. A
    dispatched failure must surface to the user exactly as it does today and must never be enqueued."""

    def __init__(self, message: str = "no relay is currently connected", dispatched: bool = False):
        super().__init__(message, "RELAY_UNAVAILABLE")
        self.dispatched = dispatched


class RelayTimeoutError(AppError):
    def __init__(self, message: str = "relay did not reply in time"):
        super().__init__(message, "RELAY_TIMEOUT")


class RelayCallError(AppError):
    """The relay answered a job with ok=false - an eConnect or validation failure on its side.
    `detail` carries the relay's own error body ({error, message, context})."""

    def __init__(self, message: str, detail: dict | None = None):
        super().__init__(message, "RELAY_CALL_FAILED")
        self.detail = detail or {}


class RelayBusyError(RelayCallError):
    """The relay refused a BACKGROUND op before running it because GP's SQL server is above the
    relay's CPU ceiling (adaptive pacing).

    Not a failure of the request and not something a user can fix by retrying now: the server is busy
    with somebody else's work, and the whole point of the refusal is that Nexus must not add to it. It
    is deliberately a distinct type rather than one more RelayCallError, because the caller's correct
    response is different in kind - stop issuing background reads and probe until the server recovers,
    rather than log the failure and carry on to the next company.

    `retry_after_seconds` is the relay's own advice on when to look again; the pause state machine uses
    it as the first probe delay instead of its configured interval. All three fields are optional
    because they come off the wire, and a relay that omits one must not break the pause."""

    def __init__(
        self,
        message: str,
        detail: dict | None = None,
        *,
        sql_cpu_pct: float | None = None,
        ceiling_pct: float | None = None,
        retry_after_seconds: float | None = None,
    ):
        super().__init__(message, detail)
        # Its own code, not RELAY_CALL_FAILED: "the server is busy, this will succeed later" and "the
        # call was rejected" are different answers, and only one of them is worth showing a user.
        self.code = "RELAY_BUSY"
        self.sql_cpu_pct = sql_cpu_pct
        self.ceiling_pct = ceiling_pct
        self.retry_after_seconds = retry_after_seconds


class RelayOpUnsupportedError(AppError):
    """The connected relay build doesn't support the requested op (issue #315). Raised either
    proactively (the relay advertised its op-set on connect and this op isn't in it) or reactively
    (the relay answered `unknown_op`). Distinct from RelayCallError so the frontend can show an
    'update the relay' banner and auto-fall back (e.g. manual tax-detail entry) instead of the raw
    `unknown op '...'` string. `detail` still carries the relay's own error body when there is one."""

    def __init__(self, op: str, detail: dict | None = None):
        message = (
            f"The connected GP relay is out of date and does not support '{op}'. Update the relay "
            f"(Relay app -> Updates -> Update) to the latest build, then retry."
        )
        super().__init__(message, "RELAY_OP_UNSUPPORTED")
        self.op = op
        self.detail = detail or {}


def validation_error_from_relay(e: RelayCallError) -> ValidationError:
    """Turn a relay refusal into a ValidationError that still carries the relay's error body.

    main.py's ResolverGuardExtension publishes `extensions.relayError` from whatever `.detail` the
    raised error has, and ValidationError has no such field - so converting the error plainly would
    strip the GP proc, the error state and the taErrorCode description on the way to the browser, and
    the dialog's GpErrorAlert would render an empty detail table. That table is the whole point of
    #187: error screenshots are how these get reported.

    Lives here rather than in one schema module because every GP write that surfaces a refusal to a
    dialog needs exactly this conversion (createGpJob #380, createGpBuyer #409)."""
    error = ValidationError(str(e.message))
    error.detail = e.detail
    return error
