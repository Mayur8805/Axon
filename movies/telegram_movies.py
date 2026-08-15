from __future__ import annotations

import asyncio
import shutil
import sqlite3
import tempfile
from pathlib import Path

from telethon import TelegramClient
from telethon.errors import ChatForwardsRestrictedError

from core.menu import get_input, load_config, save_config


SETTINGS_KEY = "movies"
DEFAULT_SOURCE_BOT = "@SearchMoviesBot"
SESSION_PATH = Path(__file__).resolve().parent / "session"
DEBUG_LOG = Path(__file__).resolve().parent / "telegram_movies_debug.log"


def _debug(message: str) -> None:
    with DEBUG_LOG.open("a", encoding="utf-8") as log:
        log.write(message + "\n")


def telegram_movie_sender() -> None:
    get_input(
        msg="Movie or series name",
        fetch_fn=search_movies,
        download_fn=send_selected_movie,
        setting_fn=settings_fn,
    )


def settings_fn(action, settings=None):
    config = load_config()
    movie_config = config.setdefault(SETTINGS_KEY, {})
    movie_config.setdefault("source_bot", DEFAULT_SOURCE_BOT)
    movie_config.setdefault("receiver_username", "")
    movie_config.setdefault("api_id", "")
    movie_config.setdefault("api_hash", "")

    if action == "load":
        return {
            "type": "toggles",
            "title": "Settings",
            "label": "Telegram",
            "options": ["configure"],
            "values": {"configure": True},
            "text_values": {
                "receiver_username": movie_config.get("receiver_username", ""),
                "api_id": str(movie_config.get("api_id", "")),
                "api_hash": movie_config.get("api_hash", ""),
                "source_bot": movie_config.get("source_bot", DEFAULT_SOURCE_BOT),
            },
            "text_fields": [
                {
                    "key": "receiver_username",
                    "label": "receiver username",
                    "placeholder": "@username",
                    "when": "configure",
                },
                {
                    "key": "api_id",
                    "label": "api id",
                    "placeholder": "123456",
                    "when": "configure",
                },
                {
                    "key": "api_hash",
                    "label": "api hash",
                    "placeholder": "telegram api hash",
                    "when": "configure",
                },
                {
                    "key": "source_bot",
                    "label": "source bot",
                    "placeholder": DEFAULT_SOURCE_BOT,
                    "when": "configure",
                },
            ],
        }

    if action == "save" and settings:
        text_values = settings.get("text_values", {})
        movie_config["receiver_username"] = text_values.get("receiver_username", "").strip()
        movie_config["api_id"] = text_values.get("api_id", "").strip()
        movie_config["api_hash"] = text_values.get("api_hash", "").strip()
        movie_config["source_bot"] = text_values.get("source_bot", DEFAULT_SOURCE_BOT).strip() or DEFAULT_SOURCE_BOT
        save_config(config)


def _movie_config() -> dict:
    config = load_config().get(SETTINGS_KEY, {})
    return {
        "source_bot": config.get("source_bot") or DEFAULT_SOURCE_BOT,
        "receiver_username": config.get("receiver_username", ""),
        "api_id": config.get("api_id", ""),
        "api_hash": config.get("api_hash", ""),
    }


def _client_from_config() -> TelegramClient:
    config = _movie_config()
    api_id = str(config.get("api_id", "")).strip()
    api_hash = str(config.get("api_hash", "")).strip()

    if not api_id or not api_hash:
        raise RuntimeError("Add Telegram api id and api hash in Movie settings.")

    try:
        parsed_api_id = int(api_id)
    except ValueError as exc:
        raise RuntimeError("Telegram api id must be a number.") from exc

    _ensure_compatible_session()
    return TelegramClient(str(SESSION_PATH), parsed_api_id, api_hash)


def _ensure_compatible_session() -> None:
    session_file = SESSION_PATH.with_suffix(".session")
    if not session_file.exists():
        return

    try:
        with sqlite3.connect(session_file) as connection:
            columns = [
                row[1]
                for row in connection.execute("pragma table_info(sessions)").fetchall()
            ]

            if columns == ["dc_id", "server_address", "port", "auth_key", "takeout_id"]:
                return

            extra_columns = [column for column in columns if column not in {
                "dc_id", "server_address", "port", "auth_key", "takeout_id",
            }]
            if extra_columns != ["tmp_auth_key"]:
                raise RuntimeError(
                    "Telegram session file has an unsupported schema. Create a fresh movies/session.session."
                )

            backup = session_file.with_suffix(".session.bak")
            if not backup.exists():
                shutil.copy2(session_file, backup)

            connection.execute("alter table sessions drop column tmp_auth_key")
            connection.commit()
            _debug("[session] removed incompatible tmp_auth_key column; backup saved as session.session.bak")
    except sqlite3.DatabaseError as exc:
        raise RuntimeError("Telegram session file is not readable. Create a fresh movies/session.session.") from exc


async def _show_buttons(message) -> list[dict]:
    if not message.buttons:
        return []

    items = []
    index = 1
    for row in message.buttons:
        for button in row:
            text = button.text or f"Option {index}"
            items.append({
                "title": text,
                "duration": "option",
                "thumbnail": "",
                "button_text": text,
                "message_id": message.id,
                "source_bot": _movie_config()["source_bot"],
                "is_more_results": "more result" in text.lower(),
            })
            index += 1
    return items


