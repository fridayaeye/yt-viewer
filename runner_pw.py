#!/usr/bin/env python3
"""
runner_pw.py — Railway orchestrator for Playwright YouTube viewer.

This script runs on Railway on startup:
1. Installs Playwright + Chromium (+ Linux deps)
2. Downloads yt_playwright_viewer.py from GitHub (or uses local copy)
3. Launches N parallel workers via subprocess
4. Logs progress continuously

Env vars:
    VIDEO_ID     — YouTube video ID (required)
    WORKERS      — parallel workers (default: 5)
    WATCH_TIME   — seconds per view (default: 60)
    VIEWS        — total views target (default: 99999 = run forever)
    GH_RAW_URL   — raw GitHub URL to fetch yt_playwright_viewer.py
                   (default: https://raw.githubusercontent.com/fridayaeye/yt-viewer/main/yt_playwright_viewer.py)
"""

import os
import sys
import subprocess
import time
import signal
import threading
from datetime import datetime


# ─────────────────────────────── Config ─────────────────────────────────────
VIDEO_ID   = os.environ.get("VIDEO_ID", "")
WORKERS    = int(os.environ.get("WORKERS", "5"))
WATCH_TIME = int(os.environ.get("WATCH_TIME", "60"))
VIEWS      = int(os.environ.get("VIEWS", "99999"))
GH_RAW_URL = os.environ.get(
    "GH_RAW_URL",
    "https://raw.githubusercontent.com/fridayaeye/yt-viewer/main/yt_playwright_viewer.py"
)
VIEWER_SCRIPT = "/tmp/yt_playwright_viewer.py"


def log(msg):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] [RUNNER] {msg}", flush=True)


# ─────────────────────────────── Install Step ────────────────────────────────
def install_playwright():
    log("Installing Playwright Chromium...")
    result = subprocess.run(
        [sys.executable, "-m", "playwright", "install", "chromium"],
        capture_output=False, text=True
    )
    if result.returncode != 0:
        log(f"playwright install failed (exit {result.returncode})")
        sys.exit(1)
    log("Playwright Chromium installed ✓")

    # On Linux, install system deps
    if sys.platform.startswith("linux"):
        log("Installing Chromium system dependencies...")
        result = subprocess.run(
            [sys.executable, "-m", "playwright", "install-deps", "chromium"],
            capture_output=False, text=True
        )
        if result.returncode != 0:
            log(f"install-deps warning (exit {result.returncode}) — continuing")
        else:
            log("Chromium deps installed ✓")

    # Install playwright-stealth if missing
    try:
        import playwright_stealth  # noqa: F401
        log("playwright-stealth already installed ✓")
    except ImportError:
        log("Installing playwright-stealth...")
        subprocess.run(
            [sys.executable, "-m", "pip", "install", "playwright-stealth"],
            check=True
        )
        log("playwright-stealth installed ✓")


# ─────────────────────────────── Download Script ─────────────────────────────
def download_viewer_script():
    """Download yt_playwright_viewer.py from GitHub, or use bundled copy."""
    import urllib.request

    # Try GitHub first
    try:
        log(f"Downloading viewer from {GH_RAW_URL}")
        urllib.request.urlretrieve(GH_RAW_URL, VIEWER_SCRIPT)
        log(f"Viewer downloaded → {VIEWER_SCRIPT} ✓")
        return
    except Exception as e:
        log(f"GitHub download failed: {e}")

    # Fallback: look for local copy next to this script
    local_candidates = [
        os.path.join(os.path.dirname(__file__), "yt_playwright_viewer.py"),
        "/app/yt_playwright_viewer.py",
        "/workspace/yt_playwright_viewer.py",
    ]
    for path in local_candidates:
        if os.path.exists(path):
            import shutil
            shutil.copy(path, VIEWER_SCRIPT)
            log(f"Using local copy: {path} → {VIEWER_SCRIPT} ✓")
            return

    log("ERROR: Could not find yt_playwright_viewer.py anywhere!")
    sys.exit(1)


