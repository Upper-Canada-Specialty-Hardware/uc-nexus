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
    def __init__(self, message: str, field: str | None = None):
        super().__init__(message, "CONFLICT", field)


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
