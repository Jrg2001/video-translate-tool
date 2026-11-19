import json
import os
import subprocess
import tempfile
from pathlib import Path

import streamlit as st

from subtitle_pipeline import FONT_PRESETS, LANGUAGE_CONFIG, STYLE_PRESETS, SubtitleJobConfig, SubtitleStyle, hex_to_ass_colour, run_subtitle_job
from ui_i18n import translate, translate_detail

SUPPORTED_VIDEO_EXTENSIONS = (".mp4", ".mkv", ".mov", ".avi", ".webm")
# Selectbox/radio widgets whose labels are translated via format_func.
TRANSLATED_CHOICE_STATE_KEYS = (
    "job_mode", "input_source", "output_dir_source", "source_language",
    "target_language", "subtitle_mode", "render_mode",
    "ui_style_preset", "ui_font_preset", "ui_orientation",
)


def t(message: str, **values) -> str:
    return translate(message, interface_language, **values)


def on_interface_language_change() -> None:
    """Resend selected labels without changing the underlying option values."""
    # A new format_func updates options, but the browser can retain the old
    # selected label. Writing the same value back makes Streamlit explicitly
    # send its freshly translated label on the next render.
    for key in TRANSLATED_CHOICE_STATE_KEYS:
        if key in st.session_state:
            st.session_state[key] = st.session_state[key]


def ass_to_hex(ass_color: str) -> str:
    """Convert ASS colour token (&H00BBGGRR) to CSS hex (#RRGGBB)."""
    import re as _re
    if _re.fullmatch(r"&H00[0-9A-Fa-f]{6}", ass_color or ""):
        b, g, r = ass_color[4:6], ass_color[6:8], ass_color[8:10]
        return f"#{r}{g}{b}".upper()
    return "#FFFFFF"


def on_style_preset_change() -> None:
    """Callback: push preset values into session_state so all widgets reflect the new style."""
    preset_name = st.session_state.get("ui_style_preset", "Custom")
    preset = STYLE_PRESETS.get(preset_name, {})
    if not preset:
        return
    font_labels = [label for label, _ in FONT_PRESETS]
    if "font_name" in preset and preset["font_name"] in font_labels:
        st.session_state["ui_font_preset"] = preset["font_name"]
    if "font_size" in preset:
        st.session_state["ui_font_size"] = int(preset["font_size"])
    if "margin_v" in preset:
        st.session_state["ui_bottom_margin"] = int(preset["margin_v"])
    if "outline" in preset:
        st.session_state["ui_outline_width"] = int(preset["outline"])
    if "primary_colour" in preset:
        st.session_state["ui_text_color"] = ass_to_hex(preset["primary_colour"])
    if "outline_colour" in preset:
        st.session_state["ui_outline_color"] = ass_to_hex(preset["outline_colour"])


def detect_video_orientation(local_path: str | None, uploaded_file) -> str:
    """Return 'portrait' or 'landscape' using ffprobe.

    For uploaded files only the first 10 MB are written to a temp file so we
    never block on reading a full 2 GB upload just to parse video dimensions.
    """
    try:
        if local_path:
            proc = subprocess.run(
                ["ffprobe", "-v", "quiet", "-print_format", "json",
                 "-show_streams", local_path],
                capture_output=True, text=True, timeout=10,
            )
            data = json.loads(proc.stdout)
        elif uploaded_file is not None:
            _CHUNK = 10 * 1024 * 1024  # 10 MB is enough for most container headers
            uploaded_file.seek(0)
            chunk = uploaded_file.read(_CHUNK)
            uploaded_file.seek(0)
            suffix = Path(uploaded_file.name).suffix or ".tmp"
            with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tf:
                tf.write(chunk)
                tmp_path = tf.name
            try:
                proc = subprocess.run(
                    ["ffprobe", "-v", "quiet", "-print_format", "json",
                     "-show_streams", tmp_path],
                    capture_output=True, text=True, timeout=10,
                )
                data = json.loads(proc.stdout)
            finally:
                os.unlink(tmp_path)
        else:
            return "landscape"

        for stream in data.get("streams", []):
            if stream.get("codec_type") == "video":
                w = int(stream.get("width", 1) or 1)
                h = int(stream.get("height", 1) or 1)
                return "portrait" if h > w else "landscape"
    except Exception:
        pass
    return "landscape"


def _apply_orientation_defaults(orientation: str) -> None:
    """Push orientation-appropriate style defaults into session_state."""
    if orientation == "portrait":
        st.session_state["ui_font_size"] = 15
        st.session_state["ui_bottom_margin"] = 80
        st.session_state["ui_orientation"] = "Portrait (9:16)"
    else:
        st.session_state["ui_font_size"] = 20
        st.session_state["ui_bottom_margin"] = 30
        st.session_state["ui_orientation"] = "Landscape (16:9)"


