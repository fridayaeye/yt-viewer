#!/usr/bin/env python3
"""
yt_playwright_viewer.py — Playwright-based YouTube viewer
Uses real Chromium browser to load and play YouTube videos so views count.

Usage:
    python3 yt_playwright_viewer.py VIDEO_ID [--views N] [--workers N] [--watch-time N]

Env vars (for Railway):
    VIDEO_ID     — YouTube video ID
    WORKERS      — parallel workers (default 5)
    WATCH_TIME   — seconds to watch per view (default 60)
"""

import os
import sys
import time
import random
import string
import threading
import argparse
import subprocess
from datetime import datetime

# ─────────────────────────────── User-Agent Pool ────────────────────────────
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:124.0) Gecko/20100101 Firefox/124.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:123.0) Gecko/20100101 Firefox/123.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_4) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15",
]

# ─────────────────────────────── Global State ───────────────────────────────
stats = {
    "views_done": 0,
    "errors": 0,
    "start_time": time.time(),
    "lock": threading.Lock(),
}


def log(worker_id, msg):
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] [W{worker_id:02d}] {msg}", flush=True)


def random_cpn():
    """Generate a random Content Playback Nonce (16 chars)"""
    chars = string.ascii_letters + string.digits + "-_"
    return "".join(random.choices(chars, k=16))


# ─────────────────────────────── Resource Blocker ───────────────────────────
def block_unnecessary(route):
    """Block non-essential resources to save bandwidth."""
    url = route.request.url
    resource = route.request.resource_type

    # Block images (thumbnails, avatars, etc.) — not needed for playback
    if resource == "image":
        route.abort()
        return

    # Block fonts
    if resource == "font":
        route.abort()
        return

    # Block stylesheets (YouTube works without them for playback)
    if resource == "stylesheet":
        route.abort()
        return

    # Block high-quality video streams (1080p, 720p) to save bandwidth
    # Only allow up to 360p (itag=18, itag=134, itag=160)
    if "googlevideo.com" in url:
        blocked_itags = [
            "itag=137",   # 1080p video
            "itag=248",   # 1080p webm
            "itag=136",   # 720p video
            "itag=247",   # 720p webm
            "itag=135",   # 480p video
            "itag=244",   # 480p webm
        ]
        for itag in blocked_itags:
            if itag in url:
                route.abort()
                return

    # Allow everything else: video streams, XHR/fetch (tracking pixels, ads), JS, etc.
    route.continue_()


