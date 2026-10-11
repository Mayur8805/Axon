import os
import json
import re
import time
import base64
import string
import subprocess
import requests
from urllib.parse import quote, urljoin, unquote

from bs4 import BeautifulSoup
from myjdapi import Myjdapi
from dotenv import load_dotenv
from core.menu import get_input

load_dotenv()

# ── DinoTube search state ──────────────────────────────────────────────────────
# When the user types "dinotube.com" inside the JDownloader prompt we switch into
# a DinoTube search mode: the next query is searched on dinotube.com instead of
# being handed straight to JDownloader.
_dinotube_active = False
DINOTUBE_BASE = "https://www.dinotube.com"
DINOTUBE_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)
QUALITY_OPTIONS = ["All", "HD", "4K"]

email = os.getenv("JD_EMAIL")
password = os.getenv("JD_PASSWORD")
DOWNLOAD_PATH  = os.path.abspath("Downloads/Videos")
os.makedirs(DOWNLOAD_PATH, exist_ok=True)

jd = Myjdapi()
jd.set_app_key("myapp")

device = None


JD_LAUNCHER = os.path.expanduser(
    "~/Downloads/jdownloader/jd2/JDownloader2"
)


def _is_jdownloader_running() -> bool:
    try:
        return bool(
            subprocess.run(
                ["pgrep", "-f", "JDownloader.jar"],
                capture_output=True, text=True,
            ).stdout.strip()
        )
    except Exception:
        return False


def _launch_jdownloader() -> None:
    if _is_jdownloader_running() or not os.path.exists(JD_LAUNCHER):
        return
    subprocess.Popen(
        ["nohup", JD_LAUNCHER],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )


def _connect(force=False):
    global device
    if device is not None and not force:
        return device
    if force:
        device = None
    try:
        jd.connect(email, password)
        device = jd.get_device("JDownloader@makwana")
    except Exception:
        device = None
        # JDownloader is likely not running — try to launch it in the background
        # and wait for it to come online, then retry once.
        if not _is_jdownloader_running():
            _launch_jdownloader()
            for _ in range(30):
                time.sleep(2)
                try:
                    jd.connect(email, password)
                    device = jd.get_device("JDownloader@makwana")
                    return device
                except Exception:
                    continue
        raise ConnectionError(
            "Could not connect to JDownloader. Make sure JDownloader is running "
            "and logged in with the device 'JDownloader@makwana'."
        )
    return device


def _jd_call(op, device, attempts: int = 6):
    """Run a myjdapi call, reconnecting (force) on transient errors such as
    'no connection established'. Returns (device, result, ok). The returned
    device may be a freshly reconnected one."""
    dev = device
    for _ in range(attempts):
        try:
            return dev, op(dev), True
        except Exception:
            try:
                dev = _connect(force=True)
            except Exception:
                pass
            time.sleep(1)
    return dev, None, False
video_ext = [".mp4",".mkv",".avi",".mov",".wmv",
             ".flv",".webm",".mpeg",".mpg",".m4v",
             ".3gp",".ogv",".ts",".mts",".m2ts",
             ".vob",".rm",".rmvb",".divx",".f4v",".asf"
]

image_ext = [
    ".jpg",".jpeg",".png",".gif",".bmp",
    ".webp",".svg",".tiff",".tif",".ico",
    ".heic",".heif",".avif",".jfif",".pjpeg",
    ".pjp",".apng",".raw",".cr2",".nef",".orf",
    ".sr2",".dng",".eps",".ai",".indd"
]

DOWNLOAD_LINK_QUERY = [{
    "bytesLoaded": True,
    "bytesTotal": True,
    "eta": True,
    "finished": True,
    "maxResults": -1,
    "name": True,
    "packageUUIDs": [],
    "running": True,
    "speed": True,
    "startAt": 0,
    "status": True,
    "url": True,
}]


def _extract_youtube_id(url):
    if not url:
        return None

    match = re.search(r"youtubev2://([^/]+)", url)
    if match:
        return match.group(1)

    match = re.search(r"(?:v=|youtu\.be/|shorts/)([A-Za-z0-9_-]{11})", url)
    if match:
        return match.group(1)

    return None


def _thumbnail_url(video_id):
    return f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg" if video_id else None


def clear_old_links(device):
    device = _connect()
    links = device.linkgrabber.query_links()
    link_ids = [link["uuid"] for link in links]
    if link_ids:
        device.linkgrabber.remove_links(link_ids)


