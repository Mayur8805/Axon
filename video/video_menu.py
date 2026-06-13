from core.menu import is_back, select_option
from video.youtube import youtube_scraper

def video_menu():
    selected = select_option(["YouTube","JDownloader (any website)"], True)

    if is_back(selected):
        return

    if selected == 0:
        youtube_scraper()
    elif selected == 1:
        print("Loading...")
        from video.Jdownloader import jdownloader
        jdownloader()
