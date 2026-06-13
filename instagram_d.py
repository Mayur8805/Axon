# import instaloader
username = "test.bot88"
name = "meam_watcher_"
password = "Test@Bot88"
# Create downloader
# L = instaloader.Instaloader()

# L.login("test.bot88", "Test@Bot88")
# Instagram post URL
url = "https://www.instagram.com/p/DYVRquqkxf3/?igsh=MTh5eGlpMHZlMzVjNg=="
shortcode = "DYVRquqkxf3"
# # Extract shortcode from URL
# shortcode = url.split("/p/")[1].split("/")[0]

# # Get and download post
# post = instaloader.Post.from_shortcode(L.context, shortcode)
# L.download_post(post, target="instagram_downloads")

# print("Download completed!")
# import instaloader

# L = instaloader.Instaloader()

# # Login first
# L.login(username, password)

# # Save session so you don't have to login every time
# L.save_session_to_file()

# # Download profile
# L.download_profile("meam_watcher_", profile_pic_only=False)

# import yt_dlp

# # url = "https://www.instagram.com/p/YOUR_POST_SHORTCODE/"

# ydl_opts = {
#     'outtmpl': 'downloads/%(uploader)s_%(id)s.%(ext)s',
#     'cookiesfrombrowser': ('firefox',),  # or ('chrome',)
# }

# with yt_dlp.YoutubeDL(ydl_opts) as ydl:
#     ydl.download([url])

#48029518853

# import asyncio
# import os
# import re
# import requests
# from playwright.async_api import async_playwright

# # ─── CONFIG ─────────────────────────────────
# IG_USERNAME  = username
# IG_PASSWORD  = password
# TARGET       = "meam_watcher_"          # account to scrape
# SAVE_FOLDER  = f"downloads/{TARGET}"
# MAX_SCROLLS  = 50                        # increase for more posts
# # ────────────────────────────────────────────

# os.makedirs(SAVE_FOLDER, exist_ok=True)

# def download_file(url, filepath):
#     headers = {"User-Agent": "Mozilla/5.0"}
#     r = requests.get(url, headers=headers, timeout=30)
#     if r.status_code == 200:
#         with open(filepath, "wb") as f:
#             f.write(r.content)
#         return True
#     return False


# async def scrape_instagram():
#     async with async_playwright() as p:
#         browser = await p.chromium.launch(headless=False)  # headless=False so you can see it
#         context = await browser.new_context()
#         page    = await context.new_page()

#         # ── Step 1: Login ───────────────────────────────
#         print("🔐 Logging in...")
#         await page.goto("https://www.instagram.com/accounts/login/", wait_until="networkidle")
#         await page.wait_for_timeout(2000)
        
#         await page.fill("input[name='username']", IG_USERNAME)
#         await page.fill("input[name='password']", IG_PASSWORD)
#         await page.click("button[type='submit']")
#         await page.wait_for_timeout(5000)

#         # Dismiss "Save login info?" and "Turn on notifications?" popups
#         for _ in range(3):
#             try:
#                 btn = page.locator("text=Not Now").first
#                 await btn.click(timeout=3000)
#                 await page.wait_for_timeout(1000)
#             except:
#                 pass

#         print("✅ Logged in!")

#         # ── Step 2: Go to target profile ────────────────
#         print(f"📷 Going to @{TARGET} ...")
#         await page.goto(f"https://www.instagram.com/{TARGET}/", wait_until="networkidle")
#         await page.wait_for_timeout(3000)

#         # ── Step 3: Collect all post links by scrolling ─
#         print("🔍 Collecting post links...")
#         post_links = set()

#         for i in range(MAX_SCROLLS):
#             # Find all post links on page
#             links = await page.eval_on_selector_all(
#                 "a[href*='/p/']",
#                 "els => els.map(e => e.href)"
#             )
#             for link in links:
#                 if "/p/" in link:
#                     post_links.add(link.split("?")[0])

#             prev_count = len(post_links)
#             await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
#             await page.wait_for_timeout(2000)

