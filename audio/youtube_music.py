import os

import yt_dlp
from ytmusicapi import YTMusic

from core.menu import get_input, load_config, save_config

DOWNLOAD_PATH = "./Downloads/Audio"
SETTINGS_KEY = "youtubemusic"
CODEC_OPTIONS = ["flac", "opus", "mp3"]
THUMBNAIL_OPTION = "include thumbnail"


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
    include_thumbnail = youtube_music_config.setdefault("include_thumbnail", True)

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
        youtube_music_config["preferredcodec"] = _codec_config(selected)
        youtube_music_config["include_thumbnail"] = bool(values.get(THUMBNAIL_OPTION, True))
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
        "js_runtimes": {"deno": {}},
        "writethumbnail": include_thumbnail,
        "verbose": True
    }

    if codec == "opus":
        ydl_opts.update({
            "format": "bestaudio[ext=webm]/bestaudio/best",
            "postprocessors": _with_thumbnail_postprocessors([
                {
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "opus",
                },
            ], include_thumbnail),
            "postprocessor_args": {
                "FFmpegExtractAudio": ["-q:a", "0"]  
            },
            "cookiesfrombrowser": ("firefox",),
        })
    elif codec == "mp3":
        ydl_opts.update(
            {
                "format": "bestaudio/best",
                "postprocessors": _with_thumbnail_postprocessors([{
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "mp3",
                    "preferredquality": "0",
                },
                ], include_thumbnail),
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
                "postprocessors": _with_thumbnail_postprocessors([{
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "flac",
                    "preferredquality": "0",
                },
                ], include_thumbnail),
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
    url = f"https://music.youtube.com/watch?v={video_id}"
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
