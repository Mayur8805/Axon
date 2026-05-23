from core.menu import get_input
import requests
import time
from bs4 import BeautifulSoup
from urllib.parse import  urljoin

BASE_URL = "https://4kwallpapers.com/"
SEARCH_URL = "https://4kwallpapers.com/search/?q="
SESSION = requests.Session()
SESSION.headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
}
DOWNLOAD_PATH = "./Downloads/Images/"

def _4kwallpapers_scraper():
    query = get_input("Enter name",fetch_fn=Scrap_results, download_fn=Download_image)


def get_soup(url):
    response = SESSION.get(url)
    return BeautifulSoup(response.content, "html.parser")

def _url_generate(query):
    query = query.strip().replace(" ", "-").lower()
    return SEARCH_URL + query

def Scrap_results(query):

    url = _url_generate(query)
    print(url)
    data = []
    soup = get_soup(url)

    a_tag = soup.find_all("a", class_="wallpapers__canvas_image")
    for a in a_tag:
        page_url = a["href"]
        img = a.find("img", {"itemprop": "thumbnail"})
        thumbnail = img["src"]

        page_soup = get_soup(page_url)
        title = page_soup.find("span", class_="selected").get_text(strip=True)
        links = page_soup.find("span", class_="res-ttl").find_all("a")

        if len(links) > 1:
            download_url = urljoin(BASE_URL,links[1]["href"])   # Original
        elif len(links) == 1:
            download_url = urljoin(BASE_URL, links[0]["href"])  # Fallback
        else:
            download_url = None

        data.append({
            "title" : title,
            "thumbnail" : thumbnail,
            "download_url" : download_url
        })

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