from core.menu import select_option
from audio.youtube import youtube_audio_scraper
from audio.youtube_music import youtube_music_scraper

def audio_menu():
    selected = select_option(["YouTube","YouTube Music", "Spotify (Coming Soon)"], True)

    if selected == 0:
        youtube_audio_scraper()

    if selected == 1:
        youtube_music_scraper()