def jdownloader():
    global _dinotube_active
    _dinotube_active = False
    query = get_input(
        "Enter url : ",
        fetch_fn=scrap_result,
        download_fn=download_fn,
        setting_fn=dinotube_settings_fn,
        filter_fn=dinotube_filter,
    )


def _is_dinotube_trigger(query: str) -> bool:
    q = (query or "").strip().lower()
    q = re.sub(r"^https?://", "", q)
    q = q.replace("www.", "")
    q = q.rstrip("/")
    return q in ("dinotube.com", "dinotube")


def scrap_result(query):
    global _dinotube_active

    # ── DinoTube trigger: switch into search mode, clear the input ────────────
    if not _dinotube_active and _is_dinotube_trigger(query):
        _dinotube_active = True
        return [{
            "_enter_mode": True,
            "message": "DinoTube search mode — type a query and press Enter",
        }]

    # ── DinoTube search mode: query dinotube.com and return video cards ───────
    if _dinotube_active:
        try:
            return _fetch_dinotube_search(query)
        except _DinoTubeSetupError as exc:
            return [{
                "title": f"[DinoTube] {exc}",
                "_result_key": "_dinotube_setup_error",
            }]

    # ── Default JDownloader behaviour: hand the URL to the linkgrabber ────────
    device = _connect()
    clear_old_links(device)
    device.linkgrabber.add_links(
        [{
            "links": query,
            "destinationFolder": DOWNLOAD_PATH,
            "overwritePackagizerRules": True,
        }]
    )
    time.sleep(5)

    packages = device.linkgrabber.query_packages()
    if packages:
        for package in packages:
            package_id = package["uuid"]
            package_name = package.get("name") or "Axon"
            device.linkgrabber.move_to_new_package(
                [],
                [package_id],
                package_name,
                DOWNLOAD_PATH,
            )

    links = device.linkgrabber.query_links()

    with open("links.json", "w") as f:
        json.dump(links, f, indent=4)

    thumbnail_map = {}
    for link in links:
        name = link.get("name", "").lower()
        video_id = _extract_youtube_id(link.get("url", ""))
        if video_id and any(name.endswith(ext) for ext in image_ext):
            thumbnail_map[video_id] = _thumbnail_url(video_id)

    result = []
    for link in links:
        name = link.get("name", "").lower()
        if any(name.endswith(ext) for ext in video_ext):
            youtube_id = _extract_youtube_id(link.get("url", ""))
            thumbnail = thumbnail_map.get(youtube_id) or _thumbnail_url(youtube_id)
            result.append({
                "title": link["name"],
                "video_id": link["uuid"],
                "thumbnail": thumbnail,
                "youtube_id": youtube_id,
                "package_id": link.get("packageUUID"),
            })

    with open('result.json', 'w') as f:
        json.dump(result, f, indent=4)

    return result


# ── DinoTube scraping ─────────────────────────────────────────────────────────
DINOTUBE_PROFILE = os.path.join(os.path.dirname(__file__), "..", ".dinotube_profile")
DINOTUBE_PROFILE = os.path.abspath(DINOTUBE_PROFILE)


def _fetch_dinotube_html(url: str) -> str:
    """Fetch a DinoTube page. requests is usually blocked (403), so fall back
    to a headless browser when the card markup isn't present."""
    try:
        resp = requests.get(url, timeout=15, headers={"User-Agent": DINOTUBE_UA})
        if resp.status_code == 200 and "data-public-id" in resp.text:
            return resp.text
    except Exception:
        pass
    return _fetch_dinotube_html_selenium(url)


def _is_cloudflare_block(html: str) -> bool:
    """Check if the HTML is a Cloudflare challenge page."""
    lower = html.lower()
    return (
        "just a moment" in lower
        or "verify you are human" in lower
        or "performing security verification" in lower
        or "checking your browser" in lower
    )


class _DinoTubeSetupError(RuntimeError):
    """Raised when the browser automation deps (selenium / Chrome) are missing."""


