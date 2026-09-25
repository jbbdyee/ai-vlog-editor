"""Run Gemini Vision feasibility once with the synthetic v0.2 contact sheets."""

from app.config import load_environment
from app.services.evaluation_result_store import JsonlVLMSmokeResultStore
from app.services.gemini_vlm_proposal_selector import GeminiVLMProposalSelector
from app.services.ollama_vlm_proposal_selector import VLMProposalSelectionInput
from app.services.proposal_contact_sheets import build_proposal_contact_sheets
from app.services.vlm_smoke_runner import run_persisted_vlm_smoke_test
from evaluation.run_local_vlm_contact_sheet_smoke_v02 import (
    _proposal,
    _synthetic_jpeg,
)


RUN_ID = "gemini-vlm-contact-sheet-smoke-v0.1-run1"


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
        contact_sheets=build_proposal_contact_sheets(proposals),
    )
    run_persisted_vlm_smoke_test(
        run_id=RUN_ID,
        selector=GeminiVLMProposalSelector(),
        selection_input=selection_input,
        video_duration_seconds=10.0,
        memo_start_seconds=9.0,
        store=store,
        runtime="gemini_api",
        provider="gemini",
        num_ctx=None,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
