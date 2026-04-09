import json
import os
import re
import subprocess
from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path
from typing import Callable, Optional

import jieba
import whisper
from openai import OpenAI


def load_env_file(env_path=".env"):
    if not os.path.exists(env_path):
        return

    with open(env_path, "r", encoding="utf-8") as env_file:
        for raw_line in env_file:
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue

            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip())


def hex_to_ass_colour(hex_color: str, default: str) -> str:
    if not isinstance(hex_color, str):
        return default

    cleaned = hex_color.strip()
    if not re.fullmatch(r"#[0-9A-Fa-f]{6}", cleaned):
        return default

    red = cleaned[1:3]
    green = cleaned[3:5]
    blue = cleaned[5:7]
    return f"&H00{blue.upper()}{green.upper()}{red.upper()}"


@dataclass
class SubtitleStyle:
    font_name: str = "Microsoft YaHei"
    font_size: int = 20
    margin_v: int = 30
    outline: int = 2
    primary_colour: str = "&H00FFFFFF"
    outline_colour: str = "&H00000000"


@dataclass
class SubtitleJobConfig:
    input_video: str
    target_language: str = "zh"
    subtitle_mode: str = "bilingual"
    render_mode: str = "burned"
    output_dir: Optional[str] = None
    batch_size: int = 10
    verbose: bool = False
    ffmpeg_exe: str = "ffmpeg"
    model_size: str = "small"
    style: SubtitleStyle = field(default_factory=SubtitleStyle)


@dataclass
class SubtitleJobResult:
    output_video: Optional[str]
    output_srt: Optional[str]
    logs: list[str]
    success: bool
    error: Optional[str] = None


