import tempfile
from pathlib import Path

import streamlit as st

from subtitle_pipeline import FONT_PRESETS, LANGUAGE_CONFIG, SubtitleJobConfig, SubtitleStyle, hex_to_ass_colour, run_subtitle_job

SUPPORTED_VIDEO_EXTENSIONS = (".mp4", ".mkv", ".mov", ".avi", ".webm")


st.set_page_config(page_title="Video Translate Tool", layout="wide")

st.title("Video Translate Tool")
st.caption("Local video translation with single or bilingual subtitle output.")

if "job_logs" not in st.session_state:
    st.session_state.job_logs = []
if "job_result" not in st.session_state:
    st.session_state.job_result = None
if "selected_output_dir" not in st.session_state:
    st.session_state.selected_output_dir = str(Path.home() / "video_translate_outputs")
if "job_progress" not in st.session_state:
    st.session_state.job_progress = 0.0
if "job_progress_stage" not in st.session_state:
    st.session_state.job_progress_stage = ""
if "job_progress_detail" not in st.session_state:
    st.session_state.job_progress_detail = ""


def pick_output_directory(initial_dir: str | None) -> tuple[str | None, str | None]:
    try:
        import tkinter as tk
        from tkinter import filedialog

        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        selected_dir = filedialog.askdirectory(initialdir=initial_dir or None)
        root.destroy()
    except Exception:
        return None, "Folder picker is unavailable in the current environment. Use Manual Path instead."

    return selected_dir or None, None

with st.sidebar:
    st.header("Job Settings")
    input_source = st.selectbox(
        "Input Source",
        [("local_path", "Local File Path"), ("upload", "Upload File")],
        index=0,
        format_func=lambda item: item[1],
    )[0]
    uploaded_file = None
    local_video_path = ""
    if input_source == "upload":
        uploaded_file = st.file_uploader(
            "Upload Video",
            type=[ext.lstrip(".") for ext in SUPPORTED_VIDEO_EXTENSIONS],
        )
    else:
        local_video_path = st.text_input("Local Video Path", value="")

    output_dir_source = st.selectbox(
        "Output Directory Source",
        [("manual", "Manual Path"), ("browse", "Browse Folder")],
        index=0,
        format_func=lambda item: item[1],
    )[0]
    manual_output_dir = ""
    if output_dir_source == "manual":
        manual_output_dir = st.text_input(
            "Output Directory",
            value=st.session_state.selected_output_dir,
        )
    else:
        st.text_input(
            "Selected Output Directory",
            value=st.session_state.selected_output_dir,
            disabled=True,
        )
        if st.button("Browse Folder"):
            selected_dir, picker_error = pick_output_directory(st.session_state.selected_output_dir)
            if picker_error:
                st.warning(picker_error)
            elif selected_dir:
                st.session_state.selected_output_dir = selected_dir
                st.rerun()
        st.caption("Browse Folder opens the local system folder picker.")
        st.caption("If folder browsing is unavailable in the current environment, use Manual Path instead.")
    st.caption("Upload File supports videos up to 2GB.")
    st.caption("For larger files or local use, choose Local File Path.")

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
    model_size = st.selectbox(
        "Whisper Model",
        ["tiny", "base", "small", "medium", "large"],
        index=2,
    )
    st.caption("Smaller models are faster. Larger models are usually more accurate.")
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
    st.caption("Auto Detect uses Whisper language detection.")
    st.caption("Manual source language is used as a hint and may be overridden if Whisper detects a different language.")
    st.caption("If source and target languages match, bilingual output is automatically downgraded to single-language subtitles.")
    st.caption("If source and target languages match, translation is skipped and the Whisper transcript is used directly.")
    st.caption("Available presets depend on fonts installed on your system. If a font is not installed, FFmpeg may fall back to another font.")

logs_placeholder = st.empty()
result_placeholder = st.empty()
progress_bar_placeholder = st.empty()
progress_text_placeholder = st.empty()


def append_log(message: str):
    st.session_state.job_logs.append(message)
    logs_placeholder.code("\n".join(st.session_state.job_logs), language="text")


def append_progress(update: dict):
    percent = max(0.0, min(100.0, float(update.get("percent", 0.0))))
    stage = str(update.get("stage", "") or "")
    detail = str(update.get("detail", "") or "")
    st.session_state.job_progress = percent
    st.session_state.job_progress_stage = stage
    st.session_state.job_progress_detail = detail
    progress_bar_placeholder.progress(percent / 100.0)

    stage_labels = {
        "start": "Preparing job",
        "transcribe": "Step 1/4: Transcribing audio",
        "translate": "Step 2/4: Translating subtitles",
        "write_srt": "Step 3/4: Writing subtitle file",
        "render": "Step 4/4: Rendering video",
        "done": "Completed",
        "failed": "Failed",
    }
    label = stage_labels.get(stage, "Processing")
    if detail:
        progress_text_placeholder.caption(f"{label} - {detail}")
    else:
        progress_text_placeholder.caption(label)


