from uuid import UUID
from unittest import TestCase

from backend.app.services.autonomous_discovery import (
    AutonomousDiscoveryError,
    _decode_analysis,
    _encode_analysis,
)


SOURCE_ID = UUID("235a2371-96d8-40a1-a5e6-c3f3ec8c7d0b")


def _manifest(count: int):
    return {
        "schema": "autonomous-modality-result-v0.1",
        "evidences": [
            {
                "interval": {
                    "source_video_id": str(SOURCE_ID),
                    "start_seconds": round(index * 4.37, 3),
                    "end_seconds": round(index * 4.37 + 2.16, 3),
                    "unit_type": "TRANSCRIPT_SEGMENT",
                    "producer": "transcript-structure",
                    "producer_version": "autonomous-discovery-v0.1",
                },
                "modality": "TRANSCRIPT",
                "evidence_type": "TRANSCRIPT_STRUCTURE",
                "payload": {
                    "segment_id": f"segment-{index + 1:04d}",
                    "speech_present": True,
                    "duration_seconds": 2.16,
                },
            }
            for index in range(count)
        ],
        "warnings": [],
    }


class ManifestCompactionTests(TestCase):
    def test_long_transcript_evidence_fits_existing_column_and_round_trips(self):
        manifest = _manifest(45)
        encoded = _encode_analysis(manifest)
        self.assertTrue(encoded.startswith("zlib2:"))
        self.assertLessEqual(len(encoded), 1024)
        decoded = _decode_analysis(encoded)
        self.assertIsNotNone(decoded)
        self.assertEqual(len(decoded.evidences), 45)
        self.assertEqual(decoded.evidences[0].interval.source_video_id, SOURCE_ID)
        self.assertEqual(decoded.evidences[-1].payload, manifest["evidences"][-1]["payload"])

    def test_short_existing_encoding_remains_readable(self):
        encoded = _encode_analysis(_manifest(1))
        self.assertTrue(encoded.startswith("zlib:"))
        self.assertEqual(len(_decode_analysis(encoded).evidences), 1)

    def test_oversized_manifest_still_fails_instead_of_truncating(self):
        with self.assertRaisesRegex(AutonomousDiscoveryError, "too large"):
            _encode_analysis(_manifest(200))

    def test_invalid_compact_encoding_is_not_accepted(self):
        self.assertIsNone(_decode_analysis("zlib2:not-base64"))
