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


def econnect_error_body(conn, e) -> dict:
    """error_body() for an econnect.EConnectError, with the numeric error_state resolved to its
    taErrorCode description where possible. Shared by both transports: the HTTP routes wrap this in
    an HTTPException(502, ...), the WS channel sends it as-is in an {ok: false, error: ...} reply.

    A proc that carries its own error text (EConnectError.proc_message, set by the WennSoft job proc -
    see the class docstring) wins over the taErrorCode description: its states are not taErrorCode
    entries, so the lookup would replace the real reason with an unrelated GP description. The
    description is still reported in context either way."""
    desc = lookup_error_description(conn, e.error_state) if e.error_state else None
    return error_body(
        "econnect_error",
        getattr(e, "proc_message", None) or desc or str(e),
        proc=e.proc,
        error_state=e.error_state,
        error_description=desc,
    )
