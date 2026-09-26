import os
import re
from typing import Any
from urllib.parse import urlsplit

import httpx


DEFAULT_BACKEND_URL = "http://127.0.0.1:8000"
HEALTH_TIMEOUT_SECONDS = 5.0
PROCESS_TIMEOUT_SECONDS = 300.0
DOWNLOAD_TIMEOUT_SECONDS = 120.0
_RESOURCE_ID_PATTERN = re.compile(r"^[0-9a-f]{32}$")


class BackendApiError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        code: str | None = None,
        stage: str | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.stage = stage


class BackendConnectionError(BackendApiError):
    pass


class BackendTimeoutError(BackendApiError):
    pass


class VideoEditorApiClient:
    """Small HTTP-only boundary between Streamlit and the FastAPI backend."""

    def __init__(
        self,
        *,
        backend_url: str | None = None,
        http_client: httpx.Client | None = None,
    ) -> None:
        configured_url = backend_url or os.getenv("BACKEND_URL", DEFAULT_BACKEND_URL)
        self.backend_url = configured_url.rstrip("/")
        if not self.backend_url:
            raise ValueError("BACKEND_URL must not be empty.")
        self._http_client = http_client or httpx.Client()

    def health_check(self) -> bool:
        try:
            response = self._http_client.get(
                f"{self.backend_url}/health",
                timeout=HEALTH_TIMEOUT_SECONDS,
            )
            return response.status_code == 200 and response.json().get("status") == "ok"
        except (httpx.RequestError, ValueError, AttributeError):
            return False

    def process_video(
        self,
        *,
        file_name: str,
        file_bytes: bytes,
        content_type: str,
        window_seconds: float,
    ) -> dict[str, Any]:
        try:
            response = self._http_client.post(
                f"{self.backend_url}/videos/process",
                files={"file": (file_name, file_bytes, content_type)},
                data={"window_seconds": str(float(window_seconds))},
                timeout=PROCESS_TIMEOUT_SECONDS,
            )
        except httpx.TimeoutException as error:
            raise BackendTimeoutError("영상 처리 요청 시간이 초과되었습니다.") from error
        except httpx.RequestError as error:
            raise BackendConnectionError("백엔드 서버에 연결할 수 없습니다.") from error

        self._raise_for_error(response)
        try:
            payload = response.json()
        except ValueError as error:
            raise BackendApiError("백엔드 응답을 읽을 수 없습니다.") from error
        if not isinstance(payload, dict):
            raise BackendApiError("백엔드 응답 형식이 올바르지 않습니다.")
        return _safe_process_payload(payload)

    def download_clip(self, download_url: str) -> bytes:
        path = _validate_download_url(download_url)
        try:
            response = self._http_client.get(
                f"{self.backend_url}{path}",
                timeout=DOWNLOAD_TIMEOUT_SECONDS,
            )
        except httpx.TimeoutException as error:
            raise BackendTimeoutError("클립 다운로드 시간이 초과되었습니다.") from error
        except httpx.RequestError as error:
            raise BackendConnectionError("백엔드 서버에 연결할 수 없습니다.") from error
        self._raise_for_error(response)
        return response.content

    @staticmethod
    def _raise_for_error(response: httpx.Response) -> None:
        if response.status_code < 400:
            return
        defaults = {
            415: "지원하지 않는 영상 형식입니다.",
            422: "입력값이 올바르지 않거나 처리할 수 없는 영상입니다.",
        }
        message = defaults.get(response.status_code, "영상 처리 중 오류가 발생했습니다.")
        code = None
        stage = None
        try:
            detail = response.json().get("detail")
            if isinstance(detail, dict):
                code = detail.get("code")
                stage = detail.get("stage")
                safe_message = detail.get("message")
                if isinstance(safe_message, str) and safe_message:
                    message = safe_message
        except (ValueError, AttributeError):
            pass
        raise BackendApiError(
            message,
            status_code=response.status_code,
            code=code,
            stage=stage,
        )


def _validate_download_url(download_url: str) -> str:
    if not isinstance(download_url, str):
        raise BackendApiError("클립 다운로드 주소가 올바르지 않습니다.")
    parsed = urlsplit(download_url)
    parts = parsed.path.split("/")
    if (
        parsed.scheme
        or parsed.netloc
        or parsed.query
        or parsed.fragment
        or len(parts) != 5
        or parts[1:3] != ["videos", "clips"]
        or _RESOURCE_ID_PATTERN.fullmatch(parts[3]) is None
        or _RESOURCE_ID_PATTERN.fullmatch(parts[4]) is None
    ):
        raise BackendApiError("클립 다운로드 주소가 올바르지 않습니다.")
    return parsed.path


def _pick(source: Any, fields: tuple[str, ...]) -> dict[str, Any]:
    if not isinstance(source, dict):
        return {}
    return {field: source.get(field) for field in fields}


def _safe_process_payload(payload: dict[str, Any]) -> dict[str, Any]:
    transcript = _pick(payload.get("transcript"), ("text", "language", "language_probability"))
    raw_transcript = payload.get("transcript")
    transcript["segments"] = [
        _pick(segment, ("start_seconds", "end_seconds", "text"))
        for segment in (
            raw_transcript.get("segments", []) if isinstance(raw_transcript, dict) else []
        )
    ]

    memos: list[dict[str, Any]] = []
    for item in payload.get("memos", []) if isinstance(payload.get("memos"), list) else []:
        if not isinstance(item, dict):
            continue
        selection = _pick(
            item.get("selection"),
            ("strategy_name", "selected_source_id", "reasoning_code", "reasoning_summary"),
        )
        raw_selection = item.get("selection")
        selection["candidate"] = _pick(
            raw_selection.get("candidate"),
            ("window_seconds", "start_seconds", "end_seconds"),
        ) or None if isinstance(raw_selection, dict) else None
        rendered = _pick(
            item.get("rendered_clip"),
            (
                "clip_id",
                "filename",
                "download_url",
                "start_seconds",
                "end_seconds",
                "duration_seconds",
                "video_codec",
                "audio_codec",
            ),
        )
        memos.append(
            {
                "memo": _pick(
                    item.get("memo"),
                    (
                        "start_seconds",
                        "end_seconds",
                        "transcript_text",
                        "matched_trigger",
                        "matched_reference",
                        "matched_action",
                    ),
                ),
                "generated_candidates": [
                    _pick(candidate, ("window_seconds", "start_seconds", "end_seconds"))
                    for candidate in item.get("generated_candidates", [])
                ],
                "selection": selection,
                "rendered_clip": rendered or None,
            }
        )

    return {
        "video_id": payload.get("video_id"),
        "stored_filename": payload.get("stored_filename"),
        "status": payload.get("status"),
        "media": _pick(
            payload.get("media"),
            (
                "duration_seconds",
                "has_video_stream",
                "has_audio_stream",
                "video_codec",
                "audio_codec",
                "format_name",
            ),
        ),
        "transcript": transcript,
        "memos": memos,
        "timings": [
            _pick(timing, ("stage", "duration_seconds"))
            for timing in payload.get("timings", [])
        ],
        "warnings": [
            warning for warning in payload.get("warnings", []) if isinstance(warning, str)
        ],
    }