#             if i % 5 == 0:
#                 print(f"  Scroll {i+1}/{MAX_SCROLLS} — Found {len(post_links)} posts so far...")

#         print(f"\n✅ Found {len(post_links)} total posts. Starting download...\n")

#         # ── Step 4: Visit each post and download images ─
#         downloaded = 0
#         for idx, post_url in enumerate(post_links):
#             try:
#                 await page.goto(post_url, wait_until="networkidle")
#                 await page.wait_for_timeout(2000)

#                 # Grab all high-res images in the post
#                 img_urls = await page.eval_on_selector_all(
#                     "img[src*='cdninstagram'], img[src*='fbcdn']",
#                     """els => els
#                         .map(e => e.src)
#                         .filter(src => src.includes('1080x') || src.includes('_n.jpg') || src.includes('e35'))
#                     """
#                 )

#                 # Fallback: grab all large images
#                 if not img_urls:
#                     img_urls = await page.eval_on_selector_all(
#                         "img[src*='cdninstagram'], img[src*='fbcdn']",
#                         "els => els.map(e => e.src)"
#                     )

#                 # Remove duplicates and tiny icons
#                 img_urls = list(set([
#                     u for u in img_urls
#                     if "150x150" not in u and "s150x150" not in u
#                 ]))

#                 shortcode = post_url.rstrip("/").split("/")[-1]

#                 for j, img_url in enumerate(img_urls):
#                     ext      = "jpg"
#                     filename = f"{shortcode}_{j+1}.{ext}"
#                     filepath = os.path.join(SAVE_FOLDER, filename)

#                     if os.path.exists(filepath):
#                         continue

#                     if download_file(img_url, filepath):
#                         downloaded += 1
#                         print(f"  [{idx+1}/{len(post_links)}] ✅ Saved: {filename}")
#                     else:
#                         print(f"  [{idx+1}/{len(post_links)}] ⚠️  Failed: {filename}")

#                 await page.wait_for_timeout(1500)

#             except Exception as e:
#                 print(f"  ❌ Error on {post_url}: {e}")
#                 continue

#         await browser.close()
#         print(f"\n🎉 Done! Downloaded {downloaded} images to '{SAVE_FOLDER}/'")


# asyncio.run(scrape_instagram())

from playwright.sync_api import sync_playwright
import time
import json

# account = "meam_watcher_"
# account = "chen_bb01"
# account = "legacyin.focus"

# with sync_playwright() as p:
#     browser = p.chromium.launch(headless=False)
#     page = browser.new_page()
#     page.goto("https://inviziogram.com/", wait_until="domcontentloaded")

#     page.wait_for_selector('[data-testid="search-input"]', timeout=60000)
#     time.sleep(3)
#     page.fill('[data-testid="search-input"]', account)
#     page.press('[data-testid="search-input"]', "Enter")
#     time.sleep(3)
#     page.wait_for_selector('.animate-slide-up', timeout=60000)

#     page.wait_for_selector('span.text-lg.md\\:text-xl.font-bold.text-foreground.tracking-tight', timeout=60000)
#     span = page.query_selector('span.text-lg.md\\:text-xl.font-bold.text-foreground.tracking-tight')

#     value = span.text_content().strip()
#     print(f"Span value: {value}")

#     try:
#         if int(value) > 0:
#             print(f"Value is {value}, clicking Posts tab...")
#             page.click('[data-testid="tab-Posts"]')

#             page.wait_for_selector('[data-testid="posts-grid"]', timeout=60000)
#             time.sleep(3)

#             images = page.query_selector_all('[data-testid="posts-grid"] img')

#             # Build list of posts
#             posts = []
#             for i, img in enumerate(images, 1):
#                 src = img.get_attribute("src") or img.get_attribute("data-src")
#                 if src:
#                     posts.append({
#                         "title": f"post{i}",
#                         "thumbnail": src
#                     })

#             # Save to JSON
#             with open(f"{account}_images.json", "w") as f:
#                 json.dump(posts, f, indent=4)

