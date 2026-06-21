from __future__ import annotations

import json
import os
import queue
import shutil
import string
import subprocess
import tempfile
import threading
import time
from pathlib import Path

from core.menu import get_input, load_config, save_config


SETTINGS_KEY  = "instagram"
MEDIA_OPTIONS = ["image", "video"]
DOWNLOAD_ALL_OPTION = "download all"
SETTING_OPTIONS = [*MEDIA_OPTIONS, DOWNLOAD_ALL_OPTION]
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
    download_all     = bool(instagram_config.get("download_all", False))
    if not any(bool(media_config.get(opt, False)) for opt in MEDIA_OPTIONS):
        media_config["image"] = True

    if action == "load":
        return {
            "type":    "toggles",
            "title":   "Settings",
            "label":   "Download media",
            "options": SETTING_OPTIONS,
            "required_groups": [MEDIA_OPTIONS],
            "values":  {
                "image": bool(media_config.get("image", False)),
                "video": bool(media_config.get("video", False)),
                DOWNLOAD_ALL_OPTION: download_all,
            },
        }

    if action == "save" and settings:
        values = settings.get("values", {})
        instagram_config["media"] = {opt: bool(values.get(opt, False)) for opt in MEDIA_OPTIONS}
        instagram_config["download_all"] = bool(values.get(DOWNLOAD_ALL_OPTION, False))
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


IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp"}
VIDEO_EXTS = {".mp4", ".mov", ".m4v", ".webm"}


def _gallery_dl_filter(values: dict) -> str:
    images = bool(values.get("image", False))
    videos = bool(values.get("video", False))
    if images and videos:
        return ""
    if images:
        return "extension in ('jpg', 'jpeg', 'png', 'webp')"
    if videos:
        return "extension in ('mp4', 'mov', 'm4v', 'webm')"
    return ""


def _gallery_dl_options(values: dict) -> list[str]:
    videos = bool(values.get("video", False))
    return ["--option", f"extractor.instagram.videos={'true' if videos else 'false'}"]


def _cookies_args() -> list[str]:
    return [f"--cookies={COOKIES_FILE}"] if COOKIES_FILE.exists() else []


def _allowed_exts(values: dict) -> set[str]:
    exts: set[str] = set()
    if values.get("image", False):
        exts.update(IMAGE_EXTS)
    if values.get("video", False):
        exts.update(VIDEO_EXTS)
    return exts


def _safe_cache_name(key: str, suffix: str) -> str:
    safe = "".join(ch if ch.isalnum() or ch in "-_." else "_" for ch in key)
    return f"{safe}{suffix}"


def _copy_to_cache(src: Path, key: str) -> str:
    dest = THUMB_CACHE / _safe_cache_name(key, src.suffix)
    shutil.copy2(src, dest)
    return str(dest)


def _media_type(path: Path) -> str:
    return "video" if path.suffix.lower() in VIDEO_EXTS else "image"


