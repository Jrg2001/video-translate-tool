"""Run with: python -m unittest discover -s tests -v"""

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from streamlit.testing.v1 import AppTest

from subtitle_pipeline import SubtitleJobResult
from ui_i18n import translate, translate_detail


class InterfaceLanguageTests(unittest.TestCase):
    def new_app(self):
        app = AppTest.from_file(str(ROOT / "app.py"), default_timeout=30).run()
        self.assertFalse(app.exception)
        return app

    def switch(self, app, language):
        app.radio(key="ui_language").set_value(language).run()
        self.assertFalse(app.exception)

    def test_settings_survive_language_round_trip(self):
        app = self.new_app()
        self.assertEqual(app.title[0].value, "视频字幕翻译工具")
        app.text_input(key="local_video_path").set_value("D:/videos/my-video.mp4")
        app.text_input(key="manual_output_dir").set_value("D:/my-subtitles")
        app.selectbox(key="source_language").set_value("ja")
        app.selectbox(key="target_language").set_value("en")
        app.selectbox(key="model_size").set_value("medium")
        app.selectbox(key="subtitle_mode").set_value(("bilingual", "Bilingual (top/bottom)"))
        app.selectbox(key="render_mode").set_value(("soft", "Soft Subtitle Video"))
        app.slider(key="batch_size").set_value(7)
        app.slider(key="translation_workers").set_value(4)
        app.checkbox(key="verbose").set_value(True)
        app.run()
        self.assertFalse(app.exception)
        app.radio(key="ui_orientation").set_value("Portrait (9:16)").run()
        app.slider(key="ui_font_size").set_value(27)
        app.slider(key="ui_bottom_margin").set_value(123)
        app.color_picker(key="ui_text_color").set_value("#123456")
        app.run()

        keys = ["local_video_path", "manual_output_dir", "source_language", "target_language",
                "model_size", "subtitle_mode", "render_mode", "batch_size",
                "translation_workers", "verbose", "ui_orientation", "ui_font_size",
                "ui_bottom_margin", "ui_text_color"]
        expected = {key: app.session_state[key] for key in keys}
        for language, title in [("en", "Video Translate Tool"), ("zh", "视频字幕翻译工具")]:
            self.switch(app, language)
            self.assertEqual(app.title[0].value, title)
            for key, value in expected.items():
                self.assertEqual(app.session_state[key], value, key)
        self.assertEqual(app.selectbox(key="target_language").options, ["简体中文", "英语", "日语", "韩语"])

    def test_burn_only_and_custom_font_survive_switch(self):
        app = self.new_app()
        app.selectbox(key="job_mode").set_value(("burn_only", "Burn Existing SRT")).run()
        app.text_input(key="external_srt_path").set_value("D:/字幕/edited.srt")
        app.selectbox(key="ui_font_preset").set_value("Custom").run()
        app.text_input(key="custom_font_name").set_value("My Font").run()
        self.switch(app, "en")
        self.assertEqual(app.text_input(key="external_srt_path").value, "D:/字幕/edited.srt")
        self.assertEqual(app.text_input(key="custom_font_name").value, "My Font")
        self.assertEqual(app.selectbox(key="job_mode").value[0], "burn_only")
        self.switch(app, "zh")
        self.assertEqual(app.text_input(key="custom_font_name").label, "自定义字体名称")

    def test_language_change_resends_selected_labels_to_browser(self):
        app = self.new_app()
        app.selectbox(key="source_language").set_value("ja")
        app.selectbox(key="target_language").set_value("ko")
        app.selectbox(key="model_size").set_value("medium")
        app.selectbox(key="subtitle_mode").set_value(("bilingual", "Bilingual (top/bottom)"))
        app.selectbox(key="render_mode").set_value(("soft", "Soft Subtitle Video"))
        app.selectbox(key="ui_style_preset").set_value("Classic Film").run()
        app.selectbox(key="ui_font_preset").set_value("Custom").run()
        labels = {
            "job_mode": "Full Pipeline (Transcribe → Translate → Burn)",
            "input_source": "Local File Path",
            "output_dir_source": "Manual Path",
            "source_language": "Japanese",
            "target_language": "Korean",
            "subtitle_mode": "Bilingual (top/bottom)",
            "render_mode": "Soft Subtitle Video",
            "ui_style_preset": "Classic Film",
            "ui_font_preset": "Custom",
        }
        selected = {key: app.session_state[key] for key in labels}
        for language in ["en", "zh", "en"]:
            self.switch(app, language)
            self.assertEqual(app.selectbox(key="model_size").value, "medium")
            for key, label in labels.items():
                widget = app.selectbox(key=key)
                self.assertEqual(widget.value, selected[key], key)
                # Updated option lists alone do not refresh the browser's selected text.
                self.assertTrue(widget.proto.set_value, key)
                self.assertEqual(widget.proto.raw_value, translate(label, language), key)

    def test_language_change_resends_orientation_selection(self):
        app = self.new_app()
        for orientation in ["Landscape (16:9)", "Portrait (9:16)"]:
            if orientation != app.session_state["ui_orientation"]:
                app.radio(key="ui_orientation").set_value(orientation).run()
            for language in ["en", "zh"]:
                self.switch(app, language)
                widget = app.radio(key="ui_orientation")
                self.assertEqual(widget.value, orientation)
                # Without an explicit value, the browser shows no option selected.
                self.assertTrue(widget.proto.set_value, language)
                self.assertEqual(widget.proto.raw_value, translate(orientation, language))

    def test_validation_is_localized(self):
        app = self.new_app()
        app.button(key="start_job").click().run()
        self.assertEqual(app.error[0].value, "请先填写本地视频路径。")
        self.switch(app, "en")
        app.button(key="start_job").click().run()
        self.assertEqual(app.error[0].value, "Enter a local video path first.")

    def test_uploaded_video_survives_language_round_trip(self):
        app = self.new_app()
        app.selectbox(key="input_source").set_value(("upload", "Upload File")).run()
        video_bytes = b"uploaded-video-content"
        app.file_uploader(key="uploaded_video").set_value(
            ("sample.mp4", video_bytes, "video/mp4")
        ).run()
        for language in ["en", "zh"]:
            self.switch(app, language)
            uploaded = app.file_uploader(key="uploaded_video").value
            self.assertEqual(uploaded.name, "sample.mp4")
            self.assertEqual(uploaded.getvalue(), video_bytes)

    def test_selected_folder_display_tracks_new_selection(self):
        app = self.new_app()
        app.selectbox(key="output_dir_source").set_value(("browse", "Browse Folder")).run()
        app.session_state.selected_output_dir = "D:/new-output-folder"
        app.run()
        self.assertEqual(app.text_input(key="output_dir_display").value, "D:/new-output-folder")
        self.switch(app, "en")
        self.assertEqual(app.text_input(key="output_dir_display").value, "D:/new-output-folder")

    def test_completed_job_is_preserved_without_rerunning_pipeline(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            video = folder / "example.mp4"
            subtitle = folder / "example.srt"
            video.write_bytes(b"test-video")
            subtitle.write_text("1\n00:00:00,000 --> 00:00:01,000\nHello\n", encoding="utf-8")

            def complete_job(config, log_hook=None, progress_hook=None):
                self.assertEqual(config.source_language, "ja")
                self.assertEqual(config.target_language, "en")
                progress_hook({"stage": "done", "percent": 100, "detail": "Video output ready"})
                return SubtitleJobResult(str(video), str(subtitle), [], True)

            with patch("subtitle_pipeline.run_subtitle_job", side_effect=complete_job) as run_job:
                app = self.new_app()
                app.text_input(key="local_video_path").set_value(str(video))
                app.text_input(key="manual_output_dir").set_value(directory)
                app.selectbox(key="source_language").set_value("ja")
                app.selectbox(key="target_language").set_value("en")
                app.button(key="start_job").click().run()
                self.assertFalse(app.exception)
                result = dict(app.session_state.job_result)
                self.assertEqual(app.success[0].value, "已完成")
                self.assertTrue(any("视频已生成" in caption.value for caption in app.caption))
                self.switch(app, "en")
                self.assertEqual(app.success[0].value, "Completed")
                self.assertEqual(app.session_state.job_result, result)
                self.assertTrue(any("Video output ready" in caption.value for caption in app.caption))
                self.assertEqual([item.proto.label for item in app.get("download_button")],
                                 ["Download Video", "Download Subtitle"])
                self.switch(app, "zh")
                self.assertEqual([item.proto.label for item in app.get("download_button")],
                                 ["下载视频", "下载字幕"])
                run_job.assert_called_once()

    def test_progress_retranslates_from_original_details(self):
        app = self.new_app()
        app.session_state.job_progress = 35
        app.session_state.job_progress_stage = "translate"
        app.session_state.job_progress_detail = "Batch 1/3"
        app.run()
        self.assertTrue(any("翻译批次 1/3" in item.value for item in app.caption))
        self.switch(app, "en")
        self.assertTrue(any("Batch 1/3" in item.value for item in app.caption))
        self.assertEqual(app.session_state.job_progress_detail, "Batch 1/3")

    def test_user_values_and_unknown_diagnostics_are_preserved(self):
        path = r"D:\English\视频 {final}.mp4"
        self.assertEqual(translate("Local video file not found: {path}", "zh", path=path),
                         f"找不到本地视频文件：{path}")
        diagnostic = "FFmpeg: unsupported codec xyz"
        self.assertEqual(translate_detail(diagnostic, "zh"), diagnostic)
        self.assertEqual(translate_detail("Target language: English", "zh"), "目标语言：英语")


if __name__ == "__main__":
    unittest.main()
