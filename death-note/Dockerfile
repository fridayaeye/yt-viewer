# Death Note Livestream — Railway Docker Image
# Platform: linux/amd64
# Stack: Python 3.11 + Xvfb + Chromium + ffmpeg + Playwright

FROM python:3.11-slim-bookworm

# ── System packages ────────────────────────────────────────────────────────────
RUN apt-get update && apt-get install -y --no-install-recommends \
    xvfb \
    x11-utils \
    chromium \
    ffmpeg \
    fonts-liberation \
    fonts-noto-core \
    ca-certificates \
    curl \
    wget \
    supervisor \
    && rm -rf /var/lib/apt/lists/*

# ── Python dependencies ────────────────────────────────────────────────────────
RUN pip install --no-cache-dir \
    playwright==1.44.0 \
    requests==2.31.0

# Install Playwright's bundled Chromium for headless=False support inside Xvfb
RUN playwright install chromium \
    && playwright install-deps chromium

# ── App files ─────────────────────────────────────────────────────────────────
WORKDIR /app

COPY stream.py           /app/stream.py
COPY game.html           /app/game.html
COPY deathnote_music.mp3 /app/deathnote_music.mp3
COPY supervisord.conf    /etc/supervisor/conf.d/deathnote.conf

# ── Environment ───────────────────────────────────────────────────────────────
ENV DISPLAY=:99 \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# ── Entrypoint ────────────────────────────────────────────────────────────────
# supervisord manages: Xvfb + stream.py
CMD ["supervisord", "-n", "-c", "/etc/supervisor/supervisord.conf"]
