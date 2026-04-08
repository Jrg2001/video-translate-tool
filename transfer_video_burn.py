import subprocess
import os
import json
import tempfile
from openai import OpenAI
import whisper
from datetime import timedelta

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


class VideoTranslatorBurn:
    """硬字幕版本 - 将中文字幕直接烧录进视频画面像素中"""
    
    def __init__(self, input_video, target_language="zh", batch_size=10, verbose=False):
        load_env_file()

        self.input_video = input_video
        self.target_language = target_language
        self.batch_size = batch_size
        self.verbose = verbose
        self.srt_path = self._create_temp_srt_path()
        
        # 硬烧字幕会重新编码，输出为 mp4 格式（B站推荐格式）
        filename, ext = os.path.splitext(input_video)
        self.output_video = f"{filename}_{target_language}_burn.mp4"

        # 直接使用系统 PATH 中的 ffmpeg
        self.ffmpeg_exe = "ffmpeg"

        api_key = os.getenv("DEEPSEEK_API_KEY")
        if not api_key:
            raise ValueError("缺少 DEEPSEEK_API_KEY。请在当前目录的 .env 文件中配置该密钥。")

        self.client = OpenAI(
            api_key=api_key,
            base_url="https://api.deepseek.com/v1"
        )
        self.whisper_model = whisper.load_model("small")

    def _create_temp_srt_path(self):
        input_dir = os.path.dirname(os.path.abspath(self.input_video)) or os.getcwd()
        filename, _ = os.path.splitext(os.path.basename(self.input_video))
        temp_file = tempfile.NamedTemporaryFile(
            prefix=f"{filename}_",
            suffix=".srt",
            dir=input_dir,
            delete=False,
        )
        temp_file.close()
        return temp_file.name

    def step1_transcribe(self):
        print("[步骤 1/4]: 正在使用已加载的 Whisper 模型识别语音...")
        result = self.whisper_model.transcribe(self.input_video, task="transcribe")
        
        segments = result["segments"]
        print(f" -> 语音识别完成，共获取到 {len(segments)} 句话")
        return segments

    def _summarize_text(self, text, max_length=50):
        normalized = " ".join(text.strip().split())
        if len(normalized) <= max_length:
            return normalized
        return normalized[:max_length].rstrip() + "..."

    def _format_sentence_numbers(self, sentence_numbers):
        return "、".join(str(number) for number in sentence_numbers)

    def _parse_batch_translation(self, content):
        cleaned = content.strip()
        if cleaned.startswith("```"):
            lines = cleaned.splitlines()
            if lines and lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            cleaned = "\n".join(lines).strip()

        translations = json.loads(cleaned)
        if not isinstance(translations, list):
            raise ValueError("批量翻译返回格式错误：结果不是 JSON 数组。")
        return translations

    def _translate_single(self, text):
        response = self.client.chat.completions.create(
            model="deepseek-chat",
            messages=[
                {
                    "role": "system",
                    "content": "你是一个视频字幕翻译专家。请将以下文本翻译为自然流畅的简体中文，只返回翻译结果，不要添加解释。"
                },
                {"role": "user", "content": text.strip()}
            ],
            temperature=0.3
        )
        return response.choices[0].message.content.strip()

    def _translate_batch(self, batch_segments):
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
                        "你是一个视频字幕翻译专家。"
                        "请将用户提供的 JSON 对象数组逐项翻译为自然流畅的简体中文。"
                        "每个对象都包含 id 和 text。"
                        "返回时必须是 JSON 对象数组，每项包含 id 和 translation。"
                        "id 必须与输入一致，不要遗漏任何项。"
                        "不要返回 Markdown，不要返回代码块，不要添加解释。"
                    ),
                },
                {"role": "user", "content": payload}
            ],
            temperature=0.3
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

        return {
            "translations": translations,
            "missing_ids": missing_ids,
        }

    def step2_translate(self, segments):
        print("[步骤 2/4]: 正在通过 DeepSeek 模型分批翻译...")
        translated_segments = []
        total_segments = len(segments)
        total_batches = (total_segments + self.batch_size - 1) // self.batch_size

        for batch_index, start in enumerate(range(0, total_segments, self.batch_size), start=1):
            batch_segments = segments[start:start + self.batch_size]
            batch_start = start + 1
            batch_end = start + len(batch_segments)
            print(f" -> 开始第 {batch_index}/{total_batches} 批：处理第 {batch_start}-{batch_end} 句，共 {len(batch_segments)} 句")

            batch_result = self._translate_batch(batch_segments)
            translations = batch_result["translations"]
            missing_ids = batch_result["missing_ids"]

            if missing_ids:
                missing_sentence_numbers = [start + missing_id + 1 for missing_id in missing_ids]
                print(
                    f" -> 第 {batch_index} 批缺少 {len(missing_ids)} 条返回，回退逐句翻译：第 {self._format_sentence_numbers(missing_sentence_numbers)} 句"
                )
                for missing_id, sentence_number in zip(missing_ids, missing_sentence_numbers):
                    original_text = batch_segments[missing_id]["text"]
                    if self.verbose:
                        summary = original_text.strip()
                    else:
                        summary = self._summarize_text(original_text)
                    print(f" -> 回退补齐第 {sentence_number} 句：{summary}")

            for segment, trans_text in zip(batch_segments, translations):
                translated_segments.append({
                    "start": segment["start"],
                    "end": segment["end"],
                    "text": trans_text.strip()
                })

            translated_count = len(translated_segments)
            print(f" -> 第 {batch_index}/{total_batches} 批翻译完成，已处理 {translated_count}/{total_segments} 句")

            if self.verbose:
                for segment, trans_text in zip(batch_segments, translations):
                    print(f'    {segment["text"]} >>> {trans_text.strip()}')

        return translated_segments

    def step3_generate_srt(self, translated_segments):
        print("[步骤 3/4]: 正在生成 .srt 字幕文件...")
        
        def format_timestamp(seconds: float):
            td = timedelta(seconds=seconds)
            total_seconds = int(td.total_seconds())
            hours, remainder = divmod(total_seconds, 3600)
            minutes, secs = divmod(remainder, 60)
            milliseconds = int((seconds - total_seconds) * 1000)
            return f"{hours:02d}:{minutes:02d}:{secs:02d},{milliseconds:03d}"
            
        with open(self.srt_path, "w", encoding="utf-8") as f:
            for idx, segment in enumerate(translated_segments):
                start_time = format_timestamp(segment["start"])
                end_time = format_timestamp(segment["end"])
                text = segment["text"]
                
                f.write(f"{idx + 1}\n")
                f.write(f"{start_time} --> {end_time}\n")
                f.write(f"{text}\n\n")
                
        print(" -> 字幕文件生成完成!")

    def step4_burn_subtitles(self):
        print("[步骤 4/4]: 正在将字幕烧录进视频（硬字幕模式")
        print(" ⏳ 提示：硬烧字幕需要重新编码视频，视频越长/分辨率越高耗时越久，请耐心...")
        
        # FFmpeg 的 subtitles 滤镜在 Windows 上需要特殊处理路径：
        # 1. 反斜杠要替换成正斜杠或双反斜杠
        # 2. 冒号前要加反斜杠转义（如 D: 变成 D\:）
        srt_abs_path = os.path.abspath(self.srt_path)
        srt_ffmpeg_path = srt_abs_path.replace("\\", "/").replace(":", "\\:")
        
        # 字幕样式设置：
        #   FontName  = 微软雅黑（Windows自带中文字体，显示效果好）
        #   FontSize  = 20（适中大小）
        #   PrimaryColour = 白色
        #   OutlineColour = 黑色描边（保证在明亮背景下也能看清）
        #   Outline   = 2（描边粗细）
        #   MarginV   = 30（距离底边距离，避免挡住画面重要内容）
        subtitle_style = "FontName=Microsoft YaHei,FontSize=20,PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000,Outline=2,MarginV=30"
        
        subtitle_filter = f"subtitles='{srt_ffmpeg_path}':force_style='{subtitle_style}'"
        
        command = [
            self.ffmpeg_exe, "-loglevel", "warning", "-y", "-i", self.input_video,
            "-vf", subtitle_filter,
            "-c:v", "libx264",   # 使用 H.264 编码（B站完美支持）
            "-crf", "18",        # 质量参数：18 是视觉无损级别，数字越小画质越好/文件越大
            "-preset", "medium", # 编码速度：medium 是速度和质量的平衡点
            "-c:a", "copy",      # 音频直接复制，不重新编码
            self.output_video
        ]
        
        subprocess.run(command, check=True)
        print(f" -> 硬字幕烧录完成! 输出文件: {self.output_video}")

    def process(self):
        try:
            segments = self.step1_transcribe()
            translated_segments = self.step2_translate(segments)
            self.step3_generate_srt(translated_segments)
            self.step4_burn_subtitles()
            print("🎉 所有步骤成功结束！")
        finally:
            if os.path.exists(self.srt_path):
                os.remove(self.srt_path)

if __name__ == "__main__":
    video_file = "d:/transfer/test_video.mp4" 
    
    if os.path.exists(video_file):
        translator = VideoTranslatorBurn(video_file)
        translator.process()
    else:
        print(f"【提醒】找不到视频：{video_file}")
