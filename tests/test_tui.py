from pathlib import Path

import pytest
from textual.widgets import ListView

from audiobookshelf_sync.api import (
    BookSearchResult,
    BrowseEntry,
    BrowseMode,
    BrowsePage,
)
from audiobookshelf_sync.queue import (
    QueueItem,
    QueueStatus,
    add_pending_item,
    load_queue,
    mark_done,
    save_queue,
)
from audiobookshelf_sync.tui import EntryItem, ResultItem, SearchQueueApp


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


async def fake_list_books(
    client: object, *, page: int, limit: int
) -> BrowsePage[BookSearchResult]:
    assert page == 0
    assert limit == 50
    return BrowsePage(
        total=2,
        items=[
            BookSearchResult(
                id="book-1",
                library_id="library-1",
                library_name="Books",
                title="Dune",
                author="Frank Herbert",
                duration=3600,
                size=1024,
            )
        ],
    )


async def fake_list_more_books(
    client: object, *, page: int, limit: int
) -> BrowsePage[BookSearchResult]:
    assert limit == 50
    items = [
        BookSearchResult(
            id=f"book-{page + 1}",
            library_id="library-1",
            library_name="Books",
            title=f"Dune {page + 1}",
            author="Frank Herbert",
            duration=None,
            size=None,
        )
    ]
    return BrowsePage(total=2, items=items)


async def fake_list_entries(
    client: object, *, mode: BrowseMode, page: int, limit: int
) -> BrowsePage[BrowseEntry]:
    assert page == 0
    assert limit == 50
    assert mode == BrowseMode.AUTHORS
    return BrowsePage(
        total=2,
        items=[
            BrowseEntry(
                mode=BrowseMode.AUTHORS,
                id="author-1",
                name="Frank Herbert",
                library_id="library-1",
                library_name="Books",
                count=2,
            ),
            BrowseEntry(
                mode=BrowseMode.AUTHORS,
                id="author-2",
                name="Isaac Asimov",
                library_id="library-1",
                library_name="Books",
                count=1,
            ),
        ],
    )


async def fake_paged_author_entries(
    client: object, *, mode: BrowseMode, page: int, limit: int
) -> BrowsePage[BrowseEntry]:
    assert limit == 50
    assert mode == BrowseMode.AUTHORS
    pages = [
        [
            BrowseEntry(
                mode=BrowseMode.AUTHORS,
                id="author-1",
                name="Frank Herbert",
                library_id="library-1",
                library_name="Books",
                count=2,
            )
        ],
        [
            BrowseEntry(
                mode=BrowseMode.AUTHORS,
                id="author-2",
                name="Isaac Asimov",
                library_id="library-1",
                library_name="Books",
                count=1,
            )
        ],
    ]
    return BrowsePage(total=2, items=pages[page] if page < len(pages) else [])


async def fake_list_entry_books(
    client: object, *, entry: BrowseEntry
) -> list[BookSearchResult]:
    assert entry.id == "author-1"
    return [
        BookSearchResult(
            id="book-1",
            library_id="library-1",
            library_name="Books",
            title="Dune",
            author="Frank Herbert",
            duration=3600,
            size=1024,
        ),
        BookSearchResult(
            id="book-2",
            library_id="library-1",
            library_name="Books",
            title="Dune Messiah",
            author="Frank Herbert",
            duration=7200,
            size=2048,
        ),
    ]


