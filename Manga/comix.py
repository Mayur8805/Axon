"""Comix.to manga scraper.

Flow:
    1. User types a manga name  -> a list of matching manga is shown.
    2. User selects a manga     -> the result box is replaced by its chapters.
    3. User selects a chapter   -> every page image is downloaded and merged
                                   into a single PDF inside Downloads/Manga.

comix.to is a JavaScript single page app and its JSON API is protected by a
per-URL signature produced by an obfuscated "secure.js". Plain HTTP requests
always answer {"message": "Missing token."}, so a headless browser is used to
render the pages and the resulting image URLs are then downloaded with
requests (which is fast, the browser never downloads the image bytes).

The whole site now sits behind a Cloudflare managed challenge that a headless
browser can no longer solve on its own. A real, persistent Chrome profile is
used so the cf_clearance cookie (set the first time the user passes the
"Verify you are human" check in a visible browser) is reused on every later
run. When the challenge is still present we open a visible browser once for a
manual solve instead of silently returning no results.
"""

from __future__ import annotations

import io
import os
import re
import shutil
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import quote_plus, urljoin

import requests
from PIL import Image

from core.menu import get_input, load_config, save_config

# ── constants ─────────────────────────────────────────────────────────────────

BASE_URL      = "https://comix.to"
DOWNLOAD_PATH = "./Downloads/Manga"
SETTINGS_KEY  = "manga"

# Cloudflare protects the whole site with a managed challenge. A headless
# browser can no longer solve it automatically, so we keep a real, persistent
# Chrome profile: the first time the user passes the challenge the cf_clearance
# cookie is stored on disk and silently reused on every later run.
PROFILE_DIR = Path(os.environ.get("COMIX_PROFILE", "./.comix_profile")).resolve()

USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/150.0.0.0 Safari/537.36"
)

DOWNLOAD_ALL_OPTION = "download all"
MERGE_ALL_OPTION    = "merge all chapters in one pdf"
KEEP_IMAGES_OPTION  = "keep images"
SETTING_OPTIONS     = [DOWNLOAD_ALL_OPTION, MERGE_ALL_OPTION, KEEP_IMAGES_OPTION]

# Makes the obfuscated anti-bot script believe it runs in a normal browser.
_STEALTH_JS = """
Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
window.chrome = window.chrome || {runtime: {}, app: {}, csi: () => {}, loadTimes: () => {}};
Object.defineProperty(navigator, 'languages', {get: () => ['en-US', 'en']});
Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3, 4, 5]});
const _gp = WebGLRenderingContext.prototype.getParameter;
WebGLRenderingContext.prototype.getParameter = function (p) {
    if (p === 37445) return 'Intel Inc.';
    if (p === 37446) return 'Intel Iris OpenGL Engine';
    return _gp.apply(this, [p]);
};
"""

# The reader recycles <img> elements while scrolling, so a URL that scrolled out
# of view disappears from the DOM. Hooking the src setter keeps every URL.
_RECORDER_JS = """
window.__IMGS__ = [];
const _push = (u) => {
    if (!u || !/^https?:/.test(u)) return;
    if (u.indexOf('static.comix.to') !== -1) return;
    if (window.__IMGS__.indexOf(u) === -1) window.__IMGS__.push(u);
};
const _d = Object.getOwnPropertyDescriptor(HTMLImageElement.prototype, 'src');
Object.defineProperty(HTMLImageElement.prototype, 'src', {
    get() { return _d.get.call(this); },
    set(v) { _push(v); return _d.set.call(this, v); },
    configurable: true,
});
const _sa = Element.prototype.setAttribute;
Element.prototype.setAttribute = function (n, v) {
    if (this.tagName === 'IMG' && (n === 'src' || n === 'srcset')) {
        _push(String(v).split(' ')[0]);
    }
    return _sa.apply(this, arguments);
};
"""

_BROWSER_LOCK = threading.Lock()
_SESSION = requests.Session()
_SESSION.headers.update({"User-Agent": USER_AGENT, "Referer": BASE_URL + "/"})


# ── entry point ───────────────────────────────────────────────────────────────

def comix_scraper() -> None:
    get_input(
        "Enter manga name",
        fetch_fn=search_manga,
        download_fn=handle_selection,
        setting_fn=settings_fn,
    )


# ── settings ──────────────────────────────────────────────────────────────────

def settings_fn(action, settings=None):
    config       = load_config()
    manga_config = config.setdefault(SETTINGS_KEY, {})

    if action == "load":
        return {
            "type":      "toggles",
            "title":     "Settings",
            "label":     "Download options",
            "options":   SETTING_OPTIONS,
            "allow_none": True,
            "values": {
                DOWNLOAD_ALL_OPTION: bool(manga_config.get("download_all", False)),
                MERGE_ALL_OPTION:    bool(manga_config.get("merge_all", False)),
                KEEP_IMAGES_OPTION:  bool(manga_config.get("keep_images", False)),
            },
        }

    if action == "save" and settings:
        values = settings.get("values", {})
        manga_config["download_all"] = bool(values.get(DOWNLOAD_ALL_OPTION, False))
        manga_config["merge_all"]    = bool(values.get(MERGE_ALL_OPTION, False))
        manga_config["keep_images"]  = bool(values.get(KEEP_IMAGES_OPTION, False))
        save_config(config)


