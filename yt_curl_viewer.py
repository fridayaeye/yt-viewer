#!/usr/bin/env python3
"""
yt_curl_viewer.py — YouTube Ad Tracking Chain Replicator
=========================================================
Simulates a real YouTube watch session using only HTTP requests.
Fires all the same tracking/impression pixels a real browser would.

Based on captured ad chain from real browser session (31 requests).

Usage:
    python3 yt_curl_viewer.py dQw4w9WgXcQ
    python3 yt_curl_viewer.py dQw4w9WgXcQ --views 5 --warp
    python3 yt_curl_viewer.py dQw4w9WgXcQ --views 10 --warp --watch-time 45
"""

import re
import sys
import time
import random
import string
import argparse
import subprocess
import urllib.parse
from datetime import datetime

try:
    import requests
    from requests.adapters import HTTPAdapter
    from urllib3.util.retry import Retry
except ImportError:
    print("ERROR: requests not installed. Run: pip3 install requests")
    sys.exit(1)

# ─────────────────────────────────────────────
# USER-AGENT POOL (real Chrome/macOS strings)
# ─────────────────────────────────────────────
USER_AGENTS = [
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:128.0) Gecko/20100101 Firefox/128.0",
]

CONVERSION_ID = "962985656"

# ─────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────

def rand_str(n=16):
    """Generate random alphanumeric string (like cpn)."""
    chars = string.ascii_letters + string.digits
    return ''.join(random.choices(chars, k=n))


def rand_id(n=8):
    """Random short ID."""
    return ''.join(random.choices(string.ascii_letters + string.digits, k=n))


def rand_base64_id(n=22):
    """Random base64-ish ID like plid."""
    chars = string.ascii_letters + string.digits + '+/='
    return ''.join(random.choices(chars, k=n))


def ts_ms():
    """Current timestamp in milliseconds."""
    return int(time.time() * 1000)


