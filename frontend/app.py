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
            st.dataframe(segments, use_container_width=True)

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
            st.dataframe(timings, use_container_width=True)


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
                    "Window": f"{candidate.get('window_seconds')}초",
                    "Start": candidate.get("start_seconds"),
                    "End": candidate.get("end_seconds"),
                }
                for candidate in candidates
            ],
            use_container_width=True,
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