# ── helpers ───────────────────────────────────────────────────────────────────

def _safe_name(name: str) -> str:
    cleaned = re.sub(r'[<>:"/\\|?*]', "", name or "").strip()
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned[:120] or "manga"


def _new_page(browser_ctx):
    page = browser_ctx.new_page()
    page.set_default_timeout(45_000)
    return page


def _launch_context(playwright, headless: bool):
    """Open a persistent Chrome profile so the cf_clearance cookie survives
    across runs. Using the real `chrome` channel avoids the headless-shell
    fingerprint that Cloudflare blocks outright."""
    launch_kwargs = dict(
        headless=headless,
        channel="chrome",
        args=[
            "--no-sandbox",
            "--disable-dev-shm-usage",
            "--disable-blink-features=AutomationControlled",
        ],
        user_data_dir=str(PROFILE_DIR),
        user_agent=USER_AGENT,
        viewport={"width": 1280, "height": 1400},
        locale="en-US",
    )
    try:
        context = playwright.chromium.launch_persistent_context(**launch_kwargs)
    except Exception:
        # Fall back to the bundled chromium if the real Chrome channel is not
        # installed (it will still be blocked by Cloudflare, but at least the
        # failure surfaces as a clear "solve the challenge" message).
        launch_kwargs.pop("channel", None)
        context = playwright.chromium.launch_persistent_context(**launch_kwargs)
    context.add_init_script(_STEALTH_JS)
    context.add_init_script(_RECORDER_JS)
    return context


def _block_images(context) -> None:
    # The browser only needs the URLs; requests downloads the bytes later.
    context.route(
        "**/*",
        lambda route, request: route.abort()
        if request.resource_type == "image"
        else route.continue_(),
    )


def _is_cloudflare_block(page) -> bool:
    try:
        return bool(
            page.evaluate(
                "() => /Performing security verification|Just a moment|"
                "Verify you are human/i.test(document.body.innerText)"
            )
        )
    except Exception:
        return True


def _wait_past_cloudflare(page, timeout_ms: int = 60_000) -> bool:
    """Return True once the page is no longer behind the CF challenge."""
    deadline = timeout_ms / 1000
    step = 1.5
    waited = 0.0
    while waited < deadline:
        if not _is_cloudflare_block(page):
            return True
        page.wait_for_timeout(int(step * 1000))
        waited += step
    return not _is_cloudflare_block(page)


def _solve_cloudflare_interactive() -> None:
    """Open a visible browser so the user can pass the Cloudflare challenge
    once. The cf_clearance cookie is written into PROFILE_DIR and reused by
    every later (headless) run."""
    from playwright.sync_api import sync_playwright

    print(
        "\n[comix.to] Cloudflare is blocking automated access.\n"
        "           A browser window will open — solve the 'Verify you are human'\n"
        "           check, wait for the manga list to appear, then close it.\n"
    )
    with sync_playwright() as playwright:
        context = _launch_context(playwright, headless=False)
        try:
            page = context.new_page()
            page.goto(BASE_URL + "/", wait_until="domcontentloaded", timeout=60_000)
            # Poll until the challenge is cleared (user solved it) or they quit.
            while _is_cloudflare_block(page):
                page.wait_for_timeout(2000)
                try:
                    if page.query_selector("text=Verify you are human"):
                        pass
                except Exception:
                    pass
            print("[comix.to] Challenge passed — cookie saved. You can close the browser.")
            # Keep it open a moment so the cookie is fully persisted.
            page.wait_for_timeout(1500)
        finally:
            context.close()


def _open_browser(playwright, block_images: bool):
    context = _launch_context(playwright, headless=True)
    if block_images:
        _block_images(context)
    return context


def _warm_up(page) -> object:
    """secure.js only starts signing requests after a first normal page load.
    If Cloudflare is blocking us, drop into an interactive solve once and then
    continue with the now-cookied persistent profile. Returns the page to use
    (which may be a freshly opened one after a re-solve)."""
    page.goto(BASE_URL + "/", wait_until="domcontentloaded", timeout=60_000)
    # The managed-challenge page renders asynchronously, so poll for up to ~25s
    # before deciding we are blocked.
    if not _wait_past_cloudflare(page, timeout_ms=25_000):
        page.context.close()
        _solve_cloudflare_interactive()
        # Re-open with the saved cookie.
        from playwright.sync_api import sync_playwright

        with sync_playwright() as playwright:
            context = _open_browser(playwright, block_images=True)
            page = _new_page(context)
            page.goto(BASE_URL + "/", wait_until="domcontentloaded", timeout=60_000)
            _wait_past_cloudflare(page, timeout_ms=25_000)
    page.wait_for_timeout(2000)
    return page


