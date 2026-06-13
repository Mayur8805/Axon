from __future__ import annotations

import inspect
import io
import json
import os
import threading
from pathlib import Path
from typing import Callable

import httpx
import pyfiglet
from PIL import Image as PILImage
from rich.align import Align
from rich.box import ROUNDED
from rich.panel import Panel
from textual.app import App, ComposeResult
from textual.containers import Container, Vertical
from textual.widgets import Input, Static
from textual_image.widget import Image as TextualImage

BACK = "__AXON_BACK__"
BACK_KEYS = {"alt+left", "ctrl+backspace", "ctrl+h"}


def is_back(value) -> bool:
    return value == BACK


class KeyApp(App):
    BINDINGS = [
        ("alt+left", "go_back", "Back"),
        ("ctrl+backspace", "go_back", "Back"),
    ]

    def __init__(self, options, panel = True):
        super().__init__()
        self.options = options
        self.selected = 0
        self.panel_show = panel

        banner = pyfiglet.figlet_format("AXON", font="ansi_shadow")
        self.panel = Panel(
            Align.center(f"[#1e90ff]{banner}[/#1e90ff]"),
            title="Makwana Ⓒ",
            border_style="#1e90ff",
            padding=(1, 2),
            box=ROUNDED
        )

    def compose(self):
        if self.panel_show:
            yield Static(self.panel) 
        yield Static("[yellow]↑ ↓ to move | Enter to select | Alt+Left / Ctrl+Backspace to go back[/yellow]")

        self.menu = Static()
        yield self.menu

    def on_mount(self):
        self.update_ui()

    def update_ui(self):
        text = ""
        for i, opt in enumerate(self.options):
            if i == self.selected:
                text += f"[#1e90ff]> {opt}[/#1e90ff]\n"
            else:
                text += f"  {opt}\n"
        self.menu.update(text)

    def action_go_back(self) -> None:
        self.exit(BACK)

    def on_key(self, event):
        if event.key in BACK_KEYS:
            self.exit(BACK)
        elif event.key == "up":
            self.selected = (self.selected - 1) % len(self.options)
        elif event.key == "down":
            self.selected = (self.selected + 1) % len(self.options)
        elif event.key == "enter":
            self.exit(self.selected)

        self.update_ui()

CONFIG_PATH = Path(__file__).resolve().parent.parent / "config.json"


def load_config() -> dict:
    if not CONFIG_PATH.exists():
        return {}

    try:
        return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def save_config(config: dict) -> None:
    CONFIG_PATH.write_text(json.dumps(config, indent=2), encoding="utf-8")


def _load_thumbnail(url: str) -> PILImage.Image | None:
    if not url:
        return None

    try:
        resp = httpx.get(url, timeout=30)
        resp.raise_for_status()

        with PILImage.open(io.BytesIO(resp.content)) as image:
            return image.convert("RGBA").copy()

    except Exception:
        return None

