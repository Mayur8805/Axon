import os
import yt_dlp
from ytmusicapi import YTMusic
from core.menu import get_input

DOWNLOAD_PATH = "./Downloads/Audio"

def youtube_music_scraper():
    selected = get_input("Select an option:", fetch_fn=scrape_results, download_fn=download)


def scrape_results(query):
    ytmusic = YTMusic()
    results = ytmusic.search(query, filter="songs")

    songs = []

    for song in results:
        songs.append({
            "title": song.get("title"),
            "videoId": song.get("videoId"),
            "thumbnail": song["thumbnails"][-1]["url"] if song.get("thumbnails") else None
        })

    return songs


def download(item, progress_hook=None):
    video_id = item.get("videoId", "")
    url      = f"https://music.youtube.com/watch?v={video_id}"

    ydl_opts = {
        "format": "bestaudio/best",
        "outtmpl": os.path.join(DOWNLOAD_PATH, "%(title)s.%(ext)s"),
        "postprocessors": [{
            "key": "FFmpegExtractAudio",
            "preferredcodec": "mp3",
            "preferredquality": "320",
        }],
        "quiet": True,
        "no_warnings": True,
    }
    if progress_hook:
        ydl_opts["progress_hooks"] = [progress_hook]

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        ydl.download([url])