def _new_chrome_driver(headless: bool = True):
    """Create a Chrome WebDriver.

    Selenium >= 4.6 ships Selenium Manager, which downloads the correct
    chromedriver automatically — so we no longer hard-depend on the separate
    'chromedriver_autoinstaller' package. If that package happens to be
    installed we still fall back to it for older selenium versions.
    """
    try:
        from selenium import webdriver
        from selenium.webdriver.chrome.options import Options
    except ImportError:
        raise _DinoTubeSetupError(
            "DinoTube search needs the 'selenium' package. Install it with "
            "'pip install \"selenium>=4.6\"' (it also handles chromedriver for you)."
        )

    options = Options()
    if headless:
        options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument(f"--user-data-dir={DINOTUBE_PROFILE}")
    options.add_argument(f"--user-agent={DINOTUBE_UA}")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)

    try:
        return webdriver.Chrome(options=options)
    except Exception:
        # Fallback for older selenium + chromedriver_autoinstaller.
        try:
            import chromedriver_autoinstaller
            chromedriver_autoinstaller.install()
            return webdriver.Chrome(options=options)
        except _DinoTubeSetupError:
            raise
        except Exception as exc:
            raise _DinoTubeSetupError(
                "Could not start Chrome for DinoTube. Install Google Chrome and "
                f"'selenium>=4.6'. Underlying error: {exc}"
            )


def _fetch_dinotube_html_selenium(url: str, tries: int = 3) -> str:
    """Use Selenium with a persistent profile to bypass Cloudflare.
    The profile stores the cf_clearance cookie so subsequent runs don't
    need to solve the challenge again."""
    last_html = ""
    for attempt in range(tries):
        driver = None
        try:
            driver = _new_chrome_driver(headless=True)
            driver.execute_cdp_cmd(
                "Page.addScriptToEvaluateOnNewDocument",
                {"source": "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"},
            )
            driver.set_page_load_timeout(30)
            driver.get(url)
            time.sleep(5)

            html = driver.page_source
            if "data-public-id" in html and len(html) > 100_000:
                return html
            last_html = html

            # If Cloudflare is blocking us, try a visible browser once so the
            # user can solve the challenge. The cf_clearance cookie is saved
            # into the profile and reused on later (headless) runs.
            if _is_cloudflare_block(html) and attempt == 0:
                driver.quit()
                driver = None
                _solve_cloudflare_interactive_dinotube(url)
                continue
        except _DinoTubeSetupError:
            raise
        except Exception:
            continue
        finally:
            if driver:
                try:
                    driver.quit()
                except Exception:
                    pass
    return last_html


def _solve_cloudflare_interactive_dinotube(url: str) -> None:
    """Open a visible Chrome window so the user can pass the Cloudflare
    challenge once. The cf_clearance cookie is stored in DINOTUBE_PROFILE."""
    print(
        "\n[dinotube.com] Cloudflare is blocking automated access.\n"
        "               A browser window will open — solve the 'Verify you are human'\n"
        "               check, wait for the page to load, then close the browser.\n"
    )
    driver = None
    try:
        driver = _new_chrome_driver(headless=False)
        driver.get(url)
        # Wait until the challenge is cleared (page has real content)
        for _ in range(60):
            time.sleep(2)
            html = driver.page_source
            if "data-public-id" in html or not _is_cloudflare_block(html):
                print("[dinotube.com] Challenge passed — cookie saved. You can close the browser.")
                time.sleep(3)
                break
    except _DinoTubeSetupError as exc:
        print(f"[dinotube.com] {exc}")
    except Exception as exc:
        print(f"[dinotube.com] Error: {exc}")
    finally:
        if driver:
            try:
                driver.quit()
            except Exception:
                pass


# Characters that may appear in a URL (RFC 3986 + common extras).
_URL_CHARS = set(
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
    "0123456789-._~:/?#[]@!$&'()*+,;=%"
)


def resolve_out_url(href: str) -> str | None:
    """The /out/?l=... link is a redirector. Its destination is base64-encoded
    inside the `l` parameter (split into chunks separated by obfuscation tokens
    like `Atl5`), optionally followed by a literal `?query` string. Decode it
    directly to avoid the Cloudflare-protected redirect."""
    m = re.search(r"[?&]l=([^&]+)", href)
    if not m:
        return None
    # The value is percent-encoded (e.g. %3D == base64 '=') and may carry
    # HTML entities; normalise before decoding.
    l = unquote(m.group(1).replace("&amp;", "&"))

    # Split off a literal query string that may be appended after the base64.
    if "?" in l:
        base64_part, query = l.split("?", 1)
    else:
        base64_part, query = l, ""

    # The base64 payload is chunked by obfuscation tokens (At + 2 chars) and
    # may use URL-safe base64 ( '-' / '_' ). Normalise, then decode each chunk.
    chunks = re.split(r"At[A-Za-z0-9]{2}", base64_part)
    decoded_parts = []
    for ch in chunks:
        ch = ch.strip()
        if not ch:
            continue
        seg = ch + ("=" * ((-len(ch)) % 4))
        seg = seg.replace("-", "+").replace("_", "/")
        try:
            decoded_parts.append(base64.b64decode(seg, validate=False).decode("latin-1"))
        except Exception:
            decoded_parts.append("")

    text = "".join(decoded_parts)
    i = text.find("http")
    if i == -1:
        return None

    j = i
    while j < len(text) and text[j] in _URL_CHARS:
        j += 1
    url = text[i:j].rstrip(".,;")
    if query:
        url = url + "?" + query if "?" not in url else url + "&" + query
    return url


