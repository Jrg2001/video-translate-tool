# video-translate-tool

Local video processing tool for transcription, translation, subtitle generation, and subtitle rendering.

## Install

```powershell
pip install -r requirements.txt
```

FFmpeg must be available in your system `PATH`.

Create a local `.env` file:

```env
DEEPSEEK_API_KEY=your_api_key_here
```

## Run The Script

```powershell
python transfer_video_burn.py
```

The default script example writes outputs to `D:\transfer\outputs`.

## Run The Streamlit App

```powershell
streamlit run app.py
```

In the Streamlit sidebar, set `Output Directory` to a folder such as `D:\transfer\outputs` or `D:\`.

## Subtitle Style In The UI

The Streamlit sidebar supports these subtitle style settings:

- Font name
- Font size
- Text color
- Outline color
- Outline width
- Bottom margin

These settings are applied to burned subtitles. Soft subtitle appearance depends on the video player.

Bilingual subtitles currently use the same style for both the source line and the translated line.

If the selected font is not installed on the system, FFmpeg may fall back to a different font.

## Features

- Single-language subtitles
- Bilingual subtitles with source text on top and translated text below
- Burned subtitle video output
- Soft subtitle video output
