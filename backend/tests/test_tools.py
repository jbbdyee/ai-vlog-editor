from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock
from uuid import uuid4

from backend.app.services.audio_extractor import AudioExtractionError, ExtractedAudio
from backend.app.services.media_probe import MediaInfo, MediaProbeError
from backend.app.services.memo_detector import EditMemo, MemoDetectionError
from backend.app.services.stt_service import STTError, STTResult, TranscriptSegment, TranscriptWord
from backend.app.storage.processing_workspace import LocalProcessingWorkspace
from backend.app.tools.contracts import (
    ToolError,
    ToolErrorCode,
    ToolExecutionMetadata,
    ToolResult,
    ToolStatus,
)
from backend.app.tools.media import (
    ExtractAudioInput,
    ProbeVideoInput,
    extract_audio,
    probe_video,
)
from backend.app.tools.resources import (
    DatabaseSourceResourceResolver,
    InvalidResourceInputError,
    ResolvedSource,
    ResourceNotFoundError,
    ResourceOwnershipError,
    ResourceSecurityError,
    TemporaryArtifactKind,
    TemporaryArtifactRegistry,
)
from backend.app.tools.transcript import (
    DetectEditMemosInput,
    TranscriptData,
    TranscriptSegmentData,
    TranscriptWordData,
    TranscribeAudioInput,
    detect_edit_memos,
    transcribe_audio,
)


class ToolContractTests(TestCase):
    def setUp(self) -> None:
        self.metadata = ToolExecutionMetadata(
            invocation_id=uuid4(),
            tool_name="test",
            tool_version="1.0",
            started_at=SimpleNamespace(),
            completed_at=SimpleNamespace(),
            duration_ms=1.0,
        )

    def test_success_and_failure_are_exclusive(self) -> None:
        success = ToolResult(ToolStatus.SUCCEEDED, self.metadata, data="ok")
        failure = ToolResult(
            ToolStatus.FAILED,
            self.metadata,
            error=ToolError(ToolErrorCode.EXECUTION_FAILED, "failed"),
        )
        self.assertEqual(success.data, "ok")
        self.assertIsNotNone(failure.error)
        for invalid in (
            lambda: ToolResult(ToolStatus.SUCCEEDED, self.metadata),
            lambda: ToolResult(
                ToolStatus.SUCCEEDED,
                self.metadata,
                data="ok",
                error=ToolError(ToolErrorCode.EXECUTION_FAILED, "failed"),
            ),
            lambda: ToolResult(ToolStatus.FAILED, self.metadata, data="bad"),
        ):
            with self.assertRaises(ValueError):
                invalid()


class ResourceResolverTests(TestCase):
    def test_database_resolver_enforces_identity_ownership_and_storage_boundary(self) -> None:
        source_id = uuid4()
        project_id = uuid4()
        path = Mock(spec=Path)
        path.is_file.return_value = True
        source = SimpleNamespace(
            id=source_id,
            project_id=project_id,
            storage_reference="projects/safe/source.mp4",
        )
        session = Mock()
        session.get.return_value = source
        storage = Mock()
        storage.resolve.return_value = path
        resolver = DatabaseSourceResourceResolver(session=session, storage=storage)

        resolved = resolver.resolve_source(source_id, expected_project_id=project_id)

        self.assertEqual(resolved.source_video_id, source_id)
        self.assertIs(resolved.path, path)
        storage.resolve.assert_called_once_with(source.storage_reference)
        for unsafe_input in (
            "C:/secret/video.mp4",
            "../../secret.mp4",
            "https://example.invalid/video.mp4",
        ):
            with self.subTest(unsafe_input=unsafe_input):
                with self.assertRaises(InvalidResourceInputError):
                    resolver.resolve_source(unsafe_input)
        with self.assertRaises(ResourceOwnershipError):
            resolver.resolve_source(source_id, expected_project_id=uuid4())

    def test_database_resolver_rejects_missing_and_malformed_reference(self) -> None:
        session = Mock()
        storage = Mock()
        resolver = DatabaseSourceResourceResolver(session=session, storage=storage)
        session.get.return_value = None
        with self.assertRaises(ResourceNotFoundError):
            resolver.resolve_source(uuid4())

        session.get.return_value = SimpleNamespace(
            id=uuid4(), project_id=uuid4(), storage_reference="../../secret"
        )
        from backend.app.storage.source_storage import InvalidSourceReference

        storage.resolve.side_effect = InvalidSourceReference("escape")
        with self.assertRaises(ResourceSecurityError):
            resolver.resolve_source(session.get.return_value.id)

    def test_tool_package_has_no_mcp_import(self) -> None:
        tool_root = Path(__file__).parents[1] / "app" / "tools"
        source = "\n".join(path.read_text(encoding="utf-8") for path in tool_root.glob("*.py"))
        self.assertNotIn("import mcp", source)
        self.assertNotIn("from mcp", source)