def _page_ready(page, selector: str, timeout_ms: int = 35_000) -> bool:
    """Wait for real content, bailing out (False) if a CF block persists."""
    deadline = timeout_ms / 1000
    waited = 0.0
    step = 1.0
    while waited < deadline:
        if not _is_cloudflare_block(page):
            try:
                page.wait_for_selector(selector, timeout=int(step * 1000))
                return True
            except Exception:
                pass
        else:
            page.wait_for_timeout(int(step * 1000))
            waited += step
            continue
        page.wait_for_timeout(int(step * 1000))
        waited += step
    return not _is_cloudflare_block(page) and page.query_selector(selector) is not None


def _first_string(data: dict, *keys: str) -> str:
    for key in keys:
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _image_url(data: dict) -> str:
    direct = _first_string(data, "thumbnail", "poster", "cover", "image", "avatar")
    if direct:
        return direct
    for key in ("poster", "cover", "image", "thumbnail"):
        value = data.get(key)
        if isinstance(value, dict):
            direct = _first_string(value, "url", "src", "path")
            if direct:
                return direct
    return ""


def _manga_url(data: dict) -> str:
    direct = _first_string(data, "url", "path", "href")
    if direct:
        return direct
    slug = _first_string(data, "slug")
    hid = _first_string(data, "hid", "hashId", "hash_id")
    if hid and slug:
        return f"/title/{hid}/{slug}"
    if hid:
        return f"/title/{hid}"
    return ""


def _normalise_manga_items(payload) -> list[dict]:
    if isinstance(payload, dict) and payload.get("status") == "ok":
        payload = payload.get("result")
    if isinstance(payload, dict):
        items = payload.get("items") or payload.get("data") or payload.get("results") or []
    else:
        items = payload
    return items if isinstance(items, list) else []


def _looks_like_cloudflare_error(exc: Exception) -> bool:
    text = str(exc)
    return any(
        marker in text
        for marker in (
            "Just a moment",
            "Cloudflare",
            "Verify you are human",
            "security verification",
            "API search failed (403)",
        )
    )


def _api_search(page, query: str) -> list[dict]:
    """Use the site's own signed API from inside the browser context.

    secure.js attaches request signing to browser fetch/XHR. Calling the API
    from the warmed page avoids brittle card scraping and keeps Python out of
    the obfuscated token implementation.
    """
    return page.evaluate(
        """async (query) => {
            const params = new URLSearchParams();
            params.set('keyword', query);
            params.set('order[relevance]', 'desc');
            params.set('page', '1');
            params.set('limit', '28');
            const response = await fetch(`/api/v1/manga?${params.toString()}`, {
                headers: {
                    'Accept': 'application/json',
                    'X-Requested-With': 'XMLHttpRequest',
                },
                credentials: 'same-origin',
            });
            const type = response.headers.get('content-type') || '';
            const body = type.includes('application/json')
                ? await response.json()
                : await response.text();
            if (!response.ok) {
                throw new Error(`API search failed (${response.status}): ${
                    typeof body === 'string' ? body.slice(0, 160) : JSON.stringify(body).slice(0, 160)
                }`);
            }
            return body;
        }""",
        query,
    )


def _title_from_mangadex(attrs: dict) -> str:
    titles = attrs.get("title") if isinstance(attrs, dict) else {}
    if isinstance(titles, dict):
        for lang in ("en", "ja-ro", "ko-ro", "zh-ro"):
            value = titles.get(lang)
            if isinstance(value, str) and value.strip():
                return value.strip()
        for value in titles.values():
            if isinstance(value, str) and value.strip():
                return value.strip()
    return ""


def _mangadex_cover_url(item: dict) -> str:
    manga_id = item.get("id")
    rels = item.get("relationships") or []
    if not manga_id or not isinstance(rels, list):
        return ""
    for rel in rels:
        if not isinstance(rel, dict) or rel.get("type") != "cover_art":
            continue
        file_name = (rel.get("attributes") or {}).get("fileName")
        if file_name:
            return f"https://uploads.mangadex.org/covers/{manga_id}/{file_name}.256.jpg"
    return ""


def _mangadex_search(query: str, limit: int = 10) -> list[dict]:
    response = _SESSION.get(
        "https://api.mangadex.org/manga",
        params={
            "title": query,
            "limit": limit,
            "includes[]": ["cover_art"],
            "order[relevance]": "desc",
        },
        headers={"Accept": "application/json"},
        timeout=25,
    )
    response.raise_for_status()
    payload = response.json()
    out: list[dict] = []
    for item in payload.get("data", []):
        if not isinstance(item, dict):
            continue
        title = _title_from_mangadex(item.get("attributes") or {})
        manga_id = item.get("id")
        if not title or not manga_id:
            continue
        out.append(
            {
                "title": title,
                "thumbnail": _mangadex_cover_url(item),
                "url": f"https://mangadex.org/title/{manga_id}",
                "kind": "manga",
                "source": "mangadex",
                "source_id": manga_id,
            }
        )
    return out


def _mangadex_id_from_url(url: str) -> str:
    match = re.search(r"mangadex\.org/title/([0-9a-f-]{36})", url or "", re.I)
    return match.group(1) if match else ""


# ── step 1: search ────────────────────────────────────────────────────────────

