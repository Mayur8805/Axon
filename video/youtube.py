import re
import os
import json
import requests
import yt_dlp

from bs4 import BeautifulSoup
from core.menu import get_input


YT_SEARCH_BASE = "https://www.youtube.com/results?search_query="
YT_WATCH_BASE  = "https://www.youtube.com/watch?v="
DOWNLOAD_PATH  = os.path.abspath("Downloads/Videos")
os.makedirs(DOWNLOAD_PATH, exist_ok=True)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}

def youtube_scraper():
    query = get_input("Search YouTube Video", fetch_fn=scrape_results, download_fn=download_video)


def build_search_url(query: str) -> str:
    return YT_SEARCH_BASE + query.strip().replace(" ", "+")

def build_format_string(resolution: dict, container: dict, codec: dict) -> str:
    base = resolution["fmt"]                    # resolution already has a base fmt

    # If codec is not "any", inject vcodec filter
    if codec["value"] != "any":
        vcodec = codec["value"]
        # Replace bestvideo with bestvideo[vcodec^=<codec>]
        base = base.replace(
            "bestvideo[height",
            f"bestvideo[vcodec^={vcodec}][height"
        ).replace(
            "bestvideo+bestaudio",
            f"bestvideo[vcodec^={vcodec}]+bestaudio"
        )

    return base

def scrape_results(query: str, max_results: int = 10) -> list:
    url = build_search_url(query)

    try:
        resp = requests.get(url, headers=HEADERS, timeout=10)
        resp.raise_for_status()
    except requests.RequestException as e:
        return []

    soup    = BeautifulSoup(resp.text, "html.parser")
    raw_json = None

    for script in soup.find_all("script"):
        text = script.string or ""
        if "ytInitialData" not in text:
            continue
        m = re.search(r"var ytInitialData\s*=\s*(\{.*?\});\s*</script>", text, re.DOTALL)
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
    except json.JSONDecodeError as e:
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

    results = []
    for sec in section_contents:
        for item in sec.get("itemSectionRenderer", {}).get("contents", []):
            vr = item.get("videoRenderer")
            if not vr:
                continue
            video_id = vr.get("videoId", "")
            if not video_id:
                continue
            title    = "".join(r.get("text", "") for r in vr.get("title", {}).get("runs", [])).strip()
            thumbnails   = vr.get("thumbnail", {}).get("thumbnails", [])
            best_thumb   = max(thumbnails,
                               key=lambda t: (t.get("width", 0), t.get("height", 0)),
                               default={})
            thumbnail_url = best_thumb.get("url", "")

            duration = vr.get("lengthText", {}).get("simpleText", "??:??")
            channel  = "".join(r.get("text", "") for r in vr.get("longBylineText", {}).get("runs", [])).strip()
            views    = vr.get("viewCountText", {}).get("simpleText", "")
            results.append({"title": title, "thumbnail": thumbnail_url, "video_id": video_id,
                            "duration": duration, "channel": channel, "views": views})
            if len(results) >= max_results:
                return results
    return results

def download_video(item: dict, progress_hook=None) -> None:
    """Download the selected item in best video quality."""

    video_id = item.get("video_id", "")
    url      = f"{YT_WATCH_BASE}{video_id}"

    ydl_opts = {
        "format": "bestvideo+bestaudio/best",
        "outtmpl": os.path.join(DOWNLOAD_PATH,"%(title)s.%(ext)s"),
        "merge_output_format": "mp4",
        "windowsfilenames": True,
        "quiet": True,
        "no_warnings": True,
    }
    if progress_hook:
        ydl_opts["progress_hooks"] = [progress_hook]

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])

    except Exception as e:
        print(f"Download Error: {e}")