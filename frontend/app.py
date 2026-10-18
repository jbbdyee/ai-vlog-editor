from uuid import UUID

import streamlit as st

from frontend.api_client import BackendApiError, VideoEditorApiClient


WINDOW_OPTIONS = (5.0, 10.0, 15.0, 30.0)


@st.cache_resource
def _api_client() -> VideoEditorApiClient:
    return VideoEditorApiClient()


def main() -> None:
    st.set_page_config(page_title="AI Vlog Editor", layout="centered")
    st.title("AI Vlog Editor")
    st.write(
        "영상 속 'AI야, 지금 장면 꼭 살려줘' 같은 편집 메모를 찾아 "
        "해당 구간을 클립으로 생성합니다."
    )

    client = _api_client()
    backend_available = client.health_check()
    if backend_available:
        st.caption("백엔드 서버에 연결되었습니다.")
    else:
        st.warning("백엔드 서버에 연결할 수 없습니다.")

    _render_project_candidates_section(client, backend_available)
    st.divider()

    uploaded_file = st.file_uploader("MOV 또는 MP4 영상", type=("mov", "mp4"))
    window_seconds = st.selectbox(
        "편집 길이",
        WINDOW_OPTIONS,
        index=0,
        format_func=lambda value: f"{int(value)}초",
    )
    st.caption("현재는 사용자가 직접 편집 길이를 선택합니다.")

    if st.button("영상 분석 및 클립 생성", type="primary"):
        if uploaded_file is None:
            st.info("먼저 MOV 또는 MP4 영상을 선택해 주세요.")
        elif not backend_available:
            st.error("백엔드 서버에 연결할 수 없습니다.")
        else:
            try:
                with st.spinner("영상 분석 중입니다..."):
                    result = client.process_video(
                        file_name=uploaded_file.name,
                        file_bytes=uploaded_file.getvalue(),
                        content_type=uploaded_file.type or "application/octet-stream",
                        window_seconds=window_seconds,
                    )
                st.session_state["process_result"] = result
                st.session_state["clip_bytes"] = {}
                st.session_state["processed_file_name"] = uploaded_file.name
                st.session_state["processed_window_seconds"] = window_seconds
            except BackendApiError as error:
                st.error(str(error))

    result = st.session_state.get("process_result")
    if isinstance(result, dict):
        _render_result(
            client,
            result,
            st.session_state.get("processed_file_name", result.get("stored_filename", "-")),
            st.session_state.get("processed_window_seconds", window_seconds),
        )


def _render_project_candidates_section(
    client: VideoEditorApiClient, backend_available: bool
) -> None:
    st.subheader("프로젝트 장면 후보")
    st.caption("현재 유효한 후보와 관측 근거만 표시합니다. 장면의 중요도나 편집 순위는 판단하지 않습니다.")
    project_id = st.text_input("프로젝트 ID", key="scene_project_id").strip()
    _render_project_scene_controls(client, backend_available, project_id)
    if st.button("장면 후보 조회"):
        st.session_state.pop("scene_candidates_result", None)
        if not project_id:
            st.info("프로젝트 ID를 입력해 주세요.")
        elif not backend_available:
            st.error("백엔드 서버에 연결할 수 없습니다.")
        else:
            try:
                with st.spinner("장면 후보를 조회하는 중입니다..."):
                    result = client.get_project_scene_candidates(project_id)
                st.session_state["scene_candidates_result"] = result
                _load_project_edit_plan(client, result)
            except BackendApiError as error:
                st.error(str(error))

    result = st.session_state.get("scene_candidates_result")
    if isinstance(result, dict) and project_id:
        try:
            current_project_id = str(UUID(project_id))
        except ValueError:
            current_project_id = None
        if result.get("project_id") == current_project_id:
            _render_project_candidate_results(result)
            _render_project_edit_plan_section(client, result, backend_available)
            _render_project_render_section(client, result, backend_available)


