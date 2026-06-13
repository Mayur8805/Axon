from core.menu import is_back, select_option
from audio.youtube import youtube_audio_scraper
from audio.youtube_music import youtube_music_scraper

def audio_menu():
    selected = select_option(["YouTube","YouTube Music", "Spotify (Coming Soon)"], True)

    if is_back(selected):
        return

    if selected == 0:
        youtube_audio_scraper()

    if selected == 1:
        youtube_music_scraper()
        