def _on_orientation_change() -> None:
    """Callback: user manually switched the orientation radio."""
    orient_val = st.session_state.get("ui_orientation", "Landscape (16:9)")
    _apply_orientation_defaults(
        "portrait" if orient_val.startswith("Portrait") else "landscape"
    )


st.session_state.setdefault("ui_language", "zh")
interface_language = st.session_state.ui_language
st.set_page_config(page_title=t("Video Translate Tool"), layout="wide")

title_column, language_column = st.columns([5, 2])
with language_column:
    st.radio(
        "界面语言 / Language",
        ["zh", "en"],
        format_func=lambda language: {"zh": "中文", "en": "English"}[language],
        key="ui_language",
        on_change=on_interface_language_change,
        horizontal=True,
        label_visibility="collapsed",
    )
with title_column:
    st.title(t("Video Translate Tool"))
    st.caption(t("Local video translation with single or bilingual subtitle output."))

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
if "detected_orientation" not in st.session_state:
    st.session_state.detected_orientation = "landscape"
if "_last_vid_key" not in st.session_state:
    st.session_state["_last_vid_key"] = ""


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
        return None, t("Folder picker is unavailable in the current environment. Use Manual Path instead.")

    return selected_dir or None, None

with st.sidebar:
    st.header(t("Job Settings"))
    job_mode = st.selectbox(
        t("Job Mode"),
        [
            ("full", "Full Pipeline (Transcribe → Translate → Burn)"),
            ("burn_only", "Burn Existing SRT"),
        ],
        format_func=lambda item: t(item[1]),
        key="job_mode",
    )[0]
    input_source = st.selectbox(
        t("Input Source"),
        [("local_path", "Local File Path"), ("upload", "Upload File")],
        index=0,
        format_func=lambda item: t(item[1]),
        key="input_source",
    )[0]
    uploaded_file = None
    local_video_path = ""
    if input_source == "upload":
        uploaded_file = st.file_uploader(
            t("Upload Video"),
            type=[ext.lstrip(".") for ext in SUPPORTED_VIDEO_EXTENSIONS],
            key="uploaded_video",
        )
    else:
        local_video_path = st.text_input(t("Local Video Path"), value="", key="local_video_path")

    # SRT path input — only shown in burn-only mode
    # Pre-fill with the last generated SRT so the user doesn't have to retype it.
    external_srt_path = ""
    if job_mode == "burn_only":
        _last_srt = (
            (st.session_state.job_result or {}).get("output_srt") or ""
        )
        external_srt_path = st.text_input(
            t("Existing SRT File Path"),
            value=_last_srt,
            key="external_srt_path",
            help=t("Path to the .srt subtitle file you want to burn into the video. Edit it first with any text editor, then come back here."),
        )

    output_dir_source = st.selectbox(
        t("Output Directory Source"),
        [("manual", "Manual Path"), ("browse", "Browse Folder")],
        index=0,
        format_func=lambda item: t(item[1]),
        key="output_dir_source",
    )[0]
    manual_output_dir = ""
    if output_dir_source == "manual":
        manual_output_dir = st.text_input(
            t("Output Directory"),
            value=st.session_state.selected_output_dir,
            key="manual_output_dir",
        )
    else:
        st.session_state["output_dir_display"] = st.session_state.selected_output_dir
        st.text_input(
            t("Selected Output Directory"),
            disabled=True,
            key="output_dir_display",
        )
        if st.button(t("Browse Folder"), key="browse_output_directory"):
            selected_dir, picker_error = pick_output_directory(st.session_state.selected_output_dir)
            if picker_error:
                st.warning(picker_error)
            elif selected_dir:
                st.session_state.selected_output_dir = selected_dir
                st.rerun()
        st.caption(t("Browse Folder opens the local system folder picker."))
        st.caption(t("If folder browsing is unavailable in the current environment, use Manual Path instead."))
    st.caption(t("Upload File supports videos up to 2GB."))
    st.caption(t("For larger files or local use, choose Local File Path."))

    # ── Auto-detect video orientation ─────────────────────────────────────
    _vid_key = ""
    if input_source == "upload" and uploaded_file is not None:
        _vid_key = f"upload:{uploaded_file.name}:{uploaded_file.size}"
    elif input_source == "local_path" and local_video_path.strip():
        _vid_key = f"local:{local_video_path.strip()}"

    if _vid_key and _vid_key != st.session_state.get("_last_vid_key", ""):
        # New video — run ffprobe and apply defaults
        st.session_state["_last_vid_key"] = _vid_key
        _detected = detect_video_orientation(
            local_path=local_video_path.strip() if input_source == "local_path" else None,
            uploaded_file=uploaded_file if input_source == "upload" else None,
        )
        if _detected != st.session_state.get("detected_orientation"):
            st.session_state["detected_orientation"] = _detected
            _apply_orientation_defaults(_detected)
    elif not _vid_key:
        st.session_state["_last_vid_key"] = ""
        st.session_state["detected_orientation"] = "landscape"

    _det_label = (
        "🔍 Auto-detected: Portrait (9:16)"
        if st.session_state.get("detected_orientation") == "portrait"
        else "🔍 Auto-detected: Landscape (16:9)"
    ) if _vid_key else "🔍 No video selected—defaulting to Landscape"

    st.radio(
        t("Video Orientation"),
        ["Landscape (16:9)", "Portrait (9:16)"],
        format_func=t,
        key="ui_orientation",
        on_change=_on_orientation_change,
        help=t("Auto-detected from the selected video. You can override manually."),
    )
    st.caption(t(_det_label))
    # ──────────────────────────────────────────────────────────

    if job_mode == "full":
        source_language_options = ["auto", *LANGUAGE_CONFIG.keys()]
        source_language = st.selectbox(
            t("Source Language"),
            source_language_options,
            index=0,
            format_func=lambda code: t("Auto Detect" if code == "auto" else LANGUAGE_CONFIG[code]["label"]),
            key="source_language",
        )
        target_language = st.selectbox(
            t("Target Language"),
            list(LANGUAGE_CONFIG.keys()),
            index=0,
            format_func=lambda code: t(LANGUAGE_CONFIG[code]["label"]),
            key="target_language",
        )
        model_size = st.selectbox(
            t("Whisper Model"),
            ["tiny", "base", "small", "medium", "large"],
            index=2,
            key="model_size",
        )
        st.caption(t("Smaller models are faster. Larger models are usually more accurate."))
        subtitle_mode = st.selectbox(
            t("Subtitle Mode"),
            [("single", "Single Language"), ("bilingual", "Bilingual (top/bottom)")],
            format_func=lambda item: t(item[1]),
            key="subtitle_mode",
        )[0]
        batch_size = st.slider(t("Batch Size"), min_value=1, max_value=20, value=10, key="batch_size")
        translation_workers = st.slider(
            t("Concurrent Translators"),
            min_value=1,
            max_value=10,
            value=3,
            key="translation_workers",
            help=t("Number of concurrent translation batches sent to the API. Higher is faster but may hit rate limits.")
        )
    else:
        # Burn-only mode: use sensible defaults, no UI needed for these
        source_language = "auto"
        target_language = "zh"
        model_size = "small"
        subtitle_mode = "single"
        batch_size = 10
        translation_workers = 3
    if job_mode == "full":
        render_mode = st.selectbox(
            t("Render Mode"),
            [("burned", "Burned Subtitle Video"), ("soft", "Soft Subtitle Video")],
            format_func=lambda item: t(item[1]),
            key="render_mode",
        )[0]
    else:
        # burn_only is inherently about re-burning subtitles; soft mode in this
        # context is contradictory and would produce a confusingly named output.
        render_mode = "burned"
    verbose = st.checkbox(t("Verbose Logs"), value=False, key="verbose")

    st.header(t("Subtitle Style"))

    st.selectbox(
        t("Style Preset"),
        list(STYLE_PRESETS.keys()),
        format_func=t,
        key="ui_style_preset",
        on_change=on_style_preset_change,
    )

    font_preset_options = [label for label, _ in FONT_PRESETS]
    font_preset = st.selectbox(
        t("Font Preset"),
        font_preset_options,
        format_func=t,
        key="ui_font_preset",
    )
    custom_font_name = ""
    if font_preset == "Custom":
        custom_font_name = st.text_input(t("Custom Font Name"), value="", key="custom_font_name")

    selected_font_name = next(
        (font_name for label, font_name in FONT_PRESETS if label == font_preset),
        "Noto Sans CJK SC",
    )
    resolved_font_name = (
        custom_font_name.strip() or "Noto Sans CJK SC"
        if font_preset == "Custom"
        else selected_font_name or "Noto Sans CJK SC"
    )

    font_size = st.slider(t("Font Size"), min_value=12, max_value=40, value=20, key="ui_font_size")
    text_color = st.color_picker(t("Text Color"), value="#FFFFFF", key="ui_text_color")
    outline_color = st.color_picker(t("Outline Color"), value="#000000", key="ui_outline_color")
    _is_portrait = st.session_state.get("ui_orientation", "Landscape (16:9)").startswith("Portrait")
    _margin_max = 1600 if _is_portrait else 900
    # Clamp the stored value so it never exceeds the current slider range
    _stored_margin = st.session_state.get("ui_bottom_margin", 80 if _is_portrait else 30)
    st.session_state["ui_bottom_margin"] = max(10, min(int(_stored_margin), _margin_max))
    bottom_margin = st.slider(
        t("Bottom Margin"),
        min_value=10,
        max_value=_margin_max,
        help=t("Pixels from the bottom of the video frame. Portrait mode allows larger values."),
        key="ui_bottom_margin",
    )


    st.caption(t("Style settings apply to burned subtitles. Soft subtitle appearance depends on the video player."))
    st.caption(t("Bilingual subtitles use the source text on top and the selected target language on the bottom."))
    st.caption(t("Auto Detect uses Whisper language detection."))
    st.caption(t("Manual source language is used as a hint and may be overridden if Whisper detects a different language."))
    st.caption(t("If source and target languages match, bilingual output is automatically downgraded to single-language subtitles."))
    st.caption(t("If source and target languages match, translation is skipped and the Whisper transcript is used directly."))
    st.caption(t("Available presets depend on fonts installed on your system. If a font is not installed, FFmpeg may fall back to another font."))

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
    render_progress()


