from pathlib import Path

import pytest
from textual.command import CommandPalette
from textual.widgets import Input, ListView, RadioButton, Static

from audiobookshelf_sync.api import (
    BookSearchResult,
    BookSort,
    BrowseEntry,
    BrowseMode,
    BrowsePage,
)
from audiobookshelf_sync.config import AppConfig, ConfigFile
from audiobookshelf_sync.queue import (
    QueueItem,
    QueueStatus,
)
from audiobookshelf_sync.tui import EntryItem, ResultItem, SearchQueueApp, SortModal


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
    client: object, *, page: int, limit: int, sort: BookSort, descending: bool
) -> BrowsePage[BookSearchResult]:
    assert page == 0
    assert limit == 50
    assert sort == BookSort.ADDED_AT
    assert descending
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
    client: object, *, page: int, limit: int, sort: BookSort, descending: bool
) -> BrowsePage[BookSearchResult]:
    assert limit == 50
    assert sort == BookSort.ADDED_AT
    assert descending
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


def varied_books() -> list[BookSearchResult]:
    return [
        BookSearchResult(
            "older",
            "library-1",
            "Books",
            "Zulu",
            "Ada Alpha",
            None,
            None,
            "Alpha, Ada",
            100,
            2000,
        ),
        BookSearchResult(
            "newer",
            "library-1",
            "Books",
            "Alpha",
            "Zoe Zeta",
            None,
            None,
            "Zeta, Zoe",
            200,
            2020,
        ),
    ]


async def fake_sorted_books(
    client: object, *, page: int, limit: int, sort: BookSort, descending: bool
) -> BrowsePage[BookSearchResult]:
    from audiobookshelf_sync.api import sort_books

    assert page == 0
    assert limit == 50
    return BrowsePage(
        total=2, items=sort_books(varied_books(), sort=sort, descending=descending)
    )


async def fake_sorted_search(
    client: object, *, query: str, limit: int
) -> list[BookSearchResult]:
    assert query == "book"
    return varied_books()


async def fake_varied_entry_books(
    client: object, *, entry: BrowseEntry
) -> list[BookSearchResult]:
    assert entry.id == "author-1"
    return varied_books()


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

    queue = ConfigFile.load(queue_path)
    assert len(queue.items) == 1
    assert queue.items[0].id == "book-1"


@pytest.mark.anyio
async def test_search_result_already_in_queue_is_marked_selected(
    tmp_path: Path,
) -> None:
    queue_path = tmp_path / "audiobookshelf-sync.json"
    config = ConfigFile.load(queue_path)
    config.add_pending_item(
        item_id="book-1",
        library_id="library-1",
        title="Dune",
        author="Frank Herbert",
    )
    config.save(queue_path)
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
@pytest.mark.parametrize(
    ("remaining_ids", "expected_index"),
    [
        (["book-0", "book-1", "book-2"], 1),
        (["book-1", "book-2", "book-0"], 0),
        (["book-0", "book-2"], 0),
        (["book-2"], 0),
        ([], None),
    ],
)
async def test_refresh_queue_preserves_selection_or_selects_previous_row(
    tmp_path: Path, remaining_ids: list[str], expected_index: int | None
) -> None:
    config_path = tmp_path / "audiobookshelf-sync.json"
    config = ConfigFile.load(config_path)
    for index in range(3):
        config.add_pending_item(
            item_id=f"book-{index}",
            library_id="library-1",
            title=f"Book {index}",
            author="Author",
        )
    config.save(config_path)
    app = SearchQueueApp(
        client=object(),
        queue_path=config_path,
        limit=25,
        list_books_func=fake_list_books,
    )
    app.config = AppConfig(config=config, config_path=config_path)

    async with app.run_test() as pilot:
        queue_list = app.query_one("#queue", ListView)
        queue_list.index = 1
        await pilot.pause()
        items = {item.id: item for item in app.config.config.items}
        app.config.config.items = [items[item_id] for item_id in remaining_ids]
        await app.refresh_queue()
        await pilot.pause()
        assert queue_list.index == expected_index


