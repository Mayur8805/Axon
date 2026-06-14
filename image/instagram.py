from __future__ import annotations

import json
import shutil
import string
import subprocess
import tempfile
from pathlib import Path

from core.menu import get_input, load_config, save_config


SETTINGS_KEY  = "instagram"
MEDIA_OPTIONS = ["image", "video"]
DOWNLOAD_PATH = "./Downloads/Instagram"
COOKIES_FILE  = Path(__file__).resolve().parent.parent / "instagram_cookies.txt"
DEBUG_LOG     = Path(__file__).resolve().parent.parent / "instagram_debug.log"

_SC_ALPHABET = string.ascii_uppercase + string.ascii_lowercase + string.digits + "-_"

# We keep one temp thumb per post here so PIL can load it even after tmp dir is gone
THUMB_CACHE = Path(tempfile.gettempdir()) / "axon_ig_thumbs"


def instagram_scraper() -> None:
    get_input(
        "@username or Instagram URL",
        fetch_fn=fetch_instagram_posts,
        download_fn=download_instagram_post,
        setting_fn=settings_fn,
    )


# ── settings ──────────────────────────────────────────────────────────────────

def settings_fn(action, settings=None):
    config           = load_config()
    instagram_config = config.setdefault(SETTINGS_KEY, {})
    media_config     = instagram_config.setdefault("media", {"image": True, "video": True})

    if action == "load":
        return {
            "type":    "toggles",
            "title":   "Settings",
            "label":   "Download media",
            "options": MEDIA_OPTIONS,
            "values":  {opt: bool(media_config.get(opt, False)) for opt in MEDIA_OPTIONS},
        }

    if action == "save" and settings:
        values = settings.get("values", {})
        instagram_config["media"] = {opt: bool(values.get(opt, False)) for opt in MEDIA_OPTIONS}
        save_config(config)


# ── helpers ───────────────────────────────────────────────────────────────────

def _log(msg: str) -> None:
    with open(DEBUG_LOG, "a", encoding="utf-8") as f:
        f.write(msg + "\n")


def _id_to_shortcode(post_id: str) -> str:
    n = int(post_id)
    result = []
    while n > 0:
        result.append(_SC_ALPHABET[n % 64])
        n //= 64
    return "".join(reversed(result))


def _build_instagram_url(query: str) -> str:
    v = query.strip()
    if v.startswith("http://") or v.startswith("https://"):
        return v
    return f"https://www.instagram.com/{v.lstrip('@').strip('/')}/"


def _gallery_dl_filter(values: dict) -> str:
    images = bool(values.get("image", False))
    videos = bool(values.get("video", False))
    if images and videos:
        return ""
    if images:
        return "extension in ('jpg', 'jpeg', 'png', 'webp')"
    if videos:
        return "extension in ('mp4', 'mov')"
    return ""


def _cookies_args() -> list[str]:
    return [f"--cookies={COOKIES_FILE}"] if COOKIES_FILE.exists() else []


# ── fetch ─────────────────────────────────────────────────────────────────────

def fetch_instagram_posts(query: str, on_result=None) -> list[dict]:
    """
    Download all media + JSON sidecars into a tmp dir.
    Use the first downloaded image of each post as its thumbnail (file path).
    Group carousel posts by post_shortcode.
    Stream results to on_result as each post's first image arrives.
    """
    DEBUG_LOG.write_text("", encoding="utf-8")

    # Clear and recreate thumb cache
    if THUMB_CACHE.exists():
        shutil.rmtree(THUMB_CACHE, ignore_errors=True)
    THUMB_CACHE.mkdir(parents=True, exist_ok=True)

    url = _build_instagram_url(query)
    _log(f"[fetch] URL: {url}")

    with tempfile.TemporaryDirectory(prefix="axon_ig_") as tmp:
        command = [
            "gallery-dl",
            *_cookies_args(),
            "--write-info-json",
            "--directory", tmp,
            "--filter", "extension in ('jpg', 'jpeg', 'png', 'webp')",
            url,
        ]
        _log(f"[fetch] cmd: {' '.join(command)}")

        try:
            proc = subprocess.run(command, capture_output=True, text=True)
        except FileNotFoundError:
            err = _err_item("❌ gallery-dl not found.")
            if on_result:
                on_result(err)
            return [err]

        _log(f"[fetch] rc={proc.returncode}")
        if proc.stderr.strip():
            _log(f"[fetch] stderr: {proc.stderr.strip()[:300]}")

        # ── collect all image files and their sidecar JSONs ──────────────────
        image_exts = {".jpg", ".jpeg", ".png", ".webp"}
        image_files = sorted(
            f for f in Path(tmp).rglob("*")
            if f.is_file() and f.suffix.lower() in image_exts
        )
        _log(f"[fetch] image files found: {len(image_files)}")

        if not image_files:
            _log("[fetch] no images — falling back to filename lines")
            return _parse_filename_lines(proc.stdout, on_result)

        # ── group images by post_shortcode from sidecar JSON ─────────────────
        posts:  dict[str, dict] = {}   # shortcode → item
        order:  list[str]       = []

        for img_path in image_files:
            json_path = img_path.with_suffix(img_path.suffix + ".json")
            meta: dict = {}
            if json_path.exists():
                try:
                    meta = json.loads(json_path.read_text(encoding="utf-8"))
                except Exception:
                    pass

            # Log all keys once for debugging
            if not posts:
                _log(f"[meta keys] {list(meta.keys())}")

            # ── pull fields using the actual key names from the log ──────────
            shortcode   = (
                meta.get("post_shortcode")
                or meta.get("shortcode")
                or meta.get("sidecar_shortcode")
                or ""
            )
            description = (
                meta.get("description")
                or meta.get("caption")
                or ""
            )
            post_id_raw = (
                meta.get("post_id")
                or meta.get("sidecar_media_id")
                or ""
            )
            date = str(meta.get("post_date") or meta.get("date") or "")

            # Derive shortcode from post_id if still missing
            if not shortcode and post_id_raw and str(post_id_raw).isdigit():
                shortcode = _id_to_shortcode(str(post_id_raw))

            # Fall back to filename stem's first segment
            if not shortcode:
                stem  = img_path.stem          # e.g. 3380927807287979486_3380927793673218846
                parts = stem.split("_")
                if parts[0].isdigit():
                    shortcode = _id_to_shortcode(parts[0])

            post_url   = f"https://www.instagram.com/p/{shortcode}/" if shortcode else ""
            short_desc = (description[:55] + "…") if len(description) > 55 else description
            title      = short_desc or post_url or img_path.name

            _log(f"[img] {img_path.name}  sc={shortcode}  desc={description[:40]!r}")

            key = shortcode or img_path.stem

            if key not in posts:
                # Copy first image of this post to the persistent thumb cache
                thumb_dest = THUMB_CACHE / f"{key}{img_path.suffix}"
                try:
                    shutil.copy2(img_path, thumb_dest)
                    thumbnail = str(thumb_dest)
                except Exception:
                    thumbnail = ""

                item = {
                    "title":       title,
                    "url":         post_url,
                    "thumbnail":   thumbnail,   # local file path
                    "shortcode":   shortcode,
                    "date":        date,
                    "_meta":       meta,
                    "_urls":       [post_url] if post_url else [],
                    "_count":      1,
                    "_base_title": title,
                }
                posts[key] = item
                order.append(key)

                if on_result:
                    on_result(item)
            else:
                # Carousel: just increment count and update title
                posts[key]["_count"] += 1
                count = posts[key]["_count"]
                posts[key]["title"] = f"{posts[key]['_base_title']}  [{count} photos]"

        items = [posts[k] for k in order]
        _log(f"[fetch] total posts: {len(items)}")
        return items


