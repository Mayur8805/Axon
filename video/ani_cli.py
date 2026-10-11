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

# ani-cli ships a self-updater: `ani-cli -U` fetches the remote script, patches
# in place if a newer version exists, then exits 0 immediately (it will NOT run
# a download in the same invocation). `ani-cli -V` prints the version.
ANI_CLI = "ani-cli"


def _ani_cli_version(ani_cli: str) -> str:
    """Return the installed ani-cli version string, or "" on failure."""
    try:
        out = subprocess.run(
            [ani_cli, "-V"], capture_output=True, text=True, timeout=15,
        ).stdout.strip()
    except (subprocess.SubprocessError, OSError):
        return ""
    return out.split()[0] if out else ""


def _update_ani_cli(ani_cli: str) -> bool:
    """
    Run the ani-cli self-updater. Returns True if an update was applied or the
    script was already up to date, False only if the update itself failed.
    The update is best-effort: a network failure must never block a download.
    """
    try:
        result = subprocess.run(
            [ani_cli, "-U"], capture_output=True, text=True, timeout=60,
        )
    except (subprocess.SubprocessError, OSError) as exc:
        print(f"[ani-cli] update skipped ({type(exc).__name__})")
        return False

    if result.returncode != 0:
        print(f"[ani-cli] update failed: {(result.stderr or result.stdout).strip()[:200]}")
        return False
    print(f"[ani-cli] update check ok: {(result.stdout).strip()[:200]}")
    return True


def _ensure_ani_cli_updated(ani_cli: str) -> None:
    """
    Always check for an update before downloading. If a newer version exists
    it is applied; if the script is already current we just continue. A failed
    update never raises — the download still runs with whatever is installed.
    """
    before = _ani_cli_version(ani_cli)
    _update_ani_cli(ani_cli)
    after = _ani_cli_version(ani_cli)
    if before and after and before != after:
        print(f"[ani-cli] updated {before} -> {after}")
    elif before and after and before == after:
        print(f"[ani-cli] up to date ({before})")


def download_anime(item: dict, progress_hook=None, settings=None) -> None:
    """
    Run ani-cli in the real terminal (TUI will suspend).
    progress_hook is ignored because the terminal is fully handed off.

    The script is always self-updated first so a stale ani-cli (which is what
    caused the earlier breakage) is patched before it is used.
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

    ani_cli = shutil.which(ANI_CLI)
    if not ani_cli:
        raise FileNotFoundError(f"{ANI_CLI} is not installed or not on PATH")

    # Always bring ani-cli up to date before using it.
    _ensure_ani_cli_updated(ani_cli)

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

    # ani-cli's fzf menu needs a real TTY. When the Textual TUI suspends and
    # hands the terminal to the child, the child's stdin is whatever the TUI
    # was holding (a pipe, not a TTY) — fzf then prints "inappropriate ioctl
    # for device" and hangs forever. Reattach the controlling terminal so
    # fzf/ani-cli get a live TTY.
    try:
        tty = open("/dev/tty", "r")
    except OSError:
        tty = None

    try:
        result = subprocess.run(
            command, env=env, cwd=str(download_dir.resolve()),
            stdin=tty if tty is not None else None,
        )
    finally:
        if tty is not None:
            tty.close()

    if result.returncode != 0:
        raise RuntimeError(f"ani-cli failed with exit code {result.returncode}")

download_anime.needs_terminal = True

