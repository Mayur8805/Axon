import os
import json
import re
import time
from myjdapi import Myjdapi
from dotenv import load_dotenv
from core.menu import get_input

load_dotenv()

email = os.getenv("JD_EMAIL")
password = os.getenv("JD_PASSWORD")
DOWNLOAD_PATH  = os.path.abspath("Downloads/Videos")
os.makedirs(DOWNLOAD_PATH, exist_ok=True)

jd = Myjdapi()
jd.set_app_key("myapp")

jd.connect(email, password)

device = jd.get_device("JDownloader@makwana")

video_ext = [".mp4",".mkv",".avi",".mov",".wmv",
             ".flv",".webm",".mpeg",".mpg",".m4v",
             ".3gp",".ogv",".ts",".mts",".m2ts",
             ".vob",".rm",".rmvb",".divx",".f4v",".asf"
]

image_ext = [
    ".jpg",".jpeg",".png",".gif",".bmp",
    ".webp",".svg",".tiff",".tif",".ico",
    ".heic",".heif",".avif",".jfif",".pjpeg",
    ".pjp",".apng",".raw",".cr2",".nef",".orf",
    ".sr2",".dng",".eps",".ai",".indd"
]

DOWNLOAD_LINK_QUERY = [{
    "bytesLoaded": True,
    "bytesTotal": True,
    "eta": True,
    "finished": True,
    "maxResults": -1,
    "name": True,
    "packageUUIDs": [],
    "running": True,
    "speed": True,
    "startAt": 0,
    "status": True,
    "url": True,
}]


def _extract_youtube_id(url):
    if not url:
        return None

    match = re.search(r"youtubev2://([^/]+)", url)
    if match:
        return match.group(1)

    match = re.search(r"(?:v=|youtu\.be/|shorts/)([A-Za-z0-9_-]{11})", url)
    if match:
        return match.group(1)

    return None


def _thumbnail_url(video_id):
    return f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg" if video_id else None


def clear_old_links(device):
    links = device.linkgrabber.query_links()
    link_ids = [link["uuid"] for link in links]
    if link_ids:
        device.linkgrabber.remove_links(link_ids)


def jdownloader():
    query = get_input("Enter url : ", fetch_fn=scrap_result, download_fn=download_fn)


def scrap_result(query):
    clear_old_links(device)
    device.linkgrabber.add_links(
        [{
            "links": query,
            "destinationFolder": DOWNLOAD_PATH,
            "overwritePackagizerRules": True,
        }]
    )
    time.sleep(5)

    packages = device.linkgrabber.query_packages()
    if packages:
        for package in packages:
            package_id = package["uuid"]
            package_name = package.get("name") or "Axon"
            device.linkgrabber.move_to_new_package(
                [],
                [package_id],
                package_name,
                DOWNLOAD_PATH,
            )

    links = device.linkgrabber.query_links()

    with open("links.json", "w") as f:
        json.dump(links, f, indent=4)

    thumbnail_map = {}
    for link in links:
        name = link.get("name", "").lower()
        video_id = _extract_youtube_id(link.get("url", ""))
        if video_id and any(name.endswith(ext) for ext in image_ext):
            thumbnail_map[video_id] = _thumbnail_url(video_id)

    result = []
    for link in links:
        name = link.get("name", "").lower()
        if any(name.endswith(ext) for ext in video_ext):
            youtube_id = _extract_youtube_id(link.get("url", ""))
            thumbnail = thumbnail_map.get(youtube_id) or _thumbnail_url(youtube_id)
            result.append({
                "title": link["name"],
                "video_id": link["uuid"],
                "thumbnail": thumbnail,
                "youtube_id": youtube_id,
                "package_id": link.get("packageUUID"),
            })

    with open('result.json', 'w') as f:
        json.dump(result, f, indent=4)

    return result


def download_fn(item, progress_hook=None):
    video_id = item.get("video_id") if isinstance(item, dict) else item
    if not video_id:
        raise ValueError("No JDownloader link id found for the selected video")

    # Move selected link to download list
    device.linkgrabber.move_to_downloadlist(
        link_ids=[video_id],
        package_ids=[]
    )

    device.downloadcontroller.start_downloads()

    # FIX 2: JDownloader reassigns UUIDs after move — match by filename instead
    # First, get the filename from the result we stored
    filename_to_find = None
    try:
        with open("result.json") as f:
            results = json.load(f)
        for r in results:
            if r["video_id"] == video_id:
                filename_to_find = r["title"].lower()
                break
    except Exception:
        pass

    max_wait = 60  # seconds before giving up
    waited = 0

    while True:
        downloads = device.downloads.query_links(DOWNLOAD_LINK_QUERY)

        if not downloads:
            time.sleep(1)
            waited += 1
            if waited > max_wait:
                if progress_hook:
                    progress_hook({"status": "error", "filename": "Unknown"})
                return
            continue

        matched = None
        for dl in downloads:
            dl_name = dl.get("name", "").lower()
            # Match by uuid first, fallback to filename
            if dl.get("uuid") == video_id or (filename_to_find and dl_name == filename_to_find):
                matched = dl
                break

        if not matched:
            time.sleep(1)
            waited += 1
            if waited > max_wait:
                if progress_hook:
                    progress_hook({"status": "error", "filename": "Unknown"})
                return
            continue

        # Reset wait counter once found
        waited = 0

        downloaded = matched.get("bytesLoaded", 0)
        total = matched.get("bytesTotal", 0)
        speed = matched.get("speed", 0)
        eta = matched.get("eta", -1)
        filename = matched.get("name", "Unknown")

        percent = round((downloaded / total) * 100, 2) if total > 0 else 0

        if progress_hook:
            progress_hook({
                "status": "downloading",
                "_percent_str": f"{percent}%",
                "_speed_str": f"{round(speed / (1024 * 1024), 2)} MB/s",
                "_eta_str": f"{eta}s",
                "filename": filename
            })

        if matched.get("finished") or (downloaded >= total and total > 0):
            if progress_hook:
                progress_hook({"status": "finished", "filename": filename})
            return

        time.sleep(1)
