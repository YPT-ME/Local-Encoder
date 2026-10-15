"""Tests for local_encoder.tray (fake pystray; no real tray icon)."""

from __future__ import annotations

import threading
from collections.abc import Callable
from typing import Any

import pytest

from local_encoder import tray

# ---------------------------------------------------------------------------
# Fake pystray
# ---------------------------------------------------------------------------


class FakeMenuItem:
    def __init__(self, text: Any, action: Callable[..., Any], default: bool = False) -> None:
        self._text = text
        self.action = action
        self.default = default

    @property
    def text(self) -> str:
        return str(self._text(self) if callable(self._text) else self._text)


class FakeMenu:
    SEPARATOR = object()

    def __init__(self, *items: Any) -> None:
        self.items = items


class FakeIcon:
    HAS_NOTIFICATION = True
    instances: list[FakeIcon] = []
    run_error: Exception | None = None

    def __init__(self, name: str, image: Any, title: str, menu: Any) -> None:
        self.name, self.image, self.title, self.menu = name, image, title, menu
        self.notifications: list[tuple[str, str]] = []
        self.stopped = False
        self.visible = False
        self.menu_updates = 0
        FakeIcon.instances.append(self)

    def run(self, setup: Callable[[Any], None]) -> None:
        if FakeIcon.run_error is not None:
            raise FakeIcon.run_error
        self.setup = setup

    def notify(self, message: str, title: str) -> None:
        self.notifications.append((message, title))

    def update_menu(self) -> None:
        self.menu_updates += 1

    def stop(self) -> None:
        self.stopped = True


class FakePystray:
    Icon = FakeIcon
    Menu = FakeMenu
    MenuItem = FakeMenuItem


@pytest.fixture(autouse=True)
def _reset_fake_icon() -> None:
    FakeIcon.instances = []
    FakeIcon.run_error = None


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def make_app(
    jobs: list[int], *, lang: str = "en", clock: Clock | None = None
) -> tuple[tray.TrayApp, list[str]]:
    events: list[str] = []
    app = tray.TrayApp(
        FakePystray,
        open_page=lambda: events.append("open"),
        on_quit=lambda: events.append("quit"),
        active_jobs=lambda: jobs[0],
        lang=lang,
        clock=clock or Clock(),
    )
    return app, events


def started_app(
    jobs: list[int], *, lang: str = "en", clock: Clock | None = None
) -> tuple[tray.TrayApp, list[str], FakeIcon]:
    app, events = make_app(jobs, lang=lang, clock=clock)
    assert app.run() is True
    return app, events, FakeIcon.instances[-1]


# ---------------------------------------------------------------------------
# Language and texts
# ---------------------------------------------------------------------------


def test_all_languages_have_the_same_keys() -> None:
    english = set(tray._STRINGS["en"])
    for lang, strings in tray._STRINGS.items():
        assert set(strings) == english, lang


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("pt_BR.UTF-8", "pt"),
        ("pt-PT", "pt"),
        ("es_ES.UTF-8", "es"),
        ("en_US.UTF-8", "en"),
        ("Portuguese_Brazil", "pt"),
        ("Spanish_Mexico", "es"),
    ],
)
def test_detect_language_from_environment(
    monkeypatch: pytest.MonkeyPatch, value: str, expected: str
) -> None:
    monkeypatch.setattr(tray, "_windows_ui_language", lambda: None)
    for variable in ("LC_ALL", "LC_MESSAGES", "LANGUAGE"):
        monkeypatch.delenv(variable, raising=False)
    monkeypatch.setenv("LANG", value)
    assert tray.detect_language() == expected


def test_detect_language_defaults_to_english(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tray, "_windows_ui_language", lambda: None)
    for variable in ("LC_ALL", "LC_MESSAGES", "LANG", "LANGUAGE"):
        monkeypatch.delenv(variable, raising=False)
    monkeypatch.setattr(tray.locale, "getlocale", lambda: ("fr_FR", "UTF-8"))
    assert tray.detect_language() == "en"


