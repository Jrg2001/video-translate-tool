"""Interface translations, independent of subtitle source/target languages."""

import re


ZH_CN = {
    "Video Translate Tool": "视频字幕翻译工具",
    "Local video translation with single or bilingual subtitle output.": "本地视频转写与翻译，支持单语和双语字幕输出。",
    "Job Settings": "任务设置",
    "Job Mode": "任务模式",
    "Full Pipeline (Transcribe → Translate → Burn)": "完整流程（转写 → 翻译 → 生成视频）",
    "Burn Existing SRT": "使用已有 SRT 烧录字幕",
    "Input Source": "视频来源",
    "Local File Path": "本地文件路径",
    "Upload File": "上传文件",
    "Upload Video": "上传视频",
    "Local Video Path": "本地视频路径",
    "Existing SRT File Path": "已有 SRT 字幕路径",
    "Path to the .srt subtitle file you want to burn into the video. Edit it first with any text editor, then come back here.": "填写需要烧录到视频中的 .srt 文件路径。可以先用文本编辑器修改字幕，再返回此处生成视频。",
    "Output Directory Source": "输出目录选择方式",
    "Manual Path": "手动输入路径",
    "Browse Folder": "浏览文件夹",
    "Output Directory": "输出目录",
    "Selected Output Directory": "已选输出目录",
    "Browse Folder opens the local system folder picker.": "点击“浏览文件夹”会打开本机的文件夹选择窗口。",
    "If folder browsing is unavailable in the current environment, use Manual Path instead.": "如果当前环境无法浏览文件夹，请手动输入路径。",
    "Folder picker is unavailable in the current environment. Use Manual Path instead.": "当前环境无法打开文件夹选择窗口，请手动输入路径。",
    "Upload File supports videos up to 2GB.": "支持上传最大 2GB 的视频。",
    "For larger files or local use, choose Local File Path.": "处理更大的文件或使用本机视频时，请选择“本地文件路径”。",
    "🔍 Auto-detected: Portrait (9:16)": "🔍 自动检测：竖屏（9:16）",
    "🔍 Auto-detected: Landscape (16:9)": "🔍 自动检测：横屏（16:9）",
    "🔍 No video selected—defaulting to Landscape": "🔍 尚未选择视频，默认使用横屏",
    "Video Orientation": "视频方向",
    "Landscape (16:9)": "横屏（16:9）",
    "Portrait (9:16)": "竖屏（9:16）",
    "Auto-detected from the selected video. You can override manually.": "根据所选视频自动检测，也可以手动调整。",
    "Source Language": "视频源语言",
    "Target Language": "字幕目标语言",
    "Auto Detect": "自动识别",
    "Chinese (Simplified)": "简体中文",
    "English": "英语",
    "Japanese": "日语",
    "Korean": "韩语",
    "Whisper Model": "Whisper 模型",
    "Smaller models are faster. Larger models are usually more accurate.": "较小的模型速度更快，较大的模型通常识别更准确。",
    "Subtitle Mode": "字幕模式",
    "Single Language": "单语字幕",
    "Bilingual (top/bottom)": "双语字幕（上下排列）",
    "Batch Size": "每批翻译条数",
    "Concurrent Translators": "翻译并发数",
    "Number of concurrent translation batches sent to the API. Higher is faster but may hit rate limits.": "同时发送的翻译批次数。提高并发数可以加快翻译，但可能触发接口限流。",
    "Render Mode": "视频输出方式",
    "Burned Subtitle Video": "硬字幕视频（字幕嵌入画面）",
    "Soft Subtitle Video": "软字幕视频（独立字幕轨道）",
    "Verbose Logs": "显示详细日志",
    "Subtitle Style": "字幕样式",
    "Style Preset": "样式预设",
    "Custom": "自定义",
    "Classic Film": "经典电影",
    "Bilibili": "哔哩哔哩",
    "Font Preset": "字体预设",
    "Custom Font Name": "自定义字体名称",
    "Font Size": "字体大小",
    "Text Color": "文字颜色",
    "Outline Color": "描边颜色",
    "Bottom Margin": "底部边距",
    "Pixels from the bottom of the video frame. Portrait mode allows larger values.": "字幕距视频画面底部的距离（像素）。竖屏模式支持更大的数值。",
    "Style settings apply to burned subtitles. Soft subtitle appearance depends on the video player.": "样式设置应用于硬字幕；软字幕的外观由视频播放器决定。",
    "Bilingual subtitles use the source text on top and the selected target language on the bottom.": "双语字幕上方显示原文，下方显示所选目标语言的译文。",
    "Auto Detect uses Whisper language detection.": "自动识别使用 Whisper 的语言检测功能。",
    "Manual source language is used as a hint and may be overridden if Whisper detects a different language.": "手动源语言作为识别提示；若 Whisper 返回不同语言，后续处理将使用返回结果。",
    "If source and target languages match, bilingual output is automatically downgraded to single-language subtitles.": "如果源语言与目标语言相同，将自动输出单语字幕，避免重复。",
    "If source and target languages match, translation is skipped and the Whisper transcript is used directly.": "如果源语言与目标语言相同，将跳过翻译，直接使用转写文本。",
    "Available presets depend on fonts installed on your system. If a font is not installed, FFmpeg may fall back to another font.": "字体预设依赖本机已安装的字体。缺少所选字体时，FFmpeg 可能使用其他字体。",
    "Preparing job": "正在准备任务",
    "Step 1/4: Transcribing audio": "第 1/4 步：转写语音",
    "Step 2/4: Translating subtitles": "第 2/4 步：翻译字幕",
    "Step 3/4: Writing subtitle file": "第 3/4 步：生成字幕文件",
    "Step 4/4: Rendering video": "第 4/4 步：生成视频",
    "Completed": "已完成",
    "Failed": "失败",
    "Processing": "处理中",
    "Name:": "文件名：",
    "Size:": "文件大小：",
    "Download {label}": "下载{label}",
    "{label} file not found: {path}": "找不到{label}文件：{path}",
    "Upload a video first.": "请先上传视频。",
    "Unsupported video format: {suffix}": "不支持的视频格式：{suffix}",
    "unknown": "未知",
    "Enter a local video path first.": "请先填写本地视频路径。",
    "Invalid local video path: {error}": "本地视频路径无效：{error}",
    "Local video file not found: {path}": "找不到本地视频文件：{path}",
    "Local video path is not a file: {path}": "本地视频路径不是文件：{path}",
    "Enter an output directory first.": "请先填写输出目录。",
    "Choose an output folder first.": "请先选择输出文件夹。",
    "Invalid output directory: {error}": "输出目录无效：{error}",
    "Outputs": "输出文件",
    "Video": "视频",
    "Subtitle": "字幕",
    "Job failed": "任务失败",
    "Start": "开始处理",
    "Enter the path to your SRT file.": "请填写 SRT 字幕文件路径。",
    "SRT file not found: {path}": "找不到 SRT 字幕文件：{path}",
    "#### 🎥 Subtitle Style Preview": "#### 🎥 字幕样式预览",
    "Sample Subtitle Text": "字幕效果预览示例",
    "Font: {font} · Size: {size} · Margin: {margin}px · Preview is approximate.": "字体：{font} · 字号：{size} · 边距：{margin}px · 预览仅供参考。",
    "Loading Whisper and transcribing audio": "正在加载 Whisper 并转写语音",
    "Translation skipped": "已跳过翻译",
    "No segments": "未检测到语音片段",
    "Translation complete": "翻译完成",
    "Writing subtitle file": "正在生成字幕文件",
    "Subtitle file ready": "字幕文件已生成",
    "Starting FFmpeg": "正在启动 FFmpeg",
    "Video output ready": "视频已生成",
    "Preparing burn-only job": "正在准备已有字幕烧录任务",
    "Using existing SRT": "正在使用已有 SRT 字幕",
    "Missing DEEPSEEK_API_KEY. Configure it in the local .env file.": "缺少 DEEPSEEK_API_KEY，请在本地 .env 文件中配置。",
}


def translate(message: str, language: str = "zh", **values) -> str:
    """Translate owned UI text; preserve file names and user-supplied values."""
    text = ZH_CN.get(message, message) if language == "zh" else message
    return text.format(**values) if values else text


def translate_detail(message: str, language: str = "zh") -> str:
    """Translate stored progress details at display time, keeping diagnostics intact."""
    if language != "zh":
        return message
    if message in ZH_CN:
        return ZH_CN[message]
    patterns = (
        (r"(\d+) segments", lambda m: f"已识别 {m[1]} 个片段"),
        (r"Batch (\d+)/(\d+)", lambda m: f"翻译批次 {m[1]}/{m[2]}"),
        (r"Target language: (.+)", lambda m: f"目标语言：{translate(m[1], language)}"),
        (r"Rendering video \((\d+)%\)", lambda m: f"正在生成视频（{m[1]}%）"),
        (r"SRT file not found: (.+)", lambda m: f"找不到 SRT 字幕文件：{m[1]}"),
    )
    for pattern, render in patterns:
        match = re.fullmatch(pattern, message)
        if match:
            return render(match)
    return message
