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

# ── Download function (passed into TUI) ──────────────────────────────────────
def download_audio(item: dict, progress_hook=None, settings=None) -> None:
    """Download the selected item as MP3. Called from the TUI's background thread."""
    video_id = item.get("video_id", "")
    url      = f"{YT_WATCH_BASE}{video_id}"
    codec = (settings or {}).get("selected", "flac")

    ydl_opts = build_audio_options(codec, progress_hook=progress_hook)
    
    if progress_hook:
        ydl_opts["progress_hooks"] = [progress_hook]

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        ydl.download([url])
def settings_fn(action, settings=None):
    config = load_config()
    youtube_config = config.setdefault(SETTINGS_KEY, {})
    codec_config = youtube_config.setdefault(
        "preferredcodec",
        {"flac": True, "opus": False, "mp3": False},
    )

    selected = next((codec for codec in CODEC_OPTIONS if codec_config.get(codec)), "flac")

    if action == "load":
        return {
            "title": "Settings",
            "label": "Preferred codec",
            "options": CODEC_OPTIONS,
            "selected": selected,
        }

    if action == "save" and settings:
        selected = settings.get("selected", "flac")
        youtube_config["preferredcodec"] = _codec_config(selected)
        save_config(config)

def build_audio_options(codec, progress_hook=None):
    ydl_opts = {
        "outtmpl": os.path.join(DOWNLOAD_PATH, "%(title)s.%(ext)s"),
        "quiet": False,
        "no_warnings": False,
    }

    if codec == "opus":
        ydl_opts.update(
            {
                "format": "bestaudio[ext=webm]/bestaudio/best",
                "postprocessors": [{
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "opus",
                    "preferredquality": "0",
                }],
            }
        )
    elif codec == "flac":
        ydl_opts.update(
            {
                "format": "bestaudio/best",
                "postprocessors": [{
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "flac",
                    "preferredquality": "0",
                }],
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
                "postprocessors": [{
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "mp3",
                    "preferredquality": "0",
                }],
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

            thumbnails   = vr.get("thumbnail", {}).get("thumbnails", [])
            best_thumb   = max(thumbnails,
                               key=lambda t: (t.get("width", 0), t.get("height", 0)),
                               default={})
            thumbnail_url = best_thumb.get("url", "")

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