def _read_meta(media_path: Path) -> dict:
    json_path = media_path.with_suffix(media_path.suffix + ".json")
    if not json_path.exists():
        return {}

    try:
        return json.loads(json_path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _item_from_media(media_path: Path, sequence: int, total_by_post: int | None = None) -> dict:
    meta = _read_meta(media_path)

    shortcode = (
        meta.get("post_shortcode")
        or meta.get("shortcode")
        or meta.get("sidecar_shortcode")
        or ""
    )
    description = meta.get("description") or meta.get("caption") or ""
    post_id_raw = meta.get("post_id") or meta.get("sidecar_media_id") or ""

    if not shortcode and post_id_raw and str(post_id_raw).isdigit():
        shortcode = _id_to_shortcode(str(post_id_raw))

    if not shortcode:
        stem_parts = media_path.stem.split("_")
        if stem_parts and stem_parts[0].isdigit():
            shortcode = _id_to_shortcode(stem_parts[0])

    post_url = f"https://www.instagram.com/p/{shortcode}/" if shortcode else ""
    media_kind = _media_type(media_path)
    media_id = (
        meta.get("media_id")
        or meta.get("sidecar_media_id")
        or meta.get("id")
        or media_path.stem
    )
    media_key = f"{shortcode or media_path.stem}:{media_id}:{media_kind}"

    cached_media = _copy_to_cache(media_path, media_key)
    thumbnail = cached_media if media_kind == "image" else ""

    short_desc = (description[:55] + "...") if len(description) > 55 else description
    base_title = media_path.name if media_kind == "video" else (short_desc or post_url or media_path.name)
    if total_by_post and total_by_post > 1:
        title = f"{base_title}  [{sequence}/{total_by_post} {media_kind}]"
    else:
        title = f"{base_title}  [{media_kind}]"

    return {
        "title":       title,
        "url":         post_url,
        "thumbnail":   thumbnail,
        "shortcode":   shortcode,
        "date":        str(meta.get("post_date") or meta.get("date") or ""),
        "_meta":       meta,
        "_urls":       [post_url] if post_url else [],
        "_count":      1,
        "_base_title": base_title,
        "_media_type": media_kind,
        "_media_id":   str(media_id),
        "_source_path": cached_media,
        "_result_key": media_key,
        "_sequence":   sequence,
    }


# ── fetch ─────────────────────────────────────────────────────────────────────

def fetch_instagram_posts(query: str, on_result=None, cancel_event=None) -> list[dict]:
    """
    Download media + JSON sidecars into a tmp dir and stream each media item
    as soon as gallery-dl finishes writing it. Carousel posts are exposed as
    separate selectable entries so Enter downloads the selected media only.
    """
    DEBUG_LOG.write_text("", encoding="utf-8")

    # Clear and recreate thumb cache
    if THUMB_CACHE.exists():
        shutil.rmtree(THUMB_CACHE, ignore_errors=True)
    THUMB_CACHE.mkdir(parents=True, exist_ok=True)

    url = _build_instagram_url(query)
    values = settings_fn("load").get("values", {"image": True, "video": True})
    media_filter = _gallery_dl_filter(values)
    allowed_exts = _allowed_exts(values)
    _log(f"[fetch] URL: {url}")

    if not allowed_exts:
        err = _err_item("Enable image or video in settings.")
        if on_result:
            on_result(err)
        return [err]

    with tempfile.TemporaryDirectory(prefix="axon_ig_") as tmp:
        command = [
            "gallery-dl",
            *_cookies_args(),
            *_gallery_dl_options(values),
            "--write-info-json",
            "--directory", tmp,
            url,
        ]
        if media_filter:
            command[-1:-1] = ["--filter", media_filter]
        _log(f"[fetch] cmd: {' '.join(command)}")

        try:
            proc = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )
        except FileNotFoundError:
            err = _err_item("❌ gallery-dl not found.")
            if on_result:
                on_result(err)
            return [err]

        items: list[dict] = []
        seen: set[Path] = set()
        seen_result_indices: dict[str, int] = {}
        stdout_lines: list[str] = []
        tmp_path = Path(tmp)
        output_queue: "queue.Queue[str]" = queue.Queue()

        def read_output() -> None:
            if not proc.stdout:
                return
            for output_line in proc.stdout:
                output_queue.put(output_line)

        threading.Thread(target=read_output, daemon=True).start()

        def collect_ready_files() -> None:
            if cancel_event and cancel_event.is_set():
                return

            media_files = sorted(
                f for f in tmp_path.rglob("*")
                if f.is_file() and f.suffix.lower() in allowed_exts and f not in seen
            )
            for media_path in media_files:
                if cancel_event and cancel_event.is_set():
                    return

                try:
                    size_before = media_path.stat().st_size
                    time.sleep(0.03)
                    if media_path.stat().st_size != size_before:
                        continue
                except OSError:
                    continue

                seen.add(media_path)
                item = _item_from_media(media_path, len(items) + 1)
                result_key = item.get("_result_key", "")
                if result_key in seen_result_indices:
                    items[seen_result_indices[result_key]] = item
                else:
                    seen_result_indices[result_key] = len(items)
                    items.append(item)
                _log(f"[media] {media_path.name} type={item['_media_type']} sc={item['shortcode']}")
                if on_result:
                    on_result(item)

        while proc.poll() is None:
            if cancel_event and cancel_event.is_set():
                _log("[fetch] cancelled; terminating gallery-dl")
                proc.terminate()
                try:
                    proc.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    _log("[fetch] terminate timed out; killing gallery-dl")
                    proc.kill()
                    proc.wait()
                return items

            while True:
                try:
                    line = output_queue.get_nowait()
                except queue.Empty:
                    break
                stdout_lines.append(line)
                _log(f"[gallery-dl] {line.strip()}")
            collect_ready_files()
            time.sleep(0.1)

        while True:
            try:
                line = output_queue.get_nowait()
            except queue.Empty:
                break
            else:
                stdout_lines.append(line)
                _log(f"[gallery-dl] {line.strip()}")
        collect_ready_files()

        rc = proc.wait()
        _log(f"[fetch] rc={rc}")

        per_post: dict[str, int] = {}
        for item in items:
            key = item.get("shortcode") or item.get("url") or item.get("_result_key", "")
            per_post[key] = per_post.get(key, 0) + 1

        post_seen: dict[str, int] = {}
        for item in items:
            key = item.get("shortcode") or item.get("url") or item.get("_result_key", "")
            post_seen[key] = post_seen.get(key, 0) + 1
            count = per_post.get(key, 1)
            if count > 1:
                item["_sequence"] = post_seen[key]
                item["title"] = f"{item['_base_title']}  [{post_seen[key]}/{count} {item['_media_type']}]"
                if on_result:
                    on_result(item)

        if not items:
            if media_filter:
                _log("[fetch] no media matched selected filters")
                err = _err_item("No matching media found for selected image/video settings.")
                if on_result:
                    on_result(err)
                return [err]

            _log("[fetch] no media — falling back to filename lines")
            return _parse_filename_lines("".join(stdout_lines), on_result)

        _log(f"[fetch] total media items: {len(items)}")
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
    if "_download_all_items" in item:
        download_instagram_items(item.get("_download_all_items", []), progress_hook=progress_hook)
        return

    source_path = item.get("_source_path", "")
    if source_path and os.path.exists(source_path):
        os.makedirs(DOWNLOAD_PATH, exist_ok=True)
        dest = Path(DOWNLOAD_PATH) / Path(source_path).name
        if progress_hook:
            progress_hook({
                "status": "downloading", "_percent_str": "",
                "_speed_str": "local copy", "_eta_str": "",
                "filename": f"Saving selected {item.get('_media_type', 'media')}...",
                "display_full_path": True,
            })
        shutil.copy2(source_path, dest)
        if progress_hook:
            progress_hook({
                "status": "finished",
                "filename": str(dest),
                "display_full_path": True,
            })
        return

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
    command = [
        "gallery-dl",
        *_cookies_args(),
        *_gallery_dl_options(values),
        "--directory", DOWNLOAD_PATH,
    ]
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


