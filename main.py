from core.menu import is_back, select_option
from audio.audio_menu import audio_menu
from video.video_menu import video_menu
from image.image_menu import image_menu
from pdf.pdf_menu import pdf_menu

while True:
    selected = select_option(["Audio", "Video", "Images", "Instagram", "PDF"], True)

    if is_back(selected):
        break

    if selected == 0:
        audio_menu()

    elif selected == 1:
        video_menu()

    elif selected == 2:
        image_menu()

    elif selected == 3:
        from image.instagram import instagram_scraper
        instagram_scraper()

    elif selected == 4:
        pdf_menu()