def search_manga(query: str, on_result=None) -> list:
    query = (query or "").strip()
    if not query:
        return []

    url = f"{BASE_URL}/browse?q={quote_plus(query)}&sort=relevance%3Adesc"

    from playwright.sync_api import sync_playwright

    results: list[dict] = []
    blocked_error: Exception | None = None

    with _BROWSER_LOCK, sync_playwright() as playwright:
        context = _open_browser(playwright, block_images=True)
        try:
            page = _new_page(context)
            page = _warm_up(page)

            page.goto(url, wait_until="domcontentloaded", timeout=60_000)
            if not _wait_past_cloudflare(page, timeout_ms=35_000):
                raise RuntimeError(
                    "comix.to is still behind a Cloudflare challenge. Run the "
                    "scraper once on a machine with a display (or delete "
                    f"{PROFILE_DIR} and retry) so the 'Verify you are human' "
                    "check can be solved and the cookie saved."
                )

            try:
                cards = _normalise_manga_items(_api_search(page, query))
            except Exception as exc:
                blocked_error = exc if _looks_like_cloudflare_error(exc) else None
                if not _page_ready(page, 'a[href^="/title/"]', timeout_ms=35_000):
                    if blocked_error:
                        cards = []
                    else:
                        raise
                else:
                    page.wait_for_timeout(1200)
                    cards = page.evaluate(
                        """() => {
                            const out = [];
                            const seen = new Set();
                            document.querySelectorAll('a[href^="/title/"]').forEach((a) => {
                                const href = a.getAttribute('href');
                                if (!href || href.split('/').length > 3) return;
                                const img = a.querySelector('img');
                                const text = (a.innerText || '').trim();
                                let entry = seen.has(href) ? out.find(o => o.url === href) : null;
                                if (!entry) {
                                    entry = {url: href, title: '', thumbnail: ''};
                                    out.push(entry); seen.add(href);
                                }
                                if (text) entry.title = text.split('\\n')[0].trim();
                                if (img && img.getAttribute('src')) entry.thumbnail = img.getAttribute('src');
                            });
                            return out;
                        }"""
                    )
        finally:
            context.close()

    for card in cards:
        title = _first_string(card, "title", "name")
        manga_url = _manga_url(card)
        if not title or not manga_url:
            continue
        item = {
            "title":     title,
            "thumbnail": urljoin(BASE_URL, _image_url(card)),
            "url":       urljoin(BASE_URL, manga_url),
            "kind":      "manga",
        }
        results.append(item)
        if on_result:
            on_result(item)

    if not results and blocked_error:
        for item in _mangadex_search(query):
            results.append(item)
            if on_result:
                on_result(item)

    return results


# ── step 2: chapters ──────────────────────────────────────────────────────────