def download_instagram_items(items: list[dict], progress_hook=None) -> None:
    downloadable = []
    seen: set[str] = set()
    for item in items:
        source_path = item.get("_source_path", "") if isinstance(item, dict) else ""
        if not source_path or not os.path.exists(source_path) or source_path in seen:
            continue
        seen.add(source_path)
        downloadable.append(item)

    if not downloadable:
        if progress_hook:
            progress_hook({"status": "finished", "filename": "No downloaded media available to save."})
        return

    os.makedirs(DOWNLOAD_PATH, exist_ok=True)
    saved = 0
    for index, item in enumerate(downloadable, 1):
        source_path = item["_source_path"]
        dest = Path(DOWNLOAD_PATH) / Path(source_path).name
        if progress_hook:
            progress_hook({
                "status": "downloading", "_percent_str": f"{index}/{len(downloadable)}",
                "_speed_str": "local copy", "_eta_str": "",
                "filename": f"Saving {Path(source_path).name}",
                "display_full_path": True,
            })
        shutil.copy2(source_path, dest)
        saved += 1

    if progress_hook:
        progress_hook({
            "status": "finished",
            "filename": f"Saved {saved} file(s) to {DOWNLOAD_PATH}",
            "display_full_path": True,
        })


if __name__ == "__main__":
    instagram_scraper()
