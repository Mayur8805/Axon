from core.menu import select_option
from video.youtube import youtube_scraper

def video_menu():
    selected = select_option(["YouTube"], True)

    if selected == 0:
        youtube_scraper()