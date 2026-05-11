from pathlib import Path

import pytest
from textual.widgets import ListView

from audiobookshelf_sync.api import BookSearchResult
from audiobookshelf_sync.queue import (
    QueueItem,
    QueueStatus,
    add_pending_item,
    load_queue,
    mark_done,
    save_queue,
)
from audiobookshelf_sync.tui import ResultItem, SearchQueueApp


async def fake_search(
    client: object, *, query: str, limit: int
) -> list[BookSearchResult]:
    assert query == "dune"
    assert limit == 25
    return [
        BookSearchResult(
            id="book-1",
            library_id="library-1",
            library_name="Books",
            title="Dune",
            author="Frank Herbert",
            duration=3600,
            size=1024,
        )
    ]


@pytest.mark.anyio
async def test_pressing_enter_on_search_result_adds_it_to_queue(tmp_path: Path) -> None:
    queue_path = tmp_path / "audiobookshelf-sync.json"
    app = SearchQueueApp(
        client=object(),
        queue_path=queue_path,
        limit=25,
        search_func=fake_search,
    )

    async with app.run_test() as pilot:
        await pilot.press("d", "u", "n", "e", "enter")
        await pilot.pause()
        results = app.query_one("#results", ListView)
        results.focus()
        await pilot.press("enter")
        await pilot.pause()

    queue = load_queue(queue_path)
    assert len(queue.items) == 1
    assert queue.items[0].id == "book-1"


@pytest.mark.anyio
async def test_search_result_already_in_queue_is_marked_selected(
    tmp_path: Path,
) -> None:
    queue_path = tmp_path / "audiobookshelf-sync.json"
    queue = load_queue(queue_path)
    add_pending_item(
        queue,
        item_id="book-1",
        library_id="library-1",
        title="Dune",
        author="Frank Herbert",
    )
    save_queue(queue_path, queue)
    app = SearchQueueApp(
        client=object(),
        queue_path=queue_path,
        limit=25,
        search_func=fake_search,
    )

    async with app.run_test() as pilot:
        await pilot.press("d", "u", "n", "e", "enter")
        await pilot.pause()
        result_list = app.query_one("#results", ListView)
        first_result = result_list.children[0]

    assert isinstance(first_result, ResultItem)
    assert (
        first_result.display_text
        == "[x] Dune - Frank Herbert - Books - 1h 00m - 1024 bytes"
    )


@pytest.mark.anyio
async def test_pressing_d_on_queue_item_removes_it_and_refreshes_result_marker(
    tmp_path: Path,
) -> None:
    queue_path = tmp_path / "audiobookshelf-sync.json"
    queue = load_queue(queue_path)
    add_pending_item(
        queue,
        item_id="book-1",
        library_id="library-1",
        title="Dune",
        author="Frank Herbert",
    )
    save_queue(queue_path, queue)
    app = SearchQueueApp(
        client=object(),
        queue_path=queue_path,
        limit=25,
        search_func=fake_search,
    )

    async with app.run_test() as pilot:
        await pilot.press("d", "u", "n", "e", "enter")
        await pilot.pause()
        queue_list = app.query_one("#queue", ListView)
        queue_list.index = 0
        queue_list.focus()
        await pilot.press("d")
        await pilot.pause()
        result_list = app.query_one("#results", ListView)
        first_result = result_list.children[0]

    queue = load_queue(queue_path)
    assert queue.items == []
    assert isinstance(first_result, ResultItem)
    assert (
        first_result.display_text
        == "[ ] Dune - Frank Herbert - Books - 1h 00m - 1024 bytes"
    )


@pytest.mark.anyio
async def test_pressing_r_on_queue_item_resets_it_to_pending(tmp_path: Path) -> None:
    queue_path = tmp_path / "audiobookshelf-sync.json"
    item = QueueItem(
        id="book-1",
        library_id="library-1",
        title="Dune",
        author="Frank Herbert",
        error="old error",
    )
    mark_done(item, output_dir=Path("downloads/Dune"))
    item.error = "old error"
    queue = load_queue(queue_path)
    queue.items.append(item)
    save_queue(queue_path, queue)
    app = SearchQueueApp(
        client=object(),
        queue_path=queue_path,
        limit=25,
        search_func=fake_search,
    )

    async with app.run_test() as pilot:
        queue_list = app.query_one("#queue", ListView)
        queue_list.index = 0
        queue_list.focus()
        await pilot.press("r")
        await pilot.pause()

    queue = load_queue(queue_path)
    assert len(queue.items) == 1
    assert queue.items[0].status == QueueStatus.PENDING
    assert queue.items[0].downloaded_at is None
    assert queue.items[0].output_dir is None
    assert queue.items[0].error is None