#             print(f"\nSaved {len(posts)} posts to '{account}_images.json'")
#             for post in posts:
#                 print(f"{post['title']}: {post['thumbnail']}")

#         else:
#             print("Value is 0, stopping.")
#             browser.close()

#     except ValueError:
#         print(f"Could not parse value: '{value}', stopping.")
#         browser.close()

#     browser.close()


from playwright.sync_api import sync_playwright
import json
import time
import requests
import os

account = "@itsathenakami"
posts = []

with sync_playwright() as p:
    browser = p.chromium.launch(headless=False)
    page = browser.new_page()

    # Navigate and wait for full load
    page.goto("https://igram.world/en1/", wait_until="domcontentloaded")
    page.wait_for_load_state("networkidle")
    time.sleep(3)
    # Search
    page.wait_for_selector('[id="search-form-input"]', timeout=30000)
    page.fill('[id="search-form-input"]', account)
    page.click('button.search-form__button[type="submit"]')

    # Wait for the first post
    page.wait_for_selector('.media-content__info', timeout=60000)

    print("Loading all posts using incremental scrolling...")
    post_selector = '.media-content__info'
    previous_count = 0
    no_change_attempts = 0
    max_no_change = 3            # stop after 3 scrolls with no new posts
    scroll_step = "viewport"     # can be changed to a pixel value like 500

    while no_change_attempts < max_no_change:
        # Scroll by one viewport height (or a fixed pixel amount)
        if scroll_step == "viewport":
            page.evaluate("window.scrollBy(0, window.innerHeight)")
        else:
            page.evaluate(f"window.scrollBy(0, {scroll_step})")

        # Wait up to 5 seconds for new posts to appear
        try:
            page.wait_for_function(
                f"document.querySelectorAll('{post_selector}').length > {previous_count}",
                timeout=5000
            )
            no_change_attempts = 0  # reset counter on success
        except:
            no_change_attempts += 1
            print(f"Scroll produced no new posts ({no_change_attempts}/{max_no_change})")

        # Update count
        current_count = page.evaluate(f"document.querySelectorAll('{post_selector}').length")
        print(f"Posts loaded so far: {current_count}")
        previous_count = current_count

    # --- Extraction ---
    posts_divs = page.query_selector_all(post_selector)
    print(f"Total posts found: {len(posts_divs)}")

    for i, div in enumerate(posts_divs, 1):
        caption_el = div.query_selector('p.media-content__caption')
        caption = caption_el.text_content().strip() if caption_el else f"post{i}"

        download_el = div.query_selector('a.button__download')
        download_url = download_el.get_attribute("href") if download_el else None

        posts.append({
            "title": f"post{i}",
            "caption": caption,
            "thumbnail": download_url
        })

    filename = f"{account.replace('@', '')}_posts.json"
    with open(filename, "w", encoding="utf-8") as f:
        json.dump(posts, f, indent=4, ensure_ascii=False)

    print(f"Saved {len(posts)} posts to '{filename}'")
    input("Press Enter to close...")


def download_posts(posts, account):
    folder = account.replace('@', '') + "_images"
    os.makedirs(folder, exist_ok=True)

    headers = {
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"
    }

    print(f"\nDownloading thumbnails into '{folder}/'...")

    for post in posts:
        url = post["thumbnail"]
        title = post["title"]

        if not url:
            print(f"  [{title}] No URL, skipping.")
            continue

        try:
            response = requests.get(url, headers=headers, timeout=30)
            response.raise_for_status()

            content_type = response.headers.get("Content-Type", "")
            if "video" in content_type:
                ext = ".mp4"
            elif "png" in content_type:
                ext = ".png"
            elif "webp" in content_type:
                ext = ".webp"
            else:
                ext = ".jpg"

            filepath = os.path.join(folder, f"{title}{ext}")
            with open(filepath, "wb") as f:
                f.write(response.content)

            print(f"  ✅ {title}{ext} downloaded ({len(response.content) // 1024} KB)")

        except Exception as e:
            print(f"  ❌ {title} failed: {e}")

    print(f"\nDone! All files saved in '{folder}/'")

download_posts(posts, account)