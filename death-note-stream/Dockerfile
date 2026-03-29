# Death Note Livestream — Railway Docker Image
# Platform: linux/amd64
# Stack: Python 3.11 + Xvfb + Chromium + ffmpeg + Playwright

FROM python:3.11-slim-bookworm

# ── System packages ────────────────────────────────────────────────────────────
# Install everything in one layer to keep image lean
RUN apt-get update && apt-get install -y --no-install-recommends \
    # Virtual framebuffer
    xvfb \
    x11-utils \
    # Chromium and its runtime dependencies
    chromium \
    chromium-driver \
    # ffmpeg with x264 support
    ffmpeg \
    # Fonts for rendering
    fonts-liberation \
    fonts-noto \
    # Network tools
    ca-certificates \
    curl \
    # Process management
    supervisor \
    # Python extras
    python3-pip \
    && rm -rf /var/lib/apt/lists/*

# ── Python dependencies ────────────────────────────────────────────────────────
RUN pip install --no-cache-dir \
    playwright==1.44.0 \
    requests==2.31.0

# Install Playwright's bundled Chromium (needed for playwright.chromium.launch)
# We'll use system chromium but playwright needs its own for headless=False support
RUN playwright install chromium \
    && playwright install-deps chromium

# ── App files ─────────────────────────────────────────────────────────────────
WORKDIR /app

COPY stream.py           /app/stream.py
COPY game.html           /app/game.html
COPY deathnote_music.mp3 /app/deathnote_music.mp3
COPY supervisord.conf    /etc/supervisor/conf.d/deathnotе.conf

# ── Environment ───────────────────────────────────────────────────────────────
ENV DISPLAY=:99 \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# ── Entrypoint ────────────────────────────────────────────────────────────────
# supervisord manages: Xvfb + stream.py
CMD ["supervisord", "-n", "-c", "/etc/supervisor/supervisord.conf"]
