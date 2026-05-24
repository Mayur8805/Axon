from core.menu import get_input
import atexit
import requests
import os
import time
import re
import threading
from concurrent.futures import ThreadPoolExecutor
from bs4 import BeautifulSoup
from urllib.parse import quote
from playwright.sync_api import sync_playwright


BASE_URL = "https://in.pinterest.com/"
SEARCH_URL = "https://in.pinterest.com/search/pins/?q="
SESSION = requests.Session()
SESSION.headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
}
DOWNLOAD_PATH = "./Downloads/Images/"
_BROWSER_LOCK = threading.Lock()
_PLAYWRIGHT = None
_BROWSER = None
_CONTEXT = None
_PAGE = None
_SCRAPE_EXECUTOR = ThreadPoolExecutor(max_workers=1)

def pinterest_scraper():
    query = get_input("Enter name",fetch_fn=Scrap_results, download_fn=Download_image)


def get_soup(url):
    response = SESSION.get(url)
    return BeautifulSoup(response.content, "html.parser")

def generate_url(query):
    return f"{SEARCH_URL}{quote(query)}&rs=typed"

def extract_pinterest_urls(html):
    soup = BeautifulSoup(html, "html.parser")

    img = soup.find("img")
    if not img:
        return None

    # Thumbnail URL (236x)
    thumbnail_url = img.get("src")

    # Download URL (original)
    srcset = img.get("srcset", "")
    match = re.search(r'(https://i\.pinimg\.com/originals/[^\s]+)', srcset)

    download_url = match.group(1) if match else None

    return {
        "thumbnail_url": thumbnail_url,
        "download_url": download_url
    }