# ─────────────────────────────── Single View Session ────────────────────────
def run_single_view(worker_id: int, video_id: str, watch_time: int) -> bool:
    """
    Open one YouTube video session, watch for watch_time seconds.
    Returns True on success, False on failure.
    """
    from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout

    ua = random.choice(USER_AGENTS)
    url = f"https://www.youtube.com/watch?v={video_id}&autoplay=1"

    try:
        with sync_playwright() as p:
            # Launch Chromium with stealth-friendly args
            browser = p.chromium.launch(
                headless=True,
                args=[
                    "--no-sandbox",
                    "--disable-setuid-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-accelerated-2d-canvas",
                    "--no-first-run",
                    "--no-zygote",
                    "--disable-gpu",
                    "--disable-blink-features=AutomationControlled",
                    "--disable-features=IsolateOrigins,site-per-process",
                    "--autoplay-policy=no-user-gesture-required",
                    "--disable-infobars",
                    "--window-size=1280,720",
                ],
            )

            context = browser.new_context(
                user_agent=ua,
                viewport={"width": 1280, "height": 720},
                locale="en-US",
                timezone_id="America/New_York",
                # Pretend to be a real device
                device_scale_factor=1,
                has_touch=False,
                is_mobile=False,
                # Accept video media
                permissions=[],
            )

            page = context.new_page()

            # Apply stealth patches
            try:
                from playwright_stealth import Stealth
                Stealth().apply_stealth_sync(page)
                log(worker_id, "Stealth applied ✓")
            except Exception as e:
                log(worker_id, f"Stealth warning (continuing): {e}")

            # Block unnecessary resources
            page.route("**/*", block_unnecessary)

            log(worker_id, f"Loading {url}")
            try:
                page.goto(url, timeout=30000, wait_until="domcontentloaded")
            except PlaywrightTimeout:
                log(worker_id, "Page load timeout (continuing anyway)")

            # Small wait for player to initialize
            time.sleep(2)

            # Try to click play if video is paused (some regions/ad scenarios)
            try:
                # Check if video is paused via JS
                is_paused = page.evaluate("""
                    () => {
                        const video = document.querySelector('video');
                        if (!video) return true;
                        return video.paused;
                    }
                """)

                if is_paused:
                    log(worker_id, "Video paused — clicking play button")
                    # Try clicking the large play button overlay
                    play_selectors = [
                        "button.ytp-play-button",
                        ".ytp-large-play-button",
                        "video",
                        "#movie_player",
                    ]
                    for sel in play_selectors:
                        try:
                            page.click(sel, timeout=2000)
                            log(worker_id, f"Clicked: {sel}")
                            break
                        except Exception:
                            continue

                    time.sleep(1)
                    # Force autoplay via JS as fallback
                    page.evaluate("""
                        () => {
                            const video = document.querySelector('video');
                            if (video) {
                                video.muted = true;
                                video.play().catch(() => {});
                            }
                        }
                    """)
                else:
                    log(worker_id, "Video already playing ✓")

            except Exception as e:
                log(worker_id, f"Play check error (continuing): {e}")
                # Try force-play via JS anyway
                try:
                    page.evaluate("""
                        () => {
                            const video = document.querySelector('video');
                            if (video) {
                                video.muted = true;
                                video.play().catch(() => {});
                            }
                        }
                    """)
                except Exception:
                    pass

            # Watch for the configured duration
            log(worker_id, f"Watching for {watch_time}s...")
            watch_start = time.time()
            check_interval = 10  # check video state every 10 seconds

            while time.time() - watch_start < watch_time:
                elapsed = time.time() - watch_start
                remaining = watch_time - elapsed

                # Log current playback position every 10 seconds
                try:
                    current_time = page.evaluate("""
                        () => {
                            const video = document.querySelector('video');
                            return video ? Math.floor(video.currentTime) : -1;
                        }
                    """)
                    log(worker_id, f"Playback: {current_time}s (watched {elapsed:.0f}/{watch_time}s)")
                except Exception:
                    log(worker_id, f"Watched {elapsed:.0f}/{watch_time}s")

                sleep_time = min(check_interval, remaining)
                if sleep_time > 0:
                    time.sleep(sleep_time)

            log(worker_id, f"View complete ✓ ({watch_time}s watched)")

            # Close browser cleanly
            context.close()
            browser.close()
            return True

    except Exception as e:
        log(worker_id, f"ERROR: {e}")
        return False


# ─────────────────────────────── Worker Thread ──────────────────────────────
def worker_thread(worker_id: int, video_id: str, views_target: int, watch_time: int):
    """Worker thread: runs views until target is reached."""
    views_done = 0

    while True:
        # Check if global target reached
        with stats["lock"]:
            if stats["views_done"] >= views_target:
                break

        success = run_single_view(worker_id, video_id, watch_time)

        with stats["lock"]:
            if success:
                stats["views_done"] += 1
                views_done += 1
            else:
                stats["errors"] += 1

            elapsed = time.time() - stats["start_time"]
            rate = stats["views_done"] / (elapsed / 3600) if elapsed > 0 else 0
            log(
                worker_id,
                f"[STATS] Total views: {stats['views_done']}/{views_target} | "
                f"Errors: {stats['errors']} | Rate: {rate:.1f}/hr"
            )

            if stats["views_done"] >= views_target:
                break

        # Small delay between sessions to avoid rate limiting
        delay = random.uniform(2, 5)
        time.sleep(delay)

    log(worker_id, f"Worker done. Local views: {views_done}")


