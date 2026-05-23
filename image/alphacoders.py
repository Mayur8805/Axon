from core.menu import get_input

import requests
import os
import time
import re
from bs4 import BeautifulSoup
from urllib.parse import quote_plus

BASE_URL = "https://alphacoders.com/"
SEARCH_URL = "https://alphacoders.com/search/view?q="
SESSION = requests.Session()
SESSION.headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
}
DOWNLOAD_PATH = "./Downloads/Images/"

def alphacoders_scraper():
    query = get_input("Enter name",fetch_fn=Scrap_results, download_fn=Download_image)


def get_soup(url):
    response = SESSION.get(url)
    return BeautifulSoup(response.content, "html.parser")

def _url_generate(query):
    return SEARCH_URL + quote_plus(query)

# def Scrap_results(query):
#     url = _url_generate(query)
#     data = []
#     soup = get_soup(url)

#     images_div = soup.find_all("div", class_="item")

#     for image in images_div:

#         item_div = image.find("div", class_="css-grid-content")

#         thumbnail = item_div.find("meta",{"itemprop": "thumbnailUrl"})["content"]

#         center_div = item_div.find("div", class_="center")
#         page_url = center_div.find("a")["href"]

#         image_page_soup = get_soup(page_url)
#         name = image_page_soup.find("h1",class_="center title").get_text(strip=True)

#         download_btn = image_page_soup.find("span",class_="button-download")
#         onclick = download_btn.get("onclick")

#         match = re.search(r"downloadContentModal\('(.+?)',\s*(\d+),\s*'(.+?)'",onclick)

#         server = match.group(1)
#         image_id = match.group(2)
#         ext = match.group(3)

#         download_url = (
#             f"https://initiate.alphacoders.com/"
#             f"download/{server}/{image_id}/{ext}"
#         )

#         data.append({
#             "title": name.replace(" ","_"),
#             "thumbnail": thumbnail,
#             "download_url": download_url
#         })
        
#     return data

import re
from concurrent.futures import ThreadPoolExecutor, as_completed

def _fetch_image_data(image, session=None):
    """Fetch data for a single image div."""
    item_div = image.find("div", class_="css-grid-content")
    thumbnail = item_div.find("meta", {"itemprop": "thumbnailUrl"})["content"]
    center_div = item_div.find("div", class_="center")
    page_url = center_div.find("a")["href"]

    image_page_soup = get_soup(page_url)  # ← the slow part, now runs in parallel
    name = image_page_soup.find("h1", class_="center title").get_text(strip=True)
    download_btn = image_page_soup.find("span", class_="button-download")
    onclick = download_btn.get("onclick")
    match = re.search(r"downloadContentModal\('(.+?)',\s*(\d+),\s*'(.+?)'", onclick)
    server = match.group(1)
    image_id = match.group(2)
    ext = match.group(3)

    return {
        "title": name.replace(" ", "_"),
        "thumbnail": thumbnail,
        "download_url": f"https://initiate.alphacoders.com/download/{server}/{image_id}/{ext}"
    }

def Scrap_results(query, max_workers=10):
    url = _url_generate(query)
    soup = get_soup(url)
    images_div = soup.find_all("div", class_="item")

    data = []
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(_fetch_image_data, image): image for image in images_div}
        for future in as_completed(futures):
            try:
                data.append(future.result())
            except Exception as e:
                print(f"Failed to fetch image data: {e}")

    return data

def Download_image(item, progress_hook=None):

    url = item.get("download_url")

    if not url:
        raise ValueError("No download URL found")

    filename = item.get("title", "image")

    headers = {
        "User-Agent": "Mozilla/5.0",
        "Referer": "https://alphacoders.com/"
    }

    response = requests.get(
        url,
        headers=headers,
        stream=True,
        allow_redirects=True
    )

    if response.status_code != 200:
        if progress_hook:
            progress_hook({
                "status": "error",
                "filename": filename
            })
        return

    # Get real extension
    content_type = response.headers.get("Content-Type", "")

    if "jpeg" in content_type:
        ext = "jpg"
    elif "png" in content_type:
        ext = "png"
    elif "webp" in content_type:
        ext = "webp"
    else:
        ext = "jpg"

    filepath = f"{DOWNLOAD_PATH}{filename}.{ext}"

    total = int(response.headers.get("content-length", 0))
    downloaded = 0

    start_time = time.time()

    with open(filepath, "wb") as f:

        for chunk in response.iter_content(chunk_size=8192):

            if not chunk:
                continue

            f.write(chunk)

            downloaded += len(chunk)

            elapsed = time.time() - start_time

            speed = downloaded / elapsed if elapsed > 0 else 0

            percent = (
                round((downloaded / total) * 100, 2)
                if total > 0 else 0
            )

            eta = (
                round((total - downloaded) / speed)
                if speed > 0 and total > 0 else -1
            )

            if progress_hook:
                progress_hook({
                    "status": "downloading",
                    "_percent_str": f"{percent}%",
                    "_speed_str": f"{round(speed / (1024*1024), 2)} MB/s",
                    "_eta_str": f"{eta}s",
                    "filename": filepath
                })

    if progress_hook:
        progress_hook({
            "status": "finished",
            "filename": filepath
        })

    return filepath