@pytest.mark.anyio
async def test_pressing_enter_on_search_result_adds_it_to_queue(tmp_path: Path) -> None:
    queue_path = tmp_path / "audiobookshelf-sync.json"
    app = SearchQueueApp(
        client=object(),
        queue_path=queue_path,
        limit=25,
        search_func=fake_search,
        list_books_func=fake_list_books,
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
        list_books_func=fake_list_books,
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
        list_books_func=fake_list_books,
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
        list_books_func=fake_list_books,
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


@pytest.mark.anyio
async def test_books_mode_loads_empty_browse_list_on_mount(tmp_path: Path) -> None:
    app = SearchQueueApp(
        client=object(),
        queue_path=tmp_path / "audiobookshelf-sync.json",
        limit=25,
        search_func=fake_search,
        list_books_func=fake_list_books,
    )

    async with app.run_test():
        result_list = app.query_one("#results", ListView)
        first_result = result_list.children[0]

    assert isinstance(first_result, ResultItem)
    assert (
        first_result.display_text
        == "[ ] Dune - Frank Herbert - Books - 1h 00m - 1024 bytes"
    )
    assert app.status_message == "Showing 1 of 2 books."


@pytest.mark.anyio
async def test_books_mode_lazy_loads_more_results(tmp_path: Path) -> None:
    app = SearchQueueApp(
        client=object(),
        queue_path=tmp_path / "audiobookshelf-sync.json",
        limit=25,
        search_func=fake_search,
        list_books_func=fake_list_more_books,
    )

    async with app.run_test() as pilot:
        await pilot.pause()
        await app.load_more_if_needed()
        await pilot.pause()
        result_list = app.query_one("#results", ListView)
        row_count = len(result_list.children)

    assert row_count == 2
    assert app.status_message == "Showing 2 of 2 books."


@pytest.mark.anyio
async def test_author_mode_filters_entries_locally(tmp_path: Path) -> None:
    app = SearchQueueApp(
        client=object(),
        queue_path=tmp_path / "audiobookshelf-sync.json",
        limit=25,
        search_func=fake_search,
        list_books_func=fake_list_books,
        list_entries_func=fake_list_entries,
        list_entry_books_func=fake_list_entry_books,
    )

    async with app.run_test() as pilot:
        await pilot.press("f4")
        await pilot.pause()
        await pilot.press("i", "s", "a")
        await pilot.pause()
        result_list = app.query_one("#results", ListView)
        entry_item = result_list.children[0]

    assert app.mode == BrowseMode.AUTHORS
    assert isinstance(entry_item, EntryItem)
    assert entry_item.display_text == "Isaac Asimov - Books - 1 book"
    assert app.status_message == "Showing 1 of 2 authors."


@pytest.mark.anyio
async def test_author_mode_filter_loads_unloaded_entries(tmp_path: Path) -> None:
    app = SearchQueueApp(
        client=object(),
        queue_path=tmp_path / "audiobookshelf-sync.json",
        limit=25,
        search_func=fake_search,
        list_books_func=fake_list_books,
        list_entries_func=fake_paged_author_entries,
        list_entry_books_func=fake_list_entry_books,
    )

    async with app.run_test() as pilot:
        await pilot.press("f4")
        await pilot.pause()
        await pilot.press("i", "s", "a")
        await pilot.pause()
        result_list = app.query_one("#results", ListView)
        entry_item = result_list.children[0]

    assert isinstance(entry_item, EntryItem)
    assert entry_item.display_text == "Isaac Asimov - Books - 1 book"
    assert app.status_message == "Showing 1 of 2 authors."


@pytest.mark.anyio
async def test_removing_queue_item_preserves_group_browse_results(
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
        list_books_func=fake_list_books,
        list_entries_func=fake_list_entries,
        list_entry_books_func=fake_list_entry_books,
    )

    async with app.run_test() as pilot:
        await pilot.press("f4")
        await pilot.pause()
        queue_list = app.query_one("#queue", ListView)
        queue_list.focus()
        queue_list.index = 0
        await pilot.press("d")
        await pilot.pause()
        result_list = app.query_one("#results", ListView)
        first_entry = result_list.children[0]

    assert isinstance(first_entry, EntryItem)
    assert first_entry.display_text == "Frank Herbert - Books - 2 books"


@pytest.mark.anyio
async def test_selecting_author_drills_into_books_and_escape_returns(
    tmp_path: Path,
) -> None:
    app = SearchQueueApp(
        client=object(),
        queue_path=tmp_path / "audiobookshelf-sync.json",
        limit=25,
        search_func=fake_search,
        list_books_func=fake_list_books,
        list_entries_func=fake_list_entries,
        list_entry_books_func=fake_list_entry_books,
    )

    async with app.run_test() as pilot:
        await pilot.press("f4")
        await pilot.pause()
        result_list = app.query_one("#results", ListView)
        result_list.focus()
        result_list.index = 0
        await pilot.press("enter")
        await pilot.pause()
        first_book = result_list.children[0]
        await pilot.press("escape")
        await pilot.pause()
        first_entry = result_list.children[0]

    assert isinstance(first_book, ResultItem)
    assert first_book.display_text.startswith("[ ] Dune - Frank Herbert")
    assert isinstance(first_entry, EntryItem)
    assert first_entry.display_text == "Frank Herbert - Books - 2 books"


@pytest.mark.anyio
async def test_bulk_add_requires_confirmation_and_queues_group_books(
    tmp_path: Path,
) -> None:
    queue_path = tmp_path / "audiobookshelf-sync.json"
    app = SearchQueueApp(
        client=object(),
        queue_path=queue_path,
        limit=25,
        search_func=fake_search,
        list_books_func=fake_list_books,
        list_entries_func=fake_list_entries,
        list_entry_books_func=fake_list_entry_books,
    )

    async with app.run_test() as pilot:
        await pilot.press("f4")
        await pilot.pause()
        result_list = app.query_one("#results", ListView)
        result_list.focus()
        result_list.index = 0
        await pilot.press("enter")
        await pilot.pause()
        await pilot.press("b")
        await pilot.pause()
        assert load_queue(queue_path).items == []
        await pilot.press("y")
        await pilot.pause()

    queue = load_queue(queue_path)
    assert [item.id for item in queue.items] == ["book-1", "book-2"]
