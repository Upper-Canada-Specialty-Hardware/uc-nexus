"""Windows DPAPI protection for the relay's shared secret at rest.

The [auth] shared_secret in config.toml is DPAPI-encrypted (CurrentUser scope) so it is never
stored in plaintext. An encrypted value carries the prefix `enc:dpapi:` followed by base64 of the
DPAPI blob; a plaintext value (dev convenience) is recognised by the absence of that prefix and used
as-is. CurrentUser scope binds the ciphertext to the Windows user the relay runs as - the same
logged-in domain user that authenticates to GP via SSPI - so only that account on that machine can
decrypt it.

Encryption happens at enroll time (or via `protect_secret`), decryption on every config read. We call
crypt32 directly through ctypes to avoid adding a pywin32 dependency.
"""

import base64
import ctypes
import sys

ENC_PREFIX = "enc:dpapi:"

# CryptProtectData / CryptUnprotectData flags. UI_FORBIDDEN guarantees no interactive prompt (the relay
# runs unattended under a scheduled task). We deliberately do NOT pass CRYPTPROTECT_LOCAL_MACHINE, so the
# default CurrentUser scope applies.
_CRYPTPROTECT_UI_FORBIDDEN = 0x1

# ctypes.wintypes cannot even be IMPORTED off Windows, and the blob struct is built out of it - so the
# whole crypt32 binding lives behind the platform check rather than just the calls that use it. That is
# what lets this module import off Windows at all, where a plaintext secret still loads and nothing is
# ever decrypted (protect/unprotect below refuse a real blob there).
if sys.platform == "win32":
    from ctypes import wintypes

    class _DataBlob(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

    _crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    for _fn in (_crypt32.CryptProtectData, _crypt32.CryptUnprotectData):
        _fn.restype = wintypes.BOOL
        _fn.argtypes = [
            ctypes.POINTER(_DataBlob),  # pDataIn
            wintypes.LPCWSTR,           # szDataDescr
            ctypes.POINTER(_DataBlob),  # pOptionalEntropy
            ctypes.c_void_p,            # pvReserved
            ctypes.c_void_p,            # pPromptStruct
            wintypes.DWORD,             # dwFlags
            ctypes.POINTER(_DataBlob),  # pDataOut
        ]
    _kernel32.LocalFree.restype = ctypes.c_void_p
    _kernel32.LocalFree.argtypes = [ctypes.c_void_p]


def is_windows() -> bool:
    return sys.platform == "win32"


def is_encrypted(value: str) -> bool:
    """True if the stored value is a DPAPI blob (vs a plaintext dev secret)."""
    return value.startswith(ENC_PREFIX)


def _in_blob(data: bytes) -> "tuple[_DataBlob, ctypes.Array]":
    # The buffer must outlive the call, so hand it back to the caller to keep a reference.
    buf = ctypes.create_string_buffer(data, len(data))
    return _DataBlob(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char))), buf


def protect(plaintext: str) -> str:
    """DPAPI-encrypt (CurrentUser) and return `enc:dpapi:<base64>`."""
    if not is_windows():
        raise RuntimeError("DPAPI encryption is only available on Windows")
    blob_in, _buf = _in_blob(plaintext.encode("utf-8"))
    blob_out = _DataBlob()
    ok = _crypt32.CryptProtectData(
        ctypes.byref(blob_in), "ucnexus-relay shared_secret", None, None, None,
        _CRYPTPROTECT_UI_FORBIDDEN, ctypes.byref(blob_out),
    )
    if not ok:
        raise OSError(ctypes.get_last_error(), "CryptProtectData failed")
    try:
        encrypted = ctypes.string_at(blob_out.pbData, blob_out.cbData)
    finally:
        _kernel32.LocalFree(ctypes.cast(blob_out.pbData, ctypes.c_void_p))
    return ENC_PREFIX + base64.b64encode(encrypted).decode("ascii")


def unprotect(value: str) -> str:
    """Decrypt a stored secret. Plaintext (no prefix) is returned unchanged so dev configs and the
    test suite still work; only a real `enc:dpapi:` blob requires Windows + the owning user."""
    if not is_encrypted(value):
        return value
    if not is_windows():
        raise RuntimeError(
            "config shared_secret is DPAPI-encrypted but this is not Windows - cannot decrypt"
        )
    encrypted = base64.b64decode(value[len(ENC_PREFIX):])
    blob_in, _buf = _in_blob(encrypted)
    blob_out = _DataBlob()
    ok = _crypt32.CryptUnprotectData(
        ctypes.byref(blob_in), None, None, None, None,
        _CRYPTPROTECT_UI_FORBIDDEN, ctypes.byref(blob_out),
    )
    if not ok:
        # Most common cause: the blob was encrypted by a DIFFERENT Windows user (CurrentUser scope) -
        # re-enroll under the account the relay runs as.
        raise OSError(
            ctypes.get_last_error(),
            "CryptUnprotectData failed - secret was likely encrypted by a different Windows user; "
            "re-run enroll (or protect-secret) under the account the relay runs as",
        )
    try:
        decrypted = ctypes.string_at(blob_out.pbData, blob_out.cbData)
    finally:
        _kernel32.LocalFree(ctypes.cast(blob_out.pbData, ctypes.c_void_p))
    return decrypted.decode("utf-8")
