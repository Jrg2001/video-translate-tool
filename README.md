# video-translate-tool

Local video processing tool for transcription, translation, subtitle generation, and subtitle rendering.

## Install

```bash
pip install -r requirements.txt
```

FFmpeg must be available in your system `PATH`.

Create a local `.env` file:

```env
DEEPSEEK_API_KEY=your_api_key_here
```

## Linux Deployment

### System Dependencies

```bash
# FFmpeg and ffprobe
sudo apt install -y ffmpeg

# CJK fonts for burned subtitle rendering
sudo apt install -y fonts-noto-cjk

# Audio decoding library
sudo apt install -y libsndfile1
```

### Option A: Direct Deployment (single server / LAN)

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
# Fill in DEEPSEEK_API_KEY

streamlit run app.py --server.port 8501 --server.address 0.0.0.0
```

To run as a persistent background service, copy `video-translate.service` to `/etc/systemd/system/`, edit the `User` and `WorkingDirectory` fields, then:

```bash
sudo systemctl daemon-reload
sudo systemctl enable video-translate
sudo systemctl start video-translate
```

### Option B: Docker (recommended for production)

```bash
cp .env.example .env
# Fill in DEEPSEEK_API_KEY

docker compose up -d
```

The app will be available at `http://<server-ip>:8501`.

Output files are persisted to `./outputs/` on the host. Whisper model weights are cached in a named Docker volume so they survive container restarts.

## Run The Script

```powershell
python transfer_video_burn.py
```

The default script example writes outputs to `D:\transfer\outputs`.

## Run The Streamlit App

```powershell
streamlit run app.py
```

## Job Modes

The sidebar **Job Mode** selector offers two operating modes:

### Full Pipeline (Transcribe → Translate → Burn)

The default mode. Runs the complete pipeline end-to-end:

1. **Transcribe** — Whisper extracts speech and word-level timestamps from the video audio.
2. **Translate** — DeepSeek translates subtitle segments in concurrent batches.
3. **Write SRT** — Subtitles are split into timed chunks and written to a `.srt` file.
4. **Burn** — FFmpeg renders the subtitled video (GPU-accelerated when NVENC is available).

### Burn Existing SRT

Skips transcription and translation entirely. Use this after editing a generated `.srt` file to re-render the video without re-running the pipeline. The total render time is typically under 10 seconds.

**Workflow:**
1. Run **Full Pipeline** to generate the initial `.srt` and video.
2. Open the `.srt` file in any text editor and make corrections.
3. Switch **Job Mode** to **Burn Existing SRT**. The SRT path is pre-filled from the previous run.
4. Click **Start** — FFmpeg re-renders the video using the edited subtitles.

## Input / Output

The Streamlit app supports two input modes:

- `Local File Path`
- `Upload File`

`Upload File` supports videos up to 2GB. For larger videos or normal local use, prefer `Local File Path`.

The sidebar supports two output directory modes:

- `Manual Path`
- `Browse Folder`

`Browse Folder` opens the local system folder picker. If the current environment does not support desktop dialogs, use `Manual Path`.

## GPU Acceleration

### Whisper Transcription

`faster-whisper` is used for transcription. It uses CTranslate2 as its inference engine and does not require PyTorch. When a CUDA-capable GPU is detected at startup, the model runs in `float16` mode. On CPU, it uses `int8` quantization, which is still significantly faster than the original `openai-whisper`.

### FFmpeg Video Rendering

The burn step automatically detects whether the local FFmpeg build supports `h264_nvenc` (NVIDIA hardware encoder). If available, NVENC is used for GPU-accelerated rendering. Otherwise, it falls back to `libx264` (CPU).

Typical render times for a 2-minute video:

| Encoder | Time |
|---|---|
| `libx264` (CPU) | ~36 seconds |
| `h264_nvenc` (GPU) | ~5 seconds |

## Translation Settings

### Whisper Model

| Model | Speed | Accuracy |
|---|---|---|
| `tiny` | Fastest | Lowest |
| `base` | Fast | Low |
| `small` | Balanced (default) | Good |
| `medium` | Slow | Better |
| `large` | Slowest | Best |

### Concurrent Translators

Controls the number of translation batches sent to the DeepSeek API simultaneously. The default is `3`. Higher values reduce translation time for longer videos but may trigger API rate limits.

### Batch Size

Number of subtitle segments per translation request. Default is `10`.

## Supported Target Languages

- Chinese (Simplified)
- English
- Japanese
- Korean

The UI also supports `Source Language`, with `Auto Detect` as the default option.

Auto Detect uses Whisper language detection.

A manual source language selection is treated as a hint for Whisper. If the manual value conflicts with Whisper's detected language, the detected result is used for downstream logic.

In bilingual mode, the first line stays as the source subtitle and the second line is translated into the selected target language.

If the source language matches the target language, bilingual output is automatically downgraded to single-language subtitles to avoid duplicate lines.

If the source language matches the target language, the translation step is skipped and the Whisper transcript is used directly to avoid unnecessary API cost.

Non-Chinese target languages use a simpler first-pass chunking strategy focused on stability and readable subtitle lengths.

Soft subtitle outputs write subtitle language metadata based on the selected target language.

## Subtitle Style In The UI

The Streamlit sidebar supports these subtitle style settings:

- Style preset (Netflix, YouTube, Bilibili, Classic Film, Custom)
- Font preset
- Custom font name
- Font size
- Text color
- Outline color
- Bottom margin
- Video orientation (Auto-detects Landscape 16:9 / Portrait 9:16)
- Real-time subtitle style preview panel

These settings are applied to burned subtitles. Soft subtitle appearance depends on the video player.

Bilingual subtitles currently use the same style for both the source line and the translated line.

If the selected font is not installed on the system, FFmpeg may fall back to a different font.

The UI provides common font presets for multilingual subtitle use, while still allowing a custom font name when needed.

## Features

- Single-language subtitles
- Bilingual subtitles with source text on top and translated text below
- Burned subtitle video output (GPU-accelerated via NVENC when available)
- Soft subtitle video output
- Target language support for Chinese, English, Japanese, and Korean
- faster-whisper transcription with automatic GPU/CPU selection
- Concurrent batch translation to reduce API wait time
- Burn-only mode for re-rendering with an edited SRT without re-running the full pipeline

## Known Issues

### Docker GPU Acceleration

The provided `Dockerfile` uses a lightweight base image (`python:3.11-slim`) that does not include a CUDA runtime. Whisper transcription and FFmpeg NVENC encoding will run on CPU inside the container.

To enable GPU acceleration in Docker, replace the base image with an appropriate `nvidia/cuda` image and ensure NVIDIA Container Toolkit is installed on the host. Run the container with `--gpus all`.

This is a planned enhancement for environments with NVIDIA GPU servers.
