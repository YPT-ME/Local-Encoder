"""Rich-based progress reporting for all pipeline stages."""

from __future__ import annotations

from rich.console import Console
from rich.progress import (
    BarColumn,
    DownloadColumn,
    Progress,
    SpinnerColumn,
    TaskID,
    TextColumn,
    TimeElapsedColumn,
    TimeRemainingColumn,
    TransferSpeedColumn,
)

console = Console(stderr=True)


class ProgressReporter:
    """Wraps Rich Progress to report download, encode, and upload stages."""

    def __init__(self, verbose: bool = False) -> None:
        self._verbose = verbose
        self._progress = Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}", justify="left"),
            BarColumn(bar_width=None),
            DownloadColumn(),
            TransferSpeedColumn(),
            TimeElapsedColumn(),
            TimeRemainingColumn(),
            console=console,
            transient=False,
            expand=True,
        )
        self._task: TaskID | None = None

    # ------------------------------------------------------------------
    # Context manager
    # ------------------------------------------------------------------

    def __enter__(self) -> ProgressReporter:
        self._progress.start()
        return self

    def __exit__(self, *args: object) -> None:
        self._progress.stop()

    # ------------------------------------------------------------------
    # Stage helpers
    # ------------------------------------------------------------------

    def _new_task(self, description: str, total: int | None = None) -> None:
        if self._task is not None:
            self._progress.remove_task(self._task)
        self._task = self._progress.add_task(description, total=total)

    # Download -----------------------------------------------------------

    def begin_download(self, url: str) -> None:
        self._new_task("[cyan]Downloading", total=None)
        if self._verbose:
            console.log(f"[dim]URL:[/dim] {url}")

    def on_download(self, status: str, downloaded: int, total: int) -> None:
        if self._task is None:
            return
        if status == "finished":
            self._progress.update(
                self._task,
                completed=total or downloaded,
                description="[green]Downloaded ",
            )
        elif status == "downloading":
            self._progress.update(
                self._task,
                total=total or None,
                completed=downloaded,
            )

    # Encode -------------------------------------------------------------

    def begin_encode(self, label: str, total_seconds: int = 100) -> None:
        self._new_task(f"[yellow]{label}", total=total_seconds)

    def on_encode(self, current_secs: int, total_secs: int) -> None:
        if self._task is None or total_secs == 0:
            return
        self._progress.update(self._task, completed=current_secs)

    # Upload -------------------------------------------------------------

    def begin_upload(self, file_size: int) -> None:
        self._new_task("[magenta]Uploading  ", total=file_size)

    def on_upload(self, status: str, uploaded: int, total: int) -> None:
        if self._task is None:
            return
        self._progress.update(self._task, total=total or None, completed=uploaded)

    # Messaging ----------------------------------------------------------

    def info(self, msg: str) -> None:
        console.print(f"  [blue]›[/blue] {msg}")

    def success(self, msg: str) -> None:
        console.print(f"  [bold green]✓[/bold green] {msg}")

    def warning(self, msg: str) -> None:
        console.print(f"  [bold yellow]⚠[/bold yellow] {msg}")

    def error(self, msg: str) -> None:
        console.print(f"  [bold red]✗[/bold red] {msg}")
