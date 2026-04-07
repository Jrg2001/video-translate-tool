import subprocess
import os
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
    """硬字幕版本 - 将中文字幕直接烧录进视频画面像素中，适用于上传B站等平台"""
    
    def __init__(self, input_video, target_language="zh"):
        load_env_file()

        self.input_video = input_video
        self.target_language = target_language
        self.srt_path = "temp_subtitle.srt"
        
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

    def step1_transcribe(self):
        print("[步骤 1/4]: 正在加载 Whisper 模型，直接从原视频中识别语音...")
        model = whisper.load_model("small")
        result = model.transcribe(self.input_video, task="transcribe")
        
        segments = result["segments"]
        print(f" -> 语音识别完成，共获取到 {len(segments)} 句话")
        return segments

    def step2_translate(self, segments):
        print("[步骤 2/4]: 正在通过 DeepSeek 模型逐句翻译...")
        translated_segments = []
        for i, segment in enumerate(segments):
            original_text = segment['text']
            
            response = self.client.chat.completions.create(
                model="deepseek-chat",
                messages=[
                    {"role": "system", "content": "你是一个视频字幕翻译专家。请将以下对话/文本翻译为自然流畅的简体中文，直接返回最终结果，不要带上任何如引号、多余注释等内容。"},
                    {"role": "user", "content": original_text}
                ],
                temperature=0.3
            )
            trans_text = response.choices[0].message.content.strip()
            
            translated_segments.append({
                "start": segment["start"],
                "end": segment["end"],
                "text": trans_text
            })
            print(f"[{i+1}/{len(segments)}] {original_text} >>> {trans_text}")
            
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
        print("[步骤 4/4]: 正在将字幕烧录进视频（硬字幕模式，适合B站上传）...")
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
            self.ffmpeg_exe, "-y", "-i", self.input_video,
            "-vf", subtitle_filter,
            "-c:v", "libx264",   # 使用 H.264 编码（B站完美支持）
            "-crf", "18",        # 质量参数：18 是视觉无损级别，数字越小画质越好/文件越大
            "-preset", "medium", # 编码速度：medium 是速度和质量的平衡点
            "-c:a", "copy",      # 音频直接复制，不重新编码
            self.output_video
        ]
        
        subprocess.run(command)
        print(f" -> 硬字幕烧录完成! 输出文件: {self.output_video}")

    def process(self):
        segments = self.step1_transcribe()
        translated_segments = self.step2_translate(segments)
        self.step3_generate_srt(translated_segments)
        self.step4_burn_subtitles()
        
        if os.path.exists(self.srt_path):
            os.remove(self.srt_path)
            
        print("🎉 所有步骤成功结束！可以直接上传B站了！")

if __name__ == "__main__":
    video_file = "d:/transfer/test_video.mp4" 
    
    if os.path.exists(video_file):
        translator = VideoTranslatorBurn(video_file)
        translator.process()
    else:
        print(f"【提醒】找不到视频：{video_file}")
