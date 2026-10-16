"""System-tray icon for ``local-encoder serve`` (the packaged app's only visible part on Windows).

The icon offers "Open Local Encoder" (also on left click) and "Quit", shows notifications when
a video finishes or fails, and asks for confirmation before quitting while videos are still
being processed. ``pystray`` is imported lazily: when it is missing or cannot show an icon
(for example Linux without a desktop), :func:`load_pystray` returns None / :meth:`TrayApp.run`
returns False and the caller keeps the console behavior.
"""

from __future__ import annotations

import locale
import logging
import os
import sys
import threading
import time
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from PIL import Image

logger = logging.getLogger(__name__)

APP_NAME = "Local Encoder"
BRAND_BLUE = "#4a7cff"
QUIT_CONFIRM_SECONDS = 15
TITLE_MAX_CHARS = 60
_MENU_REFRESH_SECONDS = 1.0

Notifier = Callable[[str, str], None]

_STRINGS: dict[str, dict[str, str]] = {
    "en": {
        "open": "Open Local Encoder",
        "quit": "Quit",
        "quit_busy_one": "Quit (1 video in progress)",
        "quit_busy_many": "Quit ({count} videos in progress)",
        "confirm_one": (
            "1 video is still being processed. "
            "Choose Quit again within {seconds} seconds to stop it."
        ),
        "confirm_many": (
            "{count} videos are still being processed. "
            "Choose Quit again within {seconds} seconds to stop them."
        ),
        "done": "“{title}” was published on your site.",
        "error": "“{title}” could not be sent. Open Local Encoder to see what happened.",
    },
    "pt": {
        "open": "Abrir o Local Encoder",
        "quit": "Sair",
        "quit_busy_one": "Sair (1 vídeo em andamento)",
        "quit_busy_many": "Sair ({count} vídeos em andamento)",
        "confirm_one": (
            "1 vídeo ainda está sendo processado. "
            "Escolha Sair de novo em até {seconds} segundos para interrompê-lo."
        ),
        "confirm_many": (
            "{count} vídeos ainda estão sendo processados. "
            "Escolha Sair de novo em até {seconds} segundos para interrompê-los."
        ),
        "done": "“{title}” foi publicado no seu site.",
        "error": (
            "Não foi possível enviar “{title}”. Abra o Local Encoder para ver o que aconteceu."
        ),
    },
    "es": {
        "open": "Abrir Local Encoder",
        "quit": "Salir",
        "quit_busy_one": "Salir (1 video en curso)",
        "quit_busy_many": "Salir ({count} videos en curso)",
        "confirm_one": (
            "1 video todavía se está procesando. "
            "Elige Salir de nuevo en menos de {seconds} segundos para detenerlo."
        ),
        "confirm_many": (
            "{count} videos todavía se están procesando. "
            "Elige Salir de nuevo en menos de {seconds} segundos para detenerlos."
        ),
        "done": "“{title}” se publicó en tu sitio.",
        "error": "No se pudo enviar “{title}”. Abre Local Encoder para ver qué pasó.",
    },
}

# Windows primary language ids (LANGID & 0x3FF)
_WINDOWS_LANGUAGES = {0x16: "pt", 0x0A: "es", 0x09: "en"}


# ---------------------------------------------------------------------------
# Language
# ---------------------------------------------------------------------------


def _language_from_code(code: str | None) -> str | None:
    """Map 'pt_BR.UTF-8', 'es-ES', 'Portuguese_Brazil' … to a supported language."""
    if not code:
        return None
    value = code.strip().lower()
    for prefix, lang in (("pt", "pt"), ("es", "es"), ("en", "en")):
        if value.startswith(prefix):
            return lang
    for name, lang in (("portuguese", "pt"), ("spanish", "es"), ("english", "en")):
        if value.startswith(name):
            return lang
    return None


def _windows_ui_language() -> str | None:
    if sys.platform != "win32":
        return None
    try:
        import ctypes

        langid = int(ctypes.windll.kernel32.GetUserDefaultUILanguage())
    except (OSError, AttributeError, ValueError):
        return None
    return _WINDOWS_LANGUAGES.get(langid & 0x3FF)