def _parse_dinotube(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "lxml")
    cards = soup.select("div.card[data-public-id]")
    results = []
    for card in cards:
        a = card.select_one("a.item-link")
        if not a:
            continue
        href = a.get("href")
        title = (a.get("title") or "").strip()
        img = card.select_one("img.item-image")
        thumbnail = img.get("src") if img else None

        quality = None
        duration = None
        badge = card.select_one("span.badge")
        if badge:
            q = badge.select_one(".font-bold.italic")
            quality = q.get_text(strip=True) if q else None
            dur_match = re.search(r"(\d{1,2}:\d{2}(?::\d{2})?)", badge.get_text(" ", strip=True))
            duration = dur_match.group(1) if dur_match else None

        dest = None
        if href:
            full = urljoin(DINOTUBE_BASE, href)
            dest = resolve_out_url(full)

        public_id = card.get("data-public-id")
        results.append({
            "title": title,
            "thumbnail": thumbnail,
            "duration": duration,
            "quality": quality,
            "url": dest,
            "public_id": public_id,
            "_result_key": public_id,
        })
    return results


def _fetch_dinotube_search(query: str) -> list[dict]:
    url = f"{DINOTUBE_BASE}/search/a/{quote(query)}"
    html = _fetch_dinotube_html(url)
    return _parse_dinotube(html)


# ── DinoTube settings + filter ────────────────────────────────────────────────
def dinotube_settings_fn(action, settings=None):
    if not _dinotube_active:
        return {}

    if action == "load":
        return {
            "title": "Search Settings",
            "label": "Quality",
            "type": "toggles",
            "options": QUALITY_OPTIONS,
            "values": {"All": True, "HD": False, "4K": False},
            "exclusive_groups": [QUALITY_OPTIONS],
            "required_groups": [QUALITY_OPTIONS],
            "groups": [{"title": "Quality", "options": QUALITY_OPTIONS}],
        }

    # State lives in the TUI's memory; nothing to persist.
    if action == "save":
        return None


def dinotube_filter(items: list[dict], settings: dict | None) -> list[dict]:
    if not items or not settings:
        return items
    values = settings.get("values", {})
    selected = next((o for o in QUALITY_OPTIONS if values.get(o)), "All")
    if selected == "All":
        return items

    wanted = "4K" if selected == "4K" else "HD"
    return [
        it for it in items
        if wanted in (it.get("quality") or "").upper()
    ]


def _track_download(device, link_uuid, filename_to_find, progress_hook=None):
    """Poll JDownloader's download list and report progress until finished.

    JDownloader's API connection can blip with a transient "no connection
    established" error even while the download keeps running fine in the
    background. We retry (re-establishing the connection if needed) instead of
    aborting, and only report a failure if polling truly cannot recover.
    """
    max_wait = 120  # seconds before giving up on *polling*
    waited = 0
    consecutive_errors = 0

    while True:
        try:
            downloads = device.downloads.query_links(DOWNLOAD_LINK_QUERY)
            consecutive_errors = 0
        except Exception:
            consecutive_errors += 1
            # Re-establish the connection after a few blips.
            if consecutive_errors >= 3:
                try:
                    device = _connect(force=True)
                except Exception:
                    pass
            time.sleep(1)
            waited += 1
            if waited > max_wait:
                # The download was already handed to JDownloader and is very
                # likely still running there — don't report a false failure.
                if progress_hook:
                    progress_hook({
                        "status": "downloading",
                        "filename": filename_to_find or "Running in JDownloader",
                        "_percent_str": "",
                        "_speed_str": "",
                        "_eta_str": "",
                    })
                return
            continue

        if not downloads:
            time.sleep(1)
            waited += 1
            if waited > max_wait:
                if progress_hook:
                    progress_hook({"status": "error", "filename": "Unknown"})
                return
            continue

        matched = None
        for dl in downloads:
            dl_name = dl.get("name", "").lower()
            # Match by uuid first, fallback to filename
            if dl.get("uuid") == link_uuid or (filename_to_find and dl_name == filename_to_find):
                matched = dl
                break

        if not matched:
            time.sleep(1)
            waited += 1
            if waited > max_wait:
                if progress_hook:
                    progress_hook({"status": "error", "filename": "Unknown"})
                return
            continue

        # Reset wait counter once found
        waited = 0

        downloaded = matched.get("bytesLoaded", 0)
        total = matched.get("bytesTotal", 0)
        speed = matched.get("speed", 0)
        eta = matched.get("eta", -1)
        filename = matched.get("name", "Unknown")

        percent = round((downloaded / total) * 100, 2) if total > 0 else 0

        if progress_hook:
            progress_hook({
                "status": "downloading",
                "_percent_str": f"{percent}%",
                "_speed_str": f"{round(speed / (1024 * 1024), 2)} MB/s",
                "_eta_str": f"{eta}s",
                "filename": filename
            })

        if matched.get("finished") or (downloaded >= total and total > 0):
            if progress_hook:
                progress_hook({"status": "finished", "filename": filename})
            return

        time.sleep(1)


