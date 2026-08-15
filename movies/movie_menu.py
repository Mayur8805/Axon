from core.menu import is_back, select_option
from movies.telegram_movies import telegram_movie_sender


def movie_menu():
    selected = select_option(["Telegram Bot"], True)

    if is_back(selected):
        return

    if selected == 0:
        telegram_movie_sender()
