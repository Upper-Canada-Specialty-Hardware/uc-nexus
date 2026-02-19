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


class InvalidStateTransitionError(AppError):
    def __init__(self, message: str):
        super().__init__(message, "INVALID_STATE_TRANSITION")


class LockedError(AppError):
    def __init__(self, message: str):
        super().__init__(message, "LOCKED")