# ─────────────────────────────── Install Check ──────────────────────────────
def ensure_playwright_installed():
    """Install Playwright Chromium if not already installed (for Railway/Linux)."""
    try:
        result = subprocess.run(
            ["python3", "-m", "playwright", "install", "--dry-run", "chromium"],
            capture_output=True, text=True, timeout=30
        )
        # On Linux, check if chromium binary exists
        import shutil
        # Check common playwright browser paths
        home = os.path.expanduser("~")
        chromium_paths = [
            f"{home}/.cache/ms-playwright/chromium-*/chrome-linux/chrome",
            f"{home}/Library/Caches/ms-playwright/chromium-*/chrome-mac/Chromium.app/Contents/MacOS/Chromium",
        ]
        import glob
        for pattern in chromium_paths:
            if glob.glob(pattern):
                print("Playwright Chromium already installed ✓")
                return
    except Exception:
        pass

    print("Installing Playwright Chromium...")
    subprocess.run(["python3", "-m", "playwright", "install", "chromium"], check=True)

    # On Linux, also install system dependencies
    if sys.platform == "linux":
        print("Installing Chromium system dependencies...")
        try:
            subprocess.run(
                ["python3", "-m", "playwright", "install-deps", "chromium"],
                check=True
            )
        except Exception as e:
            print(f"install-deps warning: {e} (may need sudo)")


# ─────────────────────────────── Main ───────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="Playwright YouTube view bot")
    parser.add_argument("video_id", nargs="?",
                        default=os.environ.get("VIDEO_ID", ""),
                        help="YouTube video ID (e.g. dQw4w9WgXcQ)")
    parser.add_argument("--views", type=int,
                        default=int(os.environ.get("VIEWS", "10")),
                        help="Total views to generate (default: 10)")
    parser.add_argument("--workers", type=int,
                        default=int(os.environ.get("WORKERS", "5")),
                        help="Parallel worker threads (default: 5)")
    parser.add_argument("--watch-time", type=int,
                        default=int(os.environ.get("WATCH_TIME", "60")),
                        help="Seconds to watch per view (default: 60)")
    parser.add_argument("--install", action="store_true",
                        help="Install Playwright Chromium before running")
    args = parser.parse_args()

    if not args.video_id:
        print("ERROR: video_id required (arg or VIDEO_ID env var)")
        parser.print_help()
        sys.exit(1)

    if args.install:
        ensure_playwright_installed()

    print("=" * 60)
    print(f"  YouTube Playwright Viewer")
    print(f"  Video ID:   {args.video_id}")
    print(f"  Target:     {args.views} views")
    print(f"  Workers:    {args.workers}")
    print(f"  Watch time: {args.watch_time}s")
    print(f"  URL:        https://youtube.com/watch?v={args.video_id}")
    print("=" * 60)

    stats["start_time"] = time.time()

    # Limit workers to views target
    actual_workers = min(args.workers, args.views)

    threads = []
    for i in range(actual_workers):
        t = threading.Thread(
            target=worker_thread,
            args=(i + 1, args.video_id, args.views, args.watch_time),
            daemon=True,
        )
        t.start()
        threads.append(t)
        # Stagger starts slightly
        time.sleep(random.uniform(0.5, 1.5))

    # Wait for all workers to finish
    for t in threads:
        t.join()

    elapsed = time.time() - stats["start_time"]
    print("=" * 60)
    print(f"  DONE!")
    print(f"  Views completed: {stats['views_done']}")
    print(f"  Errors:          {stats['errors']}")
    print(f"  Total time:      {elapsed:.0f}s")
    rate = stats["views_done"] / (elapsed / 3600) if elapsed > 0 else 0
    print(f"  Rate:            {rate:.1f} views/hr")
    print("=" * 60)


if __name__ == "__main__":
    main()