def detect_language() -> str:
    """Return 'en', 'pt' or 'es' from the operating system language (default English)."""
    lang = _windows_ui_language()
    if lang:
        return lang
    for variable in ("LC_ALL", "LC_MESSAGES", "LANG", "LANGUAGE"):
        lang = _language_from_code(os.environ.get(variable))
        if lang:
            return lang
    try:
        lang = _language_from_code(locale.getlocale()[0])
    except ValueError:
        lang = None
    return lang or "en"


def text(key: str, lang: str = "en", **values: object) -> str:
    """Translated string *key* with ``{placeholders}`` filled in."""
    strings = _STRINGS.get(lang, _STRINGS["en"])
    return strings.get(key, _STRINGS["en"][key]).format(**values)


def truncate_title(title: str, limit: int = TITLE_MAX_CHARS) -> str:
    title = " ".join((title or "").split()) or APP_NAME
    if len(title) <= limit:
        return title
    return title[: limit - 1].rstrip() + "…"


# ---------------------------------------------------------------------------
# Icon image and pystray loading
# ---------------------------------------------------------------------------


def make_icon_image(size: int = 64) -> Image.Image:
    """Brand-blue rounded square with a white "play" triangle, drawn at runtime."""
    from PIL import Image, ImageDraw

    scale = 4  # draw larger, then shrink, for smooth edges
    big = size * scale
    image = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    margin = big // 32
    draw.rounded_rectangle(
        (margin, margin, big - 1 - margin, big - 1 - margin),
        radius=big // 5,
        fill=BRAND_BLUE,
    )
    draw.polygon(
        [(big * 0.38, big * 0.27), (big * 0.38, big * 0.73), (big * 0.75, big * 0.50)],
        fill="white",
    )
    return image.resize((size, size), Image.Resampling.LANCZOS)


def load_pystray() -> Any | None:
    """Import pystray, or return None when no tray icon can be used on this system."""
    try:
        import pystray  # type: ignore[import-untyped]
    except Exception as exc:  # also Xlib display errors on Linux without a desktop
        logger.info("Tray icon not available: %s", exc)
        return None
    return pystray


# ---------------------------------------------------------------------------
# Helpers for ``serve``
# ---------------------------------------------------------------------------


