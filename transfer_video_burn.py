from subtitle_pipeline import SubtitleJobConfig, run_subtitle_job


if __name__ == "__main__":
    video_file = "d:/transfer/test_video.mp4"

    config = SubtitleJobConfig(
        input_video=video_file,
        source_language="auto",
        target_language="zh",
        subtitle_mode="single",
        render_mode="burned",
        output_dir=r"D:\transfer\outputs",
        batch_size=10,
        verbose=False,
    )

    result = run_subtitle_job(config, log_hook=print)
    if not result.success:
        raise SystemExit(result.error or "Job failed")