# ── fallback: parse # filename lines ─────────────────────────────────────────

def _parse_filename_lines(stdout: str, on_result) -> list[dict]:
    posts: dict[str, dict] = {}
    order: list[str]       = []

    for line in stdout.splitlines():
        line = line.strip()
        if not line.startswith("#"):
            continue
        filename = line[1:].strip()
        stem     = filename.rsplit(".", 1)[0]
        parts    = stem.split("_")
        if len(parts) < 2 or not parts[0].isdigit():
            continue

        post_id   = parts[0]
        shortcode = _id_to_shortcode(post_id)
        post_url  = f"https://www.instagram.com/p/{shortcode}/"

        if post_id not in posts:
            item = {
                "title":       post_url,
                "url":         post_url,
                "thumbnail":   "",
                "shortcode":   shortcode,
                "date":        "",
                "_meta":       {},
                "_urls":       [post_url],
                "_count":      1,
                "_base_title": post_url,
            }
            posts[post_id] = item
            order.append(post_id)
            if on_result:
                on_result(item)
        else:
            posts[post_id]["_count"] += 1
            posts[post_id]["title"] = f"{posts[post_id]['_base_title']}  [{posts[post_id]['_count']} photos]"

    items = [posts[k] for k in order]
    if not items:
        err = _err_item("⚠ No posts found.")
        if on_result:
            on_result(err)
        return [err]
    return items


def _err_item(msg: str) -> dict:
    return {
        "title": msg, "url": "", "thumbnail": "",
        "shortcode": "", "date": "", "_meta": {},
        "_urls": [], "_count": 0,
    }


# ── download ──────────────────────────────────────────────────────────────────

def download_instagram_post(item: dict, progress_hook=None, settings=None) -> None:
    post_url = item.get("url", "")
    if not post_url:
        if progress_hook:
            progress_hook({"status": "finished", "filename": "No URL for this post."})
        return

    values = (settings or settings_fn("load")).get("values", {"image": True, "video": True})
    if not any(values.get(opt, False) for opt in MEDIA_OPTIONS):
        if progress_hook:
            progress_hook({"status": "finished", "filename": "Enable image or video in settings."})
        return

    media_filter = _gallery_dl_filter(values)
    command = ["gallery-dl", *_cookies_args(), "--directory", DOWNLOAD_PATH]
    if media_filter:
        command.extend(["--filter", media_filter])
    command.append(post_url)

    if progress_hook:
        progress_hook({
            "status": "downloading", "_percent_str": "",
            "_speed_str": "gallery-dl", "_eta_str": "",
            "filename": f"Downloading {item.get('_count', 1)} file(s)…",
            "display_full_path": True,
        })

    try:
        process = subprocess.Popen(
            command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, bufsize=1,
        )
        last_line = ""
        for line in process.stdout or []:
            last_line = line.strip()
            if progress_hook and last_line:
                progress_hook({
                    "status": "downloading", "_percent_str": "",
                    "_speed_str": "gallery-dl", "_eta_str": "",
                    "filename": last_line, "display_full_path": True,
                })
        rc = process.wait()
        if rc != 0:
            raise subprocess.CalledProcessError(rc, command)
    except FileNotFoundError:
        if progress_hook:
            progress_hook({"status": "finished", "filename": "gallery-dl not found."})
        return
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(f"Download failed (exit {exc.returncode})") from exc

    if progress_hook:
        progress_hook({
            "status": "finished",
            "filename": last_line or f"Saved to {DOWNLOAD_PATH}",
            "display_full_path": True,
        })


if __name__ == "__main__":
    instagram_scraper()