def render_progress():
    stage = st.session_state.job_progress_stage
    detail = translate_detail(st.session_state.job_progress_detail, st.session_state.ui_language)
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
    label = t(stage_labels.get(stage, "Processing"))
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
    label = t(label)
    if not file_path.exists():
        st.warning(t("{label} file not found: {path}", label=label, path=path_value))
        return

    file_size = human_file_size(file_path.stat().st_size)
    st.markdown(f"**{label}**")
    st.write(t("Name:"), file_path.name)
    st.write(t("Size:"), file_size)
    st.code(str(file_path))

    with file_path.open("rb") as file_handle:
        st.download_button(
            label=t("Download {label}", label=label),
            data=file_handle.read(),
            file_name=file_path.name,
            mime=mime,
            key=f"download_{file_path}",
        )


def resolve_input_video_path(
    selected_input_source: str,
    uploaded_video,
    local_path_value: str,
) -> tuple[str | None, str | None]:
    if selected_input_source == "upload":
        if uploaded_video is None:
            return None, t("Upload a video first.")

        suffix = Path(uploaded_video.name).suffix.lower()
        if suffix not in SUPPORTED_VIDEO_EXTENSIONS:
            return None, t("Unsupported video format: {suffix}", suffix=suffix or t("unknown"))

        uploads_dir = Path(tempfile.gettempdir()) / "video_translate_tool_uploads"
        uploads_dir.mkdir(parents=True, exist_ok=True)
        input_path = uploads_dir / uploaded_video.name
        input_path.write_bytes(uploaded_video.getbuffer())
        return str(input_path), None

    raw_path = local_path_value.strip().strip('"').strip("'")
    if not raw_path:
        return None, t("Enter a local video path first.")

    try:
        resolved_path = Path(raw_path).expanduser().resolve()
    except OSError as exc:
        return None, t("Invalid local video path: {error}", error=exc)

    if not resolved_path.exists():
        return None, t("Local video file not found: {path}", path=resolved_path)
    if not resolved_path.is_file():
        return None, t("Local video path is not a file: {path}", path=resolved_path)
    if resolved_path.suffix.lower() not in SUPPORTED_VIDEO_EXTENSIONS:
        return None, t("Unsupported video format: {suffix}", suffix=resolved_path.suffix or t("unknown"))

    return str(resolved_path), None


