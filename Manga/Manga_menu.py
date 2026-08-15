from core.menu import is_back, select_option
from Manga.comix import comix_scraper


def manga_menu():
    selected = select_option(["comix.to"], False)

    if is_back(selected):
        return

    if selected == 0:
        comix_scraper()
