from __future__ import annotations
from textual.app import App
from textual.widgets import Static, Input
from rich.panel import Panel
from rich.align import Align
from textual.containers import Center, Middle,Vertical
from rich.box import ROUNDED
import pyfiglet

class KeyApp(App):
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
        yield Static("[yellow]↑ ↓ to move | Enter to select[/yellow]")

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

    def on_key(self, event):
        if event.key == "up":
            self.selected = (self.selected - 1) % len(self.options)
        elif event.key == "down":
            self.selected = (self.selected + 1) % len(self.options)
        elif event.key == "enter":
            self.exit(self.selected)

        self.update_ui()

"""
core/menu.py  —  Textual TUI with:
  • Left  panel : search input + results list (blue border)
  • Right top   : thumbnail rendered as Rich pixel art
  • Right bottom: download status / progress (blue border, Textual widget)
"""

"""
core/menu.py  —  Textual TUI with:
  • Left  panel : search input + results list (blue border)
  • Right top   : thumbnail rendered as Unicode block art inside a Textual widget
  • Right bottom: download status / progress (blue border, Textual widget)

  Works on any terminal (GNOME Terminal, xterm, etc.) — renders thumbnails
  as Rich pixel segments inside a Textual Static widget.
"""

"""
core/menu.py
"""


import io
import os
import threading
from typing import Callable

import httpx
from PIL import Image as PILImage
from textual.app import App, ComposeResult
from textual.widgets import Input, Static
from textual.containers import Container, Vertical
from textual_image.widget import Image as TextualImage


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

    CSS = """
    Screen {
        background: black;
        layout: horizontal;
        overflow: hidden hidden;
    }

    #left {
        width: 55%;
        height: 100%;
        padding: 0 1;
        align: center top;
    }

    Input {
        width: 80%;
        border: round #1e90ff;
        background: black;
        color: white;
        padding: 0 2;
        margin-bottom: 1;
    }
    Input:focus { border: round #1e90ff; }

    #msg {
        width: 100%;
        margin-bottom: 1;
    }

    #results {
        width: 100%;
        height: 1fr;
        border: round #1e90ff;
        padding: 0 1;
        background: black;
        color: white;
    }

    #right {
        width: 45%;
        height: 100%;
        padding: 0 1;
        layout: vertical;
        overflow: hidden hidden;
    }

    #thumb_box {
        width: 100%;
        height: 22;
        border: round #1e90ff;
        background: black;
        padding: 0 1;
        margin-bottom: 1;
        overflow: hidden hidden;
        scrollbar-size: 0 0;
        scrollbar-visibility: hidden;
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
        scrollbar-visibility: hidden;
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
    ):
        super().__init__()
        self.msg_text      = msg
        self.old_query     = old_query
        self.fetch_fn      = fetch_fn
        self.download_fn   = download_fn
        self.items: list[dict] = []
        self.selected: int     = 0
        self._last_thumb_url   = ""

    def compose(self) -> ComposeResult:
        with Vertical(id="left"):
            yield Input(value=self.old_query, placeholder="Search YouTube…")
            yield Static(self.msg_text, id="msg")
            yield Static("", id="results")

        with Vertical(id="right"):
            with Container(id="thumb_box"):
                yield TextualImage(id="thumb_image")
                yield Static("[dim]No thumbnail[/dim]", id="thumb_message")
            yield Static("[dim]No download yet.[/dim]", id="status_box")

    def on_mount(self) -> None:
        self.query_one(Input).focus()

    # ── search ───────────────────────────────────────────────────────────────
    def on_input_submitted(self, event: Input.Submitted) -> None:
        value = event.value.strip()
        if not value:
            self.query_one("#msg", Static).update("[red]Please enter something[/red]")
            return
        if self.fetch_fn:
            self.query_one("#msg", Static).update("[yellow]Fetching…[/yellow]")
            self.call_later(self._run_fetch, value)
        else:
            self.exit(value)

    def _run_fetch(self, value: str) -> None:
        self.items = self.fetch_fn(value) or []
        if not self.items:
            self.query_one("#msg", Static).update("[red]No results found[/red]")
            return
        self.selected = 0
        self.query_one(Input).disabled = True
        self.query_one("#msg", Static).update(
            "[green]↑ ↓ to pick  |  Enter to download  |  Esc to search again[/green]"
        )
        self._refresh_results()

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
    def on_key(self, event) -> None:
        if not self.items:
            return
        key = event.key
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

    def _download_thread(self, item: dict, status_widget: Static) -> None:
        def progress_hook(d: dict) -> None:
            if d["status"] == "downloading":
                pct      = d.get("_percent_str", "?%").strip()
                speed    = d.get("_speed_str", "?/s").strip()
                eta      = d.get("_eta_str", "?s").strip()
                filename = os.path.basename(d.get("filename", ""))
                msg = (
                    f"[cyan]{filename}[/cyan]\n\n"
                    f"  [green]{pct}[/green]\n"
                    f"  Speed : [white]{speed}[/white]\n"
                    f"  ETA   : [white]{eta}[/white]"
                )
                self.call_from_thread(status_widget.update, msg)
            elif d["status"] == "finished":
                filename = os.path.basename(d.get("filename", ""))
                self.call_from_thread(
                    status_widget.update,
                    f"[green]✓ Done![/green]\n\n[cyan]{filename}[/cyan]",
                )

        try:
            self.download_fn(item, progress_hook=progress_hook)
        except Exception as exc:
            self.call_from_thread(
                status_widget.update,
                f"[red]✗ Failed:[/red]\n{exc}",
            )

    # ── reset ─────────────────────────────────────────────────────────────────
    def _reset_to_search(self) -> None:
        self.items           = []
        self.selected        = 0
        self._last_thumb_url = ""
        self.query_one("#results", Static).update("")
        self._set_thumb_message("[dim]No thumbnail[/dim]")
        self.query_one("#status_box", Static).update("[dim]No download yet.[/dim]")
        self.query_one("#msg", Static).update(self.msg_text)
        inp = self.query_one(Input)
        inp.disabled = False
        inp.focus()


# ════════════════════════════════════════════════════════════════════════════
#  Public helpers
# ════════════════════════════════════════════════════════════════════════════

def get_input(
    msg: str = "",
    old_query: str = "",
    fetch_fn: Callable | None = None,
    download_fn: Callable | None = None,
):
    app = InputApp(
        msg=msg, old_query=old_query,
        fetch_fn=fetch_fn, download_fn=download_fn,
    )
    return app.run()



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
              download_fn: Callable | None = None):
    """
    Launch the TUI and return whatever the user confirmed.
    If download_fn is provided, downloading happens inside the TUI and
    this function returns the selected item dict when the TUI exits.
    """
    app = InputApp(msg=msg, old_query=old_query,
                   fetch_fn=fetch_fn, download_fn=download_fn)
    return app.run()