@pytest.mark.anyio
async def test_pressing_d_on_queue_item_removes_it_and_refreshes_result_marker(
    tmp_path: Path,
) -> None:
    queue_path = tmp_path / "audiobookshelf-sync.json"
    config = ConfigFile.load(queue_path)
    config.add_pending_item(
        item_id="book-1",
        library_id="library-1",
        title="Dune",
        author="Frank Herbert",
    )
    config.save(queue_path)
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

    queue = ConfigFile.load(queue_path)
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
    item.mark_done(output_dir=Path("downloads/Dune"))
    item.error = "old error"
    queue = ConfigFile.load(queue_path)
    queue.items.append(item)
    queue.save(queue_path)
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

    queue = ConfigFile.load(queue_path)
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
    queue = ConfigFile.load(queue_path)
    queue.add_pending_item(
        item_id="book-1",
        library_id="library-1",
        title="Dune",
        author="Frank Herbert",
    )
    queue.save(queue_path)
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
        assert ConfigFile.load(queue_path).items == []
        await pilot.press("y")
        await pilot.pause()

    queue = ConfigFile.load(queue_path)
    assert [item.id for item in queue.items] == ["book-1", "book-2"]


@pytest.mark.anyio
async def test_sort_modal_applies_and_cancels_from_search_input_and_results(
    tmp_path: Path,
) -> None:
    app = SearchQueueApp(
        client=object(),
        queue_path=tmp_path / "queue.json",
        limit=25,
        list_books_func=fake_sorted_books,
    )
    async with app.run_test() as pilot:
        assert app.query_one("#query", Input).has_focus
        assert [book.id for book in app.results] == ["newer", "older"]
        await pilot.press("ctrl+s")
        await pilot.pause()
        assert isinstance(app.screen, SortModal)
        app.screen.query_one("#title", RadioButton).value = True
        await pilot.pause()
        assert app.screen.query_one("#ascending", RadioButton).value
        await pilot.press("enter")
        await pilot.pause()
        assert [book.id for book in app.results] == ["newer", "older"]
        assert app.query_one("#results-heading", Static).content == "Results · Title ↑"

        app.query_one("#results", ListView).focus()
        await pilot.press("ctrl+s")
        await pilot.pause()
        assert isinstance(app.screen, SortModal)
        app.screen.query_one("#descending", RadioButton).value = True
        await pilot.press("escape")
        await pilot.pause()
        assert [book.id for book in app.results] == ["newer", "older"]

        await pilot.press("ctrl+s")
        await pilot.pause()
        assert isinstance(app.screen, SortModal)
        app.screen.query_one("#descending", RadioButton).value = True
        await pilot.press("enter")
        await pilot.pause()
        assert [book.id for book in app.results] == ["older", "newer"]


@pytest.mark.anyio
async def test_sorting_search_results_does_not_replace_search_or_queue(
    tmp_path: Path,
) -> None:
    queue_path = tmp_path / "queue.json"
    app = SearchQueueApp(
        client=object(),
        queue_path=queue_path,
        limit=25,
        search_func=fake_sorted_search,
        list_books_func=fake_sorted_books,
    )
    async with app.run_test() as pilot:
        await pilot.press("b", "o", "o", "k", "enter")
        await pilot.pause()
        assert [book.id for book in app.results] == ["newer", "older"]
        await pilot.press("ctrl+s")
        await pilot.pause()
        assert isinstance(app.screen, SortModal)
        app.screen.query_one("#author_first_last", RadioButton).value = True
        await pilot.pause()
        assert app.screen.current_descending is False
        await pilot.press("enter")
        await pilot.pause()
        assert [book.id for book in app.results] == ["older", "newer"]
        assert app.query_one("#query", Input).value == "book"
    assert ConfigFile.load(queue_path).items == []


@pytest.mark.anyio
async def test_sort_choice_applies_when_opening_group_books(tmp_path: Path) -> None:
    app = SearchQueueApp(
        client=object(),
        queue_path=tmp_path / "queue.json",
        limit=25,
        list_books_func=fake_sorted_books,
        list_entries_func=fake_list_entries,
        list_entry_books_func=fake_varied_entry_books,
    )
    async with app.run_test() as pilot:
        await pilot.press("f4", "ctrl+s")
        await pilot.pause()
        assert isinstance(app.screen, SortModal)
        app.screen.query_one("#author_last_first", RadioButton).value = True
        await pilot.press("enter")
        await pilot.pause()
        results = app.query_one("#results", ListView)
        results.focus()
        results.index = 0
        await pilot.press("enter")
        await pilot.pause()
        assert [book.id for book in app.results] == ["older", "newer"]


