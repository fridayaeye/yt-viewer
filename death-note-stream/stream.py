#!/usr/bin/env python3
"""
Death Note YouTube Livestream — Railway Edition
================================================
Architecture:
  - Xvfb :99 (1080x1920x24) — virtual framebuffer
  - Chromium (headless=False, inside Xvfb) — loads Flash via Ruffle
  - ffmpeg — x11grab :99 → H.264 → RTMP → YouTube
  - YouTube Live Chat API — names typed into game via Playwright
"""

import os, sys, time, random, signal, subprocess, threading
from pathlib import Path

try:
    import requests
except ImportError:
    requests = None

# ── Config ──────────────────────────────────────────────────────────────────
STREAM_KEY    = os.environ.get('STREAM_KEY', '')
RTMP_URL      = f'rtmp://a.rtmp.youtube.com/live2/{STREAM_KEY}'
FPS           = int(os.environ.get('FPS', '5'))
NAME_INTERVAL = int(os.environ.get('NAME_INTERVAL', '8'))
YT_API_KEY    = os.environ.get('YOUTUBE_API_KEY', '')
VIDEO_ID      = os.environ.get('VIDEO_ID', '')
DEMO_MODE     = os.environ.get('DEMO_MODE', 'false').lower() == 'true'
DISPLAY_NUM   = os.environ.get('DISPLAY', ':99')

SCRIPT_DIR  = Path(__file__).parent
MUSIC_FILE  = str(SCRIPT_DIR / 'deathnote_music.mp3')
GAME_HTML   = str(SCRIPT_DIR / 'game.html')

DEMO_NAMES = [
    "DarkKnight_99", "MisaMisa_fan", "L_detective", "anime_lover",
    "kira_justice", "ryuk_apples", "death_god_42", "shinigami_eyes",
    "light_yagami_x", "near_wins", "mello_choco", "matsuda_lol",
    "rem_sacrifice", "NightGod99", "DeathNoteOtaku", "ShinigamiKing",
    "ANGRYGRANNY", "FRED", "SilentKiller", "JusticeServd",
    "KiraApproves", "RyukFan2025", "GodOfNewWorld", "MisaAmane_x",
    "LLawliet42", "NearChess", "MelloPunk", "WatariSecrets",
]

# ── Globals ──────────────────────────────────────────────────────────────────
running       = True
typed_names   = set()
name_queue    = []
name_lock     = threading.Lock()
live_chat_id  = None

def handle_signal(sig, frame):
    global running
    print("\n🛑 Stopping...", flush=True)
    running = False

signal.signal(signal.SIGINT,  handle_signal)
signal.signal(signal.SIGTERM, handle_signal)


# ── Xvfb ─────────────────────────────────────────────────────────────────────
def xvfb_is_running():
    """Check if Xvfb is already running on :99."""
    try:
        result = subprocess.run(['xdpyinfo', '-display', ':99'],
                                capture_output=True, timeout=3)
        return result.returncode == 0
    except Exception:
        return False

