from core.menu import select_option
from pdf.pdfdrive import pdfdrive_scraper

def pdf_menu():
    selected = select_option(["pdfdrive"], False)

    if selected == 0:
        pdfdrive_scraper()