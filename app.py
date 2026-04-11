import tempfile
from pathlib import Path

import streamlit as st

from subtitle_pipeline import FONT_PRESETS, LANGUAGE_CONFIG, SubtitleJobConfig, SubtitleStyle, hex_to_ass_colour, run_subtitle_job


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
    font_preset_options = [label for label, _ in FONT_PRESETS]
    font_preset = st.selectbox("Font Preset", font_preset_options, index=0)
    custom_font_name = ""
    if font_preset == "Custom":
        custom_font_name = st.text_input("Custom Font Name", value="")

    selected_font_name = next(
        (font_name for label, font_name in FONT_PRESETS if label == font_preset),
        "Microsoft YaHei",
    )
    resolved_font_name = (
        custom_font_name.strip() or "Microsoft YaHei"
        if font_preset == "Custom"
        else selected_font_name or "Microsoft YaHei"
    )
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
    st.caption("Available presets depend on fonts installed on your system. If a font is not installed, FFmpeg may fall back to another font.")

uploaded_file = st.file_uploader("Upload Video", type=["mp4", "mkv", "mov", "avi", "webm"])

logs_placeholder = st.empty()
result_placeholder = st.empty()

if "job_logs" not in st.session_state:
    st.session_state.job_logs = []
if "job_result" not in st.session_state:
    st.session_state.job_result = None


def append_log(message: str):
    st.session_state.job_logs.append(message)
    logs_placeholder.code("\n".join(st.session_state.job_logs), language="text")


def human_file_size(size_bytes: int) -> str:
    units = ["B", "KB", "MB", "GB"]
    size = float(size_bytes)
    for unit in units:
        if size < 1024 or unit == units[-1]:
            return f"{size:.1f} {unit}" if unit != "B" else f"{int(size)} {unit}"
        size /= 1024


def render_result_file(label: str, path_value: str | None, mime: str):
    if not path_value:
        return

    file_path = Path(path_value)
    if not file_path.exists():
        st.warning(f"{label} file not found: {path_value}")
        return

    file_size = human_file_size(file_path.stat().st_size)
    st.markdown(f"**{label}**")
    st.write("Name:", file_path.name)
    st.write("Size:", file_size)
    st.code(str(file_path))

    with file_path.open("rb") as file_handle:
        st.download_button(
            label=f"Download {label}",
            data=file_handle.read(),
            file_name=file_path.name,
            mime=mime,
        )


def render_job_result():
    result = st.session_state.job_result
    if not result:
        return

    if result["success"]:
        result_placeholder.success("Completed")
        output_video_path = Path(result["output_video"]).resolve() if result["output_video"] else None
        output_subtitle_path = Path(result["output_srt"]).resolve() if result["output_srt"] else None

        st.subheader("Outputs")
        render_result_file("Video", str(output_video_path) if output_video_path else None, "video/mp4")
        render_result_file("Subtitle", str(output_subtitle_path) if output_subtitle_path else None, "application/x-subrip")
    else:
        result_placeholder.error(result["error"] or "Job failed")


if st.session_state.job_logs:
    logs_placeholder.code("\n".join(st.session_state.job_logs), language="text")


if st.button("Start", type="primary", disabled=uploaded_file is None):
    st.session_state.job_logs = []
    st.session_state.job_result = None
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
                font_name=resolved_font_name,
                font_size=font_size,
                margin_v=bottom_margin,
                outline=outline_width,
                primary_colour=hex_to_ass_colour(text_color, "&H00FFFFFF"),
                outline_colour=hex_to_ass_colour(outline_color, "&H00000000"),
            ),
        )

        with st.spinner("Processing video..."):
            result = run_subtitle_job(config, log_hook=append_log)

        st.session_state.job_result = {
            "success": result.success,
            "output_video": result.output_video,
            "output_srt": result.output_srt,
            "error": result.error,
        }

render_job_result()
