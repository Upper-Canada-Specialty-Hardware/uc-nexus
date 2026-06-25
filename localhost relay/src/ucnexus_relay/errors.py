"""eConnect numeric error-code translation via DYNAMICS.taErrorCode (9,407 entries)."""


def lookup_error_description(conn, error_code: int) -> str | None:
    if not error_code:
        return None
    row = conn.cursor().execute(
        "SELECT ErrorDesc FROM DYNAMICS.dbo.taErrorCode WHERE ErrorCode = ?",
        error_code,
    ).fetchone()
    return row.ErrorDesc.strip() if row else None