def fetch_chapters(manga: dict, progress_hook=None) -> list:
    if manga.get("source") == "mangadex":
        return _fetch_mangadex_chapters(manga, progress_hook=progress_hook)

    from playwright.sync_api import sync_playwright

    with _BROWSER_LOCK, sync_playwright() as playwright:
        context = _open_browser(playwright, block_images=True)
        try:
            page = _new_page(context)
            page = _warm_up(page)

            page.goto(manga["url"], wait_until="domcontentloaded", timeout=60_000)
            # Only gate on the Cloudflare challenge here — chapter links may not
            # appear until we click the "Chapter" tab, so waiting for them now
            # would falsely report a CF block.
            if not _wait_past_cloudflare(page, timeout_ms=35_000):
                raise RuntimeError(
                    "comix.to is still behind a Cloudflare challenge. Solve the "
                    "'Verify you are human' check once (delete "
                    f"{PROFILE_DIR} to force a fresh solve) so the cookie is saved."
                )
            page.wait_for_timeout(1500)

            # Prefer the site's own chapters API (called from inside the
            # CF-cleared page); it is far more reliable than scraping the
            # asynchronously-rendered SPA list.
            api_chapters = _fetch_chapters_via_api(page, manga)
            if api_chapters:
                return _finalise_chapters(api_chapters, manga)

            # Fallback: scrape the rendered chapter list once it loads.
            # The chapter list lives behind a <nav class="npager"> pager and is
            # grouped by "Chapter / Volume / Date" with a "Best / Newest / Oldest"
            # sort. By default it shows the newest chapter first (descending).
            # We click the "Chapter" view and the "Oldest" sort so the list starts
            # at chapter 0 and reads forward (0 -> 200). We then stream every
            # page with the "Next" button, emitting each chapter as it is found
            # so it appears in the result box incrementally (0, 1, 2, 3, ...).
            def _click_seg(text: str) -> bool:
                # Match case-insensitively and by substring so "Chapters",
                # "Oldest", etc. all resolve even if the UI wording drifts.
                needle = text.lower()
                return bool(
                    page.evaluate(
                        """(needle) => {
                            const b = Array.from(
                                document.querySelectorAll('button.useg__btn, button')
                            ).find(x => {
                                const t = (x.innerText || '').trim().toLowerCase();
                                return t === needle || t.includes(needle);
                            });
                            if (b) { b.click(); return true; }
                            return false;
                        }""",
                        needle,
                    )
                )

            def _npager_ready() -> bool:
                return bool(
                    page.evaluate(
                        "() => !!document.querySelector("
                        "'nav.npager button.npager__nav[aria-label=\"Next page\"]')"
                        " && !document.querySelector("
                        "'nav.npager button.npager__nav[aria-label=\"Next page\"]').disabled"
                    )
                )

            def _click_nav(kind: str) -> bool:
                label = {"next": "Next page", "prev": "Previous page"}.get(kind, f"{kind.capitalize()} page")
                return bool(
                    page.evaluate(
                        """(label) => {
                            const b = document.querySelector(
                                `nav.npager button.npager__nav[aria-label='${label}']`
                            );
                            if (b && !b.disabled) { b.click(); return true; }
                            return false;
                        }""",
                        label,
                    )
                )

            def _active_page() -> int:
                return page.evaluate(
                    """() => {
                        const a = document.querySelector('nav.npager button.npager__num.is-active');
                        const n = a ? parseInt((a.innerText || '').trim(), 10) : 0;
                        return Number.isInteger(n) ? n : 0;
                    }"""
                )

            def _collect_current() -> None:
                # The chapter entries live inside `.mpage__chapters`; collect
                # every anchor there (the section only holds chapter links),
                # plus any chapter-like link elsewhere on the page.
                rows = page.evaluate(
                    """() => {
                        const base = location.origin;
                        const section = document.querySelector('.mpage__chapters');
                        const scope = section || document;
                        const all = Array.from(scope.querySelectorAll('a'));
                        const extra = section
                            ? []
                            : Array.from(document.querySelectorAll('a[href*="chapter"], a[href*="/read/"]'));
                        return all.concat(extra).map(a => ({
                            url: a.getAttribute('href'),
                            text: (a.innerText || '').trim().replace(/\\s+/g, ' '),
                        })).filter(a => {
                            if (!a.url) return false;
                            let h = a.url;
                            if (h.startsWith('//')) h = 'https:' + h;
                            else if (h.startsWith('/')) h = base + h;
                            // Must look like an internal chapter link, and not
                            // the bare site root or the manga's own title page.
                            return /chapter|\\/ch\\/|\\/c\\/|\\/read\\//i.test(h)
                                && !/^https?:\\/\\/[^/]+\\/?$/.test(h);
                        });
                    }"""
                )
                for row in rows:
                    url = row.get("url")
                    if not url or url in seen:
                        continue
                    seen.add(url)
                    collected[url] = row
                    chapter = {
                        "title":       row.get("text") or "Chapter",
                        "url":         urljoin(BASE_URL, url),
                        "thumbnail":   manga.get("thumbnail", ""),
                        "kind":        "chapter",
                        "manga_title": manga["title"],
                        "number":      _chapter_number(url, row.get("text", "")),
                    }
                    if progress_hook:
                        progress_hook({"status": "result", "item": chapter})

            # Wait until the chapter list has actually rendered (it loads via a
            # React query after mount), then make sure we are on the Chapter tab.
            _wait_for_chapter_list(page, timeout_ms=30_000)
            _click_seg("Chapter")
            page.wait_for_timeout(900)

            collected: dict[str, dict] = {}
            seen: set[str] = set()

            # Stream forward from page 1, collecting chapters in ascending order.
            # Verify each "Next" actually advances via the active-page indicator
            # so no chapter page is ever skipped.
            _collect_current()
            active = _active_page()
            for _ in range(400):
                if not _click_nav("next"):
                    break
                moved = False
                for _ in range(8):
                    page.wait_for_timeout(120)
                    new = _active_page()
                    if new and new != active:
                        active = new
                        moved = True
                        break
                if not moved:
                    break
                _collect_current()
        finally:
            context.close()

    chapters = sorted(collected.values(), key=lambda r: _chapter_number(r["url"], r.get("text", "")))
    if not chapters:
        raise _no_chapters_error(page, manga)
    return _finalise_chapters(
        [{"url": r["url"], "text": r.get("text", "")} for r in chapters], manga
    )


def _chapter_number(url: str, text: str) -> float:
    match = re.search(r"chapter[/-]([\d.]+)", url or "", re.I)
    if not match:
        match = re.search(r"\bchapter\s+([\d.]+)", text or "", re.I)
    if not match:
        match = re.search(r"([\d.]+)", text or "")
    try:
        return float(match.group(1)) if match else 0.0
    except ValueError:
        return 0.0


def _finalise_chapters(raw_items: list[dict], manga: dict) -> list[dict]:
    """Normalise raw {url,title?,number?} items into sorted chapter dicts."""
    out: list[dict] = []
    for item in raw_items:
        url = item.get("url") or ""
        if not url:
            continue
        title = item.get("title") or item.get("text") or ""
        number = item.get("number")
        if number is None:
            number = _chapter_number(url, title)
        else:
            try:
                number = float(number)
            except (TypeError, ValueError):
                number = _chapter_number(url, title)
        out.append(
            {
                "title":       title or f"Chapter {number}",
                "url":         urljoin(BASE_URL, url),
                "thumbnail":   manga.get("thumbnail", ""),
                "kind":        "chapter",
                "manga_title": manga["title"],
                "number":      number,
            }
        )
    out.sort(key=lambda c: c["number"])
    return out


