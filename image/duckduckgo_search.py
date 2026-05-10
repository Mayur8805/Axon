from core.menu import get_input
from ddgs import DDGS
import os
import requests

DOWNLOAD_PATH = "./Downloads/Images"

os.makedirs(DOWNLOAD_PATH, exist_ok=True)

def duckduckgo_search_scraper():
    query = get_input("Enter a search query", fetch_fn=scrape_results, download_fn=download_image)


def download_image(item: dict, progress_hook=None):

    image_url = item["thumbnail"]
    title = item["title"]

    safe_title = "".join(
        c for c in title if c.isalnum() or c in " _-"
    ).strip()

    out_path = os.path.join(
        DOWNLOAD_PATH,
        f"{safe_title}.jpg"
    )

    if progress_hook:
        progress_hook({
            "status": "downloading",
            "_percent_str": "Starting",
            "filename": out_path,
        })

    temp_path = out_path + ".part"

    try:

        with requests.get(
            image_url,
            stream=True,
            timeout=120
        ) as resp:

            resp.raise_for_status()

            total = int(resp.headers.get("content-length", 0))

            downloaded = 0
            last_percent = -1

            with open(temp_path, "wb") as f:

                for chunk in resp.iter_content(chunk_size=8192):

                    if not chunk:
                        continue

                    f.write(chunk)

                    downloaded += len(chunk)

                    if progress_hook and total:

                        percent = int(downloaded * 100 / total)

                        if percent != last_percent:

                            last_percent = percent

                            progress_hook({
                                "status": "downloading",
                                "_percent_str": f"{percent}%",
                                "filename": out_path,
                            })

    except Exception:

        if os.path.exists(temp_path):
            os.remove(temp_path)

        raise

    os.replace(temp_path, out_path)

    if progress_hook:
        progress_hook({
            "status": "finished",
            "filename": out_path,
        })

    print(f"Saved: {out_path}")

def scrape_results(query: str):
    images = []
    with DDGS() as ddgs:
        try : 
            results = ddgs.images(
                query,
                region="wt-wt",
                safesearch="off",
                max_results=30
            )
        except:
            return []

        for img in results:

            title = img.get("title")
            image = img.get("image")

            images.append({
                "title": title,
                "thumbnail": image
            })

    return images