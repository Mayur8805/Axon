from core.menu import select_option
from audio.audio_menu import audio_menu
from video.video_menu import video_menu
from image.image_menu import image_menu
from pdf.pdf_menu import pdf_menu

selected = select_option(["Audio", "Video", "Images", "PDF"], True)

if selected == 0:
    audio_menu()

elif selected == 1:
    video_menu()

elif selected == 2:
    image_menu()

elif selected == 3:
    pdf_menu()