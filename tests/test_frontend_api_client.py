import os
from unittest import TestCase
from unittest.mock import patch

import httpx

from frontend.api_client import (
    BackendApiError,
    BackendConnectionError,
    BackendTimeoutError,
    DEFAULT_BACKEND_URL,
    PROCESS_TIMEOUT_SECONDS,
    VideoEditorApiClient,
)


RUN_ID = "a" * 32
CLIP_ID = "b" * 32
DOWNLOAD_URL = f"/videos/clips/{RUN_ID}/{CLIP_ID}"


class FrontendApiClientTests(TestCase):
    def test_backend_url_uses_environment_and_single_normalization_point(self) -> None:
        with patch.dict(os.environ, {"BACKEND_URL": "http://backend:9000/"}):
            client = VideoEditorApiClient(http_client=httpx.Client())
        self.addCleanup(client._http_client.close)
        self.assertEqual(client.backend_url, "http://backend:9000")

    def test_default_backend_url_is_development_server(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            client = VideoEditorApiClient(http_client=httpx.Client())
        self.addCleanup(client._http_client.close)
        self.assertEqual(client.backend_url, DEFAULT_BACKEND_URL)

    def test_health_success(self) -> None:
        client, calls = self._client(lambda request: httpx.Response(200, json={"status": "ok"}))
        self.assertTrue(client.health_check())
        self.assertEqual(calls, ["GET /health"])

    def test_health_failure_is_false_without_raw_exception(self) -> None:
        client, calls = self._client(lambda request: httpx.Response(503, text="internal"))
        self.assertFalse(client.health_check())
        self.assertEqual(len(calls), 1)

    def test_health_connection_error_is_false(self) -> None:
        def fail(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("private host failure", request=request)

        client, calls = self._client(fail)
        self.assertFalse(client.health_check())
        self.assertEqual(len(calls), 1)

    def test_process_video_sends_multipart_file_and_window(self) -> None:
        captured: dict[str, object] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["content_type"] = request.headers["content-type"]
            captured["body"] = request.read()
            return httpx.Response(200, json=self._payload("COMPLETED"))

        client, calls = self._client(handler)
        result = client.process_video(
            file_name="sample.mov",
            file_bytes=b"video-bytes",
            content_type="video/quicktime",
            window_seconds=10.0,
        )

        body = captured["body"]
        self.assertIn("multipart/form-data", captured["content_type"])
        self.assertIn(b'sample.mov', body)
        self.assertIn(b'video-bytes', body)
        self.assertIn(b'name="window_seconds"', body)
        self.assertIn(b"10.0", body)
        self.assertEqual(result["status"], "COMPLETED")
        self.assertEqual(calls, ["POST /videos/process"])

    def test_process_timeout_is_long_and_has_no_retry(self) -> None:
        observed: list[float] = []

        class TimeoutClient:
            def post(self, *args, **kwargs):
                observed.append(kwargs["timeout"])
                request = httpx.Request("POST", args[0])
                raise httpx.ReadTimeout("timeout", request=request)

        client = VideoEditorApiClient(http_client=TimeoutClient())
        with self.assertRaises(BackendTimeoutError):
            client.process_video(
                file_name="sample.mov",
                file_bytes=b"video",
                content_type="video/quicktime",
                window_seconds=5,
            )
        self.assertEqual(observed, [PROCESS_TIMEOUT_SECONDS])
        self.assertGreaterEqual(PROCESS_TIMEOUT_SECONDS, 120)

    def test_process_connection_error_has_no_retry(self) -> None:
        call_count = 0

        class FailingClient:
            def post(self, *args, **kwargs):
                nonlocal call_count
                call_count += 1
                request = httpx.Request("POST", args[0])
                raise httpx.ConnectError("private address", request=request)

        client = VideoEditorApiClient(http_client=FailingClient())
        with self.assertRaisesRegex(
            BackendConnectionError, "백엔드 서버에 연결할 수 없습니다"
        ):
            client.process_video(
                file_name="sample.mp4",
                file_bytes=b"video",
                content_type="video/mp4",
                window_seconds=5,
            )
        self.assertEqual(call_count, 1)

    def test_completed_response_is_safely_parsed(self) -> None:
        client, _ = self._client(
            lambda request: httpx.Response(200, json=self._payload("COMPLETED"))
        )
        result = self._process(client)
        self.assertEqual(result["status"], "COMPLETED")
        self.assertEqual(result["memos"][0]["rendered_clip"]["download_url"], DOWNLOAD_URL)

    def test_no_edit_memo_is_preserved(self) -> None:
        payload = self._payload("NO_EDIT_MEMO")
        payload["memos"] = []
        client, _ = self._client(lambda request: httpx.Response(200, json=payload))
        result = self._process(client)
        self.assertEqual(result["status"], "NO_EDIT_MEMO")
        self.assertEqual(result["memos"], [])

    def test_no_scene_selected_is_preserved(self) -> None:
        payload = self._payload("NO_SCENE_SELECTED")
        payload["memos"][0]["selection"]["candidate"] = None
        payload["memos"][0]["rendered_clip"] = None
        client, _ = self._client(lambda request: httpx.Response(200, json=payload))
        result = self._process(client)
        self.assertEqual(result["status"], "NO_SCENE_SELECTED")
        self.assertIsNone(result["memos"][0]["rendered_clip"])

    def test_415_has_safe_user_message(self) -> None:
        client, _ = self._client(
            lambda request: httpx.Response(415, json={"detail": "raw backend text"})
        )
        with self.assertRaisesRegex(BackendApiError, "지원하지 않는 영상 형식"):
            self._process(client)

    def test_422_has_safe_user_message(self) -> None:
        client, _ = self._client(
            lambda request: httpx.Response(422, json={"detail": {"code": "INVALID"}})
        )
        with self.assertRaisesRegex(BackendApiError, "입력값이 올바르지 않거나"):
            self._process(client)

    def test_500_pipeline_error_preserves_only_safe_metadata(self) -> None:
        client, _ = self._client(
            lambda request: httpx.Response(
                500,
                json={
                    "detail": {
                        "code": "PIPELINE_STT_FAILED",
                        "stage": "stt",
                        "message": "Video processing failed during stt.",
                        "traceback": "/Users/private/secret.py",
                    }
                },
            )
        )
        with self.assertRaises(BackendApiError) as raised:
            self._process(client)
        self.assertEqual(raised.exception.code, "PIPELINE_STT_FAILED")
        self.assertEqual(raised.exception.stage, "stt")
        self.assertNotIn("/Users/", str(raised.exception))

    def test_download_clip_combines_backend_and_relative_url_once(self) -> None:
        client, calls = self._client(
            lambda request: httpx.Response(
                200, content=b"mp4-bytes", headers={"content-type": "video/mp4"}
            )
        )
        self.assertEqual(client.download_clip(DOWNLOAD_URL), b"mp4-bytes")
        self.assertEqual(calls, [f"GET {DOWNLOAD_URL}"])

    def test_download_rejects_external_or_malformed_urls_without_request(self) -> None:
        client, calls = self._client(lambda request: httpx.Response(200, content=b"secret"))
        for url in (
            "https://evil.example/video.mp4",
            "/Users/private/clip.mp4",
            f"/videos/clips/{RUN_ID}/../.env",
        ):
            with self.subTest(url=url), self.assertRaises(BackendApiError):
                client.download_clip(url)
        self.assertEqual(calls, [])

    def test_local_paths_and_unknown_fields_are_removed_from_ui_payload(self) -> None:
        payload = self._payload("COMPLETED")
        payload["source_path"] = "/Users/private/source.mov"
        payload["memos"][0]["rendered_clip"]["clip_path"] = "C:\\secret\\clip.mp4"
        payload["transcript"]["model_internal"] = "/home/private/model"
        client, _ = self._client(lambda request: httpx.Response(200, json=payload))
        result = self._process(client)
        serialized = repr(result)
        self.assertNotIn("source_path", serialized)
        self.assertNotIn("clip_path", serialized)
        self.assertNotIn("model_internal", serialized)
        self.assertNotIn("/Users/", serialized)
        self.assertNotIn("/home/", serialized)
        self.assertNotIn("C:\\", serialized)

    def _client(self, handler):
        calls: list[str] = []

        def tracking_handler(request: httpx.Request) -> httpx.Response:
            calls.append(f"{request.method} {request.url.path}")
            return handler(request)

        http_client = httpx.Client(transport=httpx.MockTransport(tracking_handler))
        self.addCleanup(http_client.close)
        return (
            VideoEditorApiClient(
                backend_url="http://backend.test", http_client=http_client
            ),
            calls,
        )

    @staticmethod
    def _process(client: VideoEditorApiClient):
        return client.process_video(
            file_name="sample.mov",
            file_bytes=b"video",
            content_type="video/quicktime",
            window_seconds=5.0,
        )

    @staticmethod
    def _payload(status: str) -> dict:
        return {
            "video_id": "c" * 32,
            "stored_filename": f"{'c' * 32}.mov",
            "status": status,
            "media": {
                "duration_seconds": 20.95,
                "has_video_stream": True,
                "has_audio_stream": True,
                "video_codec": "hevc",
                "audio_codec": "aac",
                "format_name": "mov,mp4",
            },
            "transcript": {
                "text": "AI야 지금 장면 꼭 살려줘",
                "language": "ko",
                "language_probability": 1.0,
                "segments": [
                    {"start_seconds": 15.8, "end_seconds": 18.72, "text": "memo"}
                ],
            },
            "memos": [
                {
                    "memo": {
                        "start_seconds": 15.8,
                        "end_seconds": 18.72,
                        "transcript_text": "AI야 지금 장면 꼭 살려줘",
                        "matched_trigger": "AI야",
                        "matched_reference": "지금",
                        "matched_action": "살려줘",
                    },
                    "generated_candidates": [
                        {"window_seconds": 5.0, "start_seconds": 10.8, "end_seconds": 15.8}
                    ],
                    "selection": {
                        "strategy_name": "fixed_window",
                        "selected_source_id": "window:5.0",
                        "reasoning_code": "FIXED_WINDOW_SELECTED",
                        "reasoning_summary": None,
                        "candidate": {
                            "window_seconds": 5.0,
                            "start_seconds": 10.8,
                            "end_seconds": 15.8,
                        },
                    },
                    "rendered_clip": {
                        "clip_id": CLIP_ID,
                        "filename": f"{CLIP_ID}.mp4",
                        "download_url": DOWNLOAD_URL,
                        "start_seconds": 10.8,
                        "end_seconds": 15.8,
                        "duration_seconds": 5.0,
                        "video_codec": "h264",
                        "audio_codec": "aac",
                    },
                }
            ],
            "timings": [{"stage": "total", "duration_seconds": 13.0}],
            "warnings": [],
        }
