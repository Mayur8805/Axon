from core.menu import is_back, select_option
from pdf.pdfdrive import pdfdrive_scraper

def pdf_menu():
    selected = select_option(["pdfdrive"], False)

    if is_back(selected):
        return

    if selected == 0:
        pdfdrive_scraper()
