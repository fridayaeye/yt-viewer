#!/usr/bin/env python3
"""
Railway YouTube Viewer Runner
Runs parallel workers with WARP IP rotation
Config via environment variables
"""
import os
import sys
import time
import threading
import subprocess
import signal

# ─── Config from env ───
VIDEO_ID = os.environ.get("VIDEO_ID", "lwXMcTdz7PY")
WORKERS = int(os.environ.get("WORKERS", "10"))
WATCH_TIME = int(os.environ.get("WATCH_TIME", "3960"))  # 66 min default
TOTAL_VIEWS = int(os.environ.get("TOTAL_VIEWS", "0"))  # 0 = infinite
WARP_ROTATE_EVERY = int(os.environ.get("WARP_ROTATE_EVERY", "5"))  # Rotate WARP every N views per worker
USE_WARP = os.environ.get("USE_WARP", "true").lower() == "true"

completed = 0
errors = 0
lock = threading.Lock()
running = True

def setup_warp():
    """Initialize WARP on container start"""
    if not USE_WARP:
        print("[WARP] Disabled")
        return
    try:
        # Register WARP
        subprocess.run(["warp-cli", "--accept-tos", "registration", "new"], 
                      capture_output=True, timeout=30)
        time.sleep(2)
        # Connect
        subprocess.run(["warp-cli", "connect"], capture_output=True, timeout=15)
        time.sleep(3)
        # Check IP
        try:
            import requests as req
            ip = req.get("https://ipinfo.io/ip", timeout=5).text.strip()
            print(f"[WARP] Connected. IP: {ip}")
        except:
            print("[WARP] Connected (IP check failed)")
    except Exception as e:
        print(f"[WARP] Setup failed: {e}")

def rotate_warp():
    """Disconnect and reconnect WARP for new IP"""
    if not USE_WARP:
        return
    try:
        subprocess.run(["warp-cli", "disconnect"], capture_output=True, timeout=10)
        time.sleep(1)
        subprocess.run(["warp-cli", "connect"], capture_output=True, timeout=10)
        time.sleep(2)
    except:
        pass

def worker(worker_id):
    global completed, errors, running
    view_count = 0
    
    while running:
        if TOTAL_VIEWS > 0 and completed >= TOTAL_VIEWS:
            break
        
        try:
            result = subprocess.run(
                [sys.executable, "-u", "/app/yt_curl_viewer.py", VIDEO_ID, 
                 "--views", "1", "--watch-time", str(WATCH_TIME)],
                capture_output=True, text=True, timeout=WATCH_TIME + 120
            )
            
            with lock:
                if "View 1 complete" in result.stdout:
                    completed += 1
                    view_count += 1
                    print(f"✅ W{worker_id}: #{view_count} done (total: {completed})", flush=True)
                else:
                    errors += 1
                    # Print last few lines of output for debugging
                    lines = result.stdout.strip().split('\n')
                    last = lines[-1] if lines else "no output"
                    print(f"❌ W{worker_id}: failed - {last[:80]}", flush=True)
        except subprocess.TimeoutExpired:
            with lock:
                errors += 1
                print(f"⏰ W{worker_id}: timeout", flush=True)
        except Exception as e:
            with lock:
                errors += 1
                print(f"❌ W{worker_id}: error - {e}", flush=True)
        
        # Rotate WARP periodically
        if USE_WARP and view_count % WARP_ROTATE_EVERY == 0:
            rotate_warp()
        
        # Small delay
        time.sleep(2 + (worker_id % 3))

def signal_handler(sig, frame):
    global running
    print("\n🛑 Shutting down...", flush=True)
    running = False

signal.signal(signal.SIGTERM, signal_handler)
signal.signal(signal.SIGINT, signal_handler)

# ─── Main ───
print(f"""
╔══════════════════════════════════════════════╗
║   YT Viewer — Railway Edition                ║
╚══════════════════════════════════════════════╝
  Video:      {VIDEO_ID}
  Workers:    {WORKERS}
  Watch time: {WATCH_TIME}s ({WATCH_TIME/60:.0f} min)
  Total:      {'infinite' if TOTAL_VIEWS == 0 else TOTAL_VIEWS}
  WARP:       {USE_WARP}
  Started:    {time.strftime('%Y-%m-%d %H:%M:%S')}
""", flush=True)

# Setup WARP
setup_warp()

# Start workers
start = time.time()
threads = []
for w in range(WORKERS):
    t = threading.Thread(target=worker, args=(w+1,), daemon=True)
    t.start()
    threads.append(t)
    time.sleep(0.3)

# Status printer
try:
    while running:
        if TOTAL_VIEWS > 0 and completed >= TOTAL_VIEWS:
            break
        time.sleep(60)
        elapsed = time.time() - start
        rate = completed / elapsed * 3600 if elapsed > 0 else 0
        watch_hrs = completed * WATCH_TIME / 3600
        print(f"📊 Status: {completed} views | {errors} errors | {rate:.0f} views/hr | ~{watch_hrs:.1f} watch hours generated | uptime: {elapsed/3600:.1f}h", flush=True)
except KeyboardInterrupt:
    running = False

print(f"""
╔══════════════════════════════════════════════╗
║                  STOPPED                     ║
╚══════════════════════════════════════════════╝
  Completed: {completed}
  Errors:    {errors}
  Watch hrs: {completed * WATCH_TIME / 3600:.1f}
""", flush=True)