def _get_page():
    global _PLAYWRIGHT, _BROWSER, _CONTEXT, _PAGE

    if _PAGE is not None:
        return _PAGE

    _PLAYWRIGHT = sync_playwright().start()
    _BROWSER = _PLAYWRIGHT.chromium.launch(
        headless=True,
        args=[
            "--disable-blink-features=AutomationControlled",
            "--disable-dev-shm-usage",  
            "--no-sandbox",
            "--disable-gpu",
        ],
    )
    _CONTEXT = _BROWSER.new_context(
        user_agent=(
            "Mozilla/5.0 (X11; Linux x86_64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        viewport={"width": 1280, "height": 900},
        locale="en-IN",
    )
    _PAGE = _CONTEXT.new_page()
    _PAGE.set_default_timeout(30000)  
    return _PAGE


def _close_browser() -> None:
    global _PLAYWRIGHT, _BROWSER, _CONTEXT, _PAGE

    if _PAGE is not None:
        _PAGE.close()
    if _CONTEXT is not None:
        _CONTEXT.close()
    if _BROWSER is not None:
        _BROWSER.close()
    if _PLAYWRIGHT is not None:
        _PLAYWRIGHT.stop()

    _PAGE = None
    _CONTEXT = None
    _BROWSER = None
    _PLAYWRIGHT = None


def _shutdown_scraper() -> None:
    try:
        future = _SCRAPE_EXECUTOR.submit(_close_browser)
        future.result(timeout=10)
    except Exception:
        pass
    finally:
        _SCRAPE_EXECUTOR.shutdown(wait=False)


atexit.register(_shutdown_scraper)


def _scrape_sync(query: str, on_result=None) -> list:
    url = generate_url(query)
    results = []
    page = _get_page()

    # ✅ 1. Abort media requests to speed up page load
    def block_resources(route, request):
        if request.resource_type in ("image", "media", "font"):
            route.abort()
        else:
            route.continue_()

    page.route("**/*", block_resources)

    page.goto(url, wait_until="domcontentloaded", timeout=60000)

    try:
        page.wait_for_selector('[data-test-id="pin"]', timeout=20000)
    except Exception:
        print("Pins selector not found.")
        page.unroute("**/*")
        return results

    # ✅ 2. Reduce scroll wait — Pinterest only needs ~800ms to render
    for _ in range(3):
        page.mouse.wheel(0, 5000)
        page.wait_for_timeout(800)  # was 2000ms

    pins = page.query_selector_all('[data-test-id="pin"]')

    for pin in pins:
        img = pin.query_selector("img")
        a_tag = pin.query_selector("a")

        if not img:
            continue

        thumbnail_url = img.get_attribute("src")
        srcset = img.get_attribute("srcset") or ""

        # ✅ 3. Fallback chain: originals → 736x → 474x → thumbnail
        download_url = None
        for pattern in [
            r'https://i\.pinimg\.com/originals/[^\s,]+',
            r'https://i\.pinimg\.com/736x/[^\s,]+',
            r'https://i\.pinimg\.com/474x/[^\s,]+',
        ]:
            match = re.search(pattern, srcset)
            if match:
                download_url = match.group(0)
                break

        # ✅ 4. Derive original URL from thumbnail if srcset is empty
        if not download_url and thumbnail_url:
            download_url = re.sub(
                r'https://i\.pinimg\.com/\d+x/',
                'https://i.pinimg.com/originals/',
                thumbnail_url
            )

        title = img.get_attribute("alt") or ""
        title = re.sub(
            r"^(This contains an image of:|This may contain:)\s*",
            "",
            title
        ).strip()

        pin_url = None
        if a_tag:
            href = a_tag.get_attribute("href")
            if href:
                pin_url = "https://in.pinterest.com" + href

        item = {
            "title": title.replace(" ", "_"),
            "thumbnail": thumbnail_url,
            "download_url": download_url,
            "pin_url": pin_url
        }
        results.append(item)

        # ✅ 5. Stream results as they're found
        if on_result:
            on_result(item)

    # ✅ 6. Clean up route interceptor after scraping
    page.unroute("**/*")

    return results


def Scrap_results(query: str, on_result=None) -> list:
    future = _SCRAPE_EXECUTOR.submit(_scrape_locked, query, on_result)
    results = future.result()

    print(f"Scraped {len(results)} pins.")
    return results


def _scrape_locked(query: str, on_result=None) -> list:
    with _BROWSER_LOCK:
        return _scrape_sync(query, on_result=on_result)

def Download_image(item, progress_hook=None):

    url = item.get("download_url")

    if not url:
        raise ValueError("No download URL found")

    filename = item.get("title", "image")

    headers = {
        "User-Agent": "Mozilla/5.0",
        "Referer": "https://alphacoders.com/"
    }

    response = requests.get(
        url,
        headers=headers,
        stream=True,
        allow_redirects=True
    )

    if response.status_code != 200:
        if progress_hook:
            progress_hook({
                "status": "error",
                "filename": filename
            })
        return

    # Get real extension
    content_type = response.headers.get("Content-Type", "")

    if "jpeg" in content_type:
        ext = "jpg"
    elif "png" in content_type:
        ext = "png"
    elif "webp" in content_type:
        ext = "webp"
    else:
        ext = "jpg"

    filepath = f"{DOWNLOAD_PATH}{filename}.{ext}"

    total = int(response.headers.get("content-length", 0))
    downloaded = 0

    start_time = time.time()

    with open(filepath, "wb") as f:

        for chunk in response.iter_content(chunk_size=8192):

            if not chunk:
                continue

            f.write(chunk)

            downloaded += len(chunk)

            elapsed = time.time() - start_time

            speed = downloaded / elapsed if elapsed > 0 else 0

            percent = (
                round((downloaded / total) * 100, 2)
                if total > 0 else 0
            )

            eta = (
                round((total - downloaded) / speed)
                if speed > 0 and total > 0 else -1
            )

            if progress_hook:
                progress_hook({
                    "status": "downloading",
                    "_percent_str": f"{percent}%",
                    "_speed_str": f"{round(speed / (1024*1024), 2)} MB/s",
                    "_eta_str": f"{eta}s",
                    "filename": filepath
                })

    if progress_hook:
        progress_hook({
            "status": "finished",
            "filename": filepath
        })

    return filepath
