import tempfile
from pathlib import Path

import streamlit as st

from subtitle_pipeline import LANGUAGE_CONFIG, SubtitleJobConfig, SubtitleStyle, hex_to_ass_colour, run_subtitle_job


st.set_page_config(page_title="Video Translate Tool", layout="wide")

st.title("Video Translate Tool")
st.caption("Local video translation with single or bilingual subtitle output.")

with st.sidebar:
    st.header("Job Settings")
    source_language_options = ["auto", *LANGUAGE_CONFIG.keys()]
    source_language = st.selectbox(
        "Source Language",
        source_language_options,
        index=0,
        format_func=lambda code: "Auto Detect" if code == "auto" else LANGUAGE_CONFIG[code]["label"],
    )
    target_language = st.selectbox(
        "Target Language",
        list(LANGUAGE_CONFIG.keys()),
        index=0,
        format_func=lambda code: LANGUAGE_CONFIG[code]["label"],
    )
    subtitle_mode = st.selectbox(
        "Subtitle Mode",
        [("single", "Single Language"), ("bilingual", "Bilingual (top/bottom)")],
        format_func=lambda item: item[1],
    )[0]
    render_mode = st.selectbox(
        "Render Mode",
        [("burned", "Burned Subtitle Video"), ("soft", "Soft Subtitle Video")],
        format_func=lambda item: item[1],
    )[0]
    batch_size = st.slider("Batch Size", min_value=1, max_value=20, value=10)
    verbose = st.checkbox("Verbose Logs", value=False)
    output_dir = st.text_input("Output Directory", value=r"D:\transfer\outputs")

    st.header("Subtitle Style")
    font_name = st.text_input("Font Name", value="Microsoft YaHei")
    font_size = st.slider("Font Size", min_value=12, max_value=40, value=20)
    text_color = st.color_picker("Text Color", value="#FFFFFF")
    outline_color = st.color_picker("Outline Color", value="#000000")
    outline_width = st.slider("Outline Width", min_value=0, max_value=6, value=2)
    bottom_margin = st.slider("Bottom Margin", min_value=10, max_value=120, value=30)
    st.caption("Style settings apply to burned subtitles. Soft subtitle appearance depends on the video player.")
    st.caption("Bilingual subtitles use the source text on top and the selected target language on the bottom.")
    st.caption("Auto Detect uses Whisper language detection. You can manually select the source language if detection is inaccurate.")
    st.caption("If source and target languages match, bilingual output is automatically downgraded to single-language subtitles.")
    st.caption("If source and target languages match, translation is skipped and the Whisper transcript is used directly.")

uploaded_file = st.file_uploader("Upload Video", type=["mp4", "mkv", "mov", "avi", "webm"])

logs_placeholder = st.empty()
result_placeholder = st.empty()

if "job_logs" not in st.session_state:
    st.session_state.job_logs = []


def append_log(message: str):
    st.session_state.job_logs.append(message)
    logs_placeholder.code("\n".join(st.session_state.job_logs), language="text")


if st.button("Start", type="primary", disabled=uploaded_file is None):
    st.session_state.job_logs = []
    logs_placeholder.empty()
    result_placeholder.empty()

    if uploaded_file is None:
        st.warning("Upload a video first.")
    else:
        uploads_dir = Path(tempfile.gettempdir()) / "video_translate_tool_uploads"
        uploads_dir.mkdir(parents=True, exist_ok=True)
        input_path = uploads_dir / uploaded_file.name
        input_path.write_bytes(uploaded_file.getbuffer())

        config = SubtitleJobConfig(
            input_video=str(input_path),
            source_language=source_language,
            target_language=target_language,
            subtitle_mode=subtitle_mode,
            render_mode=render_mode,
            output_dir=output_dir.strip() or None,
            batch_size=batch_size,
            verbose=verbose,
            style=SubtitleStyle(
                font_name=font_name.strip() or "Microsoft YaHei",
                font_size=font_size,
                margin_v=bottom_margin,
                outline=outline_width,
                primary_colour=hex_to_ass_colour(text_color, "&H00FFFFFF"),
                outline_colour=hex_to_ass_colour(outline_color, "&H00000000"),
            ),
        )

        with st.spinner("Processing video..."):
            result = run_subtitle_job(config, log_hook=append_log)

        if result.success:
            result_placeholder.success("Completed")
            st.write("Output Video:", result.output_video)
            st.write("Output Subtitle:", result.output_srt)
        else:
            result_placeholder.error(result.error or "Job failed")
