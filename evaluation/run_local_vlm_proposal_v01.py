"""Run the fixed Local VLM Proposal Selector v0.1.1 evaluation one test at a time."""

from dataclasses import dataclass
from pathlib import Path
import sys

from app.services.audio_boundary_refiner import refine_scene_boundary
from app.services.candidate_evaluator import GroundTruthSegment
from app.services.evaluation_result_store import (
    JsonlLocalVLMEvaluationResultStore,
    LocalVLMEvaluationResult,
)
from app.services.local_vlm_evaluation import run_persisted_local_vlm_evaluation
from app.services.media_probe import probe_media
from app.services.memo_detector import detect_edit_memos
from app.services.ollama_vlm_proposal_selector import (
    OllamaVLMProposalSelector,
    VLMProposalSelectionInput,
)
from app.services.scene_boundary_proposals import (
    BoundarySignalInterval,
    attach_representative_frames,
    generate_scene_boundary_proposals,
)
from app.services.stt_service import load_model, transcribe_audio
from app.services.transcript_scene_retriever import build_transcript_blocks
from app.services.visual_motion_refiner import refine_visual_boundary


RUN_ID = "local-vlm-eval-v0.1.1-run2"


@dataclass(frozen=True)
class EvalCase:
    test_id: str
    video_path: Path
    audio_path: Path
    selected_block_id: str
    ground_truth: GroundTruthSegment


CASES = (
    EvalCase("eval_01", Path("evaluation/data/eval_01.MOV"), Path("evaluation/audio/b1daf28f02034de98c946f8e33434714.wav"), "block-0002", GroundTruthSegment(10.0, 15.0)),
    EvalCase("eval_02", Path("evaluation/data/eval_02.MOV"), Path("evaluation/audio/b0f29868fd7c440f8249838fe09d3e71.wav"), "block-0001", GroundTruthSegment(7.0, 11.0)),
    EvalCase("eval_03", Path("evaluation/data/eval_03.MOV"), Path("evaluation/audio/b376ccfec4f84971bd763101481f7a02.wav"), "block-0002", GroundTruthSegment(6.0, 23.0)),
    EvalCase("eval_04", Path("evaluation/data/eval_04.MOV"), Path("evaluation/audio/eeb8e0f9ef6f440cb01ad138be53ea64.wav"), "block-0002", GroundTruthSegment(7.0, 11.0)),
    EvalCase("eval_05", Path("evaluation/data/eval_05.MOV"), Path("evaluation/audio/c6f7593c9b724f069047cf9c23cd3cc3.wav"), "block-0003", GroundTruthSegment(20.0, 26.0)),
)


def main() -> int:
    store = JsonlLocalVLMEvaluationResultStore()
    completed = set(store.completed_test_ids(RUN_ID))
    pending = tuple(case for case in CASES if case.test_id not in completed)
    if not pending:
        return 0

    model = load_model()
    selector = OllamaVLMProposalSelector(timeout_seconds=120.0)
    for case in pending:
        try:
            _run_case(case, model, selector, store)
        except Exception as exc:
            if case.test_id not in store.completed_test_ids(RUN_ID):
                _persist_preparation_failure(case, selector, store, exc)
            print(f"{case.test_id}: {type(exc).__name__}", file=sys.stderr)
    return 0


def _run_case(case, model, selector, store) -> None:
    selection_input, duration, memo_start = _prepare_case(case, model)
    run_persisted_local_vlm_evaluation(
        run_id=RUN_ID,
        test_id=case.test_id,
        selector=selector,
        selection_input=selection_input,
        video_duration_seconds=duration,
        memo_start_seconds=memo_start,
        ground_truth=case.ground_truth,
        store=store,
    )


def _prepare_case(case, model):
    media = probe_media(case.video_path)
    transcript = transcribe_audio(case.audio_path, model=model, word_timestamps=True)
    memos = detect_edit_memos(transcript)
    if len(memos) != 1:
        raise RuntimeError(f"{case.test_id} must contain exactly one edit memo.")
    memo = memos[0]
    blocks = build_transcript_blocks(
        transcript, memo, video_duration_seconds=media.duration_seconds
    )
    selected_index = next(
        (index for index, block in enumerate(blocks) if block.block_id == case.selected_block_id),
        None,
    )
    if selected_index is None:
        raise RuntimeError(f"Missing fixed block {case.selected_block_id}.")
    selected = blocks[selected_index]
    previous_end = blocks[selected_index - 1].end_seconds if selected_index > 0 else None
    next_start = blocks[selected_index + 1].start_seconds if selected_index + 1 < len(blocks) else None

    audio_result = refine_scene_boundary(
        case.audio_path,
        video_duration_seconds=media.duration_seconds,
        selected_block=selected,
        previous_block_end_seconds=previous_end,
        next_block_start_seconds=next_start,
        memo_start_seconds=memo.start_seconds,
    )
    visual_result = refine_visual_boundary(
        case.video_path,
        video_duration_seconds=media.duration_seconds,
        selected_block=selected,
        previous_block_end_seconds=previous_end,
        next_block_start_seconds=next_start,
        memo_start_seconds=memo.start_seconds,
    )
    source_segments = {
        f"segment-{index:04d}": segment
        for index, segment in enumerate(transcript.segments, start=1)
    }
    audio_intervals = tuple(
        BoundarySignalInterval(
            f"audio-{index:03d}", interval.start_seconds, interval.end_seconds
        )
        for index, interval in enumerate(audio_result.activity_intervals, start=1)
    )
    visual_intervals = tuple(
        BoundarySignalInterval(
            f"visual-{index:03d}", interval.start_seconds, interval.end_seconds
        )
        for index, interval in enumerate(visual_result.activity_intervals, start=1)
    )
    proposals = generate_scene_boundary_proposals(
        selected_block=selected,
        source_segments=source_segments,
        video_duration_seconds=media.duration_seconds,
        memo_start_seconds=memo.start_seconds,
        previous_block_end_seconds=previous_end,
        next_block_start_seconds=next_start,
        audio_intervals=audio_intervals,
        visual_intervals=visual_intervals,
    )
    framed = attach_representative_frames(case.video_path, proposals)
    selection_input = VLMProposalSelectionInput(
        edit_memo_transcript=memo.transcript_text,
        selected_block_id=selected.block_id,
        selected_block_text=selected.transcript_text,
        proposals=framed,
    )
    return selection_input, media.duration_seconds, memo.start_seconds


def _persist_preparation_failure(case, selector, store, error) -> None:
    store.append(
        LocalVLMEvaluationResult.completed_now(
            run_id=RUN_ID,
            test_id=case.test_id,
            model=selector.model,
            runtime="mac_native_ollama",
            proposal_count=0,
            image_count=0,
            selected_proposal_id=None,
            reasoning_code=None,
            reasoning_summary=None,
            structured_output_success=False,
            validator_success=False,
            candidate_start=None,
            candidate_end=None,
            iou=None,
            coverage=None,
            start_boundary_error=None,
            end_boundary_error=None,
            total_boundary_error=None,
            oracle_best_proposal_id=None,
            oracle_best_iou=None,
            oracle_best_coverage=None,
            oracle_best_total_boundary_error=None,
            latency_seconds=None,
            input_tokens=None,
            output_tokens=None,
            total_tokens=None,
            provider_error=False,
            provider_error_code=None,
            preparation_error=True,
            preparation_error_code=type(error).__name__,
        )
    )


if __name__ == "__main__":
    raise SystemExit(main())
