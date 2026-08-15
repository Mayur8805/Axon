"""
youtube_audio_scraper.py
"""

import os
import json
import re
import requests
from bs4 import BeautifulSoup
import yt_dlp

from core.menu import get_input, load_config, save_config

# ── Config ───────────────────────────────────────────────────────────────────
YT_SEARCH_BASE = "https://www.youtube.com/results?search_query="
YT_WATCH_BASE  = "https://www.youtube.com/watch?v="
FORMAT_STRING  = "bestaudio[ext=m4a]/bestaudio[ext=webm]/bestaudio/best"
DOWNLOAD_PATH  = "./Downloads/Audio"
os.makedirs(DOWNLOAD_PATH, exist_ok=True)
SETTINGS_KEY = "youtubeformusic"
CODEC_OPTIONS = ["flac", "opus", "mp3"]
THUMBNAIL_OPTION = "include thumbnail"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}

def _codec_config(selected_codec):
    return {codec: codec == selected_codec for codec in CODEC_OPTIONS}


def _best_thumbnail(thumbnails):
    if not thumbnails:
        return None

    squares = [
        t for t in thumbnails
        if t.get("width") and t.get("height") and t["width"] == t["height"]
    ]
    candidates = squares or thumbnails

    def _size(t):
        return t.get("width", 0) or 0

    best = max(candidates, key=_size, default={})
    return best.get("url")


# ── Download function (passed into TUI) ──────────────────────────────────────
def download_audio(item: dict, progress_hook=None, settings=None) -> None:
    """Download the selected item as audio. Called from the TUI's background thread."""
    video_id = item.get("video_id", "")
    url      = f"{YT_WATCH_BASE}{video_id}"

    settings = settings or settings_fn("load")
    values = settings.get("values", {})
    codec = next(
        (codec for codec in CODEC_OPTIONS if values.get(codec)),
        settings.get("selected", "flac"),
    )
    include_thumbnail = bool(values.get(THUMBNAIL_OPTION, True))

    ydl_opts = build_audio_options(
        codec,
        progress_hook=progress_hook,
        include_thumbnail=include_thumbnail,
    )

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])
    except yt_dlp.utils.DownloadError:
        if not include_thumbnail:
            raise

        # Retry once without thumbnail embedding so the song isn't lost
        ydl_opts_fallback = build_audio_options(codec, progress_hook=progress_hook)
        ydl_opts_fallback["writethumbnail"] = False
        ydl_opts_fallback["postprocessors"] = [
            pp for pp in ydl_opts_fallback["postprocessors"]
            if pp["key"] not in ("EmbedThumbnail", "FFmpegThumbnailsConvertor")
        ]
        with yt_dlp.YoutubeDL(ydl_opts_fallback) as ydl:
            ydl.download([url])


def settings_fn(action, settings=None):
    config = load_config()
    youtube_config = config.setdefault(SETTINGS_KEY, {})
    codec_config = youtube_config.setdefault(
        "preferredcodec",
        {"flac": True, "opus": False, "mp3": False},
    )
    include_thumbnail = youtube_config.setdefault("include_thumbnail", True)

    selected = next((codec for codec in CODEC_OPTIONS if codec_config.get(codec)), "flac")

    if action == "load":
        return {
            "title": "Settings",
            "label": "Download options",
            "type": "toggles",
            "options": [*CODEC_OPTIONS, THUMBNAIL_OPTION],
            "values": {
                **_codec_config(selected),
                THUMBNAIL_OPTION: bool(include_thumbnail),
            },
            "exclusive_groups": [CODEC_OPTIONS],
            "required_groups": [CODEC_OPTIONS],
            "groups": [
                {"title": "Download as", "options": CODEC_OPTIONS},
                {"title": "Cover setting", "options": [THUMBNAIL_OPTION]},
            ],
        }

    if action == "save" and settings:
        values = settings.get("values", {})
        selected = next((codec for codec in CODEC_OPTIONS if values.get(codec)), "flac")
        youtube_config["preferredcodec"] = _codec_config(selected)
        youtube_config["include_thumbnail"] = bool(values.get(THUMBNAIL_OPTION, True))
        save_config(config)


