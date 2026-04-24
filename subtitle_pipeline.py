import concurrent.futures
import json
import os
import re
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path
from typing import Callable, Optional

import budoux
from faster_whisper import WhisperModel
from openai import OpenAI

# Module-level singleton — avoids reloading the model on every call.
_BUDOUX_ZH_PARSER = budoux.load_default_simplified_chinese_parser()


LANGUAGE_CONFIG = {
    "zh": {
        "label": "Chinese (Simplified)",
        "translation_prompt": "natural Simplified Chinese",
        "subtitle_language_code": "chi",
        "tokenizer": "budoux",
    },
    "en": {
        "label": "English",
        "translation_prompt": "natural English",
        "subtitle_language_code": "eng",
        "tokenizer": "whitespace",
    },
    "ja": {
        "label": "Japanese",
        "translation_prompt": "natural Japanese",
        "subtitle_language_code": "jpn",
        "tokenizer": "char",
    },
    "ko": {
        "label": "Korean",
        "translation_prompt": "natural Korean",
        "subtitle_language_code": "kor",
        "tokenizer": "char",
    },
}

FONT_PRESETS = [
    ("Noto Sans CJK SC", "Noto Sans CJK SC"),
    ("Noto Sans CJK JP", "Noto Sans CJK JP"),
    ("Noto Sans CJK KR", "Noto Sans CJK KR"),
    ("Microsoft YaHei", "Microsoft YaHei"),
    ("Microsoft JhengHei", "Microsoft JhengHei"),
    ("SimHei", "SimHei"),
    ("Arial", "Arial"),
    ("Segoe UI", "Segoe UI"),
    ("Custom", None),
]

# Style presets: each entry maps to the full set of SubtitleStyle parameters
# plus a display hint used for the live preview.
STYLE_PRESETS: dict[str, dict] = {
    "Custom": {},
    "Netflix": {
        "font_name": "Arial",
        "font_size": 22,
        "margin_v": 40,
        "outline": 2,
        "primary_colour": "&H00FFFFFF",
        "outline_colour": "&H00000000",
    },
    "YouTube": {
        "font_name": "Noto Sans CJK SC",
        "font_size": 20,
        "margin_v": 35,
        "outline": 1,
        "primary_colour": "&H00FFFFFF",
        "outline_colour": "&H00000000",
    },
    "Bilibili": {
        "font_name": "Microsoft YaHei",
        "font_size": 22,
        "margin_v": 30,
        "outline": 3,
        "primary_colour": "&H00FFFFFF",
        "outline_colour": "&H00000000",
    },
    "Classic Film": {
        "font_name": "Noto Sans CJK SC",
        "font_size": 20,
        "margin_v": 25,
        "outline": 2,
        "primary_colour": "&H0000FFFF",
        "outline_colour": "&H00000000",
    },
}


WHISPER_LANGUAGE_MAP = {
    "zh": "zh",
    "chinese": "zh",
    "en": "en",
    "english": "en",
    "ja": "ja",
    "japanese": "ja",
    "jp": "ja",
    "ko": "ko",
    "korean": "ko",
}


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
    font_name: str = "Noto Sans CJK SC"
    font_size: int = 20
    margin_v: int = 30
    outline: int = 2
    primary_colour: str = "&H00FFFFFF"
    outline_colour: str = "&H00000000"


@dataclass
class SubtitleJobConfig:
    input_video: str
    source_language: str = "auto"
    target_language: str = "zh"
    subtitle_mode: str = "bilingual"
    render_mode: str = "burned"
    output_dir: Optional[str] = None
    batch_size: int = 10
    translation_workers: int = 3
    verbose: bool = False
    ffmpeg_exe: str = "ffmpeg"
    model_size: str = "small"
    external_srt: Optional[str] = None
    style: SubtitleStyle = field(default_factory=SubtitleStyle)


@dataclass
class SubtitleJobResult:
    output_video: Optional[str]
    output_srt: Optional[str]
    logs: list[str]
    success: bool
    error: Optional[str] = None


