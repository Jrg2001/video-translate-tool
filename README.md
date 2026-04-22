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

# Audio library required by openai-whisper
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

The Streamlit app supports two input modes:

- `Local File Path`
- `Upload File`

`Upload File` supports videos up to 2GB. For larger videos or normal local use, prefer `Local File Path`.

The Streamlit sidebar also supports two output directory modes:

- `Manual Path`
- `Browse Folder`

`Browse Folder` opens the local system folder picker. If the current environment does not support desktop dialogs, use `Manual Path`.

The Streamlit UI also supports Whisper model selection:

- `tiny`
- `base`
- `small`
- `medium`
- `large`

The default is `small`. Smaller models are faster, while larger models are usually more accurate.

The Streamlit UI displays stage progress for transcription, translation, subtitle writing, and video rendering. During FFmpeg rendering, the progress bar uses parsed FFmpeg progress output when available.

After a successful run, the Streamlit UI shows structured output details and provides download buttons for the generated video and subtitle files.

When using `Local File Path`, the path must point to an existing local video file on the current machine.

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
- Burned subtitle video output
- Soft subtitle video output
- Target language support for Chinese, English, Japanese, and Korean
