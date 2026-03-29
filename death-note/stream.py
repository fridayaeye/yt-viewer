#!/usr/bin/env python3
"""Death Note Livestream — Railway (headless Canvas, file-based ffmpeg)"""
import os, sys, time, random, signal, subprocess, threading
from pathlib import Path
try:
    import requests
except:
    requests = None

STREAM_KEY    = os.environ.get('STREAM_KEY', 'adma-1e6s-e536-0jrf-2dg3')
RTMP_URL      = f'rtmps://a.rtmp.youtube.com/live2/{STREAM_KEY}'
FPS           = int(os.environ.get('FPS', '5'))
NAME_INTERVAL = int(os.environ.get('NAME_INTERVAL', '8'))
YT_API_KEY    = os.environ.get('YOUTUBE_API_KEY', '')
VIDEO_ID      = os.environ.get('VIDEO_ID', '')
DEMO_MODE     = os.environ.get('DEMO_MODE', 'true').lower() == 'true'

GAME_HTML  = '/app/notebook.html'
MUSIC_FILE = '/app/deathnote_music.mp3'
FRAME_FILE = '/tmp/dn_frame.jpg'
FRAME_TMP  = '/tmp/dn_frame.tmp.jpg'

DEMO_NAMES = [
    "DarkKnight_99", "MisaMisa_fan", "L_detective", "anime_lover",
    "kira_justice", "ryuk_apples", "death_god_42", "shinigami_eyes",
    "light_yagami_x", "near_wins", "mello_choco", "matsuda_lol",
    "rem_sacrifice", "NightGod99", "DeathNoteOtaku", "ShinigamiKing",
    "ANGRYGRANNY", "FRED", "SilentKiller", "JusticeServd",
]

running = True
typed_names = set()
name_queue = []
name_lock = threading.Lock()
live_chat_id = None

def handle_signal(sig, frame):
    global running
    print("\n🛑 Stopping...", flush=True)
    running = False
signal.signal(signal.SIGINT, handle_signal)
signal.signal(signal.SIGTERM, handle_signal)

def resolve_chat_id():
    global live_chat_id
    if not VIDEO_ID or not YT_API_KEY:
        return None
    try:
        url = f"https://www.googleapis.com/youtube/v3/videos?part=liveStreamingDetails&id={VIDEO_ID}&key={YT_API_KEY}"
        r = requests.get(url, timeout=10).json()
        items = r.get('items', [])
        if items:
            cid = items[0].get('liveStreamingDetails', {}).get('activeLiveChatId')
            if cid:
                live_chat_id = cid
                print(f"📨 Chat ID resolved", flush=True)
                return cid
    except Exception as e:
        print(f"⚠️  {e}", flush=True)
    return None

def chat_poller_thread():
    global running, live_chat_id
    if DEMO_MODE or not YT_API_KEY:
        print("📝 Demo mode", flush=True)
        idx = 0
        while running:
            with name_lock:
                name_queue.append(DEMO_NAMES[idx % len(DEMO_NAMES)])
            idx += 1
            time.sleep(NAME_INTERVAL)
        return

    while running and not live_chat_id:
        resolve_chat_id()
        if not live_chat_id:
            with name_lock:
                name_queue.append(random.choice(DEMO_NAMES))
            time.sleep(NAME_INTERVAL)

    if not running:
        return
    print("🔴 Live Chat active", flush=True)
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
                if 'no longer live' in msg.lower():
                    print("⚠️  Stream ended — demo fallback", flush=True)
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
            poll_ms = data.get('pollingIntervalMillis', 5000)
            for item in data.get('items', []):
                name = item.get('authorDetails', {}).get('displayName', '')
                if name and name not in typed_names:
                    typed_names.add(name)
                    with name_lock:
                        name_queue.append(name)
                    print(f"  💬 {name}", flush=True)
            time.sleep(max(poll_ms / 1000, 3))
        except Exception as e:
            print(f"⚠️  {e}", flush=True)
            time.sleep(10)

