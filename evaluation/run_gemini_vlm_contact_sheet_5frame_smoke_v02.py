"""Run the persisted Gemini five-frame contact-sheet synthetic smoke once."""

from app.config import load_environment
from app.services.evaluation_result_store import JsonlVLMSmokeResultStore
from app.services.gemini_vlm_proposal_selector import GeminiVLMProposalSelector
from app.services.ollama_vlm_proposal_selector import VLMProposalSelectionInput
from app.services.proposal_contact_sheets import (
    FIVE_FRAME_CONTACT_SHEET_CONFIG,
    FIVE_FRAME_CONTACT_SHEET_CONFIG_VERSION,
    build_proposal_contact_sheets,
)
from app.services.scene_boundary_proposals import (
    FIVE_FRAME_SAMPLING_FRACTIONS,
    ProposalFrameSample,
    ProposalKind,
    SceneBoundaryProposal,
)
from app.services.vlm_smoke_runner import run_persisted_vlm_smoke_test
from evaluation.run_local_vlm_contact_sheet_smoke_v02 import _synthetic_jpeg


RUN_ID = "gemini-vlm-contact-sheet-5frame-smoke-v0.2-run1"
MODEL = "gemini-3.1-flash-lite"


def main() -> int:
    load_environment()
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
        contact_sheets=build_proposal_contact_sheets(
            proposals, config=FIVE_FRAME_CONTACT_SHEET_CONFIG
        ),
    )
    run_persisted_vlm_smoke_test(
        run_id=RUN_ID,
        selector=GeminiVLMProposalSelector(model=MODEL),
        selection_input=selection_input,
        video_duration_seconds=10.0,
        memo_start_seconds=9.0,
        store=store,
        runtime="gemini_api",
        provider="gemini",
        num_ctx=None,
        config_version=FIVE_FRAME_CONTACT_SHEET_CONFIG_VERSION,
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
            for index, fraction in enumerate(
                FIVE_FRAME_SAMPLING_FRACTIONS, start=1
            )
        ),
    )


if __name__ == "__main__":
    raise SystemExit(main())