def _fetch_chapters_via_api(page, manga: dict) -> list[dict] | None:
    """Use the site's own signed chapters API from inside the warmed page.

    The React app calls N.chapters(<mangaHid>, params); the manga id (hid) is
    the first path segment of the title URL (/title/<hid>/<slug>)."""
    match = re.search(r"/title/([^/]+)", manga.get("url", "") or "")
    hid = match.group(1) if match else ""
    if not hid:
        return None
    try:
        data = page.evaluate(
            """async (hid) => {
                const out = [];
                for (let p = 1; p <= 60; p++) {
                    const u = `/api/v1/manga/${hid}/chapters?page=${p}&limit=100`;
                    let resp;
                    try {
                        resp = await fetch(u, {
                            credentials: 'same-origin',
                            headers: {
                                'Accept': 'application/json',
                                'X-Requested-With': 'XMLHttpRequest',
                            },
                        });
                    } catch (e) { break; }
                    if (!resp.ok) break;
                    const ct = resp.headers.get('content-type') || '';
                    let body = null;
                    try { body = ct.includes('application/json') ? await resp.json() : null; }
                    catch (e) { body = null; }
                    if (!body) break;
                    const items = body.items || body.data || body.chapters || [];
                    if (!Array.isArray(items) || !items.length) break;
                    for (const it of items) {
                        out.push({
                            url: it.url || it.href || '',
                            title: it.title || (it.number != null ? ('Chapter ' + it.number) : ''),
                            number: (it.number != null) ? it.number : (it.chapter != null ? it.chapter : null),
                        });
                    }
                    if (items.length < 100) break;
                }
                return out;
            }""",
            hid,
        )
    except Exception:
        return None
    cleaned = [d for d in (data or []) if d.get("url")]
    return cleaned or None


def _wait_for_chapter_list(page, timeout_ms: int = 30_000) -> bool:
    """Poll until the SPA has rendered its chapter links (it loads async)."""
    deadline = timeout_ms / 1000
    waited = 0.0
    step = 1.0
    while waited < deadline:
        ok = page.evaluate(
            """() => {
                const s = document.querySelector('.mpage__chapters');
                if (s && s.querySelectorAll('a').length) return true;
                if (document.querySelectorAll('a[href*="chapter"]').length) return true;
                if (document.querySelectorAll('a[href*="/read/"]').length) return true;
                return false;
            }"""
        )
        if ok:
            return True
        page.wait_for_timeout(int(step * 1000))
        waited += step
    return False


def _no_chapters_error(page, manga: dict) -> RuntimeError:
    try:
        info = page.evaluate(
            """() => {
                const a = Array.from(document.querySelectorAll('a')).map(x => x.getAttribute('href') || '');
                const chap = a.filter(h => /chapter|\\/read\\//i.test(h));
                return {total: a.length, chapCount: chap.length, samples: a.slice(0, 20)};
            }"""
        )
    except Exception:
        info = {"total": "?", "chapCount": "?", "samples": []}
    return RuntimeError(
        "No chapters found for this manga. "
        f"(anchors={info.get('total')}, chapter-like={info.get('chapCount')}, "
        f"samples={info.get('samples')}) — if the page does show chapters, "
        "paste this diagnostic so the selector can be adjusted."
    )


def _fetch_mangadex_chapters(manga: dict, progress_hook=None) -> list:
    manga_id = manga.get("source_id") or _mangadex_id_from_url(manga.get("url", ""))
    if not manga_id:
        raise RuntimeError("MangaDex manga id not found.")

    chapters: list[dict] = []
    offset = 0
    limit = 100
    while True:
        response = _SESSION.get(
            f"https://api.mangadex.org/manga/{manga_id}/feed",
            params={
                "translatedLanguage[]": ["en"],
                "order[chapter]": "asc",
                "order[volume]": "asc",
                "limit": limit,
                "offset": offset,
            },
            headers={"Accept": "application/json"},
            timeout=30,
        )
        response.raise_for_status()
        payload = response.json()
        rows = payload.get("data", [])
        if not rows:
            break

        for row in rows:
            attrs = row.get("attributes") or {}
            chapter_no = str(attrs.get("chapter") or "").strip()
            title = str(attrs.get("title") or "").strip()
            label = f"Chapter {chapter_no}" if chapter_no else "Chapter"
            if title:
                label = f"{label} - {title}" if chapter_no else title
            chapter = {
                "title": label,
                "url": f"https://mangadex.org/chapter/{row['id']}",
                "thumbnail": manga.get("thumbnail", ""),
                "kind": "chapter",
                "source": "mangadex",
                "source_id": row["id"],
                "manga_title": manga["title"],
                "number": _chapter_number("", label),
            }
            chapters.append(chapter)
            if progress_hook:
                progress_hook({"status": "result", "item": chapter})

        total = int(payload.get("total") or 0)
        offset += len(rows)
        if offset >= total:
            break

    return chapters


# ── step 3: page images ───────────────────────────────────────────────────────