def wait_until_started(server: Any, thread: threading.Thread | None, timeout: float) -> bool:
    """Wait for uvicorn to accept connections; False if it stopped or did not start in time."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if server.started:
            return True
        if thread is not None and not thread.is_alive():
            return False
        time.sleep(0.05)
    return bool(server.started)


def open_browser_when_ready(server: Any, url: str) -> None:
    import webbrowser

    if wait_until_started(server, None, timeout=30.0):
        webbrowser.open(url)


def server_hooks() -> tuple[Callable[[], int], Callable[[Notifier | None], None]]:
    """``server.active_job_count`` and ``server.set_notifier`` (no-ops if the server lacks them)."""
    from local_encoder import server as server_module

    def no_jobs() -> int:
        return 0

    def no_notifier(_fn: Notifier | None) -> None:
        return None

    active: Callable[[], int] = getattr(server_module, "active_job_count", no_jobs)
    set_notifier: Callable[[Notifier | None], None] = getattr(
        server_module, "set_notifier", no_notifier
    )
    return active, set_notifier


# ---------------------------------------------------------------------------
# Tray application
# ---------------------------------------------------------------------------


class TrayApp:
    """The tray icon, its menu and notifications.

    Parameters
    ----------
    pystray:
        The pystray module (from :func:`load_pystray`).
    open_page:
        Opens the web UI in the browser.
    on_quit:
        Stops the web server; called once when the user quits.
    active_jobs:
        Number of videos waiting or being processed.
    """

    def __init__(
        self,
        pystray: Any,
        *,
        open_page: Callable[[], object],
        on_quit: Callable[[], None],
        active_jobs: Callable[[], int],
        lang: str | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._pystray = pystray
        self._open_page = open_page
        self._on_quit = on_quit
        self._active_jobs = active_jobs
        self.lang = lang or detect_language()
        self._clock = clock
        self._quit_armed_at: float | None = None
        self._stopping = threading.Event()
        self._icon: Any | None = None

    # -- texts ---------------------------------------------------------------

    def _job_count(self) -> int:
        try:
            return max(0, int(self._active_jobs()))
        except Exception:
            logger.debug("Could not read the number of active jobs", exc_info=True)
            return 0

    def quit_label(self) -> str:
        count = self._job_count()
        if count == 0:
            return text("quit", self.lang)
        if count == 1:
            return text("quit_busy_one", self.lang)
        return text("quit_busy_many", self.lang, count=count)

    # -- actions -------------------------------------------------------------

    def request_quit(self) -> bool:
        """True when Local Encoder should quit now.

        With videos still in progress, the first request only shows a warning; a second one
        within ``QUIT_CONFIRM_SECONDS`` confirms it.
        """
        count = self._job_count()
        if count == 0:
            return True
        now = self._clock()
        if self._quit_armed_at is not None and now - self._quit_armed_at <= QUIT_CONFIRM_SECONDS:
            return True
        self._quit_armed_at = now
        key = "confirm_one" if count == 1 else "confirm_many"
        self._show_notification(text(key, self.lang, count=count, seconds=QUIT_CONFIRM_SECONDS))
        return False

    def notify(self, kind: str, title: str) -> None:
        """Server notifier: a video finished ('done') or failed ('error'). Never raises."""
        if kind not in ("done", "error"):
            logger.debug("Ignoring tray notification of kind %r", kind)
            return
        self._show_notification(text(kind, self.lang, title=truncate_title(title)))

    def _show_notification(self, message: str) -> None:
        icon = self._icon
        if icon is None:
            return
        try:
            if getattr(icon, "HAS_NOTIFICATION", True):
                icon.notify(message, APP_NAME)
        except Exception:
            logger.warning("Could not show a tray notification", exc_info=True)

    def _open_clicked(self, icon: Any = None, item: Any = None) -> None:
        try:
            self._open_page()
        except Exception:
            logger.warning("Could not open the browser", exc_info=True)

    def _quit_clicked(self, icon: Any = None, item: Any = None) -> None:
        if self.request_quit():
            self.stop()

    def stop(self) -> None:
        """Quit without asking (Quit confirmed, or the page's Stop button); any thread."""
        self._stopping.set()
        try:
            self._on_quit()
        finally:
            if self._icon is not None:
                self._icon.stop()

    # -- running -------------------------------------------------------------

    def build_menu(self) -> Any:
        pystray = self._pystray
        return pystray.Menu(
            pystray.MenuItem(text("open", self.lang), self._open_clicked, default=True),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(lambda _item: self.quit_label(), self._quit_clicked),
        )

    def _setup(self, icon: Any) -> None:
        """Runs in a pystray helper thread: show the icon and keep the Quit text current."""
        icon.visible = True
        shown = self.quit_label()
        while not self._stopping.wait(_MENU_REFRESH_SECONDS):
            label = self.quit_label()
            if label != shown:
                shown = label
                try:
                    icon.update_menu()
                except Exception:
                    logger.debug("Could not refresh the tray menu", exc_info=True)

    def run(self) -> bool:
        """Show the icon and block until Quit (must run on the main thread).

        Returns False when the icon could not be shown, so the caller can fall back to the
        console behavior.
        """
        try:
            self._icon = self._pystray.Icon(
                "local-encoder", make_icon_image(), APP_NAME, menu=self.build_menu()
            )
            self._icon.run(setup=self._setup)
        except Exception:
            logger.warning("The tray icon could not be shown", exc_info=True)
            self._stopping.set()
            self._icon = None
            return False
        finally:
            self._stopping.set()
        return True
