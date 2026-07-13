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
    def __init__(self, message: str = "no relay is currently connected"):
        super().__init__(message, "RELAY_UNAVAILABLE")


class RelayTimeoutError(AppError):
    def __init__(self, message: str = "relay did not reply in time"):
        super().__init__(message, "RELAY_TIMEOUT")


class RelayCallError(AppError):
    """The relay answered a job with ok=false - an eConnect or validation failure on its side.
    `detail` carries the relay's own error body ({error, message, context})."""

    def __init__(self, message: str, detail: dict | None = None):
        super().__init__(message, "RELAY_CALL_FAILED")
        self.detail = detail or {}
