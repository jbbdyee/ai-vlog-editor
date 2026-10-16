import os
import re
from math import isfinite
from typing import Any
from urllib.parse import urlsplit
from uuid import UUID

import httpx


DEFAULT_BACKEND_URL = "http://127.0.0.1:8000"
HEALTH_TIMEOUT_SECONDS = 5.0
PROCESS_TIMEOUT_SECONDS = 300.0
DOWNLOAD_TIMEOUT_SECONDS = 120.0
PROJECT_READ_TIMEOUT_SECONDS = 15.0
SCENE_RUN_STATUSES = frozenset({"NOT_STARTED", "QUEUED", "RUNNING", "COMPLETED", "COMPLETED_WITH_WARNINGS", "FAILED"})
SCENE_SOURCE_STATUSES = frozenset({"COMPLETED", "ABSTAINED", "FAILED", "BLOCKED", "SKIPPED_V1_INCOMPLETE"})
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

    def get_project_scene_candidates(self, project_id: str) -> dict[str, Any]:
        normalized_id = _project_id(project_id)
        try:
            response = self._http_client.get(
                f"{self.backend_url}/projects/{normalized_id}/scene-candidates",
                timeout=PROJECT_READ_TIMEOUT_SECONDS,
            )
        except httpx.TimeoutException as error:
            raise BackendTimeoutError("장면 후보 조회 시간이 초과되었습니다.") from error
        except httpx.RequestError as error:
            raise BackendConnectionError("백엔드 서버에 연결할 수 없습니다.") from error
        if response.status_code == 404:
            raise BackendApiError("프로젝트를 찾을 수 없습니다.", status_code=404)
        self._raise_for_error(response)
        try:
            payload = response.json()
        except ValueError as error:
            raise BackendApiError("장면 후보 응답을 읽을 수 없습니다.") from error
        return _safe_scene_candidates_payload(payload, normalized_id)

    def start_project_scene_processing(self, project_id: str) -> dict[str, Any]:
        normalized_id = _project_id(project_id)
        try:
            response = self._http_client.post(
                f"{self.backend_url}/projects/{normalized_id}/scene-process",
                timeout=PROJECT_READ_TIMEOUT_SECONDS,
            )
        except httpx.TimeoutException as error:
            raise BackendTimeoutError("장면 분석 접수 확인 시간이 초과되었습니다. 상태를 조회해 주세요.") from error
        except httpx.RequestError as error:
            raise BackendConnectionError("백엔드 서버에 연결할 수 없습니다.") from error
        if response.status_code == 404:
            raise BackendApiError("프로젝트를 찾을 수 없습니다.", status_code=404)
        if response.status_code == 409:
            raise BackendApiError("이미 장면 분석이 실행 중입니다. 상태를 조회해 주세요.", status_code=409)
        self._raise_for_error(response)
        try:
            payload = response.json()
        except ValueError as error:
            raise BackendApiError("장면 분석 접수 응답을 읽을 수 없습니다.") from error
        if (response.status_code != 202 or not isinstance(payload, dict)
            or payload.get("project_id") != normalized_id or payload.get("accepted") is not True
            or payload.get("status_url") != f"/projects/{normalized_id}/scene-processing"):
            raise BackendApiError("장면 분석 접수 응답 형식이 올바르지 않습니다.")
        return {"project_id": normalized_id, "accepted": True, "status_url": payload["status_url"]}

    def get_project_scene_processing_status(self, project_id: str) -> dict[str, Any]:
        normalized_id = _project_id(project_id)
        try:
            response = self._http_client.get(
                f"{self.backend_url}/projects/{normalized_id}/scene-processing",
                timeout=PROJECT_READ_TIMEOUT_SECONDS,
            )
        except httpx.TimeoutException as error:
            raise BackendTimeoutError("장면 분석 상태 조회 시간이 초과되었습니다.") from error
        except httpx.RequestError as error:
            raise BackendConnectionError("백엔드 서버에 연결할 수 없습니다.") from error
        if response.status_code == 404:
            raise BackendApiError("프로젝트를 찾을 수 없습니다.", status_code=404)
        self._raise_for_error(response)
        try:
            return _safe_scene_status_payload(response.json(), normalized_id)
        except ValueError as error:
            raise BackendApiError("장면 분석 상태 응답을 읽을 수 없습니다.") from error

    def get_project_scene_edit_plan(self, project_id: str) -> dict[str, Any]:
        return self._scene_edit_plan_request(project_id, None)

    def save_project_scene_edit_plan(self, project_id: str, candidate_ids: list[str]) -> dict[str, Any]:
        normalized = [_project_id(value) for value in candidate_ids]
        if len(normalized) != len(set(normalized)):
            raise BackendApiError("같은 장면을 중복 선택할 수 없습니다.")
        return self._scene_edit_plan_request(project_id, normalized)

    def _scene_edit_plan_request(self, project_id: str, candidate_ids: list[str] | None) -> dict[str, Any]:
        normalized_id = _project_id(project_id)
        url = f"{self.backend_url}/projects/{normalized_id}/scene-edit-plan"
        try:
            if candidate_ids is None:
                response = self._http_client.get(url, timeout=PROJECT_READ_TIMEOUT_SECONDS)
            else:
                response = self._http_client.put(
                    url, json={"candidate_ids": candidate_ids}, timeout=PROJECT_READ_TIMEOUT_SECONDS
                )
        except httpx.TimeoutException as error:
            raise BackendTimeoutError("편집 계획 요청 시간이 초과되었습니다. 저장 상태를 다시 확인해 주세요.") from error
        except httpx.RequestError as error:
            raise BackendConnectionError("백엔드 서버에 연결할 수 없습니다.") from error
        if response.status_code == 404:
            raise BackendApiError("프로젝트를 찾을 수 없습니다.", status_code=404)
        if response.status_code == 409:
            raise BackendApiError("선택한 장면이 현재 유효하지 않습니다. 후보를 새로 조회하고 편집 계획을 확인해 주세요.", status_code=409)
        self._raise_for_error(response)
        try:
            return _safe_scene_edit_plan_payload(response.json(), normalized_id)
        except ValueError as error:
            raise BackendApiError("편집 계획 응답을 읽을 수 없습니다.") from error

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


