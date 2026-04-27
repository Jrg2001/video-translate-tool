FROM python:3.11-slim

# 系统依赖：FFmpeg、中文字体、音频解码库
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    fonts-noto-cjk \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 先只复制依赖文件，利用 Docker layer 缓存
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 再复制项目文件
COPY . .

# Streamlit 默认端口
EXPOSE 8501

# headless=true 禁用浏览器自动打开，适合服务器部署
CMD ["streamlit", "run", "app.py", \
     "--server.port=8501", \
     "--server.address=0.0.0.0", \
     "--server.headless=true"]