class SubtitlePipeline:
    def __init__(self, config: SubtitleJobConfig, log_hook: Optional[Callable[[str], None]] = None):
        load_env_file()

        self.config = config
        self.log_hook = log_hook
        self.logs: list[str] = []

        api_key = os.getenv("DEEPSEEK_API_KEY")
        if not api_key:
            raise ValueError("Missing DEEPSEEK_API_KEY. Configure it in the local .env file.")

        self.client = OpenAI(
            api_key=api_key,
            base_url="https://api.deepseek.com/v1",
        )
        self.whisper_model = whisper.load_model(config.model_size)
        self.config.style = self._sanitize_style(config.style)
        self.input_path = Path(config.input_video).resolve()
        self.output_video = self._build_output_video_path()
        self.output_srt = self._build_output_srt_path()

    def _log(self, message: str):
        self.logs.append(message)
        if self.log_hook:
            self.log_hook(message)

    def _build_output_video_path(self) -> str:
        output_dir = self._resolve_output_dir()
        suffix = f"_{self.config.target_language}"
        if self.config.subtitle_mode == "bilingual":
            suffix += "_bilingual"

        if self.config.render_mode == "burned":
            output_name = f"{self.input_path.stem}{suffix}_burn.mp4"
        else:
            output_name = f"{self.input_path.stem}{suffix}.mkv"
        return str(output_dir / output_name)

    def _build_output_srt_path(self) -> str:
        output_dir = self._resolve_output_dir()
        suffix = f"_{self.config.target_language}"
        if self.config.subtitle_mode == "bilingual":
            suffix += "_bilingual"
        output_name = f"{self.input_path.stem}{suffix}.srt"
        return str(output_dir / output_name)

    def _resolve_output_dir(self) -> Path:
        if self.config.output_dir:
            output_dir = Path(self.config.output_dir).expanduser().resolve()
        else:
            output_dir = self.input_path.parent
        output_dir.mkdir(parents=True, exist_ok=True)
        return output_dir

    def _format_timestamp(self, seconds: float) -> str:
        td = timedelta(seconds=seconds)
        total_seconds = int(td.total_seconds())
        hours, remainder = divmod(total_seconds, 3600)
        minutes, secs = divmod(remainder, 60)
        milliseconds = int((seconds - total_seconds) * 1000)
        return f"{hours:02d}:{minutes:02d}:{secs:02d},{milliseconds:03d}"

    def _sanitize_style(self, style: SubtitleStyle) -> SubtitleStyle:
        font_name = style.font_name.strip() or "Microsoft YaHei"
        font_size = min(max(int(style.font_size), 12), 40)
        margin_v = min(max(int(style.margin_v), 10), 120)
        outline = min(max(int(style.outline), 0), 6)
        primary_colour = (
            style.primary_colour
            if re.fullmatch(r"&H[0-9A-Fa-f]{8}", style.primary_colour or "")
            else "&H00FFFFFF"
        )
        outline_colour = (
            style.outline_colour
            if re.fullmatch(r"&H[0-9A-Fa-f]{8}", style.outline_colour or "")
            else "&H00000000"
        )
        return SubtitleStyle(
            font_name=font_name,
            font_size=font_size,
            margin_v=margin_v,
            outline=outline,
            primary_colour=primary_colour.upper(),
            outline_colour=outline_colour.upper(),
        )

    def _normalize_text(self, text: str) -> str:
        return " ".join(text.strip().split())

    def _summarize_text(self, text: str, max_length: int = 50) -> str:
        normalized = self._normalize_text(text)
        if len(normalized) <= max_length:
            return normalized
        return normalized[: max_length - 3] + "..."

    def _tokenize_target_text(self, text: str) -> list[str]:
        return [token.strip() for token in jieba.lcut(text, cut_all=False) if token.strip()]

    def _join_source_words(self, words: list[str]) -> str:
        joined = " ".join(word for word in words if word)
        joined = re.sub(r"\s+([,.!?;:])", r"\1", joined)
        return joined.strip()

    def _group_translation_tokens(self, tokens: list[str], target_chars=14, max_chars=18) -> list[str]:
        chunks: list[str] = []
        current_tokens: list[str] = []
        current_length = 0
        punctuation_tokens = {"，", "。", "；", "！", "？", "、", "："}

        for token in tokens:
            token_length = len(token)

            if current_tokens and current_length + token_length > max_chars:
                chunks.append("".join(current_tokens))
                current_tokens = [token]
                current_length = token_length
                continue

            current_tokens.append(token)
            current_length += token_length

            if current_length >= target_chars and token in punctuation_tokens:
                chunks.append("".join(current_tokens))
                current_tokens = []
                current_length = 0

        if current_tokens:
            chunks.append("".join(current_tokens))

        merged_chunks: list[str] = []
        for chunk in chunks:
            if merged_chunks and len(chunk) < 4:
                merged_chunks[-1] += chunk
            else:
                merged_chunks.append(chunk)

        if len(merged_chunks) >= 2 and len(merged_chunks[-1]) < 4:
            merged_chunks[-2] += merged_chunks[-1]
            merged_chunks.pop()

        return [chunk for chunk in merged_chunks if chunk]

    def _compute_word_boundaries(self, total_words: int, chunk_texts: list[str]) -> list[int]:
        if total_words <= 0:
            return [0, 0]

        total_chars = sum(len(text) for text in chunk_texts)
        boundaries = [0]
        consumed_chars = 0

        for text in chunk_texts[:-1]:
            consumed_chars += len(text)
            ratio = consumed_chars / total_chars if total_chars else 0
            boundary = round(ratio * total_words)
            boundary = max(boundaries[-1] + 1, boundary)
            boundary = min(boundary, total_words - (len(chunk_texts) - len(boundaries)))
            boundaries.append(boundary)

        boundaries.append(total_words)
        return boundaries

    def _assign_chunk_timestamps(self, segment: dict, chunk_texts: list[str]) -> list[tuple[float, float]]:
        if not chunk_texts:
            return []

        segment_start = segment["start"]
        segment_end = segment["end"]
        duration = max(segment_end - segment_start, 0.01)
        words = segment.get("words") or []

        if len(chunk_texts) == 1:
            return [(segment_start, segment_end)]

        if not words:
            total_chars = sum(len(text) for text in chunk_texts)
            current_start = segment_start
            ranges: list[tuple[float, float]] = []
            for index, text in enumerate(chunk_texts):
                if index == len(chunk_texts) - 1:
                    current_end = segment_end
                else:
                    ratio = len(text) / total_chars if total_chars else 1 / len(chunk_texts)
                    current_end = current_start + duration * ratio
                ranges.append((current_start, current_end))
                current_start = current_end
            return ranges

        boundaries = self._compute_word_boundaries(len(words), chunk_texts)
        ranges: list[tuple[float, float]] = []
        for index in range(len(chunk_texts)):
            start_word_index = boundaries[index]
            end_word_index = boundaries[index + 1] - 1
            start_time = words[start_word_index].get("start", segment_start)
            end_time = words[end_word_index].get("end", segment_end)
            ranges.append((start_time, end_time))

        adjusted_ranges: list[tuple[float, float]] = []
        min_duration = 0.8
        for index, (start_time, end_time) in enumerate(ranges):
            start_time = max(start_time, segment_start)
            end_time = min(end_time, segment_end)
            if index > 0:
                start_time = max(start_time, adjusted_ranges[-1][1])
            if end_time <= start_time:
                end_time = min(segment_end, start_time + 0.05)
            adjusted_ranges.append((start_time, end_time))

        if duration >= len(adjusted_ranges) * min_duration:
            for index in range(len(adjusted_ranges) - 1):
                start_time, end_time = adjusted_ranges[index]
                if end_time - start_time < min_duration:
                    new_end = min(segment_end, start_time + min_duration)
                    adjusted_ranges[index] = (start_time, new_end)
                    next_start, next_end = adjusted_ranges[index + 1]
                    adjusted_ranges[index + 1] = (max(new_end, next_start), next_end)

        adjusted_ranges[-1] = (adjusted_ranges[-1][0], segment_end)
        return adjusted_ranges

    def transcribe(self) -> list[dict]:
        self._log("[Step 1/4] Transcribing audio with Whisper...")
        result = self.whisper_model.transcribe(
            str(self.input_path),
            task="transcribe",
            word_timestamps=True,
        )
        segments = result["segments"]
        self._log(f" -> Transcription complete: {len(segments)} segments")
        return segments

    def _parse_batch_translation(self, content: str) -> list:
        cleaned = content.strip()
        if cleaned.startswith("```"):
            lines = cleaned.splitlines()
            if lines and lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            cleaned = "\n".join(lines).strip()

        parsed = json.loads(cleaned)
        if not isinstance(parsed, list):
            raise ValueError("Batch translation format error: result is not a JSON array.")
        return parsed

    def _translate_single(self, text: str) -> str:
        response = self.client.chat.completions.create(
            model="deepseek-chat",
            messages=[
                {
                    "role": "system",
                    "content": "You are a video subtitle translator. Translate the text into natural Simplified Chinese and return only the translation.",
                },
                {"role": "user", "content": text.strip()},
            ],
            temperature=0.3,
        )
        return response.choices[0].message.content.strip()

    def _translate_batch(self, batch_segments: list[dict]) -> dict:
        batch_items = [
            {"id": index, "text": segment["text"].strip()}
            for index, segment in enumerate(batch_segments)
        ]
        payload = json.dumps(batch_items, ensure_ascii=False)

        response = self.client.chat.completions.create(
            model="deepseek-chat",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a video subtitle translator. "
                        "Translate each JSON object item into natural Simplified Chinese. "
                        "Each object contains id and text. "
                        "Return a JSON object array with id and translation for every item. "
                        "Do not omit items. Do not return Markdown, code fences, or explanations."
                    ),
                },
                {"role": "user", "content": payload},
            ],
            temperature=0.3,
        )
        parsed_items = self._parse_batch_translation(response.choices[0].message.content)

        translation_map = {}
        for item in parsed_items:
            if not isinstance(item, dict):
                continue
            item_id = item.get("id")
            translation = item.get("translation")
            if isinstance(item_id, int) and isinstance(translation, str):
                translation_map[item_id] = translation.strip()

        translations = []
        missing_ids = []
        for index, segment in enumerate(batch_segments):
            translated_text = translation_map.get(index)
            if translated_text:
                translations.append(translated_text)
            else:
                missing_ids.append(index)
                translations.append(None)

        for index in missing_ids:
            translations[index] = self._translate_single(batch_segments[index]["text"])

        return {"translations": translations, "missing_ids": missing_ids}

    def translate(self, segments: list[dict]) -> list[dict]:
        self._log("[Step 2/4] Translating subtitles in batches...")
        translated_segments: list[dict] = []
        total_segments = len(segments)
        total_batches = (total_segments + self.config.batch_size - 1) // self.config.batch_size

        for batch_index, start in enumerate(range(0, total_segments, self.config.batch_size), start=1):
            batch_segments = segments[start:start + self.config.batch_size]
            batch_start = start + 1
            batch_end = start + len(batch_segments)
            self._log(
                f" -> Batch {batch_index}/{total_batches}: segments {batch_start}-{batch_end} ({len(batch_segments)} items)"
            )

            batch_result = self._translate_batch(batch_segments)
            translations = batch_result["translations"]
            missing_ids = batch_result["missing_ids"]

            if missing_ids:
                missing_sentence_numbers = [start + missing_id + 1 for missing_id in missing_ids]
                self._log(
                    f" -> Batch {batch_index} missed {len(missing_ids)} items, fallback to single translation for segments {', '.join(str(num) for num in missing_sentence_numbers)}"
                )
                for missing_id, sentence_number in zip(missing_ids, missing_sentence_numbers):
                    original_text = batch_segments[missing_id]["text"]
                    summary = original_text.strip() if self.config.verbose else self._summarize_text(original_text)
                    self._log(f" -> Fallback segment {sentence_number}: {summary}")

            for segment, translated_text in zip(batch_segments, translations):
                translated_segments.append(
                    {
                        "start": segment["start"],
                        "end": segment["end"],
                        "source_text": self._normalize_text(segment["text"]),
                        "translated_text": self._normalize_text(translated_text),
                        "words": segment.get("words", []),
                    }
                )

            self._log(
                f" -> Batch {batch_index}/{total_batches} complete, processed {len(translated_segments)}/{total_segments} segments"
            )

            if self.config.verbose:
                for segment, translated_text in zip(batch_segments, translations):
                    self._log(f'    {segment["text"]} >>> {translated_text}')

        return translated_segments

    def _split_translated_segment(self, segment: dict) -> list[dict]:
        source_text = self._normalize_text(segment["source_text"])
        translated_text = self._normalize_text(segment["translated_text"])
        tokens = self._tokenize_target_text(translated_text)
        chunk_texts = self._group_translation_tokens(tokens)

        if not chunk_texts:
            return [
                {
                    "start": segment["start"],
                    "end": segment["end"],
                    "text": translated_text,
                }
            ]

        time_ranges = self._assign_chunk_timestamps(segment, chunk_texts)
        subtitle_chunks = []
        for chunk_text, (start_time, end_time) in zip(chunk_texts, time_ranges):
            subtitle_chunks.append({"start": start_time, "end": end_time, "text": chunk_text})
        return subtitle_chunks

    def _split_bilingual_segment(self, segment: dict) -> list[dict]:
        source_text = self._normalize_text(segment["source_text"])
        translated_text = self._normalize_text(segment["translated_text"])
        translated_tokens = self._tokenize_target_text(translated_text)
        translated_chunk_texts = self._group_translation_tokens(translated_tokens)

        if not translated_chunk_texts:
            return [
                {
                    "start": segment["start"],
                    "end": segment["end"],
                    "source_text": source_text,
                    "translated_text": translated_text,
                }
            ]

        time_ranges = self._assign_chunk_timestamps(segment, translated_chunk_texts)
        words = segment.get("words") or []

        if words:
            source_tokens = [self._normalize_text(word.get("word", "")) for word in words if self._normalize_text(word.get("word", ""))]
            boundaries = self._compute_word_boundaries(len(source_tokens), translated_chunk_texts)
            source_chunk_texts = []
            for index in range(len(translated_chunk_texts)):
                chunk_words = source_tokens[boundaries[index]:boundaries[index + 1]]
                source_chunk_texts.append(self._join_source_words(chunk_words) or source_text)
        else:
            source_words = source_text.split()
            if source_words:
                boundaries = self._compute_word_boundaries(len(source_words), translated_chunk_texts)
                source_chunk_texts = []
                for index in range(len(translated_chunk_texts)):
                    chunk_words = source_words[boundaries[index]:boundaries[index + 1]]
                    source_chunk_texts.append(self._join_source_words(chunk_words) or source_text)
            else:
                source_chunk_texts = [source_text] * len(translated_chunk_texts)

        bilingual_chunks = []
        for source_chunk_text, translated_chunk_text, (start_time, end_time) in zip(
            source_chunk_texts, translated_chunk_texts, time_ranges
        ):
            bilingual_chunks.append(
                {
                    "start": start_time,
                    "end": end_time,
                    "source_text": self._normalize_text(source_chunk_text),
                    "translated_text": translated_chunk_text,
                }
            )
        return bilingual_chunks

    def build_subtitle_chunks(self, translated_segments: list[dict]) -> list[dict]:
        subtitle_chunks: list[dict] = []
        for segment in translated_segments:
            if self.config.subtitle_mode == "bilingual":
                subtitle_chunks.extend(self._split_bilingual_segment(segment))
            else:
                subtitle_chunks.extend(self._split_translated_segment(segment))
        return subtitle_chunks

    def write_srt(self, subtitle_chunks: list[dict]) -> str:
        self._log("[Step 3/4] Writing subtitle file...")
        with open(self.output_srt, "w", encoding="utf-8") as subtitle_file:
            for index, chunk in enumerate(subtitle_chunks, start=1):
                if self.config.subtitle_mode == "bilingual":
                    text = f'{chunk["source_text"]}\n{chunk["translated_text"]}'
                else:
                    text = chunk["text"]

                subtitle_file.write(f"{index}\n")
                subtitle_file.write(f'{self._format_timestamp(chunk["start"])} --> {self._format_timestamp(chunk["end"])}\n')
                subtitle_file.write(f"{text}\n\n")

        self._log(f" -> Subtitle file written: {self.output_srt}")
        return self.output_srt

    def _subtitle_style_string(self) -> str:
        style = self.config.style
        return (
            f"FontName={style.font_name},"
            f"FontSize={style.font_size},"
            f"PrimaryColour={style.primary_colour},"
            f"OutlineColour={style.outline_colour},"
            f"Outline={style.outline},"
            f"MarginV={style.margin_v}"
        )

    def render_video(self) -> str:
        if self.config.render_mode == "soft":
            self._log("[Step 4/4] Muxing soft subtitles into video...")
            command = [
                self.config.ffmpeg_exe,
                "-loglevel", "warning",
                "-y",
                "-i", str(self.input_path),
                "-i", self.output_srt,
                "-c", "copy",
                "-c:s", "srt",
                "-metadata:s:s:0", "language=chi",
                self.output_video,
            ]
        else:
            self._log("[Step 4/4] Burning subtitles into video...")
            subtitle_path = os.path.abspath(self.output_srt).replace("\\", "/").replace(":", "\\:")
            subtitle_filter = (
                f"subtitles='{subtitle_path}':force_style='{self._subtitle_style_string()}'"
            )
            command = [
                self.config.ffmpeg_exe,
                "-loglevel", "warning",
                "-y",
                "-i", str(self.input_path),
                "-vf", subtitle_filter,
                "-c:v", "libx264",
                "-crf", "18",
                "-preset", "medium",
                "-c:a", "copy",
                self.output_video,
            ]

        subprocess.run(command, check=True)
        self._log(f" -> Video output ready: {self.output_video}")
        return self.output_video

    def run(self) -> SubtitleJobResult:
        try:
            segments = self.transcribe()
            translated_segments = self.translate(segments)
            subtitle_chunks = self.build_subtitle_chunks(translated_segments)
            self.write_srt(subtitle_chunks)
            self.render_video()
            self._log("Done: all steps completed successfully.")
            return SubtitleJobResult(
                output_video=self.output_video,
                output_srt=self.output_srt,
                logs=self.logs,
                success=True,
            )
        except Exception as exc:
            self._log(f"Failed: {exc}")
            return SubtitleJobResult(
                output_video=None,
                output_srt=self.output_srt if os.path.exists(self.output_srt) else None,
                logs=self.logs,
                success=False,
                error=str(exc),
            )


def run_subtitle_job(
    config: SubtitleJobConfig,
    log_hook: Optional[Callable[[str], None]] = None,
) -> SubtitleJobResult:
    pipeline = SubtitlePipeline(config, log_hook=log_hook)
    return pipeline.run()