def _with_thumbnail_postprocessors(postprocessors, include_thumbnail):
    if include_thumbnail:
        postprocessors.extend([
            {"key": "FFmpegThumbnailsConvertor", "format": "jpg"},
            {"key": "EmbedThumbnail"},
        ])

    postprocessors.append({"key": "FFmpegMetadata"})
    return postprocessors


def build_audio_options(codec, progress_hook=None, include_thumbnail=True):
    ydl_opts = {
        "outtmpl": os.path.join(DOWNLOAD_PATH, "%(title)s.%(ext)s"),
        "quiet": False,
        "no_warnings": False,
        "writethumbnail": include_thumbnail,
    }

    if codec == "opus":
        ydl_opts.update(
            {
                "format": "bestaudio[ext=webm]/bestaudio/best",
                "postprocessors": _with_thumbnail_postprocessors([{
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "opus",
                    "preferredquality": "0",
                }], include_thumbnail),
            }
        )
    elif codec == "flac":
        ydl_opts.update(
            {
                "format": "bestaudio/best",
                "postprocessors": _with_thumbnail_postprocessors([{
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "flac",
                    "preferredquality": "0",
                }], include_thumbnail),
                "postprocessor_args": {
                    "FFmpegExtractAudio": [
                        "-compression_level", "8",
                    ]
                },
            }
        )
    else:
        ydl_opts.update(
            {
                "format": "bestaudio/best",
                "postprocessors": _with_thumbnail_postprocessors([{
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "mp3",
                    "preferredquality": "0",
                }], include_thumbnail),
                "postprocessor_args": {
                    "FFmpegExtractAudio": [
                        "-q:a", "0",
                        "-compression_level", "0",
                    ]
                },
            }
        )

    if progress_hook:
        ydl_opts["progress_hooks"] = [progress_hook]

    return ydl_opts
# ── Entry point ───────────────────────────────────────────────────────────────
def youtube_audio_scraper() -> None:
    get_input(
        msg="Search for a song or artist",
        fetch_fn=scrape_results,
        download_fn=download_audio,
        setting_fn=settings_fn,
    )


# ── Scraper ───────────────────────────────────────────────────────────────────
def build_search_url(query: str) -> str:
    return YT_SEARCH_BASE + query.strip().replace(" ", "+")


def scrape_results(query: str, max_results: int = 10) -> list[dict]:
    url = build_search_url(query)
    try:
        resp = requests.get(url, headers=HEADERS, timeout=10)
        resp.raise_for_status()
    except requests.RequestException:
        return []

    soup     = BeautifulSoup(resp.text, "html.parser")
    raw_json = None

    for script in soup.find_all("script"):
        text = script.string or ""
        if "ytInitialData" not in text:
            continue
        m = re.search(r"var ytInitialData\s*=\s*(\{.*?\});\s*</script>",
                      text, re.DOTALL)
        if m:
            raw_json = m.group(1)
            break
        m = re.search(r"var ytInitialData\s*=\s*(\{.+)", text, re.DOTALL)
        if m:
            raw_json = m.group(1).rstrip().rstrip(";")
            break

    if not raw_json:
        return []

    try:
        data = json.loads(raw_json)
    except json.JSONDecodeError:
        return []

    try:
        section_contents = (
            data["contents"]
                ["twoColumnSearchResultsRenderer"]
                ["primaryContents"]
                ["sectionListRenderer"]
                ["contents"]
        )
    except (KeyError, TypeError):
        return []

    results: list[dict] = []
    for sec in section_contents:
        items = sec.get("itemSectionRenderer", {}).get("contents", [])
        for item in items:
            vr = item.get("videoRenderer")
            if not vr:
                continue

            video_id = vr.get("videoId", "")
            if not video_id:
                continue

            thumbnails     = vr.get("thumbnail", {}).get("thumbnails", [])
            thumbnail_url  = _best_thumbnail(thumbnails) or ""

            title = "".join(
                r.get("text", "")
                for r in vr.get("title", {}).get("runs", [])
            ).strip()

            duration = vr.get("lengthText", {}).get("simpleText", "??:??")

            results.append({
                "title":     title,
                "thumbnail": thumbnail_url,
                "video_id":  video_id,
                "duration":  duration,
            })

            if len(results) >= max_results:
                return results

    return results


if __name__ == "__main__":
    youtube_audio_scraper()