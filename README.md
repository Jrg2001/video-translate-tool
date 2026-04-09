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

## Supported Target Languages

- Chinese (Simplified)
- English
- Japanese
- Korean

The UI also supports `Source Language`, with `Auto Detect` as the default option.

Auto Detect uses Whisper language detection, while a manual source language selection overrides the detected result.

In bilingual mode, the first line stays as the source subtitle and the second line is translated into the selected target language.

If the source language matches the target language, bilingual output is automatically downgraded to single-language subtitles to avoid duplicate lines.

If the source language matches the target language, the translation step is skipped and the Whisper transcript is used directly to avoid unnecessary API cost.

Non-Chinese target languages use a simpler first-pass chunking strategy focused on stability and readable subtitle lengths.

Soft subtitle outputs write subtitle language metadata based on the selected target language.

## Subtitle Style In The UI

The Streamlit sidebar supports these subtitle style settings:

- Font preset
- Custom font name
- Font size
- Text color
- Outline color
- Outline width
- Bottom margin

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
