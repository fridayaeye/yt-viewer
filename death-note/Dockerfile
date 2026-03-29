# Death Note Livestream — Railway (headless Canvas, no Xvfb)
FROM python:3.11-slim-bookworm

RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    fonts-liberation \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir playwright==1.44.0 requests==2.31.0
RUN playwright install chromium && playwright install-deps chromium

WORKDIR /app
COPY stream.py /app/stream.py
COPY notebook.html /app/notebook.html
COPY deathnote_music.mp3 /app/deathnote_music.mp3

ENV PYTHONUNBUFFERED=1

# v2 - force rebuild
CMD ["python3", "/app/stream.py"]