@pytest.mark.anyio
@pytest.mark.parametrize("action", ["add", "bulk_add", "remove", "reset"])
async def test_tui_edits_preserve_external_queue_and_config_updates(
    tmp_path: Path, action: str
) -> None:
    path = tmp_path / "audiobookshelf-sync.json"
    config = ConfigFile()
    for item_id in ["keep", "edit", "removed"]:
        config.add_pending_item(item_id, "library-1", item_id, "Author")
    config.items[1].mark_synchronised()
    config.save(path)
    app = SearchQueueApp(
        client=object(), queue_path=path, limit=25, list_books_func=fake_list_books
    )
    async with app.run_test() as pilot:
        queue_list = app.query_one("#queue", ListView)
        queue_list.index = 1
        queue_list.focus()
        await pilot.pause()
        updated = ConfigFile.load(path)
        updated.items[0].mark_synchronised()
        updated.remove_item("removed")
        updated.add_pending_item("external", "library-1", "External", "Author")
        servers = ConfigFile.model_validate(
            {
                "servers": {"https://new.example": {"token": "test-token"}},
                "default_source": "https://new.example",
            }
        )
        updated.servers = servers.servers
        updated.default_source = servers.default_source
        updated.save(path)
        if action == "add":
            result = app.query_one("#results", ListView).children[0]
            assert isinstance(result, ResultItem)
            await app.add_result_item(result)
        elif action == "bulk_add":
            app.drilled_entry = BrowseEntry(
                id="author",
                mode=BrowseMode.AUTHORS,
                name="Author",
                library_id="library-1",
                library_name="Books",
                count=2,
            )
            app.bulk_confirmation_pending = True
            await app.action_confirm_bulk_add()
        elif action == "remove":
            await app.action_remove_queue_item()
        else:
            await app.action_reset_queue_item()
        await pilot.pause()
    saved = ConfigFile.load(path)
    keep = saved.find_item("keep")
    assert keep is not None
    assert keep.status == QueueStatus.SYNCHRONISED
    assert saved.find_item("external") is not None
    assert saved.find_item("removed") is None
    assert saved.servers == updated.servers
    assert saved.default_source == updated.default_source
    if action == "remove":
        assert saved.find_item("edit") is None
    elif action == "reset":
        edit = saved.find_item("edit")
        assert edit is not None
        assert edit.status == QueueStatus.PENDING
    else:
        assert saved.find_item("book-1") is not None


@pytest.mark.anyio
@pytest.mark.parametrize("status", [QueueStatus.DONE, QueueStatus.SYNCHRONISED])
async def test_palette_clears_only_selected_status_from_latest_queue(
    tmp_path: Path, status: QueueStatus
) -> None:
    path = tmp_path / "config.json"
    config = ConfigFile()
    for state in QueueStatus:
        item = config.add_pending_item(state.value, "library-1", state.value, "Author")
        item.status = state
    config.save(path)
    app = SearchQueueApp(
        client=object(), queue_path=path, limit=25, list_books_func=fake_list_books
    )
    local_file = tmp_path / "book.m4b"
    local_file.write_bytes(b"audio")
    async with app.run_test() as pilot:
        latest = ConfigFile.load(path)
        latest.add_pending_item(
            "book-1", "library-1", "Dune", "Frank Herbert"
        ).status = status
        latest.add_pending_item("external", "library-1", "External", "Author")
        latest.save(path)
        await pilot.press("ctrl+p")
        assert isinstance(app.screen, CommandPalette)
        await pilot.press(*f"Clear {status.value} items")
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        saved = ConfigFile.load(path)
        assert saved.find_item(status.value) is None
        assert saved.find_item("book-1") is None
        assert {item.id for item in saved.items} == {
            state.value for state in QueueStatus if state != status
        } | {"external"}
        assert len(app.query_one("#queue", ListView).children) == len(saved.items)
        assert app.status_message == f"Removed 2 {status.value} item(s) from the queue."
        result = app.query_one("#results", ListView).children[0]
        assert isinstance(result, ResultItem)
        assert result.display_text.startswith("[ ]")
    assert local_file.read_bytes() == b"audio"


@pytest.mark.anyio
async def test_clear_completed_items_is_blocked_during_sync(tmp_path: Path) -> None:
    path = tmp_path / "config.json"
    config = ConfigFile()
    config.add_pending_item("done", "library-1", "Book", "Author").status = QueueStatus.DONE
    config.save(path)
    app = SearchQueueApp(
        client=object(), queue_path=path, limit=25, list_books_func=fake_list_books
    )
    async with app.run_test():
        app.sync_running = True
        await app.action_clear_done()
        await app.action_clear_synchronised()
        assert ConfigFile.load(path).items == config.items
        assert not any(
            command.title.startswith("Clear ")
            for command in app.get_system_commands(app.screen)
        )
