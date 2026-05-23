from core.menu import select_option

def image_menu():
    selected = select_option(["DuckDuckGo", "GoogleImages", "Alphacoders", "4kwallpapers"], True)

    if selected == 0:
        from image.duckduckgo_search import duckduckgo_search_scraper
        duckduckgo_search_scraper()
    elif selected == 1:
        from image.google_image import google_image_scraper
        google_image_scraper()

    elif selected == 2:
        from image.alphacoders import alphacoders_scraper
        alphacoders_scraper()

    elif selected == 3:
        from image._4kwallpapers import _4kwallpapers_scraper
        _4kwallpapers_scraper()