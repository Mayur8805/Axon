from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

from core.menu import get_input, load_config, save_config

SETTINGS_KEY = "anime"
TOGGLE_OPTIONS = ["720p", "1080p", "dub", "episode"]
DOWNLOAD_BASE = Path("Downloads/Anime")


def _default_config() -> dict:
    return {
        "720p": False,
        "1080p": True,
        "dub": True,
        "episode": False,
        "episode_range": "",
    }


def _sanitize_folder_name(name: str) -> str:
    cleaned = re.sub(r'[<>:"/\\|?*]', "", name.strip())
    return cleaned or "anime"


def _quality_flag(values: dict) -> str:
    if values.get("720p"):
        return "720"
    return "1080"


def ani_cli_scraper() -> None:
    get_input(
        "Search anime",
        direct_download_fn=download_anime,
        setting_fn=settings_fn,
    )


def settings_fn(action, settings=None):
    config = load_config()
    anime_config = config.setdefault(SETTINGS_KEY, _default_config())

    if action == "load":
        return {
            "type": "toggles",
            "title": "Settings",
            "label": "Options",
            "options": TOGGLE_OPTIONS,
            "values": {
                "720p": bool(anime_config.get("720p", False)),
                "1080p": bool(anime_config.get("1080p", True)),
                "dub": bool(anime_config.get("dub", True)),
                "episode": bool(anime_config.get("episode", False)),
            },
            "text_fields": [
                {
                    "key": "episode_range",
                    "label": "Episode range",
                    "when": "episode",
                    "placeholder": "e.g. 1-12 or 7",
                }
            ],
            "text_values": {
                "episode_range": anime_config.get("episode_range", ""),
            },
            "exclusive_groups": [["720p", "1080p"]],
        }

    if action == "save" and settings:
        values = settings.get("values", {})
        if not values.get("720p") and not values.get("1080p"):
            values["1080p"] = True

        text_values = settings.get("text_values", {})
        anime_config.update(
            {
                "720p": bool(values.get("720p", False)),
                "1080p": bool(values.get("1080p", True)),
                "dub": bool(values.get("dub", True)),
                "episode": bool(values.get("episode", False)),
                "episode_range": text_values.get("episode_range", "").strip(),
            }
        )
        save_config(config)


# def download_anime(item: dict, progress_hook=None, settings=None) -> None:
#     query = item.get("query", "").strip()
#     if not query:
#         raise ValueError("Please enter an anime name")

#     state = settings or settings_fn("load")
#     values = state.get("values", {})
#     text_values = state.get("text_values", {})
#     use_episode = bool(values.get("episode", False))
#     episode_range = text_values.get("episode_range", "").strip()
#     if use_episode and not episode_range:
#         episode_range = load_config().get(SETTINGS_KEY, {}).get("episode_range", "").strip()

#     if use_episode and not episode_range:
#         raise ValueError("Set an episode range in settings (enable episode, then Enter to edit)")

#     ani_cli = shutil.which("ani-cli")
#     if not ani_cli:
#         raise FileNotFoundError("ani-cli is not installed or not on PATH")

#     download_dir = DOWNLOAD_BASE / _sanitize_folder_name(query)
#     download_dir.mkdir(parents=True, exist_ok=True)

#     command = [ani_cli, "-q", _quality_flag(values), "-d"]
#     if values.get("dub", True):
#         command.append("--dub")
#     if use_episode:
#         command.extend(["-e", episode_range])
#     command.append(query)

#     env = os.environ.copy()
#     env["ANI_CLI_DOWNLOAD_DIR"] = str(download_dir.resolve())

#     # If no progress_hook, fall back to the old blocking behaviour
#     if progress_hook is None:
#         result = subprocess.run(
#             command,
#             env=env,
#             cwd=str(download_dir.resolve()),
#         )
#         if result.returncode != 0:
#             raise RuntimeError(f"ani-cli failed with exit code {result.returncode}")
#         return

#     # ── Stream output through the progress hook ──
#     process = subprocess.Popen(
#         command,
#         env=env,
#         cwd=str(download_dir.resolve()),
#         stdout=subprocess.PIPE,
#         stderr=subprocess.STDOUT,
#         text=True,
#         bufsize=1,
#     )

#     for line in iter(process.stdout.readline, ""):
#         if not line:
#             break
#         stripped = line.rstrip("\n\r")
#         if stripped:
#             # Send the line to the TUI so it appears in the downloading box
#             progress_hook({"status": "downloading", "filename": stripped})

#     process.wait()

#     if process.returncode != 0:
#         # Report the error through the hook as well
#         progress_hook({"status": "error", "filename": f"Exit code {process.returncode}"})
#         raise RuntimeError(f"ani-cli failed with exit code {process.returncode}")

#     # Final success
#     progress_hook({"status": "finished", "filename": query})

def download_anime(item: dict, progress_hook=None, settings=None) -> None:
    """
    Run ani-cli in the real terminal (TUI will suspend).
    progress_hook is ignored because the terminal is fully handed off.
    """
    query = item.get("query", "").strip()
    if not query:
        raise ValueError("Please enter an anime name")

    state = settings or settings_fn("load")
    values = state.get("values", {})
    text_values = state.get("text_values", {})
    use_episode = bool(values.get("episode", False))
    episode_range = text_values.get("episode_range", "").strip()
    if use_episode and not episode_range:
        episode_range = load_config().get(SETTINGS_KEY, {}).get("episode_range", "").strip()

    if use_episode and not episode_range:
        raise ValueError("Set an episode range in settings (enable episode, then Enter to edit)")

    ani_cli = shutil.which("ani-cli")
    if not ani_cli:
        raise FileNotFoundError("ani-cli is not installed or not on PATH")

    download_dir = DOWNLOAD_BASE / _sanitize_folder_name(query)
    download_dir.mkdir(parents=True, exist_ok=True)

    command = [ani_cli, "-q", _quality_flag(values), "-d"]
    if values.get("dub", True):
        command.append("--dub")
    if use_episode:
        command.extend(["-e", episode_range])
    command.append(query)

    env = os.environ.copy()
    env["ANI_CLI_DOWNLOAD_DIR"] = str(download_dir.resolve())

    # Run ani-cli in the foreground – this takes over the terminal completely.
    result = subprocess.run(command, env=env, cwd=str(download_dir.resolve()))

    if result.returncode != 0:
        raise RuntimeError(f"ani-cli failed with exit code {result.returncode}")

download_anime.needs_terminal = True