def resolve_output_directory(
    selected_output_dir_source: str,
    manual_output_dir: str,
    selected_output_dir: str,
) -> tuple[str | None, str | None]:
    if selected_output_dir_source == "manual":
        raw_path = manual_output_dir.strip()
        if not raw_path:
            return None, t("Enter an output directory first.")
    else:
        raw_path = selected_output_dir.strip()
        if not raw_path:
            return None, t("Choose an output folder first.")

    try:
        resolved_path = Path(raw_path).expanduser().resolve()
    except OSError as exc:
        return None, t("Invalid output directory: {error}", error=exc)

    return str(resolved_path), None


def render_job_result():
    result = st.session_state.job_result
    if not result:
        return

    if result["success"]:
        result_placeholder.success(t("Completed"))
        output_video_path = Path(result["output_video"]).resolve() if result["output_video"] else None
        output_subtitle_path = Path(result["output_srt"]).resolve() if result["output_srt"] else None

        st.subheader(t("Outputs"))
        render_result_file("Video", str(output_video_path) if output_video_path else None, "video/mp4")
        render_result_file("Subtitle", str(output_subtitle_path) if output_subtitle_path else None, "application/x-subrip")
    else:
        result_placeholder.error(translate_detail(result["error"] or "Job failed", st.session_state.ui_language))