def main():
    global running

    print(f"""
╔══════════════════════════════════════════╗
║   💀  Death Note Stream (Railway)  💀   ║
╚══════════════════════════════════════════╝
  RTMP  : {RTMP_URL}
  FPS   : {FPS}  |  Mode: {'DEMO' if DEMO_MODE else 'LIVE CHAT'}
  Video : {VIDEO_ID or 'N/A'}
""", flush=True)

    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        print("🌐 Launching headless Chromium...", flush=True)
        browser = p.chromium.launch(headless=True, args=['--no-sandbox', '--disable-dev-shm-usage', '--disable-gpu'])
        ctx = browser.new_context(viewport={'width': 1080, 'height': 1920})
        page = ctx.new_page()
        page.goto(f'file://{GAME_HTML}', wait_until='domcontentloaded')
        time.sleep(4)

        has_api = page.evaluate("typeof window.streamAPI !== 'undefined'")
        print(f"🔌 streamAPI: {'✅' if has_api else '❌'}", flush=True)
        if not has_api:
            browser.close()
            sys.exit(1)

        page.screenshot(path=FRAME_FILE, type='jpeg', quality=70, timeout=10000)
        print(f"📸 First frame: {os.path.getsize(FRAME_FILE):,} bytes", flush=True)

        # ffmpeg reads file in loop
        print("🎬 Starting ffmpeg...", flush=True)
        ffmpeg = subprocess.Popen([
            'ffmpeg', '-y',
            '-re', '-loop', '1', '-framerate', str(FPS),
            '-i', FRAME_FILE,
            '-stream_loop', '-1', '-i', MUSIC_FILE,
            '-c:v', 'libx264', '-preset', 'ultrafast', '-tune', 'zerolatency',
            '-pix_fmt', 'yuv420p', '-g', str(FPS*2),
            '-b:v', '2500k', '-maxrate', '2500k', '-bufsize', '5000k',
            '-s', '1080x1920',
            '-c:a', 'aac', '-b:a', '128k', '-ar', '44100',
            '-map', '0:v', '-map', '1:a',
            '-f', 'flv', RTMP_URL,
        ], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)

        time.sleep(3)
        if ffmpeg.poll() is not None:
            err = ffmpeg.stderr.read().decode(errors='replace')[-800:]
            print(f"❌ ffmpeg died!\n{err}", flush=True)
            browser.close()
            sys.exit(1)

        print(f"✅ ffmpeg PID: {ffmpeg.pid}", flush=True)
        print("🔴 LIVE!", flush=True)
        print("─" * 50, flush=True)

        chat_t = threading.Thread(target=chat_poller_thread, daemon=True)
        chat_t.start()

        frame_interval = 1.0 / FPS
        last_name_time = 0
        name_count = 0
        frame_count = 0
        t_start = time.time()

        try:
            while running:
                t0 = time.time()

                try:
                    page.screenshot(path=FRAME_TMP, type='jpeg', quality=70, timeout=5000)
                    os.rename(FRAME_TMP, FRAME_FILE)
                    frame_count += 1
                except Exception as e:
                    print(f"⚠️  Screenshot: {e}", flush=True)
                    break

                now = time.time()
                if now - last_name_time > NAME_INTERVAL:
                    name = None
                    with name_lock:
                        if name_queue:
                            name = name_queue.pop(0)
                    if name:
                        name_count += 1
                        is_super = random.random() < 0.15
                        ntype = 'superchat' if is_super else 'sub'
                        safe = name.replace("'", "\\'").replace('"', '\\"')
                        try:
                            page.evaluate(f'window.streamAPI.writeName("{safe}", "{ntype}")')
                        except Exception as e:
                            print(f"⚠️  Write: {e}", flush=True)
                        badge = "💰" if is_super else "✍️ "
                        print(f"  {badge} [{name_count:04d}] {name}", flush=True)
                        if name_count % 10 == 0:
                            print(f"📊 {name_count} names, {frame_count} frames", flush=True)
                        last_name_time = now

                if ffmpeg.poll() is not None:
                    print(f"❌ ffmpeg died (code {ffmpeg.returncode})", flush=True)
                    break

                elapsed = time.time() - t0
                sleep = frame_interval - elapsed
                if sleep > 0:
                    time.sleep(sleep)

                if frame_count % (FPS * 60) == 0 and frame_count > 0:
                    runtime = time.time() - t_start
                    print(f"💓 {frame_count} frames | {runtime/60:.1f}min | {name_count} names", flush=True)

        except KeyboardInterrupt:
            pass
        finally:
            running = False
            print("\n🧹 Cleaning up...", flush=True)
            try:
                ffmpeg.terminate()
                ffmpeg.wait(timeout=5)
            except:
                ffmpeg.kill()
            browser.close()
            print("✅ Done.", flush=True)

if __name__ == '__main__':
    main()