def _render_project_scene_controls(
    client: VideoEditorApiClient, backend_available: bool, project_id: str
) -> None:
    try:
        normalized_id = str(UUID(project_id))
    except (ValueError, AttributeError):
        normalized_id = None
    status = st.session_state.get("scene_processing_status")
    current = status if isinstance(status, dict) and status.get("project_id") == normalized_id else None
    active = current is not None and current.get("run_status") in {"QUEUED", "RUNNING"}

    if st.button("AI 장면 분석 실행", disabled=active or not backend_available):
        if not normalized_id:
            st.info("올바른 프로젝트 ID를 입력해 주세요.")
        else:
            try:
                client.start_project_scene_processing(normalized_id)
                current = {"project_id": normalized_id, "run_status": "QUEUED", "sources": []}
                st.session_state["scene_processing_status"] = current
                st.session_state.pop("scene_candidates_result", None)
                st.success("AI 장면 분석이 접수되었습니다. 상태 새로고침으로 진행 상황을 확인해 주세요.")
            except BackendApiError as error:
                st.error(str(error))

    if st.button("장면 분석 상태 새로고침", disabled=not backend_available):
        if not normalized_id:
            st.info("올바른 프로젝트 ID를 입력해 주세요.")
        else:
            try:
                current = client.get_project_scene_processing_status(normalized_id)
                st.session_state["scene_processing_status"] = current
                if current["run_status"] in {"COMPLETED", "COMPLETED_WITH_WARNINGS", "FAILED"}:
                    # A terminal run can contain successful Sources even when another Source failed.
                    st.session_state["scene_candidates_result"] = client.get_project_scene_candidates(normalized_id)
                    _load_project_edit_plan(client, st.session_state["scene_candidates_result"])
            except BackendApiError as error:
                st.error(str(error))

    if current is not None:
        _render_project_scene_status(current)


def _load_project_edit_plan(client: VideoEditorApiClient, candidates: dict) -> None:
    project_id = candidates["project_id"]
    st.session_state.pop("scene_edit_plan", None)
    try:
        plan = client.get_project_scene_edit_plan(project_id)
    except BackendApiError as error:
        st.error(str(error))
        return
    st.session_state["scene_edit_plan"] = plan
    active = {item["candidate_id"] for item in candidates["candidates"]}
    st.session_state[f"scene_selected_{project_id}"] = [
        value for value in plan["candidate_ids"] if value in active
    ]
    st.session_state[f"scene_order_{project_id}"] = list(st.session_state[f"scene_selected_{project_id}"])


def _reconcile_selection_order(order: list[str], selected: list[str]) -> list[str]:
    chosen = set(selected)
    return [value for value in order if value in chosen] + [
        value for value in selected if value not in order
    ]


def _render_project_edit_plan_section(
    client: VideoEditorApiClient, candidates: dict, backend_available: bool
) -> None:
    project_id = candidates["project_id"]
    plan = st.session_state.get("scene_edit_plan")
    if not isinstance(plan, dict) or plan.get("project_id") != project_id:
        st.info("편집 계획을 불러온 뒤 장면을 선택할 수 있습니다.")
        return
    st.subheader("사용할 장면과 순서")
    st.caption("AI 추천 후보 중 사용할 장면과 순서를 정하고 저장합니다. 저장된 계획으로 최종 영상을 만들 수 있습니다.")
    invalid = plan["invalid_candidate_ids"]
    conflict_confirmed = True
    if invalid:
        st.warning("AI 재분석으로 현재 유효하지 않은 장면이 편집 계획에 있습니다. 아래 목록을 검토하고 저장해 충돌을 해결해 주세요: " + ", ".join(invalid))
        conflict_confirmed = st.checkbox("무효 후보를 제외하고 편집 계획을 다시 저장하겠습니다.")
    rows = {item["candidate_id"]: item for item in candidates["candidates"]}
    selected_key = f"scene_selected_{project_id}"
    order_key = f"scene_order_{project_id}"
    if selected_key not in st.session_state:
        st.session_state[selected_key] = [value for value in plan["candidate_ids"] if value in rows]
    if order_key not in st.session_state:
        st.session_state[order_key] = list(st.session_state[selected_key])
    selected = st.multiselect(
        "사용할 장면", options=list(rows), key=selected_key,
        format_func=lambda value: _scene_option_label(rows[value]),
    )
    ordered = _reconcile_selection_order(st.session_state[order_key], selected)
    st.session_state[order_key] = ordered
    if ordered:
        chosen = st.selectbox("순서를 바꿀 장면", ordered, format_func=lambda value: _scene_option_label(rows[value]))
        if st.button("위로 이동", disabled=ordered.index(chosen) == 0):
            index = ordered.index(chosen)
            ordered[index - 1], ordered[index] = ordered[index], ordered[index - 1]
            st.session_state[order_key] = ordered
            st.rerun()
        if st.button("아래로 이동", disabled=ordered.index(chosen) == len(ordered) - 1):
            index = ordered.index(chosen)
            ordered[index + 1], ordered[index] = ordered[index], ordered[index + 1]
            st.session_state[order_key] = ordered
            st.rerun()
        st.write("저장할 순서: " + " → ".join(_scene_option_label(rows[value]) for value in ordered))
    else:
        st.info("선택한 장면이 없습니다. 빈 편집 계획도 저장할 수 있습니다.")
    if st.button("편집 계획 저장", disabled=not backend_available or not conflict_confirmed):
        try:
            saved = client.save_project_scene_edit_plan(project_id, ordered)
        except BackendApiError as error:
            st.error(str(error))
        else:
            st.session_state["scene_edit_plan"] = saved
            st.session_state.pop(f"project_render_status_{project_id}", None)
            st.session_state.pop(f"project_render_bytes_{project_id}", None)
            st.success("편집 계획을 저장했습니다.")