def start_xvfb():
    """Start Xvfb on :99 1080x1920x24. Returns process or None if already running."""
    if xvfb_is_running():
        print("🖥️  Xvfb already running on :99 (started by supervisor)", flush=True)
        os.environ['DISPLAY'] = ':99'
        return None
    print("🖥️  Starting Xvfb :99 (1080x1920x24)...", flush=True)
    proc = subprocess.Popen([
        'Xvfb', ':99',
        '-screen', '0', '1080x1920x24',
        '-ac',        # disable access control
        '+extension', 'GLX',
    ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(2)
    if proc.poll() is not None:
        print("❌ Xvfb failed to start!", flush=True)
        sys.exit(1)
    os.environ['DISPLAY'] = ':99'
    print(f"✅ Xvfb PID {proc.pid}", flush=True)
    return proc


# ── YouTube Live Chat ─────────────────────────────────────────────────────────
def resolve_chat_id():
    global live_chat_id
    if not VIDEO_ID or not YT_API_KEY or not requests:
        return None
    try:
        url = (f"https://www.googleapis.com/youtube/v3/videos"
               f"?part=liveStreamingDetails&id={VIDEO_ID}&key={YT_API_KEY}")
        r = requests.get(url, timeout=10).json()
        items = r.get('items', [])
        if items:
            cid = items[0].get('liveStreamingDetails', {}).get('activeLiveChatId')
            if cid:
                live_chat_id = cid
                print(f"📨 Chat ID resolved: {cid[:20]}...", flush=True)
                return cid
    except Exception as e:
        print(f"⚠️  resolve_chat_id: {e}", flush=True)
    return None


def chat_poller_thread():
    global running, live_chat_id

    if DEMO_MODE or not YT_API_KEY or not requests:
        print("📝 Demo mode — using DEMO_NAMES", flush=True)
        idx = 0
        while running:
            with name_lock:
                name_queue.append(DEMO_NAMES[idx % len(DEMO_NAMES)])
            idx += 1
            time.sleep(NAME_INTERVAL)
        return

    # Wait for live chat ID
    while running and not live_chat_id:
        resolve_chat_id()
        if not live_chat_id:
            with name_lock:
                name_queue.append(random.choice(DEMO_NAMES))
            time.sleep(NAME_INTERVAL)

    if not running:
        return

    print("🔴 Live Chat active — polling for names", flush=True)
    next_page = None

    while running:
        try:
            url = (f"https://www.googleapis.com/youtube/v3/liveChat/messages"
                   f"?liveChatId={live_chat_id}&part=snippet,authorDetails"
                   f"&key={YT_API_KEY}&maxResults=50")
            if next_page:
                url += f"&pageToken={next_page}"
            data = requests.get(url, timeout=10).json()

            if 'error' in data:
                msg = data['error'].get('message', '')
                print(f"⚠️  API error: {msg}", flush=True)
                if 'no longer live' in msg.lower():
                    print("⚠️  Stream ended — switching to demo", flush=True)
                    DEMO_MODE_fallback = True
                    idx = 0
                    while running:
                        with name_lock:
                            name_queue.append(DEMO_NAMES[idx % len(DEMO_NAMES)])
                        idx += 1
                        time.sleep(NAME_INTERVAL)
                    return
                time.sleep(30)
                continue

            next_page = data.get('nextPageToken')
            poll_ms   = data.get('pollingIntervalMillis', 5000)

            for item in data.get('items', []):
                name = item.get('authorDetails', {}).get('displayName', '')
                if name and name not in typed_names:
                    typed_names.add(name)
                    with name_lock:
                        name_queue.append(name)
                    print(f"  💬 {name}", flush=True)

            time.sleep(max(poll_ms / 1000.0, 3))

        except Exception as e:
            print(f"⚠️  Chat poll error: {e}", flush=True)
            time.sleep(10)


# ── ffmpeg ────────────────────────────────────────────────────────────────────
def start_ffmpeg():
    """Launch ffmpeg with x11grab capturing :99 and streaming to RTMP."""
    print(f"🎬 Starting ffmpeg (x11grab :99 → {RTMP_URL[:40]}...)...", flush=True)

    has_music = os.path.exists(MUSIC_FILE)
    print(f"🎵 Music: {'YES' if has_music else 'NO (silent audio)'}", flush=True)

    if has_music:
        cmd = [
            'ffmpeg', '-y',
            # Video: x11grab from Xvfb
            '-f', 'x11grab',
            '-video_size', '1080x1920',
            '-framerate', str(FPS),
            '-i', ':99',
            # Audio: loop music file
            '-stream_loop', '-1',
            '-i', MUSIC_FILE,
            # Video encode
            '-filter_complex', '[0:v]format=yuv420p[v]',
            '-map', '[v]',
            '-map', '1:a',
            '-c:v', 'libx264',
            '-preset', 'ultrafast',
            '-tune', 'zerolatency',
            '-g', str(FPS * 2),
            '-b:v', '2500k',
            '-maxrate', '2500k',
            '-bufsize', '5000k',
            # Audio encode
            '-c:a', 'aac',
            '-b:a', '128k',
            '-ar', '44100',
            '-shortest',
            # Output
            '-f', 'flv',
            RTMP_URL,
        ]
    else:
        # Silent fallback: generate silent audio
        cmd = [
            'ffmpeg', '-y',
            '-f', 'x11grab',
            '-video_size', '1080x1920',
            '-framerate', str(FPS),
            '-i', ':99',
            '-f', 'lavfi',
            '-i', 'anullsrc=channel_layout=stereo:sample_rate=44100',
            '-filter_complex', '[0:v]format=yuv420p[v]',
            '-map', '[v]',
            '-map', '1:a',
            '-c:v', 'libx264',
            '-preset', 'ultrafast',
            '-tune', 'zerolatency',
            '-g', str(FPS * 2),
            '-b:v', '2500k',
            '-maxrate', '2500k',
            '-bufsize', '5000k',
            '-c:a', 'aac',
            '-b:a', '128k',
            '-ar', '44100',
            '-f', 'flv',
            RTMP_URL,
        ]

    proc = subprocess.Popen(
        cmd,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )
    return proc


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    global running

    print(f"""
╔══════════════════════════════════════════════╗
║   💀  Death Note Livestream  (Railway)  💀  ║
║   x11grab + Xvfb + Playwright + Ruffle      ║
╚══════════════════════════════════════════════╝
  RTMP      : {RTMP_URL}
  FPS       : {FPS}
  Interval  : {NAME_INTERVAL}s per name
  Mode      : {'DEMO' if DEMO_MODE else 'LIVE CHAT'}
  Video ID  : {VIDEO_ID or '(not set)'}
""", flush=True)

    # Validate
    if not STREAM_KEY:
        print("❌ STREAM_KEY not set!", flush=True)
        sys.exit(1)
    for label, path in [("Game HTML", GAME_HTML)]:
        if not os.path.exists(path):
            print(f"❌ {label} not found: {path}", flush=True)
            sys.exit(1)

    # 1. Start Xvfb
    xvfb_proc = start_xvfb()

    # 2. Launch Chromium via Playwright (headless=False, runs inside Xvfb)
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        print("🌐 Launching Chromium (visible, inside Xvfb)...", flush=True)
        browser = p.chromium.launch(
            headless=False,
            args=[
                '--no-sandbox',
                '--disable-setuid-sandbox',
                '--disable-dev-shm-usage',
                '--autoplay-policy=no-user-gesture-required',
                '--window-position=0,0',
                '--window-size=1080,1920',
                '--disable-gpu',
            ]
        )
        ctx  = browser.new_context(viewport={'width': 1080, 'height': 1920})
        page = ctx.new_page()
        page.goto(f'file://{GAME_HTML}', wait_until='domcontentloaded')

        print("⏳ Waiting 15s for Ruffle/Flash to load...", flush=True)
        time.sleep(15)

        # Click through any splash screens
        print("🖱️  Clicking through splash...", flush=True)
        for _ in range(5):
            page.mouse.click(540, 540)
            time.sleep(2)

        try:
            page.locator('ruffle-player').click(timeout=3000)
        except Exception:
            page.mouse.click(540, 540)
        time.sleep(1)
        print("🎮 Game ready", flush=True)

        # 3. Start ffmpeg
        ffmpeg = start_ffmpeg()
        time.sleep(3)
        if ffmpeg.poll() is not None:
            err = ffmpeg.stderr.read().decode(errors='replace')[-1000:]
            print(f"❌ ffmpeg died on start!\n{err}", flush=True)
            browser.close()
            if xvfb_proc: xvfb_proc.terminate()
            sys.exit(1)
        print(f"✅ ffmpeg running (PID {ffmpeg.pid})", flush=True)
        print("🔴 LIVE — starting name loop", flush=True)
        print("─" * 50, flush=True)

        # 4. Start chat polling thread
        chat_t = threading.Thread(target=chat_poller_thread, daemon=True)
        chat_t.start()

        # 5. Main loop: type names + monitor ffmpeg
        name_count    = 0
        last_name_time = 0

        try:
            while running:
                now = time.time()

                # Type next name if interval elapsed
                if now - last_name_time >= NAME_INTERVAL:
                    name = None
                    with name_lock:
                        if name_queue:
                            name = name_queue.pop(0)
                        elif DEMO_MODE or not YT_API_KEY:
                            name = DEMO_NAMES[name_count % len(DEMO_NAMES)]

                    if name:
                        name_count += 1
                        # Update overlay
                        try:
                            safe_name = name.replace("\\", "\\\\").replace('"', '\\"')
                            page.evaluate(
                                f'window.setCurrentName && window.setCurrentName("{safe_name}")'
                            )
                            # Update queue display
                            with name_lock:
                                queued = list(name_queue[:5])
                            if queued:
                                safe_q = str(queued).replace("'", '"')
                                page.evaluate(f'window.setQueue && window.setQueue({safe_q})')
                        except Exception:
                            pass

                        # Type into Flash game via keyboard
                        try:
                            for char in name.upper():
                                if not running:
                                    break
                                if char.isalpha() or char.isdigit():
                                    page.keyboard.press(char)
                                elif char == ' ':
                                    page.keyboard.press('Space')
                                elif char == '_':
                                    page.keyboard.press('Minus')
                                elif char == '-':
                                    page.keyboard.press('Minus')
                                time.sleep(random.uniform(0.05, 0.11))
                            time.sleep(0.3)
                            page.keyboard.press('Enter')
                        except Exception as e:
                            print(f"⚠️  Type error: {e}", flush=True)

                        print(f"  ✍️  [{name_count:04d}] {name}", flush=True)
                        if name_count % 10 == 0:
                            print(f"📊 Status: {name_count} names typed | queue={len(name_queue)}", flush=True)

                        last_name_time = now
                        time.sleep(2.5)

                # Health-check ffmpeg
                if ffmpeg.poll() is not None:
                    print(f"❌ ffmpeg died (exit {ffmpeg.returncode}) — restarting...", flush=True)
                    try:
                        err = ffmpeg.stderr.read().decode(errors='replace')[-500:]
                        print(err, flush=True)
                    except Exception:
                        pass
                    # Restart ffmpeg
                    ffmpeg = start_ffmpeg()
                    time.sleep(3)
                    if ffmpeg.poll() is not None:
                        print("❌ ffmpeg restart failed — giving up", flush=True)
                        break
                    print(f"✅ ffmpeg restarted (PID {ffmpeg.pid})", flush=True)

                time.sleep(0.4)

        except KeyboardInterrupt:
            pass

        finally:
            running = False
            print("\n🧹 Cleaning up...", flush=True)
            try:
                ffmpeg.terminate()
                ffmpeg.wait(timeout=5)
            except Exception:
                try:
                    ffmpeg.kill()
                except Exception:
                    pass
            try:
                browser.close()
            except Exception:
                pass
            try:
                if xvfb_proc: xvfb_proc.terminate()
            except Exception:
                pass
            print("✅ Done.", flush=True)


if __name__ == '__main__':
    main()