def _chapter_total_pages(page) -> int | None:
    match = page.evaluate(
        "() => { const t = document.body.innerText.match(/(\\d+)\\s*\\/\\s*(\\d+)/); return t ? parseInt(t[2], 10) : null; }"
    )
    return match


def _collect_page_images(page, chapter_url: str) -> list[str]:
    # The recorder hook accumulates URLs in window.__IMGS__ across navigations,
    # so reset it before each chapter and clear it again after reading.
    page.evaluate("() => { window.__IMGS__ = []; }")
    page.goto(chapter_url, wait_until="domcontentloaded", timeout=60_000)
    page.wait_for_timeout(4000)

    target = _chapter_total_pages(page)

    seen: set[str] = set()
    unique = 0
    stall = 0
    offset = 0

    # Scroll in steps of roughly one viewport so the virtualised reader renders
    # every page; recycling re-fires the src setter, hence the dedup by base URL.
    while stall < 20:
        before = unique

        step = page.evaluate(
            "() => { const m = document.querySelector('main.rpage-main'); return m ? m.clientHeight : 700; }"
        ) or 700
        offset += step
        page.evaluate(
            "(y) => { const m = document.querySelector('main.rpage-main'); if (m) m.scrollTop = y; }",
            offset,
        )
        page.wait_for_timeout(200)

        captured = page.evaluate("() => window.__IMGS__") or []
        for url in captured:
            base = url.split("?")[0]
            if "static.comix.to" in base or not re.search(r"/i\d*/", base):
                continue
            if base not in seen:
                seen.add(base)
                unique += 1

        height = page.evaluate(
            "() => { const m = document.querySelector('main.rpage-main'); return m ? m.scrollHeight : 0; }"
        )

        if target and unique >= target:
            break
        if height and offset + step + 50 >= height:
            # Reached the bottom; let any final pages settle.
            page.wait_for_timeout(800)
            if unique == before:
                break
            stall = stall + 1
        else:
            stall = stall + 1 if unique == before else 0

    # Preserve reading order (first-seen) while dropping query-string variants
    # and any non-reader images captured by the hook.
    pages: list[str] = []
    for url in page.evaluate("() => window.__IMGS__") or []:
        base = url.split("?")[0]
        if "static.comix.to" in base or not re.search(r"/i\d*/", base):
            continue
        if base not in pages:
            pages.append(base)
    page.evaluate("() => { window.__IMGS__ = []; }")
    return pages


def _download_image(url: str) -> bytes:
    response = _SESSION.get(url, timeout=60)
    response.raise_for_status()
    return response.content


def _mangadex_page_urls(chapter: dict) -> list[str]:
    chapter_id = chapter.get("source_id") or ""
    if not chapter_id:
        match = re.search(r"mangadex\.org/chapter/([0-9a-f-]{36})", chapter.get("url", ""), re.I)
        chapter_id = match.group(1) if match else ""
    if not chapter_id:
        raise RuntimeError(f"MangaDex chapter id not found for {chapter.get('title', 'chapter')}.")

    response = _SESSION.get(
        f"https://api.mangadex.org/at-home/server/{chapter_id}",
        headers={"Accept": "application/json"},
        timeout=30,
    )
    response.raise_for_status()
    payload = response.json()
    base_url = payload.get("baseUrl")
    chapter_data = payload.get("chapter") or {}
    chapter_hash = chapter_data.get("hash")
    pages = chapter_data.get("data") or []
    if not base_url or not chapter_hash or not pages:
        raise RuntimeError(f"No pages found for {chapter.get('title', 'chapter')}.")
    return [f"{base_url}/data/{chapter_hash}/{page}" for page in pages]


def _save_pdf(images: list[bytes], pdf_path: Path) -> None:
    frames = []
    for blob in images:
        try:
            frame = Image.open(io.BytesIO(blob))
            frames.append(frame.convert("RGB"))
        except Exception:
            continue

    if not frames:
        raise RuntimeError("No readable images for this chapter.")

    pdf_path.parent.mkdir(parents=True, exist_ok=True)
    frames[0].save(pdf_path, "PDF", save_all=True, append_images=frames[1:])


def _download_chapter(page, chapter: dict, out_dir: Path, keep_images: bool,
                      progress_hook=None, label: str = "") -> tuple[Path, list[bytes]]:
    urls = (
        _mangadex_page_urls(chapter)
        if chapter.get("source") == "mangadex"
        else _collect_page_images(page, chapter["url"])
    )
    if not urls:
        raise RuntimeError(f"No pages found for {chapter['title']}.")

    total  = len(urls)
    blobs: list[bytes | None] = [None] * total
    done   = 0
    lock   = threading.Lock()

    def worker(index_url):
        nonlocal done
        index, url = index_url
        data = _download_image(url)
        with lock:
            blobs[index] = data
            done += 1
            if progress_hook:
                progress_hook(
                    {
                        "status": "downloading",
                        "_percent_str": f"{done * 100 // total}%",
                        "_speed_str": f"{done}/{total} pages",
                        "_eta_str": "",
                        "filename": f"{label}{chapter['title']}",
                    }
                )

    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(worker, enumerate(urls)))

    images = [b for b in blobs if b]

    pdf_path = out_dir / f"{_safe_name(chapter['title'])}.pdf"
    _save_pdf(images, pdf_path)

    if keep_images:
        image_dir = out_dir / _safe_name(chapter["title"])
        image_dir.mkdir(parents=True, exist_ok=True)
        for index, blob in enumerate(images, start=1):
            (image_dir / f"{index:04d}.jpg").write_bytes(blob)

    return pdf_path, images