class SubtitlePipeline:
    def __init__(
        self,
        config: SubtitleJobConfig,
        log_hook: Optional[Callable[[str], None]] = None,
        progress_hook: Optional[Callable[[dict], None]] = None,
    ):
        load_env_file()

        self.config = config
        if self.config.source_language not in {"auto", *LANGUAGE_CONFIG.keys()}:
            self.config.source_language = "auto"
        if self.config.target_language not in LANGUAGE_CONFIG:
            self.config.target_language = "zh"
        self.log_hook = log_hook
        self.progress_hook = progress_hook
        self.logs: list[str] = []
        self.requested_source_language = self._normalize_language_code(self.config.source_language)
        self.detected_source_language: Optional[str] = None
        self.effective_source_language: Optional[str] = None
        self.effective_subtitle_mode = (
            "bilingual" if self.config.subtitle_mode == "bilingual" else "single"
        )
        self.media_duration: Optional[float] = None
        self._last_reported_progress: float = -1.0

        if not config.external_srt:
            # Full pipeline: load Whisper model and DeepSeek client
            api_key = os.getenv("DEEPSEEK_API_KEY")
            if not api_key:
                raise ValueError("Missing DEEPSEEK_API_KEY. Configure it in the local .env file.")
            self.client = OpenAI(
                api_key=api_key,
                base_url="https://api.deepseek.com/v1",
            )
            try:
                import ctranslate2
                _device = "cuda" if ctranslate2.get_cuda_device_count() > 0 else "cpu"
            except Exception:
                _device = "cpu"
            _compute_type = "float16" if _device == "cuda" else "int8"
            self.whisper_model = WhisperModel(config.model_size, device=_device, compute_type=_compute_type)
        else:
            # Burn-only mode: transcription and translation are skipped entirely
            self.client = None
            self.whisper_model = None
        self.config.style = self._sanitize_style(config.style)
        self.input_path = Path(config.input_video).resolve()
        self.output_video: Optional[str] = None
        self.output_srt: Optional[str] = None

    def _log(self, message: str):
        timestamp = time.strftime("%H:%M:%S")
        stamped = f"[{timestamp}] {message}"
        self.logs.append(stamped)
        if self.log_hook:
            self.log_hook(stamped)

    def _report_progress(self, stage: str, percent: float, detail: str = ""):
        clamped_percent = max(0.0, min(100.0, float(percent)))
        if (
            self.progress_hook
            and (clamped_percent >= 100.0 or self._last_reported_progress < 0 or abs(clamped_percent - self._last_reported_progress) >= 0.5)
        ):
            self.progress_hook(
                {
                    "stage": stage,
                    "percent": clamped_percent,
                    "detail": detail,
                }
            )
            self._last_reported_progress = clamped_percent

    def _build_output_video_path(self) -> str:
        output_dir = self._resolve_output_dir()
        suffix = f"_{self.config.target_language}"
        if self._is_effective_bilingual():
            suffix += "_bilingual"

        if self.config.render_mode == "burned":
            output_name = f"{self.input_path.stem}{suffix}_burn.mp4"
        else:
            output_name = f"{self.input_path.stem}{suffix}.mkv"
        return str(output_dir / output_name)

    def _build_output_srt_path(self) -> str:
        output_dir = self._resolve_output_dir()
        suffix = f"_{self.config.target_language}"
        if self._is_effective_bilingual():
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

    def _resolve_ffprobe_path(self) -> Optional[str]:
        ffmpeg_path = Path(self.config.ffmpeg_exe)
        ffprobe_name = "ffprobe.exe" if os.name == "nt" else "ffprobe"
        if ffmpeg_path.parent != Path("."):
            sibling_path = ffmpeg_path.parent / ffprobe_name
            if sibling_path.exists():
                return str(sibling_path)
        return shutil.which("ffprobe")

    def _probe_media_duration(self) -> Optional[float]:
        ffprobe_path = self._resolve_ffprobe_path()
        if not ffprobe_path:
            return None

        try:
            result = subprocess.run(
                [
                    ffprobe_path,
                    "-v",
                    "error",
                    "-show_entries",
                    "format=duration",
                    "-of",
                    "default=noprint_wrappers=1:nokey=1",
                    str(self.input_path),
                ],
                capture_output=True,
                text=True,
                check=True,
            )
            duration = float(result.stdout.strip())
            return duration if duration > 0 else None
        except (subprocess.SubprocessError, ValueError):
            return None

    def _sanitize_style(self, style: SubtitleStyle) -> SubtitleStyle:
        font_name = style.font_name.strip() or "Microsoft YaHei"
        font_size = min(max(int(style.font_size), 12), 40)
        margin_v = min(max(int(style.margin_v), 10), 2000)
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

    def _get_language_config(self, language_code: str) -> dict:
        return LANGUAGE_CONFIG.get(language_code, LANGUAGE_CONFIG["zh"])

    def _normalize_language_code(self, raw_language: Optional[str]) -> Optional[str]:
        if not raw_language:
            return None
        normalized = raw_language.strip().lower()
        if not normalized:
            return None
        if normalized in LANGUAGE_CONFIG:
            return normalized
        return WHISPER_LANGUAGE_MAP.get(normalized)

    def _resolve_effective_source_language(self) -> Optional[str]:
        if self.requested_source_language and self.config.source_language != "auto":
            requested_label = self._get_language_config(self.requested_source_language)["label"]
            self._log(
                f" -> User-selected source language hint: {requested_label} ({self.requested_source_language})"
            )
            if self.detected_source_language:
                if self.detected_source_language != self.requested_source_language:
                    detected_label = self._get_language_config(self.detected_source_language)["label"]
                    self._log(
                        f" -> Source language mismatch: user selected {requested_label} "
                        f"({self.requested_source_language}), but Whisper detected {detected_label} "
                        f"({self.detected_source_language})."
                    )
                    self._log(
                        f" -> Using detected source language: {detected_label} ({self.detected_source_language})"
                    )
                    return self.detected_source_language

                self._log(
                    f" -> Using source language: {requested_label} ({self.requested_source_language})"
                )
                return self.requested_source_language

            self._log(
                f" -> Whisper did not return a reliable source language. "
                f"Using user-selected source language: {requested_label} ({self.requested_source_language})"
            )
            return self.requested_source_language

        if self.detected_source_language:
            label = self._get_language_config(self.detected_source_language)["label"]
            self._log(f" -> Using detected source language: {label} ({self.detected_source_language})")
            return self.detected_source_language

        self._log(" -> Source language could not be determined reliably.")
        return None

    def _resolve_effective_subtitle_mode(self) -> str:
        if self.config.subtitle_mode != "bilingual":
            return "single"
        if self.effective_source_language and self.effective_source_language == self.config.target_language:
            self._log(
                f" -> Source language matches target language ({self.config.target_language}). "
                "Bilingual output downgraded to single-language subtitles."
            )
            return "single"
        return "bilingual"

    def _is_effective_bilingual(self) -> bool:
        return self.effective_subtitle_mode == "bilingual"

    def _should_skip_translation(self) -> bool:
        return (
            self.effective_source_language is not None
            and self.effective_source_language == self.config.target_language
        )

    def _build_translation_prompt(self) -> str:
        language_profile = self._get_language_config(self.config.target_language)
        return (
            "You are a video subtitle translator. "
            f"Translate the text into {language_profile['translation_prompt']} "
            "and return only the translation."
        )

    def _get_soft_subtitle_language_code(self) -> str:
        language_profile = self._get_language_config(self.config.target_language)
        return language_profile.get("subtitle_language_code", "und")

    def _summarize_text(self, text: str, max_length: int = 50) -> str:
        normalized = self._normalize_text(text)
        if len(normalized) <= max_length:
            return normalized
        return normalized[: max_length - 3] + "..."

    def _tokenize_target_text(self, text: str) -> list[str]:
        language_profile = self._get_language_config(self.config.target_language)
        tokenizer = language_profile["tokenizer"]

        if tokenizer == "budoux":
            # Returns display-appropriate phrase chunks, not individual chars/words.
            return _BUDOUX_ZH_PARSER.parse(text)
        if tokenizer == "whitespace":
            return [token for token in text.split() if token]
        return [char for char in text if not char.isspace()]

    def _join_source_words(self, words: list[str]) -> str:
        joined = " ".join(word for word in words if word)
        joined = re.sub(r"\s+([,.!?;:])", r"\1", joined)
        return joined.strip()

    def _group_translation_tokens(self, tokens: list[str]) -> list[str]:
        language_profile = self._get_language_config(self.config.target_language)
        tokenizer = language_profile["tokenizer"]

        if tokenizer == "whitespace":
            return self._split_english_tokens(tokens)
        if tokenizer == "budoux":
            return self._group_budoux_phrases(tokens, max_chars=20)
        if tokenizer == "char":
            return self._group_character_tokens(tokens, target_chars=18, max_chars=24)
        return self._group_character_tokens(tokens, target_chars=14, max_chars=18)

    def _is_weak_english_start(self, token: str) -> bool:
        normalized = token.strip(".,!?;:").lower()
        return normalized in {
            "a", "an", "the",
            "to", "of", "in", "on", "at", "for", "by", "with", "from", "into", "onto",
            "and", "or", "but", "nor", "so", "yet",
        }

    def _is_weak_english_end(self, token: str) -> bool:
        """Return True if this token is a poor choice to end a subtitle line on."""
        normalized = token.strip(".,!?;:").lower()
        return normalized in {
            "a", "an", "the",
            "to", "of", "in", "on", "at", "for", "by", "with", "as",
            "and", "or", "but",
            "his", "her", "its", "their", "our", "my", "your",
            "not", "also",
        }

    def _score_english_break(self, left_tokens: list[str], right_tokens: list[str]) -> float:
        if not left_tokens or not right_tokens:
            return float("-inf")

        left_text = " ".join(left_tokens)
        right_text = " ".join(right_tokens)
        left_word_count = len(left_tokens)
        right_word_count = len(right_tokens)
        score = 0.0

        if left_tokens[-1].endswith((".", "?", "!")):
            score += 4.0
        elif left_tokens[-1].endswith((",", ";", ":")):
            score += 3.0

        if 6 <= left_word_count <= 8:
            score += 2.0
        elif 4 <= left_word_count <= 10:
            score += 1.0

        left_len = len(left_text)
        right_len = len(right_text)
        if 28 <= left_len <= 38:
            score += 1.5
        elif left_len <= 48:
            score += 0.5

        score -= abs(left_len - right_len) / 12

        if right_word_count < 3:
            score -= 4.0
        elif right_word_count < 4:
            score -= 1.5

        if self._is_weak_english_start(right_tokens[0]):
            score -= 4.5

        if self._is_weak_english_end(left_tokens[-1]):
            score -= 4.5

        if left_word_count < 3:
            score -= 3.0

        return score

    def _split_english_tokens(
        self,
        tokens: list[str],
        target_words: int = 7,
        max_words: int = 10,
        target_chars: int = 34,
        max_chars: int = 46,
    ) -> list[str]:
        if not tokens:
            return []

        chunks: list[str] = []
        start = 0

        while start < len(tokens):
            remaining_tokens = tokens[start:]
            if len(remaining_tokens) <= max_words and len(" ".join(remaining_tokens)) <= max_chars:
                chunks.append(" ".join(remaining_tokens))
                break

            min_break = min(start + 3, len(tokens) - 1)
            max_break = min(start + max_words, len(tokens) - 1)
            best_break = None
            best_score = float("-inf")

            for break_index in range(min_break, max_break + 1):
                left_tokens = tokens[start:break_index]
                right_tokens = tokens[break_index:]
                if not left_tokens or not right_tokens:
                    continue

                left_text = " ".join(left_tokens)
                if len(left_text) > max_chars:
                    break

                score = self._score_english_break(left_tokens, right_tokens)
                score -= abs(len(left_tokens) - target_words) * 0.35
                score -= abs(len(left_text) - target_chars) * 0.04

                if score > best_score:
                    best_score = score
                    best_break = break_index

            if best_break is None:
                best_break = min(start + target_words, len(tokens) - 1)

            chunks.append(" ".join(tokens[start:best_break]))
            start = best_break

        chunks = self._merge_short_english_chunks(chunks)
        return chunks

    def _merge_short_english_chunks(self, chunks: list[str]) -> list[str]:
        if not chunks:
            return []

        merged_chunks: list[str] = []
        for chunk in chunks:
            word_count = len(chunk.split())
            if merged_chunks and word_count < 3:
                merged_chunks[-1] = f"{merged_chunks[-1]} {chunk}".strip()
            else:
                merged_chunks.append(chunk)

        if len(merged_chunks) >= 2:
            last_words = merged_chunks[-1].split()
            prev_words = merged_chunks[-2].split()
            should_merge = (
                len(last_words) < 3
                or (last_words and self._is_weak_english_start(last_words[0]))
                or (prev_words and self._is_weak_english_end(prev_words[-1]))
            )
            if should_merge:
                merged_chunks[-2] = f"{merged_chunks[-2]} {merged_chunks[-1]}".strip()
                merged_chunks.pop()

        return merged_chunks

    def _is_dangling_chinese_phrase(self, phrase: str) -> bool:
        """Return True if this budoux phrase is a modifier that shouldn't end a subtitle line.

        Short phrases (≤ 4 chars) that start with a demonstrative, conjunction, or
        preposition are treated as dangling — they should attach to whatever follows.
        Examples: 这场、那次、并质疑、在于、且.
        """
        if not phrase:
            return False
        dangling_starters = set(
            "这那此该某每各其"         # demonstratives / determiners
            "并且或与和但而及还"        # conjunctions
            "在于从向往对为以被把将让使" # prepositions / causatives
            "如若当虽因"               # conditionals
        )
        return len(phrase) <= 4 and phrase[0] in dangling_starters

    def _group_budoux_phrases(self, phrases: list[str], max_chars: int = 20) -> list[str]:
        """Group budoux phrase tokens into subtitle lines by concatenating up to max_chars.

        Unlike _group_character_tokens, tokens here are already display-appropriate
        phrase chunks (e.g. ['国务卿', '马克·鲁比奥', '称赞了这次演讲']), so we
        never split mid-phrase — we only break between phrase boundaries.

        When the last phrase added to the current line is a dangling modifier
        (e.g. '这场', '并质疑'), the next phrase is absorbed into the same line
        before flushing, even if this causes a slight overrun of max_chars.
        """
        if not phrases:
            return []

        chunks: list[str] = []
        current_line = ""
        last_phrase = ""

        for phrase in phrases:
            if not current_line:
                current_line = phrase
                last_phrase = phrase
            elif len(current_line) + len(phrase) <= max_chars:
                current_line += phrase
                last_phrase = phrase
            else:
                if self._is_dangling_chinese_phrase(last_phrase):
                    # Absorb next phrase to fix the dangling end, then flush.
                    # A slightly longer line is far better than a subtitle
                    # ending on a dangling word like "这场" or "并质疑".
                    current_line += phrase
                    chunks.append(current_line)
                    current_line = ""
                    last_phrase = ""
                else:
                    chunks.append(current_line)
                    current_line = phrase
                    last_phrase = phrase

        if current_line:
            chunks.append(current_line)

        return self._merge_short_chunks(chunks, min_length=4, separator="")

    def _group_character_tokens(self, tokens: list[str], target_chars: int, max_chars: int) -> list[str]:
        chunks: list[str] = []
        current_tokens: list[str] = []
        current_length = 0
        punctuation_tokens = {"，", "。", "！", "？", "；", "：", "、", ",", ".", "!", "?", ";", ":"}

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

        return self._merge_short_chunks(chunks, min_length=4, separator="")

    def _merge_short_chunks(self, chunks: list[str], min_length: int, separator: str) -> list[str]:
        merged_chunks: list[str] = []
        for chunk in chunks:
            if merged_chunks and len(chunk) < min_length:
                merged_chunks[-1] = f"{merged_chunks[-1]}{separator}{chunk}".strip()
            else:
                merged_chunks.append(chunk)

        if len(merged_chunks) >= 2 and len(merged_chunks[-1]) < min_length:
            merged_chunks[-2] = f"{merged_chunks[-2]}{separator}{merged_chunks[-1]}".strip()
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
        self._report_progress("transcribe", 5, "Loading Whisper and transcribing audio")
        transcribe_kwargs: dict = {
            "word_timestamps": True,
        }
        if self.config.source_language != "auto":
            transcribe_kwargs["language"] = self.config.source_language
            label = self._get_language_config(self.config.source_language)["label"]
            self._log(f" -> Using user-selected source language for Whisper: {label} ({self.config.source_language})")
        else:
            self._log(" -> Whisper source language mode: auto detect")

        # faster-whisper returns a lazy generator + info object (not a dict)
        segments_iter, info = self.whisper_model.transcribe(str(self.input_path), **transcribe_kwargs)

        # Materialise the generator and convert objects -> dicts so the rest
        # of the pipeline works without any further changes.
        segments: list[dict] = []
        for seg in segments_iter:
            words = [
                {"word": w.word, "start": w.start, "end": w.end}
                for w in (seg.words or [])
            ]
            segments.append({
                "start": seg.start,
                "end": seg.end,
                "text": seg.text,
                "words": words,
            })

        self.detected_source_language = self._normalize_language_code(info.language)
        if self.detected_source_language:
            label = self._get_language_config(self.detected_source_language)["label"]
            self._log(f" -> Detected source language: {label} ({self.detected_source_language})")
        else:
            self._log(" -> Source language detection unavailable")

        self.effective_source_language = self._resolve_effective_source_language()
        self.effective_subtitle_mode = self._resolve_effective_subtitle_mode()
        self.output_video = self._build_output_video_path()
        self.output_srt = self._build_output_srt_path()

        if segments:
            self.media_duration = max(seg["end"] for seg in segments) or None
        self._report_progress("transcribe", 25, f"{len(segments)} segments")
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
                    "content": self._build_translation_prompt(),
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
        language_profile = self._get_language_config(self.config.target_language)

        response = self.client.chat.completions.create(
            model="deepseek-chat",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a video subtitle translator. "
                        f"Translate each JSON object item into {language_profile['translation_prompt']}. "
                        "Each object contains id and text. "
                        "Return a JSON object array with id and translation for every item. "
                        "Do not omit items. Do not return Markdown, code fences, or explanations."
                    ),
                },
                {"role": "user", "content": payload},
            ],
            temperature=0.3,
        )
        raw_content = response.choices[0].message.content
        try:
            parsed_items = self._parse_batch_translation(raw_content)
        except (json.JSONDecodeError, ValueError) as exc:
            self._log(f" -> Batch translation parse failed ({exc}), falling back to single translation")
            translations = [self._translate_single(seg["text"]) for seg in batch_segments]
            return {"translations": translations, "missing_ids": []}

        # Strategy 1: if the returned array length matches exactly, map by position (order-based).
        # This avoids failures caused by the API returning 1-indexed ids instead of 0-indexed.
        valid_items = [
            item for item in parsed_items
            if isinstance(item, dict) and isinstance(item.get("translation"), str)
        ]
        if len(valid_items) == len(batch_segments):
            translations = [item["translation"].strip() for item in valid_items]
            return {"translations": translations, "missing_ids": []}

        # Strategy 2: fall back to id-based lookup, tolerating off-by-one id offsets.
        translation_map = {}
        id_offset = 0
        for item in parsed_items:
            if not isinstance(item, dict):
                continue
            item_id = item.get("id")
            translation = item.get("translation")
            if isinstance(item_id, int) and isinstance(translation, str):
                translation_map[item_id] = translation.strip()

        # Detect if the API returned 1-indexed ids when we sent 0-indexed.
        if translation_map and 0 not in translation_map and 1 in translation_map:
            id_offset = 1

        translations = []
        missing_ids = []
        for index, segment in enumerate(batch_segments):
            translated_text = translation_map.get(index + id_offset)
            if translated_text is not None:
                translations.append(translated_text)
            else:
                missing_ids.append(index)
                translations.append(None)

        for index in missing_ids:
            translations[index] = self._translate_single(batch_segments[index]["text"])

        return {"translations": translations, "missing_ids": missing_ids}

    def translate(self, segments: list[dict]) -> list[dict]:
        language_label = self._get_language_config(self.config.target_language)["label"]
        self._log(f"[Step 2/4] Translating subtitles in batches to {language_label}...")
        self._report_progress("translate", 25, f"Target language: {language_label}")

        if self._should_skip_translation():
            self._log(
                f" -> Source language matches target language ({self.config.target_language}). "
                "Skipping translation and using Whisper transcript directly."
            )
            self._report_progress("translate", 55, "Translation skipped")
            return [
                {
                    "start": segment["start"],
                    "end": segment["end"],
                    "source_text": self._normalize_text(segment["text"]),
                    "translated_text": self._normalize_text(segment["text"]),
                    "words": segment.get("words", []),
                }
                for segment in segments
            ]

        total_segments = len(segments)
        total_batches = (total_segments + self.config.batch_size - 1) // self.config.batch_size

        # Build all batches upfront so we can submit them concurrently.
        batches: list[tuple[int, int, list[dict]]] = [
            (batch_index, start, segments[start:start + self.config.batch_size])
            for batch_index, start in enumerate(range(0, total_segments, self.config.batch_size), start=1)
        ]

        # Log all batch starts before launching (keeps the log readable).
        workers = min(self.config.translation_workers, total_batches)
        self._log(f" -> {total_batches} batch(es), {workers} concurrent worker(s)")
        for batch_index, start, batch_segs in batches:
            self._log(
                f" -> Batch {batch_index}/{total_batches}: segments {start + 1}-{start + len(batch_segs)}"
                f" ({len(batch_segs)} items)"
            )

        # Submit all batches concurrently and collect results keyed by batch_index.
        batch_results: dict[int, tuple[int, list[dict], dict]] = {}
        with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
            future_to_meta = {
                executor.submit(self._translate_batch, batch_segs): (batch_index, start, batch_segs)
                for batch_index, start, batch_segs in batches
            }
            for future in concurrent.futures.as_completed(future_to_meta):
                batch_index, start, batch_segs = future_to_meta[future]
                try:
                    batch_results[batch_index] = (start, batch_segs, future.result())
                except Exception as exc:
                    self._log(f" -> Batch {batch_index} raised an exception ({exc}), falling back to single translation")
                    translations = [self._translate_single(seg["text"]) for seg in batch_segs]
                    batch_results[batch_index] = (start, batch_segs, {"translations": translations, "missing_ids": []})

        # Assemble translated_segments in original order and emit per-batch logs.
        translated_segments: list[dict] = []
        for batch_index in sorted(batch_results):
            start, batch_segs, batch_result = batch_results[batch_index]
            translations = batch_result["translations"]
            missing_ids = batch_result["missing_ids"]

            if missing_ids:
                missing_sentence_numbers = [start + mid + 1 for mid in missing_ids]
                self._log(
                    f" -> Batch {batch_index} missed {len(missing_ids)} items, fallback to single translation"
                    f" for segments {', '.join(str(n) for n in missing_sentence_numbers)}"
                )
                for mid, sentence_number in zip(missing_ids, missing_sentence_numbers):
                    original_text = batch_segs[mid]["text"]
                    summary = original_text.strip() if self.config.verbose else self._summarize_text(original_text)
                    self._log(f" -> Fallback segment {sentence_number}: {summary}")

            for segment, translated_text in zip(batch_segs, translations):
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
                f" -> Batch {batch_index}/{total_batches} complete,"
                f" processed {len(translated_segments)}/{total_segments} segments"
            )
            translate_percent = 25 + (30 * batch_index / total_batches)
            self._report_progress("translate", translate_percent, f"Batch {batch_index}/{total_batches}")

            if self.config.verbose:
                for segment, translated_text in zip(batch_segs, translations):
                    self._log(f'    {segment["text"]} >>> {translated_text}')

        self._report_progress("translate", 55, "Translation complete")
        return translated_segments

    def _split_translated_segment(self, segment: dict) -> list[dict]:
        translated_text = self._normalize_text(segment["translated_text"])
        tokens = self._tokenize_target_text(translated_text)
        chunk_texts = self._group_translation_tokens(tokens)

        if self.config.verbose and self.config.target_language == "en" and chunk_texts:
            self._log("[EN chunking]")
            self._log(f"Original: {translated_text}")
            for index, chunk_text in enumerate(chunk_texts, start=1):
                self._log(f"{index}. {chunk_text}")

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

        if self.config.verbose and self.config.target_language == "en" and translated_chunk_texts:
            self._log("[EN chunking]")
            self._log(f"Original: {translated_text}")
            for index, chunk_text in enumerate(translated_chunk_texts, start=1):
                self._log(f"{index}. {chunk_text}")

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
            source_tokens = [
                self._normalize_text(word.get("word", ""))
                for word in words
                if self._normalize_text(word.get("word", ""))
            ]
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

    def _merge_short_duration_chunks(self, chunks: list[dict], min_duration: float = 1.2) -> list[dict]:
        """Merge any subtitle chunk shorter than min_duration seconds into its predecessor.

        This should only be called on chunks from a *single* Whisper segment so that
        short chunks are never merged across unrelated utterances.
        """
        if len(chunks) <= 1:
            return chunks

        # CJK languages do not use spaces between words; joining with a space
        # produces "今天 下雨" style corruption.  Use an empty separator instead.
        target_profile = self._get_language_config(self.config.target_language)
        target_sep = "" if target_profile["tokenizer"] != "whitespace" else " "

        # Apply the same logic to the source side: the source language is not
        # always English — a Japanese or Chinese source video needs no space either.
        source_lang = self.effective_source_language or "en"
        source_profile = (
            self._get_language_config(source_lang)
            if source_lang in LANGUAGE_CONFIG
            else {"tokenizer": "whitespace"}
        )
        source_sep = "" if source_profile["tokenizer"] != "whitespace" else " "

        result = [chunks[0]]
        for chunk in chunks[1:]:
            duration = chunk["end"] - chunk["start"]
            if duration < min_duration:
                prev = result[-1]
                if self._is_effective_bilingual():
                    result[-1] = {
                        "start": prev["start"],
                        "end": chunk["end"],
                        "source_text": (prev["source_text"] + source_sep + chunk["source_text"]).strip(),
                        "translated_text": (prev["translated_text"] + target_sep + chunk["translated_text"]).strip(),
                    }
                else:
                    result[-1] = {
                        "start": prev["start"],
                        "end": chunk["end"],
                        "text": (prev["text"] + target_sep + chunk["text"]).strip(),
                    }
            else:
                result.append(chunk)
        return result

    def build_subtitle_chunks(self, translated_segments: list[dict]) -> list[dict]:
        subtitle_chunks: list[dict] = []
        for segment in translated_segments:
            if self._is_effective_bilingual():
                seg_chunks = self._split_bilingual_segment(segment)
            else:
                seg_chunks = self._split_translated_segment(segment)
            # Merge short-duration chunks *within this segment only* to avoid
            # concatenating unrelated utterances across Whisper segment boundaries.
            seg_chunks = self._merge_short_duration_chunks(seg_chunks)
            subtitle_chunks.extend(seg_chunks)
        return subtitle_chunks

    def write_srt(self, subtitle_chunks: list[dict]) -> str:
        self._log("[Step 3/4] Writing subtitle file...")
        self._report_progress("write_srt", 55, "Writing subtitle file")
        with open(self.output_srt, "w", encoding="utf-8") as subtitle_file:
            for index, chunk in enumerate(subtitle_chunks, start=1):
                if self._is_effective_bilingual():
                    text = f'{chunk["source_text"]}\n{chunk["translated_text"]}'
                else:
                    text = chunk["text"]

                subtitle_file.write(f"{index}\n")
                subtitle_file.write(f'{self._format_timestamp(chunk["start"])} --> {self._format_timestamp(chunk["end"])}\n')
                subtitle_file.write(f"{text}\n\n")

        self._log(f" -> Subtitle file written: {self.output_srt}")
        self._report_progress("write_srt", 60, "Subtitle file ready")
        return self.output_srt

    def _probe_nvenc_available(self) -> bool:
        """Return True if the local FFmpeg build includes the h264_nvenc encoder."""
        try:
            result = subprocess.run(
                [self.config.ffmpeg_exe, "-hide_banner", "-encoders"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            return "h264_nvenc" in result.stdout
        except Exception:
            return False

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
        if not self.media_duration:
            self.media_duration = self._probe_media_duration()
        if self.config.render_mode == "soft":
            self._log("[Step 4/4] Muxing soft subtitles into video...")
            command = [
                self.config.ffmpeg_exe,
                "-loglevel", "warning",
                "-progress", "pipe:2",
                "-nostats",
                "-y",
                "-i", str(self.input_path),
                "-i", self.output_srt,
                "-c", "copy",
                "-c:s", "srt",
                "-metadata:s:s:0", f"language={self._get_soft_subtitle_language_code()}",
                self.output_video,
            ]
        else:
            self._log("[Step 4/4] Burning subtitles into video...")
            subtitle_path = os.path.abspath(self.output_srt).replace("\\", "/").replace(":", "\\:")
            subtitle_filter = (
                f"subtitles='{subtitle_path}':force_style='{self._subtitle_style_string()}'"
            )
            use_nvenc = self._probe_nvenc_available()
            if use_nvenc:
                self._log(" -> Encoder: h264_nvenc (GPU)")
                encoder_args = [
                    "-c:v", "h264_nvenc",
                    "-preset", "p4",
                    "-rc:v", "vbr",
                    "-cq:v", "20",
                    "-b:v", "0",
                ]
            else:
                self._log(" -> Encoder: libx264 (CPU, NVENC not available)")
                encoder_args = [
                    "-c:v", "libx264",
                    "-crf", "18",
                    "-preset", "medium",
                ]
            command = [
                self.config.ffmpeg_exe,
                "-loglevel", "warning",
                "-progress", "pipe:2",
                "-nostats",
                "-y",
                "-i", str(self.input_path),
                "-vf", subtitle_filter,
                *encoder_args,
                "-c:a", "copy",
                self.output_video,
            ]

        self._report_progress("render", 60, "Starting FFmpeg")
        process = subprocess.Popen(
            command,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
            universal_newlines=True,
        )
        assert process.stderr is not None
        for raw_line in process.stderr:
            line = raw_line.strip()
            if not line:
                continue

            current_seconds = None
            if line.startswith("out_time_us="):
                try:
                    current_seconds = int(line.split("=", 1)[1]) / 1_000_000
                except ValueError:
                    current_seconds = None
            elif line.startswith("out_time="):
                time_value = line.split("=", 1)[1]
                try:
                    hours, minutes, seconds = time_value.split(":")
                    current_seconds = int(hours) * 3600 + int(minutes) * 60 + float(seconds)
                except ValueError:
                    current_seconds = None

            if current_seconds is not None and self.media_duration:
                render_fraction = min(max(current_seconds / self.media_duration, 0.0), 1.0)
                overall_percent = 60 + 40 * render_fraction
                self._report_progress("render", overall_percent, f"Rendering video ({overall_percent:.0f}%)")

        return_code = process.wait()
        if return_code != 0:
            raise subprocess.CalledProcessError(return_code, command)
        self._log(f" -> Video output ready: {self.output_video}")
        self._report_progress("done", 100, "Video output ready")
        return self.output_video

    def _run_burn_only(self) -> SubtitleJobResult:
        """Fast path: skip transcription and translation, burn a user-supplied SRT directly."""
        try:
            self._report_progress("start", 0, "Preparing burn-only job")

            srt_path = Path(self.config.external_srt).resolve()
            if not srt_path.exists():
                raise FileNotFoundError(f"SRT file not found: {srt_path}")

            self.output_srt = str(srt_path)

            # Derive output video path from the input video stem
            output_dir = (
                Path(self.config.output_dir).resolve()
                if self.config.output_dir
                else self.input_path.parent
            )
            output_dir.mkdir(parents=True, exist_ok=True)
            self.output_video = str(output_dir / f"{self.input_path.stem}_burn.mp4")

            self._log("[Step 1/2] Using existing subtitle file...")
            self._log(f" -> SRT: {self.output_srt}")
            self._report_progress("write_srt", 50, "Using existing SRT")

            self._log("[Step 2/2] Burning subtitles into video...")
            self.render_video()

            self._log("Done: burn-only job completed successfully.")
            return SubtitleJobResult(
                output_video=self.output_video,
                output_srt=self.output_srt,
                logs=self.logs,
                success=True,
            )
        except Exception as exc:
            self._report_progress(
                "failed",
                self._last_reported_progress if self._last_reported_progress >= 0 else 0,
                str(exc),
            )
            self._log(f"Failed: {exc}")
            return SubtitleJobResult(
                output_video=None,
                output_srt=None,
                logs=self.logs,
                success=False,
                error=str(exc),
            )

    def run(self) -> SubtitleJobResult:
        if self.config.external_srt:
            return self._run_burn_only()
        try:
            self._report_progress("start", 0, "Preparing job")
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
            self._report_progress("failed", self._last_reported_progress if self._last_reported_progress >= 0 else 0, str(exc))
            self._log(f"Failed: {exc}")
            return SubtitleJobResult(
                output_video=None,
                output_srt=self.output_srt if self.output_srt and os.path.exists(self.output_srt) else None,
                logs=self.logs,
                success=False,
                error=str(exc),
            )


def run_subtitle_job(
    config: SubtitleJobConfig,
    log_hook: Optional[Callable[[str], None]] = None,
    progress_hook: Optional[Callable[[dict], None]] = None,
) -> SubtitleJobResult:
    pipeline = SubtitlePipeline(config, log_hook=log_hook, progress_hook=progress_hook)
    return pipeline.run()
