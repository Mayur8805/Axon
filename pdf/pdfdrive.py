import os
import re
import time
import requests
from bs4 import BeautifulSoup
from core.menu import get_input
from urllib.parse import quote_plus, unquote, urljoin, urlparse

PDF_DRIVE_BASE   = "https://pdfdrive.com.co/"
PDF_DRIVE_SEARCH = "https://pdfdrive.com.co/?s="
DOWNLOAD_PATH    = "./Downloads/PDF"
os.makedirs(DOWNLOAD_PATH, exist_ok=True)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}
session = requests.Session()
session.headers.update(HEADERS)


def _get(url: str, **kwargs) -> requests.Response:
    timeout = kwargs.pop("timeout", 60)
    last_error: Exception | None = None

    for attempt in range(3):
        try:
            response = session.get(url, timeout=timeout, **kwargs)
            response.raise_for_status()
            return response
        except requests.RequestException as exc:
            last_error = exc
            if attempt < 2:
                time.sleep(1 + attempt)

    raise RuntimeError(f"Could not fetch {url}: {last_error}")


def _safe_filename(title: str) -> str:
    safe_title = "".join(c for c in title if c.isalnum() or c in " _-").strip()
    return safe_title or "download"


def _is_pdf_url(url: str) -> bool:
    parsed = urlparse(url)
    return unquote(parsed.path).lower().endswith(".pdf")


def _find_pdf_url(soup: BeautifulSoup, base_url: str) -> str | None:
    candidates: list[str] = []

    for tag in soup.find_all(["a", "iframe", "embed", "source"]):
        href = tag.get("href") or tag.get("src")
        if not href:
            continue
        absolute_url = urljoin(base_url, href)
        if _is_pdf_url(absolute_url):
            candidates.append(absolute_url)

    for match in re.findall(r"""["']([^"']+?\.pdf(?:\?[^"']*)?)["']""", str(soup), re.I):
        absolute_url = urljoin(base_url, match)
        if _is_pdf_url(absolute_url):
            candidates.append(absolute_url)

    if not candidates:
        return None

    same_site = [
        url for url in candidates
        if urlparse(url).netloc == urlparse(PDF_DRIVE_BASE).netloc
    ]
    return (same_site or candidates)[0]


def _find_download_page_url(soup: BeautifulSoup, base_url: str) -> str | None:
    for a in soup.find_all("a", href=True):
        href = a["href"]
        text = a.get_text(" ", strip=True).lower()
        if "download=links" in href or text == "download":
            absolute_url = urljoin(base_url, href)
            if urlparse(absolute_url).netloc == urlparse(PDF_DRIVE_BASE).netloc:
                return absolute_url
    return None


def _resolve_pdf_url(page_url: str) -> str:
    visited: set[str] = set()
    current_url = page_url

    for _ in range(4):
        if current_url in visited:
            break
        visited.add(current_url)

        r = _get(current_url)
        soup = BeautifulSoup(r.text, "html.parser")

        pdf_url = _find_pdf_url(soup, r.url)
        if pdf_url:
            return pdf_url

        download_page_url = _find_download_page_url(soup, r.url)
        if not download_page_url:
            break
        current_url = download_page_url

    raise RuntimeError("No direct PDF link found on the page.")


def pdfdrive_scraper():
    result = get_input("Enter book name", fetch_fn=scrape_results, download_fn=download_pdf)
    # if not result:
    #     return

    # _, item = result  # (selected_index, item_dict)
    # download_pdf(item)


def download_pdf(item: dict, progress_hook=None)-> None:
    page_url = urljoin(PDF_DRIVE_BASE, item["url"])
    title    = item["title"]
    safe_title = _safe_filename(title)
    out_path = os.path.join(DOWNLOAD_PATH, f"{safe_title}.pdf")

    if progress_hook:
        progress_hook({
            "status": "downloading",
            "_percent_str": "Resolving",
            "_speed_str": "",
            "_eta_str": "",
            "filename": out_path,
        })
    pdf_url = _resolve_pdf_url(page_url)

    print(f"Downloading: {pdf_url}")
    temp_path = f"{out_path}.part"
    try:
        with _get(
            pdf_url,
            stream=True,
            timeout=120,
            headers={"Referer": page_url},
        ) as resp:
            total = int(resp.headers.get("content-length") or 0)
            downloaded = 0
            last_percent = -1
            first_chunk = True
            with open(temp_path, "wb") as f:
                for chunk in resp.iter_content(chunk_size=8192):
                    if not chunk:
                        continue
                    if first_chunk:
                        first_chunk = False
                        if not chunk.lstrip().startswith(b"%PDF"):
                            raise RuntimeError("Download response is not a PDF file.")
                    f.write(chunk)
                    downloaded += len(chunk)
                    if progress_hook and total:
                        percent = int(downloaded * 100 / total)
                        if percent == last_percent:
                            continue
                        last_percent = percent
                        progress_hook({
                            "status": "downloading",
                            "_percent_str": f"{downloaded / total:.1%}",
                            "_speed_str": "",
                            "_eta_str": "",
                            "filename": out_path,
                        })
    except Exception:
        if os.path.exists(temp_path):
            os.unlink(temp_path)
        raise

    os.replace(temp_path, out_path)

    if progress_hook:
        progress_hook({"status": "finished", "filename": out_path})

    print(f"Saved to: {out_path}")

def scrape_results(query: str):
    url = PDF_DRIVE_SEARCH + quote_plus(query.strip())
    print(url)
    r = _get(url)
    soup = BeautifulSoup(r.text, "html.parser")

    pdfs = []
    for div in soup.find_all("div", class_="bav bav1"):
        a = div.find("a")
        if not a:
            continue

        title     = a.get("title", "")
        href      = urljoin(PDF_DRIVE_BASE, a.get("href", ""))
        img       = a.find("img")
        thumbnail = img.get("src", "") if img else ""
        stars     = a.find("span", class_="stars")
        rating    = (
            stars.get("style", "")
                 .replace("width:", "")
                 .replace("%", "")
                 .strip()
            if stars else ""
        )

        pdfs.append({
            "title":     title,
            "url":       href,
            "thumbnail": thumbnail,
            "rating":    rating,
        })

    return pdfs