class ToolAdapterTests(TestCase):
    def setUp(self) -> None:
        self.temporary_directory = TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)
        self.original = self.root / "originals" / "source.mp4"
        self.original.parent.mkdir()
        self.original.write_bytes(b"source")
        self.workspace_root = self.root / "temporary"
        self.project_id = uuid4()
        self.source_id = uuid4()
        self.resolver = Mock()
        self.resolver.resolve_source.return_value = ResolvedSource(
            self.source_id, self.project_id, self.original
        )
        self.workspace = LocalProcessingWorkspace(self.workspace_root)
        self.registry = TemporaryArtifactRegistry(self.workspace_root)

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def test_probe_resolves_source_calls_service_once_and_maps_without_path(self) -> None:
        service = Mock(
            return_value=MediaInfo(2.5, True, True, "h264", "aac", "mov,mp4")
        )
        result = probe_video(
            ProbeVideoInput(self.source_id, self.project_id),
            resolver=self.resolver,
            probe=service,
        )
        self.assertEqual(result.status, ToolStatus.SUCCEEDED)
        service.assert_called_once_with(self.original)
        self.assertEqual(result.data.duration_seconds, 2.5)
        self.assertNotIn(str(self.original), repr(result))
        self.assertEqual(result.metadata.tool_name, "probe_video")
        self.assertEqual(result.metadata.tool_version, "1.0")
        self.assertGreaterEqual(result.metadata.duration_ms, 0)

    def test_expected_probe_failure_is_safe_and_programmer_error_propagates(self) -> None:
        failed = probe_video(
            ProbeVideoInput(self.source_id),
            resolver=self.resolver,
            probe=Mock(side_effect=MediaProbeError(f"secret {self.original}")),
        )
        self.assertEqual(failed.error.code, ToolErrorCode.EXECUTION_FAILED)
        self.assertNotIn(str(self.original), repr(failed))
        with self.assertRaises(TypeError):
            probe_video(
                ProbeVideoInput(self.source_id),
                resolver=self.resolver,
                probe=Mock(side_effect=TypeError("programmer bug")),
            )

    def test_resource_failure_is_structured(self) -> None:
        self.resolver.resolve_source.side_effect = ResourceNotFoundError("missing")
        result = probe_video(ProbeVideoInput(self.source_id), resolver=self.resolver)
        self.assertEqual(result.error.code, ToolErrorCode.RESOURCE_NOT_FOUND)

    def test_extract_registers_opaque_artifact_and_preserves_original(self) -> None:
        service = Mock(side_effect=self._write_extracted_audio)
        result = extract_audio(
            ExtractAudioInput(self.source_id, self.project_id),
            resolver=self.resolver,
            workspace=self.workspace,
            registry=self.registry,
            extractor=service,
        )
        service.assert_called_once()
        self.assertEqual(result.status, ToolStatus.SUCCEEDED)
        self.assertFalse(hasattr(result.data.artifact, "path"))
        audio_path = self.registry.resolve(
            result.data.artifact.artifact_id,
            expected_project_id=self.project_id,
            expected_source_video_id=self.source_id,
            expected_scope_id=result.data.artifact.scope_id,
            expected_kind=TemporaryArtifactKind.AUDIO_WAV,
        )
        self.assertTrue(audio_path.is_file())
        self.assertTrue(self.original.is_file())
        self.assertNotIn(str(audio_path), repr(result))
        self.registry.cleanup(result.data.artifact.artifact_id)
        self.assertFalse(audio_path.exists())

    def test_extract_failure_does_not_register_artifact(self) -> None:
        result = extract_audio(
            ExtractAudioInput(self.source_id),
            resolver=self.resolver,
            workspace=self.workspace,
            registry=self.registry,
            extractor=Mock(side_effect=AudioExtractionError("raw ffmpeg stderr")),
        )
        self.assertEqual(result.error.code, ToolErrorCode.EXECUTION_FAILED)
        self.assertTrue(self.original.is_file())
        self.assertNotIn("stderr", repr(result))

    def test_transcribe_uses_registry_and_preloaded_model_once(self) -> None:
        artifact = self._registered_audio()
        model = Mock()
        service = Mock(return_value=self._stt_result())
        result = transcribe_audio(
            TranscribeAudioInput(
                artifact.artifact_id,
                expected_project_id=self.project_id,
                expected_source_video_id=self.source_id,
                expected_scope_id=artifact.scope_id,
            ),
            registry=self.registry,
            model=model,
            transcriber=service,
        )
        self.assertEqual(result.status, ToolStatus.SUCCEEDED)
        service.assert_called_once()
        self.assertIs(service.call_args.kwargs["model"], model)
        self.assertTrue(service.call_args.kwargs["word_timestamps"])
        self.assertEqual(result.data.segments[0].words[0].text, "AI야")
        self.assertNotIn(str(self.workspace_root), repr(result))

    def test_transcribe_rejects_scope_mismatch_and_does_not_hide_bug(self) -> None:
        artifact = self._registered_audio()
        failed = transcribe_audio(
            TranscribeAudioInput(artifact.artifact_id, expected_scope_id=uuid4()),
            registry=self.registry,
            model=Mock(),
        )
        self.assertEqual(failed.error.code, ToolErrorCode.SECURITY_VIOLATION)
        with self.assertRaises(TypeError):
            transcribe_audio(
                TranscribeAudioInput(artifact.artifact_id),
                registry=self.registry,
                model=Mock(),
                transcriber=Mock(side_effect=TypeError("bug")),
            )

    def test_stt_expected_failure_is_safe(self) -> None:
        artifact = self._registered_audio()
        result = transcribe_audio(
            TranscribeAudioInput(artifact.artifact_id),
            registry=self.registry,
            model=Mock(),
            transcriber=Mock(side_effect=STTError("provider details")),
        )
        self.assertEqual(result.error.code, ToolErrorCode.EXECUTION_FAILED)
        self.assertNotIn("provider details", repr(result))

    def test_memo_tool_maps_result_and_zero_is_success(self) -> None:
        transcript = self._transcript_data()
        detector = Mock(return_value=(EditMemo(1, 2, "AI야 방금 살려줘", "AI야", "방금", "살려줘"),))
        result = detect_edit_memos(DetectEditMemosInput(transcript), detector=detector)
        detector.assert_called_once()
        self.assertEqual(result.data.memos[0].matched_action, "살려줘")
        empty = detect_edit_memos(
            DetectEditMemosInput(transcript), detector=Mock(return_value=())
        )
        self.assertEqual(empty.status, ToolStatus.SUCCEEDED)
        self.assertEqual(empty.data.memos, ())

    def test_memo_expected_failure_is_mapped_and_programmer_error_propagates(self) -> None:
        request = DetectEditMemosInput(self._transcript_data())
        failed = detect_edit_memos(
            request, detector=Mock(side_effect=MemoDetectionError("invalid"))
        )
        self.assertEqual(failed.error.code, ToolErrorCode.INVALID_INPUT)
        with self.assertRaises(RuntimeError):
            detect_edit_memos(request, detector=Mock(side_effect=RuntimeError("bug")))

    def test_registry_rejects_root_escape_and_missing_id(self) -> None:
        outside = self.root / "outside.wav"
        outside.write_bytes(b"RIFF")
        with self.assertRaises(ResourceSecurityError):
            self.registry.register(
                outside,
                project_id=self.project_id,
                source_video_id=self.source_id,
                scope_id=uuid4(),
                artifact_kind=TemporaryArtifactKind.AUDIO_WAV,
            )
        with self.assertRaises(ResourceNotFoundError):
            self.registry.resolve(uuid4())

    def _write_extracted_audio(self, source_path: Path, output_directory: Path) -> ExtractedAudio:
        output_directory.mkdir(parents=True, exist_ok=True)
        audio = output_directory / "generated.wav"
        audio.write_bytes(b"RIFF-wave")
        return ExtractedAudio(source_path, audio, 2.5, 16000, 1, "pcm_s16le")

    def _registered_audio(self):
        audio_dir = self.workspace.audio_directory(
            project_id=self.project_id, source_video_id=self.source_id
        )
        path = audio_dir / f"{uuid4().hex}.wav"
        path.write_bytes(b"RIFF-wave")
        return self.registry.register(
            path,
            project_id=self.project_id,
            source_video_id=self.source_id,
            scope_id=uuid4(),
            artifact_kind=TemporaryArtifactKind.AUDIO_WAV,
        )

    @staticmethod
    def _stt_result() -> STTResult:
        return STTResult(
            text="AI야 방금 장면 꼭 살려줘",
            language="ko",
            language_probability=0.99,
            segments=(
                TranscriptSegment(
                    1,
                    2,
                    "AI야 방금 장면 꼭 살려줘",
                    (TranscriptWord(1, 1.2, "AI야", 0.9),),
                ),
            ),
        )

    @classmethod
    def _transcript_data(cls) -> TranscriptData:
        result = cls._stt_result()
        return TranscriptData(
            result.text,
            (
                TranscriptSegmentData(
                    1,
                    2,
                    result.text,
                    (TranscriptWordData(1, 1.2, "AI야", 0.9),),
                ),
            ),
            "ko",
            0.99,
        )