def test_windows_language_wins(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tray, "_windows_ui_language", lambda: "es")
    monkeypatch.setenv("LANG", "pt_BR.UTF-8")
    assert tray.detect_language() == "es"


def test_unknown_language_falls_back_to_english() -> None:
    assert tray.text("quit", "de") == "Quit"


def test_truncate_title() -> None:
    assert tray.truncate_title("  My   video ") == "My video"
    assert tray.truncate_title("") == "Local Encoder"
    long = tray.truncate_title("x" * 200)
    assert len(long) == tray.TITLE_MAX_CHARS
    assert long.endswith("…")


# ---------------------------------------------------------------------------
# Icon image
# ---------------------------------------------------------------------------


def test_icon_image_is_blue_square_with_white_triangle() -> None:
    image = tray.make_icon_image()
    assert image.size == (64, 64)
    assert image.mode == "RGBA"
    assert image.getpixel((0, 0))[3] == 0  # rounded, transparent corner
    red, green, blue, alpha = image.getpixel((10, 32))  # blue body
    assert (red, green, blue, alpha) == (0x4A, 0x7C, 0xFF, 255)
    assert image.getpixel((32, 32))[:3] == (255, 255, 255)  # play triangle


# ---------------------------------------------------------------------------
# Menu, quit confirmation, notifications
# ---------------------------------------------------------------------------


def test_menu_has_open_default_and_dynamic_quit() -> None:
    jobs = [0]
    app, events = make_app(jobs)
    menu = app.build_menu()
    open_item, separator, quit_item = menu.items
    assert open_item.text == "Open Local Encoder"
    assert open_item.default is True
    assert separator is FakeMenu.SEPARATOR
    assert quit_item.text == "Quit"
    jobs[0] = 1
    assert quit_item.text == "Quit (1 video in progress)"
    jobs[0] = 2
    assert quit_item.text == "Quit (2 videos in progress)"
    open_item.action(None, None)
    assert events == ["open"]


def test_quit_label_in_portuguese_and_spanish() -> None:
    assert make_app([3], lang="pt")[0].quit_label() == "Sair (3 vídeos em andamento)"
    assert make_app([1], lang="es")[0].quit_label() == "Salir (1 video en curso)"


def test_quit_without_jobs_stops_immediately() -> None:
    app, events, icon = started_app([0])
    app._quit_clicked(icon, None)
    assert events == ["quit"]
    assert icon.stopped
    assert icon.notifications == []


def test_quit_with_jobs_needs_a_second_click_within_15_seconds() -> None:
    clock = Clock()
    app, events, icon = started_app([2], clock=clock)

    app._quit_clicked(icon, None)
    assert events == []
    assert not icon.stopped
    assert icon.notifications == [
        (
            "2 videos are still being processed. Choose Quit again within 15 seconds to stop them.",
            "Local Encoder",
        )
    ]

    clock.now += 10
    app._quit_clicked(icon, None)
    assert events == ["quit"]
    assert icon.stopped


def test_quit_confirmation_expires() -> None:
    clock = Clock()
    app, events, icon = started_app([1], clock=clock)
    app._quit_clicked(icon, None)
    clock.now += 16
    app._quit_clicked(icon, None)  # too late: warns again
    assert events == []
    assert len(icon.notifications) == 2
    assert icon.notifications[0][0].startswith("1 video is still being processed.")
    clock.now += 1
    app._quit_clicked(icon, None)
    assert events == ["quit"]


def test_broken_job_counter_does_not_block_quit() -> None:
    def boom() -> int:
        raise RuntimeError("server gone")

    app = tray.TrayApp(
        FakePystray, open_page=lambda: None, on_quit=lambda: None, active_jobs=boom, lang="en"
    )
    assert app.quit_label() == "Quit"
    assert app.request_quit() is True