# ─────────────────────────────── Worker Launcher ─────────────────────────────
active_procs = []
proc_lock = threading.Lock()
views_done = 0
errors_done = 0
stats_lock = threading.Lock()


def run_worker(worker_id: int, video_id: str, watch_time: int):
    """Launch a single viewer subprocess and monitor it."""
    global views_done, errors_done

    log(f"[W{worker_id:02d}] Starting worker")

    while True:
        # Check global view target
        with stats_lock:
            if views_done >= VIEWS:
                log(f"[W{worker_id:02d}] Target reached, exiting")
                return

        # Run one view
        proc = subprocess.Popen(
            [
                sys.executable,
                VIEWER_SCRIPT,
                video_id,
                "--views", "1",
                "--workers", "1",
                "--watch-time", str(watch_time),
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )

        with proc_lock:
            active_procs.append(proc)

        # Stream output
        for line in proc.stdout:
            line = line.rstrip()
            if line:
                print(f"[W{worker_id:02d}] {line}", flush=True)

        proc.wait()

        with proc_lock:
            if proc in active_procs:
                active_procs.remove(proc)

        with stats_lock:
            if proc.returncode == 0:
                views_done += 1
                log(f"[W{worker_id:02d}] View ✓ | Total: {views_done}/{VIEWS}")
            else:
                errors_done += 1
                log(f"[W{worker_id:02d}] Error (exit {proc.returncode}) | Errors: {errors_done}")

            if views_done >= VIEWS:
                return

        # Brief delay between views
        time.sleep(2)


# ─────────────────────────────── Graceful Shutdown ───────────────────────────
def shutdown(signum, frame):
    log(f"Signal {signum} received — shutting down workers...")
    with proc_lock:
        for proc in active_procs:
            try:
                proc.terminate()
            except Exception:
                pass
    log("All workers terminated.")
    sys.exit(0)


signal.signal(signal.SIGTERM, shutdown)
signal.signal(signal.SIGINT, shutdown)


# ─────────────────────────────── Stats Thread ────────────────────────────────
def stats_reporter():
    """Print stats every 60 seconds."""
    start = time.time()
    while True:
        time.sleep(60)
        elapsed = time.time() - start
        rate = views_done / (elapsed / 3600) if elapsed > 0 else 0
        log(
            f"[STATS] Views: {views_done}/{VIEWS} | Errors: {errors_done} | "
            f"Rate: {rate:.1f}/hr | Uptime: {elapsed/3600:.1f}h"
        )


# ─────────────────────────────── Main ────────────────────────────────────────
def main():
    if not VIDEO_ID:
        log("ERROR: VIDEO_ID environment variable is required!")
        sys.exit(1)

    log("=" * 60)
    log("  Railway Playwright YouTube Viewer")
    log(f"  Video ID:   {VIDEO_ID}")
    log(f"  Workers:    {WORKERS}")
    log(f"  Watch time: {WATCH_TIME}s")
    log(f"  Target:     {VIEWS} views")
    log("=" * 60)

    # Step 1: Install playwright + chromium
    install_playwright()

    # Step 2: Download viewer script
    download_viewer_script()

    # Step 3: Launch stats reporter
    t_stats = threading.Thread(target=stats_reporter, daemon=True)
    t_stats.start()

    # Step 4: Launch worker threads
    threads = []
    for i in range(WORKERS):
        t = threading.Thread(
            target=run_worker,
            args=(i + 1, VIDEO_ID, WATCH_TIME),
            daemon=True,
        )
        t.start()
        threads.append(t)
        time.sleep(1)  # stagger starts

    # Wait for all workers
    for t in threads:
        t.join()

    log(f"All done! Total views: {views_done}, errors: {errors_done}")


if __name__ == "__main__":
    main()
