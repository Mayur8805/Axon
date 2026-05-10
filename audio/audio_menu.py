from core.menu import select_option
from audio.youtube import youtube_audio_scraper

def audio_menu():
    selected = select_option(["YouTube", "Spotify (Coming Soon)"], True)

    if selected == 0:
        youtube_audio_scraper()