async def _search_movies_async(query: str) -> list[dict]:
    config = _movie_config()
    source_bot = config["source_bot"]
    items: list[dict] = []
    DEBUG_LOG.write_text(f"[search] bot={source_bot} query={query!r}\n", encoding="utf-8")

    client = _client_from_config()
    async with client:
        if not await client.is_user_authorized():
            raise RuntimeError(
                "Telegram session is not logged in. Run this movie option once in a terminal and complete login."
            )

        async with client.conversation(source_bot, timeout=300) as conv:
            await conv.send_message(query)

            while True:
                response = await conv.get_response()
                _debug(
                    f"[response] id={response.id} media={bool(response.media)} "
                    + f"buttons={bool(response.buttons)} text={response.text!r}"
                )

                if response.media:
                    title = response.text or f"Media message {response.id}"
                    return [{
                        "title": title,
                        "duration": "media",
                        "thumbnail": "",
                        "message_id": response.id,
                        "source_bot": source_bot,
                        "is_media": True,
                    }]

                buttons = await _show_buttons(response)
                if buttons:
                    for button in buttons:
                        button["query"] = query
                        button["button_path"] = [button["button_text"]]
                    return buttons

                if response.text:
                    title = response.text.strip()
                    if not buttons and "too many argument" in title.lower():
                        title = (
                            "Bot replied: "
                            + title
                            + "  This came from Telegram bot, not Axon splitting your search."
                        )
                    items.append({
                        "title": title,
                        "duration": "message",
                        "thumbnail": "",
                        "message_id": response.id,
                        "source_bot": source_bot,
                    })

                if items:
                    return items


def search_movies(query: str) -> list[dict]:
    return asyncio.run(_search_movies_async(query))


async def _send_selected_movie_async(item: dict, progress_hook=None) -> None:
    config = _movie_config()
    receiver = config.get("receiver_username", "").strip()
    if not receiver:
        raise RuntimeError("Add receiver username in Movie settings.")

    source_bot = item.get("source_bot") or config["source_bot"]
    message_id = item.get("message_id")
    if not message_id:
        raise RuntimeError("This result cannot be sent because it has no Telegram message id.")

    _debug(
        f"[send] receiver={receiver!r} source_bot={source_bot!r} "
        + f"message_id={message_id!r} title={item.get('title', '')!r}"
    )

    client = _client_from_config()
    async with client:
        if not await client.is_user_authorized():
            raise RuntimeError(
                "Telegram session is not logged in. Run this movie option once in a terminal and complete login."
            )

        if progress_hook:
            progress_hook({
                "status": "downloading",
                "_percent_str": "",
                "_speed_str": "Telegram",
                "_eta_str": "",
                "filename": "Requesting selected movie...",
                "display_full_path": True,
            })

        media_message = None

        if item.get("is_media"):
            media_message = await client.get_messages(source_bot, ids=int(message_id))
        else:
            query = item.get("query")
            button_path = item.get("button_path") or [item.get("button_text")]
            if not query or not button_path or not button_path[0]:
                raise RuntimeError("This result is missing its Telegram selection path. Search again and select it.")

            async with client.conversation(source_bot, timeout=300) as conv:
                await conv.send_message(query)
                response = await conv.get_response()
                _debug(
                    f"[send-replay] query response id={response.id} media={bool(response.media)} "
                    + f"buttons={bool(response.buttons)} text={response.text!r}"
                )

                for button_text in button_path:
                    await response.click(text=button_text)
                    _debug(f"[send-replay] clicked button={button_text!r}")
                    response = await conv.get_response()
                    _debug(
                        f"[send-replay] response id={response.id} media={bool(response.media)} "
                        + f"buttons={bool(response.buttons)} text={response.text!r}"
                    )

                if response.media:
                    media_message = response
                else:
                    buttons = await _show_buttons(response)
                    if buttons:
                        for button in buttons:
                            button["query"] = query
                            button["button_path"] = [*button_path, button["button_text"]]
                        return buttons

                    if response.text:
                        raise RuntimeError(response.text.strip())

        if not media_message:
            raise RuntimeError("The bot did not return a media file for this selection.")

        if progress_hook:
            progress_hook({
                "status": "downloading",
                "_percent_str": "",
                "_speed_str": "Telegram",
                "_eta_str": "",
                "filename": f"Forwarding to {receiver}...",
                "display_full_path": True,
            })

        try:
            await client.forward_messages(receiver, media_message)
            _debug(f"[send] forwarded message_id={media_message.id} to {receiver!r}")
        except ChatForwardsRestrictedError:
            _debug("[send] forward restricted; falling back to download and upload")
            await _download_and_upload(client, receiver, media_message, progress_hook)

    if progress_hook:
        progress_hook({
            "status": "finished",
            "filename": f"Sent to {receiver}",
            "display_full_path": True,
        })


def send_selected_movie(item: dict, progress_hook=None, settings=None):
    return asyncio.run(_send_selected_movie_async(item, progress_hook=progress_hook))


async def _download_and_upload(client, receiver: str, message, progress_hook=None) -> None:
    with tempfile.TemporaryDirectory(prefix="axon_movie_") as tmp:
        if progress_hook:
            progress_hook({
                "status": "downloading",
                "_percent_str": "",
                "_speed_str": "Telegram",
                "_eta_str": "",
                "filename": "Forward is restricted. Downloading first...",
                "display_full_path": True,
            })

        media_path = await client.download_media(message, file=tmp)
        if not media_path:
            raise RuntimeError("Telegram did not provide a downloadable media file.")

        if progress_hook:
            progress_hook({
                "status": "downloading",
                "_percent_str": "",
                "_speed_str": "Telegram",
                "_eta_str": "",
                "filename": f"Uploading {Path(media_path).name} to {receiver}...",
                "display_full_path": True,
            })

        await client.send_file(
            receiver,
            media_path,
            caption=message.text or "",
            force_document=True,
        )
        _debug(f"[send] uploaded downloaded file={media_path!r} to {receiver!r}")