def build_session(ua: str) -> requests.Session:
    """Build a requests.Session with retry logic and browser-like headers."""
    session = requests.Session()
    retry = Retry(
        total=3,
        backoff_factor=0.5,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET", "POST"],
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    # Base headers
    session.headers.update({
        "User-Agent": ua,
        "Accept-Language": "en-US,en;q=0.9",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Encoding": "gzip, deflate, br",
        "DNT": "1",
        "Sec-Fetch-Site": "same-origin",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-User": "?1",
        "Sec-Fetch-Dest": "document",
        "Upgrade-Insecure-Requests": "1",
        "Connection": "keep-alive",
    })
    return session


def jitter(base: float, pct: float = 0.3) -> float:
    """Add ±pct jitter to a base delay."""
    spread = base * pct
    return base + random.uniform(-spread, spread)


def sleep(secs: float):
    actual = max(0.05, jitter(secs))
    time.sleep(actual)


# ─────────────────────────────────────────────
# WARP IP ROTATION
# ─────────────────────────────────────────────

def rotate_warp():
    """Disconnect then reconnect Cloudflare WARP to get new IP."""
    print("  [WARP] Rotating IP...")
    try:
        subprocess.run(["warp-cli", "disconnect"], capture_output=True, timeout=10)
        time.sleep(1.5)
        subprocess.run(["warp-cli", "connect"], capture_output=True, timeout=10)
        time.sleep(3)  # Wait for connection
        print("  [WARP] Rotated ✓")
        return True
    except (subprocess.TimeoutExpired, FileNotFoundError) as e:
        print(f"  [WARP] Failed: {e}")
        return False


# ─────────────────────────────────────────────
# PHASE 1: PAGE FETCH + TOKEN EXTRACTION
# ─────────────────────────────────────────────

def fetch_page(session: requests.Session, video_id: str) -> dict:
    """
    GET youtube.com/watch?v=VIDEO_ID
    Extract: cpn, ei, cl, session_token, visitor_data, plid, vm, of, len
    Save cookies automatically via session.
    """
    url = f"https://www.youtube.com/watch?v={video_id}"
    headers = {
        "Referer": "https://www.youtube.com/",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
    }
    
    print(f"  [1] Fetching page: {url}")
    try:
        resp = session.get(url, headers=headers, timeout=20)
        resp.raise_for_status()
    except requests.RequestException as e:
        print(f"  [1] Page fetch FAILED: {e}")
        return {}

    html = resp.text
    tokens = {}

    # ── Extract cpn (Client Playback Nonce) ──
    # In the page JS: "cpn":"IydG8nuHO6Ay1Yib"
    m = re.search(r'"cpn":"([A-Za-z0-9_\-]{10,20})"', html)
    tokens['cpn'] = m.group(1) if m else rand_str(16)
    
    # ── Extract ei (Event ID) ──
    m = re.search(r'"eid":"([^"]+)"', html)
    if not m:
        m = re.search(r'[?&]ei=([A-Za-z0-9_\-]+)', html)
    tokens['ei'] = m.group(1) if m else rand_str(20)
    
    # ── Extract cl (Client Library version) ──
    m = re.search(r'"cver":"([^"]+)"', html)
    if not m:
        m = re.search(r'"cl":(\d+)', html)
    tokens['cver'] = m.group(1) if m else "2.20260325.08.00"
    
    # Also try page cl (different from cver)
    m = re.search(r'"pageLabel":"youtube\.desktop\.web_([^"]+)"', html)
    tokens['page_label'] = f"youtube.desktop.web_{m.group(1)}" if m else "youtube.desktop.web_20260325_08_RC00"
    
    m = re.search(r'"cl":(\d{8,12})', html)
    tokens['cl'] = m.group(1) if m else "888952760"

    # ── Extract session_token (XSRF) ──
    # Appears as "session_token" in page data or XSRF_TOKEN cookie
    m = re.search(r'"XSRF_TOKEN":"([^"]+)"', html)
    if not m:
        m = re.search(r'"xsrf_token":"([^"]+)"', html)
    if not m:
        m = re.search(r'session_token["\s]*[:=]["\s]*([A-Za-z0-9%+/=_\-]{20,200})', html)
    tokens['session_token'] = m.group(1) if m else ""
    # Fallback: check cookies
    if not tokens['session_token']:
        xsrf = session.cookies.get('XSRF_TOKEN', '')
        tokens['session_token'] = urllib.parse.quote(xsrf) if xsrf else ""

    # ── Extract visitor_data / x-goog-visitor-id ──
    m = re.search(r'"visitorData":"([^"]+)"', html)
    if not m:
        m = re.search(r'"VISITOR_DATA":"([^"]+)"', html)
    tokens['visitor_data'] = m.group(1) if m else ""

    # ── Extract plid (Player Load ID) ──
    m = re.search(r'"playerLoadId":"([^"]+)"', html)
    if not m:
        m = re.search(r'"plid":"([^"]{10,30})"', html)
    tokens['plid'] = m.group(1) if m else rand_base64_id(22)

    # ── Extract of (opaque field) ──
    m = re.search(r'"of":"([^"]{10,40})"', html)
    tokens['of'] = m.group(1) if m else rand_base64_id(24)

    # ── Extract video length ──
    m = re.search(r'"approxDurationMs":"(\d+)"', html)
    tokens['len'] = str(int(m.group(1)) / 1000) if m else "213.061"
    
    # ── Extract vm (video metadata blob) ──
    m = re.search(r'"vm":"([A-Za-z0-9+/=_\-]{30,})"', html)
    tokens['vm'] = m.group(1) if m else ""
    
    # ── Extract full pagead/lvz URLs (contains evtid + sigh signature) ──
    # Page has them with unicode escapes: \u003d = \u0026 &
    lvz_raw = re.findall(r'(https?://[^"]*pagead/lvz\?[^"]+)', html)
    lvz_urls = []
    for raw in lvz_raw:
        clean = raw.replace('\\u003d','=').replace('\\u0026','&')
        if clean not in lvz_urls:
            lvz_urls.append(clean)
    tokens['lvz_urls'] = lvz_urls
    # Also extract evtid separately for logging
    m = re.search(r'evtid(?:\\u003d|=)([A-Za-z0-9_\-]+)', html)
    tokens['evtid'] = m.group(1) if m else ""
    
    # ── Extract req_ts for pagead/lvz ──
    tokens['req_ts'] = str(int(time.time()))

    # ── Extract utuid (channel/user tracking ID) ──
    m = re.search(r'"utuid":"([^"]{10,30})"', html)
    tokens['utuid'] = m.group(1) if m else rand_base64_id(22)
    
    # ── Extract ptchn / oid (for ptracking) ──
    m = re.search(r'"ptchn":"([^"]+)"', html)
    tokens['ptchn'] = m.group(1) if m else rand_base64_id(22)
    m = re.search(r'"oid":"([^"]+)"', html)
    tokens['oid'] = m.group(1) if m else rand_base64_id(22)

    # ── Cookies ──
    visitor = session.cookies.get('VISITOR_INFO1_LIVE', '')
    ysc = session.cookies.get('YSC', '')
    tokens['visitor_info'] = visitor
    tokens['ysc'] = ysc

    # ── fexp (experiment flags from qoe URL) ──
    tokens['fexp'] = "v1%2C23848210%2C156434%2C15321210%2C11684381%2C53408%2C9105%2C22730%2C2821%2C106030%2C18644%2C77203%2C65%2C13917%2C26504%2C9252%2C3479%2C13030%2C23206%2C15179%2C20225%2C34437%2C8206%2C2625%2C1904%2C18126%2C9720%2C5385%2C25059%2C4174%2C12720%2C16963%2C764%2C13516%2C5189%2C1734%2C18069%2C1634%2C4571%2C5237%2C5801%2C1978%2C11442%2C4645%2C9404%2C23826%2C9500%2C1840%2C1058%2C11547%2C2178%2C5927%2C1764%2C1644%2C441%2C6962%2C2724%2C1363%2C518%2C725%2C8865%2C13159%2C446%2C5346%2C13952%2C993%2C455%2C328%2C7376%2C763%2C6250%2C2615%2C3686%2C14341%2C1170%2C1194%2C1905%2C389%2C953%2C2754%2C3358%2C1489%2C4996%2C2787%2C144%2C3794%2C2434%2C741%2C1181%2C2103%2C1439%2C1482%2C6491%2C1127%2C1563%2C4773%2C2468%2C2230%2C4595%2C1032"
    
    print(f"  [1] Tokens: cpn={tokens['cpn']}, ei={tokens['ei'][:12]}..., cl={tokens['cl']}")
    print(f"  [1] Cookies: VISITOR_INFO1_LIVE={visitor[:20] if visitor else 'none'}, YSC={ysc[:10] if ysc else 'none'}")
    return tokens


# ─────────────────────────────────────────────
# PHASE 1b: CDN PINGS (generate_204)
# ─────────────────────────────────────────────

CDN_PING_URLS = [
    "https://i.ytimg.com/generate_204",
    "https://www.youtube.com/generate_204",
    # Dynamic CDN — use a random one from typical pattern
    "https://rr1---sn-qxaelnll.googlevideo.com/generate_204",
    "https://rr4---sn-qxaeenlk.c.youtube.com/generate_204",
]

def fire_pings(session: requests.Session, video_id: str):
    """Fire generate_204 pings to CDN servers."""
    headers = {
        "Referer": "https://www.youtube.com/",
        "Sec-Fetch-Dest": "empty",
        "Sec-Fetch-Mode": "no-cors",
        "Sec-Fetch-Site": "cross-site",
    }
    for url in CDN_PING_URLS:
        try:
            r = session.get(url, headers=headers, timeout=5, allow_redirects=False)
            print(f"  [ping] {url.split('/')[2]} → {r.status_code}")
        except Exception as e:
            print(f"  [ping] {url.split('/')[2]} → ERR: {e}")
        sleep(0.2)
    
    # Also POST generate_204 to youtube.com (as captured)
    try:
        headers2 = dict(headers)
        headers2["Referer"] = f"https://www.youtube.com/watch?v={video_id}"
        r = session.post("https://www.youtube.com/generate_204", headers=headers2, timeout=5, allow_redirects=False)
        print(f"  [ping] POST youtube.com/generate_204 → {r.status_code}")
    except Exception as e:
        print(f"  [ping] POST generate_204 → ERR: {e}")

    # Doubleclick ad_status.js
    try:
        r = session.get("https://static.doubleclick.net/instream/ad_status.js",
                       headers={"Referer": "https://www.youtube.com/"}, timeout=5)
        print(f"  [ping] ad_status.js → {r.status_code}")
    except Exception as e:
        print(f"  [ping] ad_status.js → ERR: {e}")


# ─────────────────────────────────────────────
# PHASE 2: AD IMPRESSION
# ─────────────────────────────────────────────

def fire_ad_impression(session: requests.Session, video_id: str, tokens: dict):
    """
    Fire all ad impression tracking pixels:
    - googleads pagead/id
    - pagead/lvz (impression pixel)
    - pagead/viewthroughconversion
    - pagead/1p-user-list
    """
    ua = session.headers.get('User-Agent', USER_AGENTS[0])
    referer_yt = "https://www.youtube.com/"
    referer_watch = f"https://www.youtube.com/watch?v={video_id}"
    visitor_id = tokens.get('visitor_data', '')
    
    base_ch_headers = {
        "Referer": referer_yt,
        "Sec-Fetch-Dest": "empty",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Site": "cross-site",
    }
    
    # ── googleads.g.doubleclick.net/pagead/id ──
    for suffix in ["", "?slf_rd=1"]:
        url = f"https://googleads.g.doubleclick.net/pagead/id{suffix}"
        try:
            r = session.get(url, headers=base_ch_headers, timeout=8)
            print(f"  [ad] pagead/id{suffix} → {r.status_code}")
        except Exception as e:
            print(f"  [ad] pagead/id{suffix} → ERR: {e}")
        sleep(0.15)

    # ── pagead/lvz (impression pixel) — use REAL URLs from page ──
    lvz_urls = tokens.get('lvz_urls', [])
    if lvz_urls:
        for lvz_url in lvz_urls:
            try:
                r = session.get(lvz_url, headers={"Referer": referer_yt}, timeout=8)
                domain = re.search(r'//([^/]+)', lvz_url).group(1)
                print(f"  [ad] {domain}/pagead/lvz → {r.status_code}")
            except Exception as e:
                print(f"  [ad] pagead/lvz → ERR: {e}")
            sleep(0.2)
    else:
        print("  [ad] pagead/lvz → SKIPPED (no lvz URLs in page)")

    # ── pagead/viewthroughconversion ──
    utuid = tokens.get('utuid', rand_base64_id(22))
    vtc_params = {
        'backend': 'innertube',
        'cname': '1',
        'cver': '2_20260325',
        'data': f'backend=innertube;cname=1;cver=2_20260325;m=1;ptype=f_view;type=view;utuid={utuid};utvid={video_id};w=1',
        'foc_id': utuid,
        'label': 'followon_view',
        'ptype': 'f_view',
        'random': str(random.randint(100000000, 999999999)),
        'utuid': utuid,
    }
    vtc_headers = {
        "Referer": referer_watch,
        "x-goog-visitor-id": visitor_id,
        "Sec-Fetch-Dest": "empty",
        "Sec-Fetch-Mode": "cors",
    }
    
    for domain, path_prefix in [
        ("www.youtube.com", ""),
        ("googleads.g.doubleclick.net", ""),
    ]:
        url = f"https://{domain}/pagead/viewthroughconversion/{CONVERSION_ID}/?" + urllib.parse.urlencode(vtc_params)
        try:
            r = session.get(url, headers=vtc_headers, timeout=8)
            print(f"  [ad] {domain}/vtc → {r.status_code}")
        except Exception as e:
            print(f"  [ad] vtc → ERR: {e}")
        sleep(0.2)

    # ── pagead/1p-user-list ──
    ul_params = {
        'backend': 'innertube',
        'cname': '1',
        'cver': '2_20260325',
        'data': f'backend=innertube;cname=1;cver=2_20260325;m=1;ptype=f_view;type=view;utuid={utuid};utvid={video_id};w=1',
        'is_vtc': '0',
        'ptype': 'f_view',
        'random': str(random.randint(100000000, 999999999)),
        'utuid': utuid,
    }
    ul_headers = {
        "Referer": referer_yt,
    }
    for domain in ["www.google.com", "www.google.co.in"]:
        url = f"https://{domain}/pagead/1p-user-list/{CONVERSION_ID}/?" + urllib.parse.urlencode(ul_params)
        try:
            r = session.get(url, headers=ul_headers, timeout=8)
            print(f"  [ad] {domain}/1p-user-list → {r.status_code}")
        except Exception as e:
            print(f"  [ad] 1p-user-list → ERR: {e}")
        sleep(0.2)


# ─────────────────────────────────────────────
# PHASE 3: PLAYBACK START
# ─────────────────────────────────────────────

def build_yt_headers(session: requests.Session, video_id: str, tokens: dict) -> dict:
    """Build common YouTube XHR/fetch headers."""
    now_ms = ts_ms()
    visitor_id = tokens.get('visitor_data', '')
    cver = tokens.get('cver', '2.20260325.08.00')
    page_label = tokens.get('page_label', 'youtube.desktop.web_20260325_08_RC00')
    cl = tokens.get('cl', '888952760')
    
    return {
        "Referer": f"https://www.youtube.com/watch?v={video_id}",
        "x-youtube-client-name": "1",
        "x-youtube-client-version": cver,
        "x-youtube-page-label": page_label,
        "x-youtube-page-cl": cl,
        "x-youtube-utc-offset": "330",
        "x-youtube-time-zone": "Asia/Calcutta",
        "x-goog-visitor-id": visitor_id,
        "x-goog-event-time": str(now_ms),
        "x-goog-request-time": str(now_ms),
        "x-youtube-device": "cbr=Chrome&cbrand=apple&cbrver=131.0.0.0&ceng=WebKit&cengver=537.36&cos=Macintosh&cosver=10_15_7&cplatform=DESKTOP",
        "x-youtube-ad-signals": f"dt={now_ms}&flash=0&frm&u_tz=330&u_his=2&u_h=1080&u_w=1920&u_ah=1080&u_aw=1920&u_cd=24&bc=31&bih=1080&biw=1920&brdim=0%2C0%2C0%2C0%2C1920%2C0%2C1920%2C1080%2C1920%2C1080&vis=1&wgl=true&ca_type=image",
        "Sec-Fetch-Dest": "empty",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Site": "same-origin",
    }


def build_playback_params(video_id: str, tokens: dict, rt: float) -> dict:
    """Build params for /api/stats/playback."""
    cpn = tokens['cpn']
    cver = tokens.get('cver', '2.20260325.08.00')
    cl = tokens.get('cl', '888952760')
    ei = tokens.get('ei', rand_str(20))
    plid = tokens.get('plid', rand_base64_id(22))
    vm = tokens.get('vm', '')
    of = tokens.get('of', rand_base64_id(24))
    fexp = tokens.get('fexp', '')
    length = tokens.get('len', '213.061')

    return {
        'ns': 'yt',
        'el': 'detailpage',
        'cpn': cpn,
        'ver': '2',
        'cmt': '0.01',
        'fmt': '397',
        'fs': '0',
        'rt': str(round(rt, 3)),
        'euri': '',
        'lact': str(int(rt * 1000 - 43)),
        'cl': cl,
        'mos': '0',
        'volume': '100',
        'cbrand': 'apple',
        'cbr': 'Chrome',
        'cbrver': '131.0.0.0',
        'c': 'WEB',
        'cver': cver,
        'cplayer': 'UNIPLAYER',
        'cos': 'Macintosh',
        'cosver': '10_15_7',
        'cplatform': 'DESKTOP',
        'hl': 'en_US',
        'cr': 'IN',
        'len': length,
        'fexp': fexp,
        'rtn': '12',
        'afmt': '251',
        'muted': '0',
        'docid': video_id,
        'ei': ei,
        'plid': plid,
        'of': of,
        'vm': vm,
    }


def fire_playback_start(session: requests.Session, video_id: str, tokens: dict, rt: float = 5.31):
    """GET /api/stats/playback — marks the start of playback."""
    params = build_playback_params(video_id, tokens, rt)
    headers = build_yt_headers(session, video_id, tokens)
    
    url = "https://www.youtube.com/api/stats/playback?" + urllib.parse.urlencode(params)
    try:
        r = session.get(url, headers=headers, timeout=10)
        print(f"  [3] stats/playback → {r.status_code}")
        return r.status_code
    except Exception as e:
        print(f"  [3] stats/playback → ERR: {e}")
        return 0


# ─────────────────────────────────────────────
# PHASE 3b: PTRACKING
# ─────────────────────────────────────────────

def fire_ptracking(session: requests.Session, video_id: str, tokens: dict):
    """GET /ptracking — partner/channel tracking."""
    cpn = tokens['cpn']
    ei = tokens.get('ei', rand_str(20))
    ptchn = tokens.get('ptchn', rand_base64_id(22))
    oid = tokens.get('oid', rand_base64_id(22))
    
    params = {
        'html5': '1',
        'video_id': video_id,
        'cpn': cpn,
        'ei': ei,
        'ptk': 'youtube_single',
        'oid': oid,
        'ptchn': ptchn,
        'pltype': 'content',
    }
    headers = build_yt_headers(session, video_id, tokens)
    
    url = "https://www.youtube.com/ptracking?" + urllib.parse.urlencode(params)
    try:
        r = session.get(url, headers=headers, timeout=10)
        print(f"  [3] ptracking → {r.status_code}")
        return r.status_code
    except Exception as e:
        print(f"  [3] ptracking → ERR: {e}")
        return 0


# ─────────────────────────────────────────────
# PHASE 3c: WATCHTIME (every ~10s)
# ─────────────────────────────────────────────

def fire_watchtime(session: requests.Session, video_id: str, tokens: dict,
                   st: float, et: float, rt: float, rtn: int):
    """GET /api/stats/watchtime — sent every ~10 seconds during playback."""
    cpn = tokens['cpn']
    cver = tokens.get('cver', '2.20260325.08.00')
    cl = tokens.get('cl', '888952760')
    ei = tokens.get('ei', rand_str(20))
    plid = tokens.get('plid', rand_base64_id(22))
    vm = tokens.get('vm', '')
    of = tokens.get('of', rand_base64_id(24))
    fexp = tokens.get('fexp', '')
    length = tokens.get('len', '213.061')

    params = {
        'ns': 'yt',
        'el': 'detailpage',
        'cpn': cpn,
        'ver': '2',
        'cmt': str(round(et, 3)),
        'fmt': '397',
        'fs': '0',
        'rt': str(round(rt, 3)),
        'euri': '',
        'lact': str(int(et * 1000)),
        'cl': cl,
        'state': 'playing',
        'volume': '100',
        'cbrand': 'apple',
        'cbr': 'Chrome',
        'cbrver': '131.0.0.0',
        'c': 'WEB',
        'cver': cver,
        'cplayer': 'UNIPLAYER',
        'cos': 'Macintosh',
        'cosver': '10_15_7',
        'cplatform': 'DESKTOP',
        'hl': 'en_US',
        'cr': 'IN',
        'len': length,
        'fexp': fexp,
        'rtn': str(rtn),
        'afmt': '251',
        'idpj': '-4',
        'ldpj': '-27',
        'rti': str(int(rt)),
        'st': str(round(st, 3)),
        'et': str(round(et, 3)),
        'muted': '0',
        'docid': video_id,
        'ei': ei,
        'plid': plid,
        'of': of,
        'vm': vm,
    }
    headers = build_yt_headers(session, video_id, tokens)
    
    url = "https://www.youtube.com/api/stats/watchtime?" + urllib.parse.urlencode(params)
    try:
        r = session.get(url, headers=headers, timeout=10)
        print(f"  [wt] watchtime st={round(st,1)}-{round(et,1)}s → {r.status_code}")
        return r.status_code
    except Exception as e:
        print(f"  [wt] watchtime → ERR: {e}")
        return 0


# ─────────────────────────────────────────────
# PHASE 3d: ATR (Ad Timing Report)
# ─────────────────────────────────────────────

def fire_atr(session: requests.Session, video_id: str, tokens: dict, cmt: float = 1.054, rt: float = 6.389):
    """POST /api/stats/atr — Ad timing report."""
    cpn = tokens['cpn']
    cver = tokens.get('cver', '2.20260325.08.00')
    cl = tokens.get('cl', '888952760')
    ei = tokens.get('ei', rand_str(20))
    plid = tokens.get('plid', rand_base64_id(22))
    vm = tokens.get('vm', '')
    fexp = tokens.get('fexp', '')
    length = tokens.get('len', '213.061')
    session_token = tokens.get('session_token', '')

    params = {
        'ns': 'yt',
        'el': 'detailpage',
        'cpn': cpn,
        'ver': '2',
        'cmt': str(round(cmt, 3)),
        'fmt': '397',
        'fs': '0',
        'rt': str(round(rt, 3)),
        'euri': '',
        'lact': str(int(cmt * 1000)),
        'cl': cl,
        'mos': '0',
        'volume': '100',
        'cbrand': 'apple',
        'cbr': 'Chrome',
        'cbrver': '131.0.0.0',
        'c': 'WEB',
        'cver': cver,
        'cplayer': 'UNIPLAYER',
        'cos': 'Macintosh',
        'cosver': '10_15_7',
        'cplatform': 'DESKTOP',
        'hl': 'en_US',
        'cr': 'IN',
        'len': length,
        'fexp': fexp,
        'afmt': '251',
        'muted': '0',
        'docid': video_id,
        'ei': ei,
        'plid': plid,
        'vm': vm,
    }
    
    headers = build_yt_headers(session, video_id, tokens)
    headers['content-type'] = 'application/x-www-form-urlencoded'
    
    url = "https://www.youtube.com/api/stats/atr?" + urllib.parse.urlencode(params)
    body = f"session_token={urllib.parse.quote(session_token)}" if session_token else ""
    
    try:
        r = session.post(url, data=body, headers=headers, timeout=10)
        print(f"  [ad] stats/atr → {r.status_code}")
        return r.status_code
    except Exception as e:
        print(f"  [ad] stats/atr → ERR: {e}")
        return 0


# ─────────────────────────────────────────────
# PHASE 4: QoE (Quality of Experience)
# ─────────────────────────────────────────────

def fire_qoe(session: requests.Session, video_id: str, tokens: dict,
             seq: int = 1, cmt: float = 5.0, rt: float = 10.0):
    """POST /api/stats/qoe — Quality of experience report."""
    cpn = tokens['cpn']
    cver = tokens.get('cver', '2.20260325.08.00')
    cl = tokens.get('cl', '888952760')
    ei = tokens.get('ei', rand_str(20))
    plid = tokens.get('plid', rand_base64_id(22))
    fexp = tokens.get('fexp', '')
    session_token = tokens.get('session_token', '')
    visitor_id = tokens.get('visitor_data', '')

    # Build qclc (quality check code)
    qclc_raw = f"ChB{cpn}EA{seq}"
    qclc = urllib.parse.quote(qclc_raw)

    params = {
        'fmt': '397',
        'afmt': '251',
        'cpn': cpn,
        'el': 'detailpage',
        'ns': 'yt',
        'fexp': fexp,
        'cl': cl,
        'seq': str(seq),
        'docid': video_id,
        'ei': ei,
        'event': 'streamingstats',
        'plid': plid,
        'cbrand': 'apple',
        'cbr': 'Chrome',
        'cbrver': '131.0.0.0',
        'c': 'WEB',
        'cver': cver,
        'cplayer': 'UNIPLAYER',
        'cos': 'Macintosh',
        'cosver': '10_15_7',
        'cplatform': 'DESKTOP',
        'cmt': f"{cmt:.3f}:0.000",
        'vps': f"{cmt:.3f}:PL",
        'bh': f"{cmt:.3f}:20.001",
        'bwm': f"{cmt:.3f}:888243:0.322",
        'bwe': f"{cmt:.3f}:641677",
        'bat': f"{cmt:.3f}:1:1",
        'df': f"{cmt:.3f}:59",
        'qclc': qclc,
    }
    
    headers = build_yt_headers(session, video_id, tokens)
    headers['content-type'] = 'text/plain;charset=UTF-8'
    headers['x-goog-visitor-id'] = visitor_id
    
    url = "https://www.youtube.com/api/stats/qoe?" + urllib.parse.urlencode(params)
    body = f"session_token={urllib.parse.quote(session_token)}" if session_token else ""
    
    try:
        r = session.post(url, data=body, headers=headers, timeout=10)
        print(f"  [qoe] stats/qoe seq={seq} → {r.status_code}")
        return r.status_code
    except Exception as e:
        print(f"  [qoe] stats/qoe → ERR: {e}")
        return 0


# ─────────────────────────────────────────────
# MAIN VIEW SIMULATION
# ─────────────────────────────────────────────

def simulate_view(video_id: str, watch_time: int = 35, ua: str = None) -> dict:
    """
    Simulate one complete YouTube view with ad tracking.
    Returns stats dict.
    """
    if ua is None:
        ua = random.choice(USER_AGENTS)
    
    t_start = time.time()
    results = {'ok': 0, 'err': 0, 'codes': []}
    
    session = build_session(ua)
    
    print(f"\n  UA: {ua[:60]}...")

    # ── Phase 1: Fetch page ──
    sleep(random.uniform(0.3, 1.2))
    tokens = fetch_page(session, video_id)
    if not tokens:
        return {'ok': 0, 'err': 1, 'codes': [], 'elapsed': 0}
    
    sleep(jitter(1.0))

    # ── Phase 1b: CDN pings ──
    print("  [2] Firing CDN pings...")
    fire_pings(session, video_id)
    sleep(jitter(0.8))

    # ── Phase 2: Ad impression ──
    print("  [2] Firing ad impressions...")
    fire_ad_impression(session, video_id, tokens)
    sleep(jitter(1.5))

    # ── Phase 3: Playback start ──
    print("  [3] Firing playback start...")
    rt = random.uniform(4.5, 7.0)
    code = fire_playback_start(session, video_id, tokens, rt=rt)
    results['codes'].append(code)
    sleep(jitter(0.5))

    # ── Phase 3b: ptracking ──
    code = fire_ptracking(session, video_id, tokens)
    results['codes'].append(code)
    sleep(jitter(0.3))

    # ── Phase 3c: ATR (initial) ──
    fire_atr(session, video_id, tokens, cmt=1.054, rt=rt)
    sleep(jitter(0.5))

    # ── Phase 4: QoE initial ──
    fire_qoe(session, video_id, tokens, seq=1, cmt=2.0, rt=rt)
    sleep(jitter(0.5))

    # ── Phase 3c: Watchtime loop ──
    print(f"  [wt] Starting watchtime loop ({watch_time}s)...")
    interval = random.uniform(8.0, 12.0)
    st = 0.0
    rtn_counter = 12
    qoe_seq = 2
    
    elapsed_watch = 0.0
    while elapsed_watch < watch_time:
        actual_sleep = min(interval, watch_time - elapsed_watch)
        time.sleep(actual_sleep + random.uniform(-0.5, 0.5))
        elapsed_watch += actual_sleep
        
        et = elapsed_watch
        actual_rt = rt + elapsed_watch
        rtn_counter += random.randint(8, 18)
        
        code = fire_watchtime(session, video_id, tokens,
                              st=st, et=et, rt=actual_rt, rtn=rtn_counter)
        results['codes'].append(code)
        
        # Fire QoE every 2nd watchtime
        if rtn_counter % 25 < 15:
            fire_qoe(session, video_id, tokens, seq=qoe_seq, cmt=et, rt=actual_rt)
            qoe_seq += 1
        
        st = et
        interval = random.uniform(8.0, 12.0)

    # ── Final ATR ──
    fire_atr(session, video_id, tokens, cmt=elapsed_watch, rt=rt + elapsed_watch)

    # ── Final QoE ──
    fire_qoe(session, video_id, tokens, seq=qoe_seq, cmt=elapsed_watch, rt=rt + elapsed_watch)

    elapsed = time.time() - t_start
    results['elapsed'] = round(elapsed, 1)
    results['ok'] = sum(1 for c in results['codes'] if c in (200, 204))
    results['err'] = sum(1 for c in results['codes'] if c not in (200, 204, 0))
    
    return results


# ─────────────────────────────────────────────
# ENTRY POINT
# ─────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="YouTube Ad Tracking Chain Simulator — fires all tracking pixels a real browser would"
    )
    parser.add_argument("video_id", help="YouTube video ID (e.g. dQw4w9WgXcQ)")
    parser.add_argument("--views", type=int, default=1, help="Number of views to simulate (default: 1)")
    parser.add_argument("--warp", action="store_true", help="Rotate WARP IP between views")
    parser.add_argument("--watch-time", type=int, default=35, help="Seconds to simulate watching (default: 35)")
    parser.add_argument("--delay", type=float, default=5.0, help="Delay between views in seconds (default: 5)")
    args = parser.parse_args()

    print(f"""
╔══════════════════════════════════════════════╗
║   YT Ad Chain Simulator — yt_curl_viewer.py  ║
╚══════════════════════════════════════════════╝
  Video:      {args.video_id}
  Views:      {args.views}
  Watch time: {args.watch_time}s
  WARP:       {'enabled' if args.warp else 'disabled'}
  Started:    {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
""")

    total_ok = 0
    total_err = 0
    total_time = 0.0
    
    for i in range(1, args.views + 1):
        print(f"━━━ View {i}/{args.views} ━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        
        if args.warp and i > 1:
            rotate_warp()
        
        ua = random.choice(USER_AGENTS)
        
        try:
            stats = simulate_view(args.video_id, watch_time=args.watch_time, ua=ua)
            total_ok += stats.get('ok', 0)
            total_err += stats.get('err', 0)
            total_time += stats.get('elapsed', 0)
            elapsed = stats.get('elapsed', 0)
            print(f"\n  ✓ View {i} complete: {stats['ok']} OK, {stats['err']} errors, {elapsed}s")
        except KeyboardInterrupt:
            print("\n  Interrupted by user.")
            break
        except Exception as e:
            print(f"  ✗ View {i} FAILED: {e}")
            total_err += 1
        
        if i < args.views:
            delay = jitter(args.delay)
            print(f"  Waiting {delay:.1f}s before next view...")
            time.sleep(delay)

    avg_time = total_time / args.views if args.views else 0
    print(f"""
╔══════════════════════════════════════════════╗
║                  FINAL STATS                 ║
╚══════════════════════════════════════════════╝
  Views completed:  {args.views}
  Total OK pings:   {total_ok}
  Total errors:     {total_err}
  Avg time/view:    {avg_time:.1f}s
  Finished:         {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
""")


if __name__ == "__main__":
    main()