def download_fn(item, progress_hook=None, settings=None):
    # ── DinoTube: the item already carries the resolved video URL ─────────────
    if _dinotube_active and isinstance(item, dict) and item.get("url"):
        return _dinotube_download(item, progress_hook)

    video_id = item.get("video_id") if isinstance(item, dict) else item
    if not video_id:
        raise ValueError("No JDownloader link id found for the selected video")

    device = _connect()

    # Move selected link to download list (resilient to transient API blips)
    device, _, _ = _jd_call(
        lambda d: d.linkgrabber.move_to_downloadlist(
            link_ids=[video_id], package_ids=[]
        ),
        device,
    )
    _jd_call(lambda d: d.downloadcontroller.start_downloads(), device)

    # FIX 2: JDownloader reassigns UUIDs after move — match by filename instead
    # First, get the filename from the result we stored
    filename_to_find = None
    try:
        with open("result.json") as f:
            results = json.load(f)
        for r in results:
            if r["video_id"] == video_id:
                filename_to_find = r["title"].lower()
                break
    except Exception:
        pass

    _track_download(device, video_id, filename_to_find, progress_hook)


def _dinotube_download(item, progress_hook=None):
    url = item.get("url")
    if not url:
        raise ValueError("No DinoTube video URL found for the selected video")

    device = _connect()

    # Hand the resolved destination URL to JDownloader's linkgrabber. JDownloader
    # scans it and (with autostart) begins downloading — we don't wait for the
    # user to pick again; the chosen video is fetched directly.
    device, _, ok = _jd_call(
        lambda d: d.linkgrabber.add_links([{
            "links": url,
            "destinationFolder": DOWNLOAD_PATH,
            "overwritePackagizerRules": True,
        }]),
        device,
    )
    if not ok:
        if progress_hook:
            progress_hook({"status": "error", "filename": "Unknown"})
        return

    # Find our link in the linkgrabber (by URL) and move it to the download list.
    # Never fall back to an unrelated link.
    target = None
    url_l = url.lower()
    for _ in range(20):
        device, links, ok = _jd_call(lambda d: d.linkgrabber.query_links(), device)
        if ok:
            for link in links or []:
                lu = (link.get("url") or "").lower()
                name = (link.get("name") or "").lower()
                if url_l in lu or lu in url_l or url_l in name:
                    target = link
                    break
        if target:
            break
        time.sleep(1)

    if not target:
        # The link was handed to JDownloader and is most likely already
        # downloading via autostart — don't report a false failure.
        if progress_hook:
            progress_hook({
                "status": "downloading",
                "filename": "Running in JDownloader",
                "_percent_str": "",
                "_speed_str": "",
                "_eta_str": "",
            })
        return

    link_uuid = target["uuid"]
    filename_to_find = target.get("name", "").lower() or None

    device, _, ok = _jd_call(
        lambda d: d.linkgrabber.move_to_downloadlist(
            link_ids=[link_uuid], package_ids=[]
        ),
        device,
    )
    if ok:
        _jd_call(lambda d: d.downloadcontroller.start_downloads(), device)

    _track_download(device, link_uuid, filename_to_find, progress_hook)