class InputApp(App):

    BINDINGS = [
        ("ctrl+comma", "focus_settings", "Focus settings"),
        ("ctrl+s", "focus_settings", "Focus settings"),
        ("f2", "focus_settings", "Focus settings"),
        ("alt+left", "go_back", "Back"),
        ("ctrl+backspace", "go_back", "Back"),
    ]

    CSS = """
    Screen {
        background: black;
        layout: vertical;
        overflow: hidden hidden;
    }

    #search_bar {
        width: 100%;
        height: 3;
        padding: 0 1;
    }

    #msg {
        width: 100%;
        height: 2;
        padding: 0 1;
        color: white;
    }

    Input {
        width: 100%;
        border: round #1e90ff;
        background: black;
        color: white;
    }
    Input:focus { border: round #1e90ff; }

    #main_grid {
        width: 100%;
        height: 1fr;
        layout: horizontal;
        align: left top;
        padding: 0 1 1 1;
    }

    #left {
        width: 50%;
        height: 100%;
        layout: vertical;
        align: left top;
        padding-right: 1;
    }

    #results_box {
        width: 100%;
        height: 1fr;
        border: round #1e90ff;
        padding: 0 1;
        background: black;
        color: white;
        margin-bottom: 1;
    }

    #results {
        width: 100%;
        height: 1fr;
    }

    #settings_box {
        width: 100%;
        height: 1fr;
        border: round #1e90ff;
        background: black;
        color: white;
        padding: 0 1;
    }

    #right {
        width: 50%;
        height: 100%;
        layout: vertical;
        align: left top;
        padding-left: 1;
        overflow: hidden hidden;
    }

    #thumb_box {
        width: 100%;
        height: 1fr;
        border: round #1e90ff;
        background: black;
        padding: 0 1;
        margin-bottom: 1;
        overflow: hidden hidden;
        scrollbar-size: 0 0;
        scrollbar-background: black;
        scrollbar-color: black;
        scrollbar-corner-color: black;
        align: center middle;
    }

    #thumb_image {
        display: none;
        width: auto;
        height: 90%;
        background: black;
        overflow: hidden hidden;
        scrollbar-size: 0 0;
        scrollbar-background: black;
        scrollbar-color: black;
        scrollbar-corner-color: black;
    }

    #thumb_message {
        width: 100%;
        height: 100%;
        content-align: center middle;
        color: $text-muted;
    }

    #status_box {
        width: 100%;
        height: 1fr;
        border: round #1e90ff;
        background: black;
        color: white;
        padding: 0 1;
        overflow: hidden hidden;
    }
    """

    def __init__(
        self,
        msg: str = "",
        old_query: str = "",
        fetch_fn: Callable | None = None,
        download_fn: Callable | None = None,
        direct_download_fn: Callable | None = None,
        setting_fn: Callable | None = None,
    ):
        super().__init__()
        self.msg_text      = msg
        self.old_query     = old_query
        self.fetch_fn      = fetch_fn
        self.download_fn   = download_fn
        self.direct_download_fn = direct_download_fn
        self.setting_fn    = setting_fn
        self.items: list[dict] = []
        self.selected: int     = 0
        self._last_thumb_url   = ""
        self.focus_mode        = "search"
        self.settings_state    = self._load_settings_state()
        self._settings_dirty   = False
        self._fetching         = False

    def _load_settings_state(self) -> dict:
        if not self.setting_fn:
            return {}

        settings = self.setting_fn(action="load") or {}
        if settings.get("type") == "toggles":
            settings.setdefault("cursor", 0)
            settings.setdefault("values", {})
            return settings

        options = settings.get("options", [])
        selected = settings.get("selected")
        if options and selected not in options:
            settings["selected"] = options[0]
        return settings

    def compose(self) -> ComposeResult:
        with Container(id="search_bar"):
            yield Input(value=self.old_query, placeholder="Search YouTube…")

        yield Static(self.msg_text, id="msg")

        with Container(id="main_grid"):
            with Vertical(id="left"):
                with Container(id="results_box"):
                    yield Static("", id="results")
                yield Static("", id="settings_box")

            with Vertical(id="right"):
                with Container(id="thumb_box"):
                    yield TextualImage(id="thumb_image")
                    yield Static("[dim]No thumbnail[/dim]", id="thumb_message")
                yield Static("[dim]No download yet.[/dim]", id="status_box")

    def on_mount(self) -> None:
        self.query_one(Input).focus()
        self._refresh_settings()

    def on_unmount(self) -> None:
        self._save_settings_if_needed()

    def _refresh_settings(self) -> None:
        widget = self.query_one("#settings_box", Static)
        if not self.settings_state:
            widget.update("[dim]No settings available[/dim]")
            return

        title = self.settings_state.get("title", "Settings")
        label = self.settings_state.get("label", "Options")
        if self.settings_state.get("type") == "toggles":
            values = self.settings_state.get("values", {})
            options = self.settings_state.get("options", [])
            cursor = self.settings_state.get("cursor", 0)
            lines = [f"[bold]{title}[/bold]", "", label]

            for index, option in enumerate(options):
                enabled = bool(values.get(option, False))
                marker = ">" if index == cursor else " "
                value = "true" if enabled else "false"
                color = "#63b3ff" if self.focus_mode == "settings" and index == cursor else "white"
                lines.append(f"[{color}]{marker} {option}: {value}[/{color}]")

            if self.setting_fn:
                lines.extend(["", "[dim]Ctrl+, Ctrl+S, or F2 to focus settings[/dim]", "[dim]Use Up/Down and Enter[/dim]"])

            widget.update("\n".join(lines))
            return

        selected = self.settings_state.get("selected")
        lines = [f"[bold]{title}[/bold]", "", label]

        for option in self.settings_state.get("options", []):
            is_selected = option == selected
            marker = ">" if is_selected else " "
            color = "#63b3ff" if self.focus_mode == "settings" and is_selected else ("#1e90ff" if is_selected else "white")
            lines.append(f"[{color}]{marker} {option}[/{color}]")

        if self.setting_fn:
            lines.extend(["", "[dim]Ctrl+, Ctrl+S, or F2 to focus settings[/dim]", "[dim]Use Up/Down and Enter[/dim]"])

        widget.update("\n".join(lines))

    def _save_settings_if_needed(self) -> None:
        if not self.setting_fn or not self._settings_dirty:
            return

        self.setting_fn(action="save", settings=self.settings_state)
        self._settings_dirty = False

    # ── search ───────────────────────────────────────────────────────────────
    def on_input_submitted(self, event: Input.Submitted) -> None:
        value = event.value.strip()
        if not value:
            self.query_one("#msg", Static).update("[red]Please enter something[/red]")
            return
        if self.fetch_fn:
            self.items = []
            self.selected = 0
            self._last_thumb_url = ""
            self.query_one("#results", Static).update("")
            self._set_thumb_message("[dim]No thumbnail[/dim]")
            self.query_one(Input).disabled = True
            self._fetching = True
            self.query_one("#msg", Static).update("[yellow]Fetching…[/yellow]")
            threading.Thread(target=self._run_fetch, args=(value,), daemon=True).start()
        elif self.direct_download_fn:
            self.query_one(Input).disabled = True
            self.query_one("#msg", Static).update("[yellow]Downloading…[/yellow]")
            self.query_one("#results", Static).update(f"[#1e90ff]▶ {value}[/#1e90ff]")
            self._set_thumb_message("[dim]No thumbnail[/dim]")
            self._start_direct_download(value)
        else:
            self.exit(value)

    def _run_fetch(self, value: str) -> None:
        try:
            kwargs = {}
            if "on_result" in inspect.signature(self.fetch_fn).parameters:
                kwargs["on_result"] = self._queue_result
            results = self.fetch_fn(value, **kwargs) or []
            self.call_from_thread(self._finish_fetch, results)
        except Exception as exc:
            self.call_from_thread(
                self.query_one("#msg", Static).update,
                f"[red]Fetch failed:[/red] {exc}",
            )
            self.call_from_thread(self._unlock_search)

    def _queue_result(self, item: dict) -> None:
        self.call_from_thread(self._append_result, item)

    def _append_result(self, item: dict) -> None:
        self.items.append(item)
        if len(self.items) == 1:
            self.selected = 0
            self.query_one("#msg", Static).update(
                "[green]↑ ↓ to pick  |  Enter to download  |  Esc to search again[/green]"
            )
        self._refresh_results()

    def _finish_fetch(self, results: list[dict]) -> None:
        if not self.items:
            self.items = results

        self._fetching = False
        if not self.items:
            self.query_one("#msg", Static).update("[red]No results found[/red]")
            self._unlock_search()
            return

        self.selected = min(self.selected, len(self.items) - 1)
        self.query_one("#msg", Static).update(
            "[green]↑ ↓ to pick  |  Enter to download  |  Esc to search again[/green]"
        )
        self._refresh_results()

    def _unlock_search(self) -> None:
        self._fetching = False
        inp = self.query_one(Input)
        inp.disabled = False
        inp.focus()

    # ── results ───────────────────────────────────────────────────────────────
    def _refresh_results(self) -> None:
        lines: list[str] = []
        for i, item in enumerate(self.items):
            title = item.get("title", "?") if isinstance(item, dict) else str(item)
            dur   = item.get("duration", "") if isinstance(item, dict) else ""
            dur_s = f"  [{dur}]" if dur else ""
            if i == self.selected:
                lines.append(f"[#1e90ff]▶ {title}{dur_s}[/#1e90ff]")
            else:
                lines.append(f"  [white]{title}[/white][dim]{dur_s}[/dim]")
        self.query_one("#results", Static).update("\n".join(lines))
        self._trigger_thumb()
        self._refresh_settings()

    # ── thumbnail ─────────────────────────────────────────────────────────────
    def _set_thumb_message(self, message: str) -> None:
        image_widget = self.query_one("#thumb_image", TextualImage)
        message_widget = self.query_one("#thumb_message", Static)
        image_widget.image = None
        image_widget.display = False
        image_widget.refresh(layout=True)
        message_widget.display = True
        message_widget.update(message)

    def _set_thumb_image(self, url: str, image: PILImage.Image | None) -> None:
        if url != self._last_thumb_url:
            return

        if image is None:
            self._set_thumb_message("[dim]Preview unavailable[/dim]")
            return

        image_widget = self.query_one("#thumb_image", TextualImage)
        message_widget = self.query_one("#thumb_message", Static)
        image_widget.image = None
        image_widget.refresh(layout=True)
        image_widget.image = image
        image_widget.display = True
        message_widget.display = False

    def _trigger_thumb(self) -> None:
        item = self.items[self.selected] if self.items else {}
        url  = item.get("thumbnail", "") if isinstance(item, dict) else ""
        if url == self._last_thumb_url:
            return
        self._last_thumb_url = url

        self._set_thumb_message("[dim]Loading…[/dim]")

        captured_url = url  # capture for closure

        def _worker() -> None:
            image = _load_thumbnail(captured_url)
            self.call_from_thread(self._set_thumb_image, captured_url, image)

        threading.Thread(target=_worker, daemon=True).start()

    # ── keyboard ──────────────────────────────────────────────────────────────
    def action_go_back(self) -> None:
        self.exit(BACK)

    def action_focus_settings(self) -> None:
        if not self.setting_fn:
            return

        self.focus_mode = "settings"
        self._refresh_settings()

    def on_key(self, event) -> None:
        key = event.key

        if key in BACK_KEYS:
            self.exit(BACK)
            return

        if key == "escape" and not self.items:
            self._reset_to_search()
            return

        if self.focus_mode == "settings":
            if key in {"up", "down"}:
                self._move_setting(-1 if key == "up" else 1)
            elif key == "enter":
                if self.settings_state.get("type") == "toggles":
                    self._toggle_setting()
                else:
                    self.focus_mode = "results" if self.items else "search"
                    self._refresh_settings()
            elif key == "escape":
                self.focus_mode = "results" if self.items else "search"
                self._refresh_settings()
            return

        if not self.items:
            return

        if key == "up":
            self.selected = (self.selected - 1) % len(self.items)
            self._refresh_results()
        elif key == "down":
            self.selected = (self.selected + 1) % len(self.items)
            self._refresh_results()
        elif key == "enter":
            self._start_download()
        elif key == "escape":
            self._reset_to_search()

    def _move_setting(self, direction: int) -> None:
        if self.settings_state.get("type") == "toggles":
            options = self.settings_state.get("options", [])
            if not options:
                return

            cursor = self.settings_state.get("cursor", 0)
            self.settings_state["cursor"] = (cursor + direction) % len(options)
            self._refresh_settings()
            return

        options = self.settings_state.get("options", [])
        if not options:
            return

        current = self.settings_state.get("selected")
        index = options.index(current) if current in options else 0
        self.settings_state["selected"] = options[(index + direction) % len(options)]

        self._settings_dirty = True
        self._save_settings_if_needed()
        self._refresh_settings()

    def _toggle_setting(self) -> None:
        options = self.settings_state.get("options", [])
        if not options:
            return

        cursor = self.settings_state.get("cursor", 0)
        option = options[cursor]
        values = self.settings_state.setdefault("values", {})
        values[option] = not bool(values.get(option, False))

        if not any(values.get(item, False) for item in options):
            values[option] = True

        self._settings_dirty = True
        self._save_settings_if_needed()
        self._refresh_settings()

    # ── download ──────────────────────────────────────────────────────────────
    def _start_download(self) -> None:
        item   = self.items[self.selected]
        status = self.query_one("#status_box", Static)
        status.update("[yellow]⏳ Starting download…[/yellow]")
        if self.download_fn:
            threading.Thread(
                target=self._download_thread,
                args=(item, status),
                daemon=True,
            ).start()
        else:
            self.exit((self.selected, item))

    def _start_direct_download(self, value: str) -> None:
        status = self.query_one("#status_box", Static)
        status.update("[yellow]⏳ Starting download…[/yellow]")
        threading.Thread(
            target=self._download_thread,
            args=({"query": value}, status, self.direct_download_fn, True),
            daemon=True,
        ).start()

    def _download_thread(
        self,
        item: dict,
        status_widget: Static,
        download_fn: Callable | None = None,
        unlock_when_done: bool = False,
    ) -> None:
        download_fn = download_fn or self.download_fn

        def progress_hook(d: dict) -> None:
            if d["status"] == "downloading":
                pct      = d.get("_percent_str", "?%").strip()
                speed    = d.get("_speed_str", "?/s").strip()
                eta      = d.get("_eta_str", "?s").strip()
                raw_filename = d.get("filename", "")
                filename = raw_filename if d.get("display_full_path") else os.path.basename(raw_filename)
                if not pct and not eta:
                    msg = f"[cyan]{filename}[/cyan]\n\n[dim]{speed}[/dim]"
                else:
                    msg = (
                        f"[cyan]{filename}[/cyan]\n\n"
                        f"  [green]{pct}[/green]\n"
                        f"  Speed : [white]{speed}[/white]\n"
                        f"  ETA   : [white]{eta}[/white]"
                    )
                self.call_from_thread(status_widget.update, msg)
            elif d["status"] == "finished":
                raw_filename = d.get("filename", "")
                filename = raw_filename if d.get("display_full_path") else os.path.basename(raw_filename)
                self.call_from_thread(
                    status_widget.update,
                    f"[green]✓ Done![/green]\n\n[cyan]{filename}[/cyan]",
                )


        try:
            kwargs = {"progress_hook": progress_hook}
            if "settings" in inspect.signature(download_fn).parameters:
                kwargs["settings"] = self.settings_state
            download_fn(item, **kwargs)
        except Exception as exc:
            self.call_from_thread(
                status_widget.update,
                f"[red]✗ Failed:[/red]\n{exc}",
            )
        finally:
            if unlock_when_done:
                self.call_from_thread(self._unlock_search)

    # ── reset ─────────────────────────────────────────────────────────────────
    def _reset_to_search(self) -> None:
        self.items           = []
        self.selected        = 0
        self._last_thumb_url = ""
        self._fetching       = False
        self.query_one("#results", Static).update("")
        self._set_thumb_message("[dim]No thumbnail[/dim]")
        self.query_one("#status_box", Static).update("[dim]No download yet.[/dim]")
        self.query_one("#msg", Static).update(self.msg_text)
        self._unlock_search()
        self.focus_mode = "search"
        self._refresh_settings()


# ════════════════════════════════════════════════════════════════════════════
#  Public helpers
# ════════════════════════════════════════════════════════════════════════════

def select_option(options: list, msg: str = "Select an option"):
    """Simple wrapper: show a static list and return the chosen item."""
    items = [{"title": str(o)} for o in options]

    class _Picker(InputApp):
        def on_mount(self):
            self.items    = items
            self.selected = 0
            self._refresh_results()

    app = _Picker(msg=msg)
    result = app.run()
    if isinstance(result, tuple):
        return options[result[0]]
    return result

def select_option(options, panel_show):
    return KeyApp(options, panel_show).run()

 
def get_input(msg: str = "", old_query: str = "",
              fetch_fn: Callable | None = None,
              download_fn: Callable | None = None,
              direct_download_fn: Callable | None = None,
              setting_fn: Callable | None = None):
    """
    Launch the TUI and return whatever the user confirmed.
    If download_fn is provided, downloading happens inside the TUI and
    this function returns the selected item dict when the TUI exits.
    """
    app = InputApp(msg=msg, old_query=old_query,
                   fetch_fn=fetch_fn, download_fn=download_fn,
                   direct_download_fn=direct_download_fn,
                   setting_fn=setting_fn)
    return app.run()
