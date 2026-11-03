"""Serve a render output from the exact handle whose SHA-256 was just verified.

Starlette's FileResponse reopens ``path`` when it streams, which leaves a window
in which a replaced file could be served. This subclass keeps the Range parsing,
416/multipart behaviour and headers of Starlette 1.6 (pinned in
requirements.txt) but reads only from the verified handle, never uses
``http.response.pathsend`` and closes the handle afterwards.

Full (non-Range) bodies are hashed again while streaming and the final chunk is
held back until the digest matches, so a body that changed mid-stream is
truncated instead of completed. Range bodies cannot be verified piecewise; they
re-check the handle's identity (device, inode, size, mtime) before the last
chunk. The Windows share mode in render_integrity already denies writers.
"""

from __future__ import annotations

from hashlib import sha256
import hmac
import os
from secrets import token_hex

import anyio
from starlette.datastructures import MutableHeaders
from starlette.responses import FileResponse
from starlette.types import Receive, Scope, Send

from backend.app.services.render_integrity import IntegrityStatus, OutputIntegrityError, VerifiedFile


def _identity(result: os.stat_result) -> tuple[int, int, int, int]:
    return (result.st_dev, result.st_ino, result.st_size, result.st_mtime_ns)


class VerifiedFileResponse(FileResponse):
    chunk_size = 256 * 1024

    def __init__(self, verified: VerifiedFile, *, media_type: str, filename: str,
                 content_disposition_type: str) -> None:
        if (verified.status is not IntegrityStatus.VERIFIED or verified.handle is None
                or verified.stat_result is None or verified.sha256 is None):
            raise ValueError("Only an open, verified render file can be served.")
        self._verified = verified
        super().__init__(
            path=filename, media_type=media_type, filename=filename,
            stat_result=verified.stat_result, content_disposition_type=content_disposition_type,
            # Strong validator bound to content, not mtime/size, so If-Range cannot
            # splice bytes from a different file version.
            headers={"etag": f'"sha256-{verified.sha256}"'},
        )

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        try:
            await super().__call__(scope, receive, send)
        finally:
            await anyio.to_thread.run_sync(self._verified.close)

    async def _read(self, offset: int, length: int) -> bytes:
        handle = self._verified.handle

        def read() -> bytes:
            handle.seek(offset)
            return handle.read(length)

        return await anyio.to_thread.run_sync(read)

    async def _assert_unchanged(self) -> None:
        current = await anyio.to_thread.run_sync(os.fstat, self._verified.handle.fileno())
        if _identity(current) != _identity(self._verified.stat_result):
            raise OutputIntegrityError("Render output changed while it was served.")

    async def _handle_simple(self, send: Send, send_header_only: bool, send_pathsend: bool) -> None:
        await send({"type": "http.response.start", "status": self.status_code, "headers": self.raw_headers})
        if send_header_only:
            await send({"type": "http.response.body", "body": b"", "more_body": False})
            return
        size, offset, digest, held = self._verified.stat_result.st_size, 0, sha256(), None
        while offset < size:
            chunk = await self._read(offset, min(self.chunk_size, size - offset))
            if not chunk:
                raise OutputIntegrityError("Render output ended early while it was served.")
            offset += len(chunk)
            digest.update(chunk)
            if held is not None:
                await send({"type": "http.response.body", "body": held, "more_body": True})
            held = chunk
        if not hmac.compare_digest(digest.hexdigest(), self._verified.sha256):
            # Abort: the client sees a truncated body, never a completed wrong file.
            raise OutputIntegrityError("Render output changed while it was served.")
        await send({"type": "http.response.body", "body": held or b"", "more_body": False})

    async def _send_range(self, send: Send, start: int, end: int, *, last: bool) -> None:
        while start < end:
            chunk = await self._read(start, min(self.chunk_size, end - start))
            if not chunk:
                raise OutputIntegrityError("Render output ended early while it was served.")
            start += len(chunk)
            if last and start >= end:
                await self._assert_unchanged()
            await send({"type": "http.response.body", "body": chunk, "more_body": not (last and start >= end)})

    async def _handle_single_range(self, send: Send, start: int, end: int, file_size: int,
                                   send_header_only: bool) -> None:
        headers = MutableHeaders(raw=list(self.raw_headers))
        headers["content-range"] = f"bytes {start}-{end - 1}/{file_size}"
        headers["content-length"] = str(end - start)
        await send({"type": "http.response.start", "status": 206, "headers": headers.raw})
        if send_header_only:
            await send({"type": "http.response.body", "body": b"", "more_body": False})
            return
        await self._send_range(send, start, end, last=True)

    async def _handle_multiple_ranges(self, send: Send, ranges: list[tuple[int, int]], file_size: int,
                                      send_header_only: bool) -> None:
        boundary = token_hex(13)
        content_length, header_generator = self.generate_multipart(
            ranges, boundary, file_size, self.headers["content-type"])
        headers = MutableHeaders(raw=list(self.raw_headers))
        headers["content-type"] = f"multipart/byteranges; boundary={boundary}"
        headers["content-length"] = str(content_length)
        await send({"type": "http.response.start", "status": 206, "headers": headers.raw})
        if send_header_only:
            await send({"type": "http.response.body", "body": b"", "more_body": False})
            return
        for start, end in ranges:
            await send({"type": "http.response.body", "body": header_generator(start, end), "more_body": True})
            await self._send_range(send, start, end, last=False)
            await send({"type": "http.response.body", "body": b"\r\n", "more_body": True})
        await self._assert_unchanged()
        await send({"type": "http.response.body", "body": f"--{boundary}--".encode("latin-1"), "more_body": False})