def _render_readiness(plan: dict, ordered: list[str]) -> str | None:
    if plan["invalid_candidate_ids"]:
        return "무효화된 장면이 있습니다. 편집 계획의 충돌을 해결하고 저장해 주세요."
    if ordered != plan["candidate_ids"]:
        return "화면에서 변경한 장면 선택·순서를 먼저 저장해 주세요."
    if not plan["candidate_ids"]:
        return "편집 계획이 비어 있습니다. 사용할 장면을 선택하고 저장해 주세요."
    return None


def _render_project_render_section(
    client: VideoEditorApiClient, candidates: dict, backend_available: bool
) -> None:
    project_id = candidates["project_id"]
    plan = st.session_state.get("scene_edit_plan")
    if not isinstance(plan, dict) or plan.get("project_id") != project_id:
        return
    st.subheader("최종 영상")
    ordered = st.session_state.get(f"scene_order_{project_id}", [])
    reason = _render_readiness(plan, ordered)
    status_key = f"project_render_status_{project_id}"
    bytes_key = f"project_render_bytes_{project_id}"
    error_key = f"project_render_status_error_{project_id}"
    status = st.session_state.get(status_key)
    active = isinstance(status, dict) and status.get("status") in {"QUEUED", "RUNNING"}
    if reason:
        st.info(reason)
    if st.button("최종 영상 만들기", key=f"start_render_{project_id}",
                 disabled=not backend_available or reason is not None or active):
        try:
            client.start_project_render(project_id)
        except BackendApiError as error:
            st.error(str(error))
        else:
            status = {"project_id": project_id, "status": "QUEUED", "render_id": None,
                      "download_available": False, "output": None}
            st.session_state[status_key] = status
            st.session_state.pop(bytes_key, None)
            st.session_state.pop(error_key, None)
            st.success("렌더링 작업이 접수되었습니다. 상태 새로고침으로 확인해 주세요.")

    if st.button("렌더링 상태 새로고침", key=f"refresh_render_{project_id}",
                 disabled=not backend_available):
        try:
            status = client.get_project_rendering_status(project_id)
        except BackendApiError as error:
            st.session_state.pop(status_key, None)
            st.session_state.pop(bytes_key, None)
            st.session_state[error_key] = True
            st.error(str(error))
        else:
            st.session_state[status_key] = status
            st.session_state.pop(error_key, None)
            if status["status"] != "COMPLETED" or not status["download_available"]:
                st.session_state.pop(bytes_key, None)

    if st.session_state.get(error_key):
        st.warning("렌더링 상태를 확인할 수 없습니다. 상태 새로고침을 다시 눌러 주세요.")
        return
    if not isinstance(status, dict):
        st.info("렌더링 상태를 아직 조회하지 않았습니다.")
        return
    _render_project_render_status(status)
    if status["status"] != "COMPLETED" or not status["download_available"]:
        return
    render_id = status["render_id"]
    if st.button("최종 영상 다운로드 준비", key=f"prepare_render_{project_id}"):
        try:
            latest = client.get_project_rendering_status(project_id)
            if (latest["status"] != "COMPLETED" or not latest["download_available"]
                or latest["render_id"] != render_id):
                st.session_state[status_key] = latest
                st.session_state.pop(bytes_key, None)
                st.warning("렌더링 상태가 변경되었습니다. 다시 확인해 주세요.")
                return
            st.session_state[bytes_key] = (render_id, client.download_project_render(project_id, render_id))
        except BackendApiError as error:
            st.session_state.pop(bytes_key, None)
            st.error(str(error))
    cached = st.session_state.get(bytes_key)
    if isinstance(cached, tuple) and cached[0] == render_id:
        st.download_button("최종 영상 다운로드", data=cached[1],
                           file_name=f"cutory-{render_id}.mp4", mime="video/mp4",
                           key=f"download_render_{project_id}")


