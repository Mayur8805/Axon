import os

import yt_dlp
from ytmusicapi import YTMusic

from core.menu import get_input, load_config, save_config

DOWNLOAD_PATH = "./Downloads/Audio"
SETTINGS_KEY = "youtubemusic"
CODEC_OPTIONS = ["flac", "opus", "mp3"]


def _codec_config(selected_codec):
    return {codec: codec == selected_codec for codec in CODEC_OPTIONS}

def youtube_music_scraper():
    get_input(
        "Select an option:",
        fetch_fn=scrape_results,
        download_fn=download,
        setting_fn=settings_fn,
    )


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


def settings_fn(action, settings=None):
    config = load_config()
    youtube_music_config = config.setdefault(SETTINGS_KEY, {})
    codec_config = youtube_music_config.setdefault(
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
        youtube_music_config["preferredcodec"] = _codec_config(selected)
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
                "cookiesfrombrowser": ("firefox",),
            }
        )
    elif codec == "mp3":
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
                "cookiesfrombrowser": ("firefox",),
            }
        )
    else:
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
                "cookiesfrombrowser": ("firefox",),
            }
        )

    if progress_hook:
        ydl_opts["progress_hooks"] = [progress_hook]

    return ydl_opts


def download(item, progress_hook=None, settings=None):
    video_id = item.get("videoId", "")
    url      = f"https://music.youtube.com/watch?v={video_id}"

    codec = (settings or {}).get("selected", "flac")
    ydl_opts = build_audio_options(codec, progress_hook=progress_hook)

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        ydl.download([url])
