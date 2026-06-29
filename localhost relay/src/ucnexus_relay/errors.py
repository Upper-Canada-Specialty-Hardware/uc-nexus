"""Relay error helpers: the uniform error-response shape every endpoint raises, plus the eConnect
numeric error-code translation via DYNAMICS.taErrorCode (9,407 entries)."""


def error_body(error: str, message: str, **context) -> dict:
    """The relay's single error-response shape. Every HTTPException the relay raises uses this as its
    `detail`, so a client always sees the same three keys (FastAPI nests them under the top-level
    "detail"):
      - error:   machine-readable code (e.g. 'job_not_registered', 'econnect_error', 'unauthorized')
      - message: human-readable string
      - context: structured extras, {} when none (e.g. an eConnect proc / error_state / description)
    """
    return {"error": error, "message": message, "context": dict(context)}


def lookup_error_description(conn, error_code: int) -> str | None:
    if not error_code:
        return None
    row = conn.cursor().execute(
        "SELECT ErrorDesc FROM DYNAMICS.dbo.taErrorCode WHERE ErrorCode = ?",
        error_code,
    ).fetchone()
    return row.ErrorDesc.strip() if row else None