# ── download entry point ──────────────────────────────────────────────────────

def handle_selection(item: dict, progress_hook=None, settings=None):
    """Called by the TUI when the user presses Enter on a result.

    Returning a list replaces the result box, which turns the manga list into
    the chapter list.
    """
    values      = (settings or {}).get("values", {}) if isinstance(settings, dict) else {}
    download_all = bool(values.get(DOWNLOAD_ALL_OPTION, False))
    merge_all   = bool(values.get(MERGE_ALL_OPTION, False))
    keep_images = bool(values.get(KEEP_IMAGES_OPTION, False))

    # "download all" wraps the visible rows into one synthetic item. At the
    # manga/search level this means every result; we only want the manga the
    # user actually highlighted, so honour the selected index. At the chapter
    # level it means every chapter of the chosen manga.
    bulk = item.get("_download_all_items")
    if bulk:
        manga_rows   = [r for r in bulk if r.get("kind") == "manga"]
        chapter_rows = [r for r in bulk if r.get("kind") == "chapter"]
        if manga_rows:
            idx = item.get("_selected_index", 0)
            if not 0 <= idx < len(manga_rows):
                idx = 0
            chapters = fetch_chapters(manga_rows[idx])
            if not chapters:
                raise RuntimeError("No chapters found for this manga.")
            return _download_many(chapters, merge_all, keep_images, progress_hook)
        if chapter_rows:
            return _download_many(chapter_rows, merge_all, keep_images, progress_hook)
        raise RuntimeError("Nothing to download.")

    if item.get("kind") == "manga":
        if progress_hook:
            # Clear any previous (manga) results, then stream chapters in from
            # chapter 0 so they appear in the result box incrementally.
            progress_hook({"status": "results_clear"})
            progress_hook(
                {
                    "status": "downloading",
                    "_percent_str": "",
                    "_speed_str": "Loading chapters…" if not download_all else "Downloading all chapters…",
                    "_eta_str": "",
                    "filename": item.get("title", ""),
                }
            )
        chapters = fetch_chapters(item, progress_hook=progress_hook)
        if progress_hook:
            progress_hook({"status": "results_done"})
        if not chapters:
            raise RuntimeError("No chapters found for this manga.")
        # "download all" -> grab every chapter of this selected manga (and merge
        # them into one PDF if that setting is also on). Otherwise just show the
        # chapter list so the user can pick one.
        if download_all:
            return _download_many(chapters, merge_all, keep_images, progress_hook)
        return None

    if item.get("kind") == "chapter":
        return _download_many([item], merge_all, keep_images, progress_hook)

    raise RuntimeError("Unsupported selection.")


def _download_many(chapters: list[dict], merge_all: bool, keep_images: bool,
                   progress_hook=None) -> None:
    manga_title = _safe_name(chapters[0].get("manga_title", "Manga"))
    out_dir     = Path(DOWNLOAD_PATH) / manga_title
    out_dir.mkdir(parents=True, exist_ok=True)

    combined: list[bytes] = []
    written:  list[Path]  = []

    if all(chapter.get("source") == "mangadex" for chapter in chapters):
        for index, chapter in enumerate(chapters, start=1):
            label = f"[{index}/{len(chapters)}] " if len(chapters) > 1 else ""
            pdf_path, images = _download_chapter(
                None, chapter, out_dir, keep_images, progress_hook, label
            )
            written.append(pdf_path)
            if merge_all:
                combined.extend(images)
    else:
        from playwright.sync_api import sync_playwright

        with _BROWSER_LOCK, sync_playwright() as playwright:
            context = _open_browser(playwright, block_images=True)
            try:
                page = _new_page(context)
                page = _warm_up(page)

                for index, chapter in enumerate(chapters, start=1):
                    label = f"[{index}/{len(chapters)}] " if len(chapters) > 1 else ""
                    pdf_path, images = _download_chapter(
                        page, chapter, out_dir, keep_images, progress_hook, label
                    )
                    written.append(pdf_path)
                    if merge_all:
                        combined.extend(images)
            finally:
                context.close()

    final_path = written[-1] if written else None

    if merge_all and combined:
        merged = Path(DOWNLOAD_PATH) / f"{manga_title}.pdf"
        _save_pdf(combined, merged)
        final_path = merged
        if not keep_images:
            # Per-chapter files were only an intermediate step.
            for path in written:
                path.unlink(missing_ok=True)
            if not any(out_dir.iterdir()):
                shutil.rmtree(out_dir, ignore_errors=True)

    if progress_hook and final_path:
        progress_hook(
            {
                "status": "finished",
                "filename": str(final_path),
                "display_full_path": True,
            }
        )