def _render_project_render_status(status: dict) -> None:
    state = status["status"]
    if state == "NOT_STARTED":
        st.info("현재 서버 프로세스에 렌더링 실행 기록이 없습니다. 서버 재시작으로 상태가 유실됐을 수 있습니다. 파일만으로 완료를 판단하지 않습니다.")
    elif state in {"QUEUED", "RUNNING"}:
        st.info("최종 영상 렌더링 중입니다. 상태 새로고침으로 확인해 주세요.")
    elif state == "FAILED":
        st.error(f"렌더링에 실패했습니다. 오류 코드: {status.get('safe_error_code') or '-'}")
    elif status["download_available"]:
        st.success("최종 영상이 완성됐습니다. 다운로드를 준비할 수 있습니다.")
    else:
        st.warning("렌더링은 완료됐지만 결과 파일을 다운로드할 수 없습니다.")


def _scene_option_label(row: dict) -> str:
    return (f"{row['source_video_id'][:8]} · "
            f"{_seconds(row['start_seconds'])}~{_seconds(row['end_seconds'])} "
            f"({row['candidate_id'][:8]})")


def _render_project_scene_status(status: dict) -> None:
    run_status = status["run_status"]
    if run_status == "NOT_STARTED":
        st.info("현재 서버 프로세스에 장면 분석 실행 기록이 없습니다. 서버 재시작으로 상태가 유실됐을 수 있습니다. 기존 후보는 별도로 조회할 수 있습니다.")
        return
    if run_status in {"QUEUED", "RUNNING"}:
        st.info("AI 장면 분석 실행 중입니다. 상태 새로고침으로 확인해 주세요.")
    elif run_status == "FAILED":
        st.error("AI 장면 분석 실행이 실패했습니다.")
    elif run_status == "COMPLETED_WITH_WARNINGS":
        st.warning("AI 장면 분석이 종료됐지만 일부 Source가 실패·차단·건너뜀 상태입니다.")
    else:
        st.success("AI 장면 분석이 완료되었습니다.")
    if "total_sources" in status:
        st.caption(f"처리 {status['processed_count']} / {status['total_sources']} Source · "
                   f"완료 {status['completed_count']} · 후보 없음 {status['abstained_count']} · "
                   f"실패 {status['failed_count']} · 차단 {status['blocked_count']} · "
                   f"건너뜀 {status['skipped_count']}")
    labels = {"COMPLETED": "완료", "ABSTAINED": "후보 없음(정상 기권)",
              "FAILED": "실패", "BLOCKED": "실행 차단",
              "SKIPPED_V1_INCOMPLETE": "건너뜀(v1 미완료)"}
    sources = status.get("sources", [])
    if sources:
        st.dataframe([{"Source ID": item["source_video_id"],
                       "상태": labels[item["status"]], "후보 수": item["candidate_count"],
                       "오류 코드": item.get("safe_error_code") or "-"}
                      for item in sources], width="stretch", hide_index=True)


def _render_project_candidate_results(result: dict) -> None:
    candidates = result["candidates"]
    if not candidates:
        st.info("현재 조회할 수 있는 장면 후보가 없습니다.")
        return
    st.dataframe(
        [
            {
                "후보 ID": item["candidate_id"],
                "원본 영상 ID": item["source_video_id"],
                "시작": _seconds(item["start_seconds"]),
                "종료": _seconds(item["end_seconds"]),
                "길이": _seconds(item["end_seconds"] - item["start_seconds"]),
                "Evidence": ", ".join(
                    f"{row['modality']}/{row['evidence_type']} ({row['count']})"
                    for row in item["evidence"]
                ) or "없음",
            }
            for item in candidates
        ],
        width="stretch",
        hide_index=True,
    )


