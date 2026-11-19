import argparse
from pathlib import Path

from subtitle_pipeline import LANGUAGE_CONFIG, SubtitleJobConfig, run_subtitle_job

DEFAULT_OUTPUT_DIR = Path(__file__).resolve().parent / "outputs"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Transcribe, translate and burn subtitles into a video.")
    parser.add_argument("video", help="Path to the input video file.")
    parser.add_argument("--source-language", default="auto", choices=["auto", *LANGUAGE_CONFIG],
                        help="Source language of the video (default: auto).")
    parser.add_argument("--target-language", default="zh", choices=list(LANGUAGE_CONFIG),
                        help="Subtitle target language (default: zh).")
    parser.add_argument("--subtitle-mode", default="single", choices=["single", "bilingual"],
                        help="Single-language or bilingual subtitles (default: single).")
    parser.add_argument("--render-mode", default="burned", choices=["burned", "soft"],
                        help="Burned (hard) or soft subtitles (default: burned).")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR),
                        help="Output directory (default: outputs/ in the project folder).")
    parser.add_argument("--verbose", action="store_true", help="Print detailed logs.")
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()

    config = SubtitleJobConfig(
        input_video=args.video,
        source_language=args.source_language,
        target_language=args.target_language,
        subtitle_mode=args.subtitle_mode,
        render_mode=args.render_mode,
        output_dir=args.output_dir,
        batch_size=10,
        verbose=args.verbose,
    )

    result = run_subtitle_job(config, log_hook=print)
    if not result.success:
        raise SystemExit(result.error or "Job failed")
