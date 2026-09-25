"""Run the persisted Local VLM contact-sheet v0.2 synthetic smoke once."""

import subprocess

from app.services.evaluation_result_store import JsonlVLMSmokeResultStore
from app.services.ollama_vlm_proposal_selector import (
    OllamaVLMProposalSelector,
    VLMProposalSelectionInput,
)
from app.services.proposal_contact_sheets import build_proposal_contact_sheets
from app.services.scene_boundary_proposals import (
    ProposalFrameSample,
    ProposalKind,
    SceneBoundaryProposal,
)
from app.services.vlm_smoke_runner import run_persisted_vlm_smoke_test


RUN_ID = "local-vlm-contact-sheet-smoke-v0.2-run1"


def main() -> int:
    store = JsonlVLMSmokeResultStore()
    if store.has_run(RUN_ID):
        return 0
    synthetic_jpeg = _synthetic_jpeg()
    proposals = (
        _proposal(1, 1.0, 3.0, synthetic_jpeg),
        _proposal(2, 0.0, 5.0, synthetic_jpeg),
        _proposal(3, 0.0, 8.0, synthetic_jpeg),
    )
    selection_input = VLMProposalSelectionInput(
        edit_memo_transcript="AI야 방금 장면 꼭 살려줘",
        selected_block_id="block-smoke",
        selected_block_text="아 뭐야 물건 떨어졌네",
        proposals=proposals,
        contact_sheets=build_proposal_contact_sheets(proposals),
    )
    run_persisted_vlm_smoke_test(
        run_id=RUN_ID,
        selector=OllamaVLMProposalSelector(timeout_seconds=120.0),
        selection_input=selection_input,
        video_duration_seconds=10.0,
        memo_start_seconds=9.0,
        store=store,
    )
    return 0


def _proposal(
    number: int, start: float, end: float, jpeg_bytes: bytes
) -> SceneBoundaryProposal:
    proposal_id = f"proposal-{number:03d}"
    duration = end - start
    return SceneBoundaryProposal(
        proposal_id=proposal_id,
        proposal_kind=ProposalKind.RAW_BLOCK,
        start_seconds=start,
        end_seconds=end,
        source_block_id="block-smoke",
        source_segment_ids=("segment-smoke",),
        source_audio_interval_ids=(),
        source_visual_interval_ids=(),
        frame_samples=tuple(
            ProposalFrameSample(
                frame_id=f"{proposal_id}-frame-{index:02d}",
                timestamp_seconds=start + duration * fraction,
                jpeg_bytes=jpeg_bytes,
            )
            for index, fraction in enumerate((0.10, 0.50, 0.90), start=1)
        ),
    )


def _synthetic_jpeg() -> bytes:
    command = [
        "ffmpeg",
        "-v",
        "error",
        "-nostdin",
        "-f",
        "lavfi",
        "-i",
        "color=c=blue:s=512x288:d=0.04",
        "-vf",
        "drawbox=x=196:y=84:w=120:h=120:color=yellow:t=fill",
        "-frames:v",
        "1",
        "-map_metadata",
        "-1",
        "-q:v",
        "3",
        "-f",
        "image2pipe",
        "-vcodec",
        "mjpeg",
        "pipe:1",
    ]
    result = subprocess.run(command, capture_output=True, check=False)
    if result.returncode != 0 or not result.stdout:
        detail = result.stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(f"Could not create synthetic JPEG: {detail}")
    return result.stdout


if __name__ == "__main__":
    raise SystemExit(main())