def _render_result(
    client: VideoEditorApiClient,
    result: dict,
    original_file_name: str,
    selected_window_seconds: float,
) -> None:
    status = result.get("status")
    media = result.get("media", {})
    st.subheader("처리 결과")
    st.write(f"원본 파일: {original_file_name}")
    st.write(f"영상 길이: {_seconds(media.get('duration_seconds'))}")
    st.write(f"선택한 편집 길이: {int(selected_window_seconds)}초")

    transcript = result.get("transcript", {})
    st.subheader("Transcript")
    st.write(transcript.get("text") or "Transcript가 없습니다.")
    segments = transcript.get("segments", [])
    if segments:
        with st.expander("Segment 보기"):
            st.dataframe(segments, width="stretch")

    if status == "NO_EDIT_MEMO":
        st.info("영상에서 편집 메모를 찾지 못했습니다.")
    elif status == "NO_SCENE_SELECTED":
        st.info("편집 메모는 찾았지만 생성할 장면을 선택하지 못했습니다.")
    elif status == "COMPLETED":
        st.success("클립 생성이 완료되었습니다.")
    else:
        st.warning("알 수 없는 처리 상태입니다.")

    for index, memo_result in enumerate(result.get("memos", []), start=1):
        _render_memo(client, memo_result, index)

    warnings = result.get("warnings", [])
    for warning in warnings:
        st.warning(warning)

    timings = result.get("timings", [])
    if timings:
        with st.expander("처리 시간 보기"):
            st.dataframe(timings, width="stretch")


def _render_memo(client: VideoEditorApiClient, memo_result: dict, index: int) -> None:
    st.subheader(f"EditMemo {index}")
    memo = memo_result.get("memo", {})
    st.write(memo.get("transcript_text") or "-")
    st.caption(
        f"{_seconds(memo.get('start_seconds'))} ~ {_seconds(memo.get('end_seconds'))} · "
        f"trigger: {memo.get('matched_trigger', '-')} · "
        f"reference: {memo.get('matched_reference', '-')} · "
        f"action: {memo.get('matched_action', '-')}"
    )

    candidates = memo_result.get("generated_candidates", [])
    if candidates:
        st.write("Candidates")
        st.dataframe(
            [
                {
                    "Window": _seconds(candidate.get("window_seconds")),
                    "Start": _seconds(candidate.get("start_seconds")),
                    "End": _seconds(candidate.get("end_seconds")),
                }
                for candidate in candidates
            ],
            width="stretch",
        )

    selection = memo_result.get("selection", {})
    selected = selection.get("candidate")
    st.write("Selection")
    if selected:
        st.write(
            f"{selection.get('strategy_name')} · {selection.get('selected_source_id')} · "
            f"{_seconds(selected.get('start_seconds'))} ~ "
            f"{_seconds(selected.get('end_seconds'))}"
        )
    else:
        st.write("선택된 장면이 없습니다.")

    rendered = memo_result.get("rendered_clip")
    if not rendered:
        return
    st.write(
        f"클립: {_seconds(rendered.get('duration_seconds'))} · "
        f"{rendered.get('video_codec', '-')} / {rendered.get('audio_codec', '-')}"
    )
    download_url = rendered.get("download_url")
    if not download_url:
        st.warning("클립 다운로드 주소가 없습니다.")
        return

    clip_cache = st.session_state.setdefault("clip_bytes", {})
    try:
        if download_url not in clip_cache:
            clip_cache[download_url] = client.download_clip(download_url)
        video_bytes = clip_cache[download_url]
    except BackendApiError as error:
        st.error(str(error))
        return
    st.video(video_bytes, format="video/mp4")
    st.download_button(
        "MP4 다운로드",
        data=video_bytes,
        file_name=rendered.get("filename") or "clip.mp4",
        mime="video/mp4",
        key=f"download-{rendered.get('clip_id')}",
    )


def _seconds(value: object) -> str:
    if isinstance(value, (int, float)):
        return f"{float(value):.2f}초"
    return "-"


if __name__ == "__main__":
    main()