def test_notify_done_and_error() -> None:
    app, _events, icon = started_app([0])
    app.notify("done", "My trip")
    app.notify("error", "Broken " + "y" * 100)
    app.notify("progress", "ignored")
    assert icon.notifications[0] == (
        "“My trip” was published on your site.",
        "Local Encoder",
    )
    message = icon.notifications[1][0]
    assert message.startswith("“Broken yyy")
    assert "…” could not be sent. Open Local Encoder" in message
    assert len(icon.notifications) == 2


def test_notify_in_portuguese() -> None:
    app, _events, icon = started_app([0], lang="pt")
    app.notify("done", "Viagem")
    assert icon.notifications[0][0] == "“Viagem” foi publicado no seu site."


def test_notify_before_icon_and_notify_errors_never_raise() -> None:
    app, _events = make_app([0])
    app.notify("done", "x")  # no icon yet

    app, _events, icon = started_app([0])

    def failing_notify(message: str, title: str) -> None:
        raise OSError("no notification area")

    icon.notify = failing_notify  # type: ignore[method-assign]
    app.notify("error", "x")


# ---------------------------------------------------------------------------
# Running
# ---------------------------------------------------------------------------


def test_run_creates_icon_and_setup_shows_it() -> None:
    _app, _events, icon = started_app([0])
    assert icon.title == "Local Encoder"
    assert icon.image.size == (64, 64)

    icon.setup(icon)  # the loop has ended (run() returned), so setup returns at once
    assert icon.visible is True


def test_setup_refreshes_menu_when_job_count_changes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tray, "_MENU_REFRESH_SECONDS", 0.01)
    jobs = [0]
    app, _events, icon = started_app(jobs)
    app._stopping.clear()
    worker = threading.Thread(target=icon.setup, args=(icon,))
    worker.start()
    jobs[0] = 3
    pause = threading.Event()
    for _ in range(300):
        if icon.menu_updates:
            break
        pause.wait(0.01)
    app._stopping.set()
    worker.join(timeout=3)
    assert icon.menu_updates >= 1


def test_run_returns_false_when_icon_fails() -> None:
    FakeIcon.run_error = RuntimeError("no system tray")
    app, _events = make_app([0])
    assert app.run() is False
    app.notify("done", "x")  # no icon: silently ignored


def test_load_pystray_returns_none_when_import_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    import builtins

    real_import = builtins.__import__

    def fake_import(name: str, *args: Any, **kwargs: Any) -> Any:
        if name == "pystray":
            raise RuntimeError("Can't connect to display")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    assert tray.load_pystray() is None


# ---------------------------------------------------------------------------
# Helpers for serve
# ---------------------------------------------------------------------------


class FakeServer:
    def __init__(self, started: bool = False) -> None:
        self.started = started


def test_wait_until_started() -> None:
    assert tray.wait_until_started(FakeServer(started=True), None, timeout=1) is True
    assert tray.wait_until_started(FakeServer(), None, timeout=0.05) is False

    dead = threading.Thread(target=lambda: None)
    dead.start()
    dead.join()
    assert tray.wait_until_started(FakeServer(), dead, timeout=5) is False


def test_server_hooks_fall_back_when_server_lacks_them(monkeypatch: pytest.MonkeyPatch) -> None:
    from local_encoder import server

    monkeypatch.delattr(server, "active_job_count", raising=False)
    monkeypatch.delattr(server, "set_notifier", raising=False)
    active, set_notifier = tray.server_hooks()
    assert active() == 0
    set_notifier(None)


def test_server_hooks_use_server_functions(monkeypatch: pytest.MonkeyPatch) -> None:
    from local_encoder import server

    registered: list[Any] = []
    monkeypatch.setattr(server, "active_job_count", lambda: 4, raising=False)
    monkeypatch.setattr(server, "set_notifier", registered.append, raising=False)
    active, set_notifier = tray.server_hooks()
    assert active() == 4
    set_notifier(None)
    assert registered == [None]
