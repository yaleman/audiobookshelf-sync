import asyncio
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

import pytest
from textual.command import CommandPalette
from textual.widgets import Button, RichLog

from audiobookshelf_sync.api import BookSearchResult, BrowseMode, BrowsePage
from audiobookshelf_sync.config import ConfigFile
from audiobookshelf_sync.queue import QueueStatus
from audiobookshelf_sync.sync_ui import OverwriteModal, SyncModal, SyncState
from audiobookshelf_sync.test import FakeClient
from audiobookshelf_sync.tui import SearchQueueApp


async def empty_books(*args: Any, **kwargs: Any) -> BrowsePage[BookSearchResult]:
    return BrowsePage(items=[], total=0)


@pytest.fixture
def sync_app(tmp_path: Path) -> SearchQueueApp:
    path = tmp_path / "config.json"
    config = ConfigFile.model_validate(
        {
            "servers": {
                "https://target.example": {
                    "token": "test-token",
                    "target_library": "Books",
                }
            },
            "default_target": "https://target.example",
        }
    )
    config.add_pending_item("book", "books", "Example", "Author")
    config.save(path)
    return SearchQueueApp(
        client=FakeClient(), queue_path=path, limit=25, list_books_func=empty_books
    )


def log_text(modal: SyncModal) -> str:
    return "\n".join(line.text for line in modal.query_one("#sync-log", RichLog).lines)


@pytest.mark.anyio
async def test_palette_sync_blocks_queue_actions_and_shows_live_progress(
    sync_app: SearchQueueApp, monkeypatch: pytest.MonkeyPatch
) -> None:
    started = asyncio.Event()
    release = asyncio.Event()
    target = FakeClient()
    monkeypatch.setattr(
        "audiobookshelf_sync.sync_ui.get_client", AsyncMock(return_value=target)
    )

    async def sync(**kwargs: Any) -> None:
        assert kwargs["source_client"] is sync_app.client
        assert kwargs["target_client"] is target
        assert kwargs["target_library"] == "Books"
        kwargs["reporter"]("Downloading file 1/2: track.m4b")
        kwargs["reporter"]("Prepared file 1/2: track.m4b")
        started.set()
        await release.wait()
        kwargs["reporter"]("Uploaded 2/2 file(s)")
        config = kwargs["app_config"]
        config.mark_synchronised(config.config.items)

    monkeypatch.setattr("audiobookshelf_sync.sync_ui.sync_items", sync)
    async with sync_app.run_test() as pilot:
        await pilot.press("ctrl+p")
        await pilot.pause()
        assert isinstance(sync_app.screen, CommandPalette)
        await pilot.press("s", "y", "n", "c")
        await pilot.pause()
        await pilot.press("enter")
        await asyncio.wait_for(started.wait(), 3)
        await pilot.pause()
        modal = sync_app.screen
        assert isinstance(modal, SyncModal)
        assert "Downloading file 1/2: track.m4b" in log_text(modal)
        assert modal.query_one("#sync-close", Button).disabled
        await pilot.press("escape", "q", "f2", "r", "d", "ctrl+p")
        await pilot.pause()
        assert sync_app.screen is modal
        assert sync_app.sync_running
        assert sync_app.mode == BrowseMode.BOOKS
        assert (
            ConfigFile.load(sync_app.queue_path).items[0].status == QueueStatus.PENDING
        )
        release.set()
        await pilot.pause()
        assert modal.state == SyncState.FINISHED
        assert "Uploaded 2/2 file(s)" in log_text(modal)
        assert not modal.query_one("#sync-close", Button).disabled
        await pilot.click("#sync-close")
        await pilot.pause()
        assert not sync_app.sync_running
        assert not isinstance(sync_app.screen, SyncModal)
        assert sync_app.config.config.items[0].status == QueueStatus.SYNCHRONISED


@pytest.mark.anyio
@pytest.mark.parametrize("confirm", [False, True])
async def test_sync_overwrite_confirmation_stays_in_the_modal(
    sync_app: SearchQueueApp, monkeypatch: pytest.MonkeyPatch, confirm: bool
) -> None:
    monkeypatch.setattr(
        "audiobookshelf_sync.sync_ui.get_client", AsyncMock(return_value=FakeClient())
    )
    answers: list[bool] = []

    async def sync(**kwargs: Any) -> None:
        answers.append(
            await kwargs["confirm_overwrite"](
                "Overwrite target metadata for 'Example'?"
            )
        )

    monkeypatch.setattr("audiobookshelf_sync.sync_ui.sync_items", sync)
    async with sync_app.run_test() as pilot:
        sync_app.action_sync()
        await pilot.pause()
        assert isinstance(sync_app.screen, OverwriteModal)
        assert sync_app.sync_running
        if confirm:
            await pilot.click("#confirm-overwrite")
        else:
            await pilot.press("escape")
        await pilot.pause()
        assert answers == [confirm]
        assert isinstance(sync_app.screen, SyncModal)
        assert sync_app.screen.state == SyncState.FINISHED
        await pilot.press("escape")
        await pilot.pause()
        assert not sync_app.sync_running


@pytest.mark.anyio
@pytest.mark.parametrize("failure", ["config", "network"])
async def test_sync_errors_are_displayed_and_the_dialog_can_be_closed(
    sync_app: SearchQueueApp, monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    if failure == "config":
        config = ConfigFile.load(sync_app.queue_path)
        config.default_target = None
        config.save(sync_app.queue_path)
    else:
        monkeypatch.setattr(
            "audiobookshelf_sync.sync_ui.get_client",
            AsyncMock(side_effect=RuntimeError("connection failed")),
        )
    async with sync_app.run_test() as pilot:
        sync_app.action_sync()
        await pilot.pause()
        modal = sync_app.screen
        assert isinstance(modal, SyncModal)
        assert modal.state == SyncState.FAILED
        expected = "No default target" if failure == "config" else "connection failed"
        assert expected in log_text(modal)
        assert not modal.query_one("#sync-close", Button).disabled
        await pilot.press("escape")
        await pilot.pause()
        assert not sync_app.sync_running
