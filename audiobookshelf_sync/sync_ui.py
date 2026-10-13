from __future__ import annotations

from enum import StrEnum
from logging import getLogger

import aiohttp
from textual import work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Label, RichLog, Static

from .api import AudiobookshelfClient, get_client, sync_items
from .config import AppConfig


class SyncState(StrEnum):
    RUNNING = "running"
    FINISHED = "finished"
    FAILED = "failed"


class OverwriteModal(ModalScreen[bool]):
    CSS = """
    OverwriteModal { align: center middle; }
    #overwrite-dialog {
        width: 64; height: auto; padding: 1 2;
        background: $surface; border: solid $primary;
    }
    #overwrite-actions { height: auto; align-horizontal: right; }
    """
    BINDINGS = [Binding("escape", "skip", "Skip")]

    def __init__(self, prompt: str) -> None:
        super().__init__()
        self.prompt = prompt

    def compose(self) -> ComposeResult:
        with Vertical(id="overwrite-dialog"):
            yield Label(self.prompt, markup=False)
            with Horizontal(id="overwrite-actions"):
                yield Button("Skip", id="skip-overwrite")
                yield Button("Overwrite", variant="warning", id="confirm-overwrite")

    def action_skip(self) -> None:
        self.dismiss(False)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        self.dismiss(event.button.id == "confirm-overwrite")


class SyncModal(ModalScreen[None]):
    CSS = """
    SyncModal { align: center middle; }
    #sync-dialog {
        width: 90%; max-width: 100; height: 80%; padding: 1 2;
        background: $surface; border: solid $primary;
    }
    #sync-log { height: 1fr; margin: 1 0; }
    #sync-status { height: auto; }
    #sync-close { align-horizontal: right; }
    """
    BINDINGS = [Binding("escape", "close", "Close")]

    def __init__(self, client: AudiobookshelfClient, config: AppConfig) -> None:
        super().__init__()
        self.client = client
        self.config = config
        self.state = SyncState.RUNNING

    def compose(self) -> ComposeResult:
        with Vertical(id="sync-dialog"):
            yield Label("Sync")
            yield Static("Starting sync…", id="sync-status", markup=False)
            yield RichLog(id="sync-log", wrap=True, markup=False)
            yield Button("Close", id="sync-close", disabled=True)

    def on_mount(self) -> None:
        self.run_sync()

    def report(self, message: str) -> None:
        self.query_one("#sync-status", Static).update(message)
        self.query_one("#sync-log", RichLog).write(message)

    async def confirm_overwrite(self, prompt: str) -> bool:
        return await self.app.push_screen_wait(OverwriteModal(prompt))

    @work
    async def run_sync(self) -> None:
        try:
            target = self.config.default_target()
            if target is None:
                raise ValueError("No default target server configured.")
            server = self.config.config.servers[target]
            if server.target_library is None:
                raise ValueError("No target library configured for the target server.")
            self.report(f"Connecting to target: {target}")
            async with aiohttp.ClientSession() as session:
                client = await get_client(session, server, getLogger(__name__))
                await sync_items(
                    source_client=self.client,
                    target_client=client,
                    target_library=server.target_library,
                    app_config=self.config,
                    reporter=self.report,
                    confirm_overwrite=self.confirm_overwrite,
                )
            self.state = SyncState.FINISHED
            self.report("Sync finished.")
        except Exception as error:  # noqa: BLE001 - keep sync errors in the dialog.
            self.state = SyncState.FAILED
            self.report(f"Sync failed: {error}")
        self.query_one("#sync-close", Button).disabled = False
        self.query_one("#sync-close", Button).focus()

    def action_close(self) -> None:
        if self.state != SyncState.RUNNING:
            self.dismiss(None)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "sync-close":
            event.stop()
            self.action_close()