def _project_id(value: str) -> str:
    try:
        return str(UUID(value))
    except (TypeError, ValueError, AttributeError) as error:
        raise BackendApiError("프로젝트 ID가 올바르지 않습니다.") from error


def _safe_scene_status_payload(payload: Any, project_id: str) -> dict[str, Any]:
    message = "장면 분석 상태 응답 형식이 올바르지 않습니다."
    counts = ("total_sources", "processed_count", "completed_count", "abstained_count",
              "failed_count", "blocked_count", "skipped_count")
    if (not isinstance(payload, dict) or payload.get("project_id") != project_id
        or not isinstance(payload.get("run_status"), str)
        or payload["run_status"] not in SCENE_RUN_STATUSES
        or not isinstance(payload.get("sources"), list)):
        raise BackendApiError(message)
    if any(type(payload.get(key)) is not int or payload[key] < 0 for key in counts):
        raise BackendApiError(message)
    sources = []
    for source in payload["sources"]:
        if not isinstance(source, dict):
            raise BackendApiError(message)
        try:
            source_id = str(UUID(source["source_video_id"]))
            if (not isinstance(source["status"], str)
                or source["status"] not in SCENE_SOURCE_STATUSES
                or type(source["candidate_count"]) is not int or source["candidate_count"] < 0):
                raise ValueError
        except (KeyError, ValueError, TypeError, AttributeError) as error:
            raise BackendApiError(message) from error
        sources.append({"source_video_id": source_id, "status": source["status"],
                        "candidate_count": source["candidate_count"],
                        "safe_error_code": _safe_error_code(source.get("safe_error_code"))})
    return {"project_id": project_id, "run_status": payload["run_status"],
            **{key: payload[key] for key in counts},
            "safe_error_code": _safe_error_code(payload.get("safe_error_code")),
            "sources": sources}


def _safe_error_code(value: Any) -> str | None:
    return value if isinstance(value, str) and re.fullmatch(r"[A-Z0-9_]{1,80}", value) else None


def _safe_scene_edit_plan_payload(payload: Any, project_id: str) -> dict[str, Any]:
    if not isinstance(payload, dict) or payload.get("project_id") != project_id:
        raise BackendApiError("편집 계획 응답 형식이 올바르지 않습니다.")
    try:
        selected = [_project_id(value) for value in payload["candidate_ids"]]
        invalid = [_project_id(value) for value in payload["invalid_candidate_ids"]]
        if (not isinstance(payload["candidate_ids"], list)
            or not isinstance(payload["invalid_candidate_ids"], list)
            or len(selected) != len(set(selected)) or not set(invalid).issubset(selected)):
            raise ValueError
    except (KeyError, TypeError, ValueError, BackendApiError) as error:
        raise BackendApiError("편집 계획 응답 형식이 올바르지 않습니다.") from error
    return {"project_id": project_id, "candidate_ids": selected, "invalid_candidate_ids": invalid}


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


def _safe_scene_candidates_payload(payload: Any, project_id: str) -> dict[str, Any]:
    if not isinstance(payload, dict) or payload.get("project_id") != project_id:
        raise BackendApiError("장면 후보 응답 형식이 올바르지 않습니다.")
    raw_candidates = payload.get("candidates")
    if not isinstance(raw_candidates, list):
        raise BackendApiError("장면 후보 응답 형식이 올바르지 않습니다.")
    candidates = []
    for item in raw_candidates:
        if not isinstance(item, dict):
            raise BackendApiError("장면 후보 응답 형식이 올바르지 않습니다.")
        try:
            candidate_id = str(UUID(item["candidate_id"]))
            source_id = str(UUID(item["source_video_id"]))
            start = item["start_seconds"]
            end = item["end_seconds"]
            if (
                isinstance(start, bool) or not isinstance(start, (int, float))
                or isinstance(end, bool) or not isinstance(end, (int, float))
                or not isfinite(start) or not isfinite(end)
                or start < 0 or end <= start
            ):
                raise ValueError
            raw_evidence = item["evidence"]
            if not isinstance(raw_evidence, list):
                raise ValueError
            evidence = []
            for row in raw_evidence:
                if not isinstance(row, dict):
                    raise ValueError
                modality = row["modality"]
                evidence_type = row["evidence_type"]
                count = row["count"]
                if (
                    not isinstance(modality, str) or not modality or len(modality) > 32
                    or not isinstance(evidence_type, str) or not evidence_type
                    or len(evidence_type) > 64 or not isinstance(count, int)
                    or isinstance(count, bool) or count < 1
                ):
                    raise ValueError
                evidence.append({"modality": modality, "evidence_type": evidence_type, "count": count})
        except (KeyError, TypeError, ValueError, AttributeError) as error:
            raise BackendApiError("장면 후보 응답 형식이 올바르지 않습니다.") from error
        candidates.append({
            "candidate_id": candidate_id,
            "source_video_id": source_id,
            "start_seconds": float(start),
            "end_seconds": float(end),
            "evidence": evidence,
        })
    return {"project_id": project_id, "candidates": candidates}
