"""SHA-256 content integrity for render outputs (QA-03).

Path, symlink and size checks cannot detect a same-size rewrite of a finished
MP4/SRT. Completion records the content digest; every status, preview, download
and Range request recomputes it from the *same open handle* that is then
streamed, so a path swapped after verification is never served.

On Windows the handle is opened with ``FILE_SHARE_READ`` only: while it is open,
no other handle can write, rename or delete the file. POSIX has no mandatory
equivalent, so an in-place rewrite of the same inode during streaming remains a
documented residual risk (see docs/handoff/qa-03-render-integrity-implementation.md).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from hashlib import sha256
import hmac
import os
from pathlib import Path
import stat as stat_module
from typing import BinaryIO


HASH_CHUNK_BYTES = 1024 * 1024
_HEX = frozenset("0123456789abcdef")


class IntegrityStatus(str, Enum):
    VERIFIED = "VERIFIED"
    MISSING = "MISSING"          # absent, not a regular file, or cannot be opened safely
    CORRUPT = "CORRUPT"          # present, but size or SHA-256 differs from the record
    UNVERIFIED = "UNVERIFIED"    # present with the recorded size, but no digest was recorded


class OutputIntegrityError(RuntimeError):
    """The file changed or could not be read consistently while hashing."""


FileIdentity = tuple[int, int, int, int]


def is_sha256_hex(value: object) -> bool:
    return isinstance(value, str) and len(value) == 64 and set(value) <= _HEX


def _identity(result: os.stat_result) -> FileIdentity:
    return (result.st_dev, result.st_ino, result.st_size, result.st_mtime_ns)


if os.name == "nt":  # pragma: no cover - exercised on the Windows deployment host
    import ctypes
    from ctypes import wintypes
    import msvcrt

    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _CreateFileW = _kernel32.CreateFileW
    _CreateFileW.argtypes = (wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID,
                             wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE)
    _CreateFileW.restype = wintypes.HANDLE
    _CloseHandle = _kernel32.CloseHandle
    _CloseHandle.argtypes = (wintypes.HANDLE,)
    _GENERIC_READ = 0x80000000
    _FILE_SHARE_READ = 0x00000001
    _OPEN_EXISTING = 3
    _FILE_ATTRIBUTE_NORMAL = 0x80
    _INVALID_HANDLE = wintypes.HANDLE(-1).value

    def _open_read_fd(path: Path) -> int:
        handle = _CreateFileW(str(path), _GENERIC_READ, _FILE_SHARE_READ, None,
                              _OPEN_EXISTING, _FILE_ATTRIBUTE_NORMAL, None)
        if handle is None or handle == _INVALID_HANDLE:
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            return msvcrt.open_osfhandle(handle, os.O_RDONLY | os.O_BINARY)
        except Exception:
            _CloseHandle(handle)
            raise
else:
    def _open_read_fd(path: Path) -> int:
        return os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0))


def open_regular_file(path: Path) -> BinaryIO:
    """Open for reading without following a final symlink (POSIX) and deny writers (Windows)."""
    fd = _open_read_fd(Path(path))
    try:
        if not stat_module.S_ISREG(os.fstat(fd).st_mode):
            raise OSError("Render output is not a regular file.")
        return os.fdopen(fd, "rb", buffering=0)
    except Exception:
        os.close(fd)
        raise


def hash_open_file(handle: BinaryIO) -> tuple[str, os.stat_result]:
    """Stream the whole handle; reject a file whose identity/size changed while reading."""
    before = os.fstat(handle.fileno())
    handle.seek(0)
    digest, total = sha256(), 0
    while chunk := handle.read(HASH_CHUNK_BYTES):
        digest.update(chunk)
        total += len(chunk)
    after = os.fstat(handle.fileno())
    if _identity(before) != _identity(after) or total != after.st_size:
        raise OutputIntegrityError("Render output changed while it was hashed.")
    handle.seek(0)
    return digest.hexdigest(), after


def record_output_digest(path: Path, expected_size: int) -> tuple[str, FileIdentity]:
    """Completion-time digest. Raises unless the hashed handle is still the file at ``path``."""
    with open_regular_file(path) as handle:
        digest, result = hash_open_file(handle)
        if result.st_size != expected_size or expected_size <= 0:
            raise OutputIntegrityError("Render output size changed before hashing.")
        if _identity(os.stat(path, follow_symlinks=False)) != _identity(result):
            raise OutputIntegrityError("Render output path was replaced while it was hashed.")
        return digest, _identity(result)


def same_file(path: Path, identity: FileIdentity) -> bool:
    """Cheap re-check right before publishing; never a substitute for the digest itself."""
    try:
        return _identity(os.stat(path, follow_symlinks=False)) == identity
    except OSError:
        return False


@dataclass
class VerifiedFile:
    """Result of one verification. ``handle`` is open only for VERIFIED and keep_open=True."""

    status: IntegrityStatus
    handle: BinaryIO | None = None
    stat_result: os.stat_result | None = None
    sha256: str | None = None

    def close(self) -> None:
        if self.handle is not None:
            try:
                self.handle.close()
            finally:
                self.handle = None


def verify_file(path: Path | None, expected_size: int | None, expected_sha256: str | None,
                *, keep_open: bool = False) -> VerifiedFile:
    """Check size and SHA-256 on one open handle; NULL digests are never treated as matching.

    The caller must already have validated the reconstructed path (root, project,
    render ID, no symlinked parents). Missing → MISSING; different size or digest
    → CORRUPT; recorded size but no digest → UNVERIFIED (blocked by default).
    """
    if path is None:
        return VerifiedFile(IntegrityStatus.MISSING)
    try:
        if Path(path).is_symlink():
            return VerifiedFile(IntegrityStatus.MISSING)
        handle = open_regular_file(path)
    except OSError:
        return VerifiedFile(IntegrityStatus.MISSING)
    try:
        current = os.fstat(handle.fileno())
        if current.st_size <= 0 or (expected_size is not None and current.st_size != expected_size):
            handle.close()
            return VerifiedFile(IntegrityStatus.CORRUPT, stat_result=current)
        if expected_sha256 is None:
            handle.close()
            return VerifiedFile(IntegrityStatus.UNVERIFIED, stat_result=current)
        if not is_sha256_hex(expected_sha256):
            handle.close()
            return VerifiedFile(IntegrityStatus.CORRUPT, stat_result=current)
        actual, current = hash_open_file(handle)
        if not hmac.compare_digest(actual, expected_sha256):
            handle.close()
            return VerifiedFile(IntegrityStatus.CORRUPT, stat_result=current)
    except (OSError, OutputIntegrityError):
        handle.close()
        return VerifiedFile(IntegrityStatus.CORRUPT)
    if not keep_open:
        handle.close()
        return VerifiedFile(IntegrityStatus.VERIFIED, stat_result=current, sha256=actual)
    return VerifiedFile(IntegrityStatus.VERIFIED, handle=handle, stat_result=current, sha256=actual)
