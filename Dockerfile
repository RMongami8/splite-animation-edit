# Hugging Face Spaces (Docker SDK) 向け。7860番で待ち受ける(HF Spacesの既定)。
# av / imageio-ffmpeg は manylinux wheel に ffmpeg 本体を同梱しているため、
# 追加の apt install (ffmpeg) は不要。
FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# HF Spaces のコンテナは非rootユーザーで実行する。data/ 以下に書き込むため
# アプリ一式の所有者を先に切り替えておく(§9 originals/derived の書き込み権限)。
RUN useradd -m -u 1000 user && chown -R user:user /app
USER user

ENV HOST=0.0.0.0 \
    PORT=7860
EXPOSE 7860

CMD ["python", "app.py"]