if st.session_state.job_logs:
    logs_placeholder.code("\n".join(st.session_state.job_logs), language="text")
render_progress()


if st.button(t("Start"), type="primary", key="start_job"):
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

    # Validate SRT for burn-only mode
    srt_error = None
    if job_mode == "burn_only":
        if not external_srt_path.strip():
            srt_error = t("Enter the path to your SRT file.")
        elif not Path(external_srt_path.strip()).exists():
            srt_error = t("SRT file not found: {path}", path=external_srt_path.strip())

    if input_error:
        result_placeholder.error(input_error)
    elif output_error:
        result_placeholder.error(output_error)
    elif srt_error:
        result_placeholder.error(srt_error)
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
            translation_workers=translation_workers,
            verbose=verbose,
            external_srt=external_srt_path.strip() or None,
            style=SubtitleStyle(
                font_name=resolved_font_name,
                font_size=font_size,
                margin_v=bottom_margin,
                outline=2,
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

# ── Subtitle style preview (below Start button) ───────────────────────────
if not st.session_state.job_result:
    _pv_font_size   = st.session_state.get("ui_font_size",     20)
    _pv_text_color  = st.session_state.get("ui_text_color",   "#FFFFFF")
    _pv_outline_col = st.session_state.get("ui_outline_color","#000000")
    _pv_outline_w   = 2
    _pv_margin      = st.session_state.get("ui_bottom_margin", 30)
    _pv_font_lbl    = st.session_state.get("ui_font_preset",  "Noto Sans CJK SC")
    _pv_font = next(
        (fn for lbl, fn in FONT_PRESETS if lbl == _pv_font_lbl and fn),
        "Noto Sans CJK SC",
    )
    _pv_s = max(0, _pv_outline_w)
    if _pv_s > 0:
        # 8-directional shadows give a proper full stroke outline (matches ASS subtitle rendering)
        _dirs = [
            (-_pv_s, -_pv_s), (0, -_pv_s), (_pv_s, -_pv_s),
            (-_pv_s,  0),                   (_pv_s,  0),
            (-_pv_s,  _pv_s), (0,  _pv_s), (_pv_s,  _pv_s),
        ]
        _shadow_parts = [f"{dx}px {dy}px 0 {_pv_outline_col}" for dx, dy in _dirs]
        _pv_shadow = ", ".join(_shadow_parts)
    else:
        _pv_shadow = "none"
    _pv_is_portrait = st.session_state.get("ui_orientation", "Landscape (16:9)").startswith("Portrait")
    _pv_aspect = "9 / 16" if _pv_is_portrait else "16 / 9"
    _pv_max_w  = "220px"  if _pv_is_portrait else "720px"
    # margin_v is pixels from the bottom of a 1080p (landscape) or 1920-tall
    # (portrait) frame; convert accurately to % for preview
    _ref_h = 1920 if _pv_is_portrait else 1080
    _pv_pad = max(1, round((_pv_margin / _ref_h) * 100))
    _pv_px  = _pv_font_size + 4
    st.markdown(t("#### 🎥 Subtitle Style Preview"))
    st.markdown(
        f"""
<div style="
  background: linear-gradient(160deg, #0d1117 60%, #1a2236);
  border-radius: 10px;
  aspect-ratio: {_pv_aspect};
  max-width: {_pv_max_w};
  position: relative;
  overflow: hidden;
  margin: 8px 0;
">
  <div style="
    position: absolute;
    bottom: {_pv_pad}%;
    left: 0;
    width: 100%;
    text-align: center;
    box-sizing: border-box;
    padding: 0 5%;
  ">
  <span style="
    color: {_pv_text_color};
    font-family: '{_pv_font}', 'Noto Sans CJK SC', sans-serif;
    font-size: {_pv_px}px;
    text-shadow: {_pv_shadow};
    line-height: 1.6;
  ">{t("Sample Subtitle Text")}</span>
  </div>
</div>""",
        unsafe_allow_html=True,
    )
    st.caption(
        t("Font: {font} · Size: {size} · Margin: {margin}px · Preview is approximate.",
          font=_pv_font, size=_pv_font_size, margin=_pv_margin)
    )
