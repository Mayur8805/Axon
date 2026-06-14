from core.menu import is_back, select_option

while True:
    selected = select_option(["Audio", "Video", "Anime", "Images", "PDF", "Instagram"], True)

    if is_back(selected):
        break

    if selected == 0:
        from audio.audio_menu import audio_menu
        audio_menu()

    elif selected == 1:
        from video.video_menu import video_menu
        video_menu()

    elif selected == 2:
        from video.ani_cli import ani_cli_scraper
        ani_cli_scraper()
        
    elif selected == 3:
        from image.image_menu import image_menu
        image_menu()

    elif selected == 4:
        from pdf.pdf_menu import pdf_menu
        pdf_menu()

    elif selected == 5:
        from image.instagram import instagram_scraper
        instagram_scraper()
