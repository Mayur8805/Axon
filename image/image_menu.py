from core.menu import select_option
from image.duckduckgo_search import duckduckgo_search_scraper

def image_menu():
    selected = select_option(["DuckDuckGo"], True)

    if selected == 0:
        duckduckgo_search_scraper()