def render_progress():
    stage = st.session_state.job_progress_stage
    detail = st.session_state.job_progress_detail
    percent = st.session_state.job_progress
    if percent <= 0 and not stage and not detail:
        return

    progress_bar_placeholder.progress(percent / 100.0)
    stage_labels = {
        "start": "Preparing job",
        "transcribe": "Step 1/4: Transcribing audio",
        "translate": "Step 2/4: Translating subtitles",
        "write_srt": "Step 3/4: Writing subtitle file",
        "render": "Step 4/4: Rendering video",
        "done": "Completed",
        "failed": "Failed",
    }
    label = stage_labels.get(stage, "Processing")
    if detail:
        progress_text_placeholder.caption(f"{label} - {detail}")
    else:
        progress_text_placeholder.caption(label)


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


def resolve_input_video_path(
    selected_input_source: str,
    uploaded_video,
    local_path_value: str,
) -> tuple[str | None, str | None]:
    if selected_input_source == "upload":
        if uploaded_video is None:
            return None, "Upload a video first."

        suffix = Path(uploaded_video.name).suffix.lower()
        if suffix not in SUPPORTED_VIDEO_EXTENSIONS:
            return None, f"Unsupported video format: {suffix or 'unknown'}"

        uploads_dir = Path(tempfile.gettempdir()) / "video_translate_tool_uploads"
        uploads_dir.mkdir(parents=True, exist_ok=True)
        input_path = uploads_dir / uploaded_video.name
        input_path.write_bytes(uploaded_video.getbuffer())
        return str(input_path), None

    raw_path = local_path_value.strip()
    if not raw_path:
        return None, "Enter a local video path first."

    try:
        resolved_path = Path(raw_path).expanduser().resolve()
    except OSError as exc:
        return None, f"Invalid local video path: {exc}"

    if not resolved_path.exists():
        return None, f"Local video file not found: {resolved_path}"
    if not resolved_path.is_file():
        return None, f"Local video path is not a file: {resolved_path}"
    if resolved_path.suffix.lower() not in SUPPORTED_VIDEO_EXTENSIONS:
        return None, f"Unsupported video format: {resolved_path.suffix or 'unknown'}"

    return str(resolved_path), None


def resolve_output_directory(
    selected_output_dir_source: str,
    manual_output_dir: str,
    selected_output_dir: str,
) -> tuple[str | None, str | None]:
    if selected_output_dir_source == "manual":
        raw_path = manual_output_dir.strip()
        if not raw_path:
            return None, "Enter an output directory first."
    else:
        raw_path = selected_output_dir.strip()
        if not raw_path:
            return None, "Choose an output folder first."

    try:
        resolved_path = Path(raw_path).expanduser().resolve()
    except OSError as exc:
        return None, f"Invalid output directory: {exc}"

    return str(resolved_path), None


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
render_progress()


if st.button("Start", type="primary"):
    st.session_state.job_logs = []
    st.session_state.job_result = None
    st.session_state.job_progress = 0.0
    st.session_state.job_progress_stage = ""
    st.session_state.job_progress_detail = ""
    logs_placeholder.empty()
    result_placeholder.empty()
    progress_bar_placeholder.empty()
    progress_text_placeholder.empty()

    input_video_path, input_error = resolve_input_video_path(
        input_source,
        uploaded_file,
        local_video_path,
    )
    output_dir, output_error = resolve_output_directory(
        output_dir_source,
        manual_output_dir,
        st.session_state.selected_output_dir,
    )

    if input_error:
        result_placeholder.error(input_error)
    elif output_error:
        result_placeholder.error(output_error)
    else:
        if output_dir_source == "manual":
            st.session_state.selected_output_dir = output_dir
        config = SubtitleJobConfig(
            input_video=input_video_path,
            source_language=source_language,
            target_language=target_language,
            model_size=model_size,
            subtitle_mode=subtitle_mode,
            render_mode=render_mode,
            output_dir=output_dir,
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

        result = run_subtitle_job(config, log_hook=append_log, progress_hook=append_progress)

        st.session_state.job_result = {
            "success": result.success,
            "output_video": result.output_video,
            "output_srt": result.output_srt,
            "error": result.error,
        }

render_job_result()
