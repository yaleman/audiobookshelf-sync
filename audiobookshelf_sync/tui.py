from __future__ import annotations

from collections.abc import Awaitable, Callable
from pathlib import Path

from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Footer, Header, Input, Label, ListItem, ListView, Static

from audiobookshelf_sync.api import (
    BookSearchResult,
    BrowseEntry,
    BrowseMode,
    BrowsePage,
    list_books,
    list_books_for_entry,
    list_browse_entries,
    search_books,
)
from audiobookshelf_sync.queue import (
    QUEUE_FILE,
    QueueItem,
    add_pending_item,
    load_queue,
    remove_item,
    reset_item,
    save_queue,
)

BROWSE_LIMIT = 50


class ResultItem(ListItem):
    def __init__(self, result: BookSearchResult, *, selected: bool = False) -> None:
        self.display_text = format_result(result, selected=selected)
        super().__init__(Label(self.display_text))
        self.result = result


class EntryItem(ListItem):
    def __init__(self, entry: BrowseEntry) -> None:
        self.entry = entry
        self.display_text = format_entry(entry)
        super().__init__(Label(self.display_text))


class QueueListItem(ListItem):
    def __init__(self, item: QueueItem) -> None:
        self.item_id = item.id
        self.title = item.title
        super().__init__(Label(f"{item.status}: {item.title} - {item.author}"))


class SearchQueueApp(App[None]):
    CSS = """
    Screen {
        layout: vertical;
    }

    #body {
        height: 1fr;
    }

    #results, #queue {
        width: 1fr;
        height: 1fr;
        border: solid $primary;
    }

    #status {
        height: 1;
    }
    """

    BINDINGS = [
        ("f1", "switch_books", "Books"),
        ("f2", "switch_series", "Series"),
        ("f3", "switch_collections", "Collections"),
        ("f4", "switch_authors", "Authors"),
        ("f5", "switch_narrators", "Narrators"),
        ("a", "add_selected", "Add selected"),
        ("b", "bulk_add", "Add group"),
        ("y", "confirm_bulk_add", "Confirm"),
        ("n", "cancel_bulk_add", "Cancel"),
        ("d", "remove_queue_item", "Remove"),
        ("delete", "remove_queue_item", "Remove"),
        ("r", "reset_queue_item", "Reset"),
        ("escape", "go_back", "Back"),
        ("backspace", "go_back", "Back"),
        ("q", "quit", "Quit"),
    ]

    def __init__(
        self,
        *,
        client: object,
        queue_path: Path = QUEUE_FILE,
        limit: int,
        search_func: Callable[..., Awaitable[list[BookSearchResult]]] = search_books,
        list_books_func: Callable[
            ..., Awaitable[BrowsePage[BookSearchResult]]
        ] = list_books,
        list_entries_func: Callable[
            ..., Awaitable[BrowsePage[BrowseEntry]]
        ] = list_browse_entries,
        list_entry_books_func: Callable[
            ..., Awaitable[list[BookSearchResult]]
        ] = list_books_for_entry,
    ) -> None:
        super().__init__()
        self.client = client
        self.queue_path = queue_path
        self.limit = limit
        self.search_func = search_func
        self.list_books_func = list_books_func
        self.list_entries_func = list_entries_func
        self.list_entry_books_func = list_entry_books_func
        self.mode = BrowseMode.BOOKS
        self.results: list[BookSearchResult] = []
        self.entries: list[BrowseEntry] = []
        self.filtered_entries: list[BrowseEntry] = []
        self.current_page = 0
        self.total = 0
        self.drilled_entry: BrowseEntry | None = None
        self.bulk_confirmation_pending = False
        self.status_message = ""

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static("", id="mode")
        yield Input(placeholder="Search books", id="query")
        with Horizontal(id="body"):
            with Vertical():
                yield Static("Results")
                yield ListView(id="results")
            with Vertical():
                yield Static("Queue")
                yield ListView(id="queue")
        yield Static("", id="status")
        yield Footer()

    async def on_mount(self) -> None:
        await self.refresh_queue()
        self.update_mode_label()
        await self.load_mode_page(reset=True)
        self.query_one("#query", Input).focus()

    async def action_switch_books(self) -> None:
        await self.switch_browse_mode(BrowseMode.BOOKS)

    async def action_switch_series(self) -> None:
        await self.switch_browse_mode(BrowseMode.SERIES)

    async def action_switch_collections(self) -> None:
        await self.switch_browse_mode(BrowseMode.COLLECTIONS)

    async def action_switch_authors(self) -> None:
        await self.switch_browse_mode(BrowseMode.AUTHORS)

    async def action_switch_narrators(self) -> None:
        await self.switch_browse_mode(BrowseMode.NARRATORS)

    async def switch_browse_mode(self, mode: BrowseMode) -> None:
        self.mode = mode
        self.drilled_entry = None
        self.bulk_confirmation_pending = False
        self.query_one("#query", Input).value = ""
        self.update_mode_label()
        await self.load_mode_page(reset=True)

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        query = event.value.strip()
        if self.drilled_entry is not None:
            return
        if not query:
            await self.load_mode_page(reset=True)
            return
        if self.mode != BrowseMode.BOOKS:
            self.apply_entry_filter(query)
            await self.refresh_entries()
            self.set_browse_status()
            return
        self.set_status(f"Searching for {query}...")
        results = await self.search_func(self.client, query=query, limit=self.limit)
        self.results = results
        self.total = len(results)
        await self.refresh_results()
        if results:
            self.query_one("#results", ListView).focus()
        self.set_status(
            f"Found {len(results)} result(s). Press Enter or a to queue the selected book."
        )

    async def on_input_changed(self, event: Input.Changed) -> None:
        if self.mode == BrowseMode.BOOKS or self.drilled_entry is not None:
            return
        self.apply_entry_filter(event.value.strip())
        await self.refresh_entries()
        self.set_browse_status()

    async def load_mode_page(self, *, reset: bool) -> None:
        self.bulk_confirmation_pending = False
        if reset:
            self.current_page = 0
            self.total = 0
            self.results = []
            self.entries = []
            self.filtered_entries = []
        if self.mode == BrowseMode.BOOKS:
            page = await self.list_books_func(
                self.client, page=self.current_page, limit=BROWSE_LIMIT
            )
            self.total = page.total
            self.results = page.items if reset else [*self.results, *page.items]
            await self.refresh_results()
            self.set_browse_status()
            return

        page = await self.list_entries_func(
            self.client, mode=self.mode, page=self.current_page, limit=BROWSE_LIMIT
        )
        self.total = page.total
        self.entries = page.items if reset else [*self.entries, *page.items]
        self.apply_entry_filter(self.query_one("#query", Input).value.strip())
        await self.refresh_entries()
        self.set_browse_status()

    async def load_more_if_needed(self) -> None:
        if self.drilled_entry is not None:
            return
        loaded_count = len(self.results) if self.mode == BrowseMode.BOOKS else len(self.entries)
        if loaded_count >= self.total:
            return
        self.current_page += 1
        await self.load_mode_page(reset=False)

    async def on_list_view_highlighted(self, event: ListView.Highlighted) -> None:
        if event.list_view.id != "results":
            return
        child_count = len(event.list_view.children)
        if child_count < BROWSE_LIMIT:
            return
        if child_count > 0 and (event.list_view.index or 0) >= child_count - 2:
            await self.load_more_if_needed()

    async def refresh_results(self) -> None:
        queue = load_queue(self.queue_path)
        selected_ids = {item.id for item in queue.items}
        result_list = self.query_one("#results", ListView)
        selected_index = result_list.index
        await result_list.clear()
        for result in self.results:
            await result_list.append(ResultItem(result, selected=result.id in selected_ids))
        if self.results:
            result_list.index = max(0, min(selected_index or 0, len(self.results) - 1))

    async def refresh_entries(self) -> None:
        result_list = self.query_one("#results", ListView)
        selected_index = result_list.index
        await result_list.clear()
        for entry in self.filtered_entries:
            await result_list.append(EntryItem(entry))
        if self.filtered_entries:
            result_list.index = max(0, min(selected_index or 0, len(self.filtered_entries) - 1))

    async def on_list_view_selected(self, event: ListView.Selected) -> None:
        if event.list_view.id == "results":
            event.stop()
            if isinstance(event.item, EntryItem):
                await self.drill_into_entry(event.item.entry)
                return
            await self.add_result_item(event.item)

    async def action_add_selected(self) -> None:
        result_list = self.query_one("#results", ListView)
        item = result_list.highlighted_child
        if isinstance(item, EntryItem):
            await self.drill_into_entry(item.entry)
            return
        await self.add_result_item(result_list.highlighted_child)

    async def drill_into_entry(self, entry: BrowseEntry) -> None:
        self.drilled_entry = entry
        self.bulk_confirmation_pending = False
        self.results = await self.list_entry_books_func(self.client, entry=entry)
        self.total = len(self.results)
        await self.refresh_results()
        self.query_one("#results", ListView).focus()
        self.set_status(
            f"Showing {len(self.results)} book(s) for {entry.name}. Press b to add all."
        )

    async def action_go_back(self) -> None:
        if self.drilled_entry is None:
            return
        self.drilled_entry = None
        self.bulk_confirmation_pending = False
        await self.refresh_entries()
        self.query_one("#results", ListView).focus()
        self.set_browse_status()

    async def action_bulk_add(self) -> None:
        if self.drilled_entry is None:
            self.set_status("Open a group before adding all books.")
            return
        if not self.results:
            self.set_status("There are no books to add.")
            return
        self.bulk_confirmation_pending = True
        self.set_status(
            f"Queue all {len(self.results)} book(s) from {self.drilled_entry.name}? "
            "Press y to confirm or n to cancel."
        )

    async def action_confirm_bulk_add(self) -> None:
        if not self.bulk_confirmation_pending or self.drilled_entry is None:
            return
        queue = load_queue(self.queue_path)
        before_count = len(queue.items)
        for result in self.results:
            add_pending_item(
                queue,
                item_id=result.id,
                library_id=result.library_id,
                title=result.title,
                author=result.author,
            )
        save_queue(self.queue_path, queue)
        self.bulk_confirmation_pending = False
        await self.refresh_queue()
        await self.refresh_results()
        added_count = len(queue.items) - before_count
        self.set_status(f"Queued {added_count} book(s) from {self.drilled_entry.name}.")

    def action_cancel_bulk_add(self) -> None:
        if not self.bulk_confirmation_pending:
            return
        self.bulk_confirmation_pending = False
        self.set_status("Bulk add cancelled.")

    async def action_remove_queue_item(self) -> None:
        if not self.queue_has_focus():
            return
        queue_item = self.highlighted_queue_item()
        if queue_item is None:
            self.set_status("Select a queue item first.")
            return
        queue = load_queue(self.queue_path)
        removed = remove_item(queue, queue_item.item_id)
        if removed is None:
            self.set_status("Select a queue item first.")
            return
        save_queue(self.queue_path, queue)
        await self.refresh_queue()
        await self.refresh_results()
        self.set_status(f"Removed {removed.title}.")

    async def action_reset_queue_item(self) -> None:
        if not self.queue_has_focus():
            return
        queue_item = self.highlighted_queue_item()
        if queue_item is None:
            self.set_status("Select a queue item first.")
            return
        queue = load_queue(self.queue_path)
        reset = reset_item(queue, queue_item.item_id)
        if reset is None:
            self.set_status("Select a queue item first.")
            return
        save_queue(self.queue_path, queue)
        await self.refresh_queue()
        await self.refresh_results()
        self.set_status(f"Reset {reset.title} to pending.")

    async def add_result_item(self, item: ListItem | None) -> None:
        if not isinstance(item, ResultItem):
            self.set_status("Select a result first.")
            return
        self.bulk_confirmation_pending = False
        queue = load_queue(self.queue_path)
        before_count = len(queue.items)
        queued = add_pending_item(
            queue,
            item_id=item.result.id,
            library_id=item.result.library_id,
            title=item.result.title,
            author=item.result.author,
        )
        save_queue(self.queue_path, queue)
        await self.refresh_queue()
        await self.refresh_results()
        if len(queue.items) == before_count:
            self.set_status(f"{queued.title} is already queued with status {queued.status}.")
        else:
            self.set_status(f"Queued {queued.title}.")

    async def refresh_queue(self) -> None:
        queue = load_queue(self.queue_path)
        queue_list = self.query_one("#queue", ListView)
        await queue_list.clear()
        for item in queue.items:
            await queue_list.append(QueueListItem(item))

    def queue_has_focus(self) -> bool:
        return self.query_one("#queue", ListView).has_focus

    def highlighted_queue_item(self) -> QueueListItem | None:
        item = self.query_one("#queue", ListView).highlighted_child
        if isinstance(item, QueueListItem):
            return item
        return None

    def set_status(self, message: str) -> None:
        self.status_message = message
        self.query_one("#status", Static).update(message)

    def update_mode_label(self) -> None:
        modes = [
            ("F1", BrowseMode.BOOKS),
            ("F2", BrowseMode.SERIES),
            ("F3", BrowseMode.COLLECTIONS),
            ("F4", BrowseMode.AUTHORS),
            ("F5", BrowseMode.NARRATORS),
        ]
        labels = [
            f"[{key} {mode.value.title()}]" if mode == self.mode else f"{key} {mode.value.title()}"
            for key, mode in modes
        ]
        self.query_one("#mode", Static).update("  ".join(labels))

    def apply_entry_filter(self, query: str) -> None:
        if not query:
            self.filtered_entries = list(self.entries)
            return
        query_lower = query.lower()
        self.filtered_entries = [
            entry for entry in self.entries if query_lower in entry.name.lower()
        ]

    def set_browse_status(self) -> None:
        if self.mode == BrowseMode.BOOKS:
            self.set_status(f"Showing {len(self.results)} of {self.total} books.")
            return
        label = self.mode.value
        self.set_status(f"Showing {len(self.filtered_entries)} of {self.total} {label}.")


def format_result(result: BookSearchResult, *, selected: bool = False) -> str:
    marker = "[x]" if selected else "[ ]"
    parts = [f"{marker} {result.title}", result.author, result.library_name]
    if result.duration is not None:
        parts.append(format_duration(result.duration))
    if result.size is not None:
        parts.append(format_size(result.size))
    return " - ".join(parts)


def format_entry(entry: BrowseEntry) -> str:
    noun = "book" if entry.count == 1 else "books"
    return f"{entry.name} - {entry.library_name} - {entry.count} {noun}"


def format_duration(seconds: float) -> str:
    hours, remainder = divmod(int(seconds), 3600)
    minutes, _ = divmod(remainder, 60)
    return f"{hours:d}h {minutes:02d}m"


def format_size(size: int) -> str:
    if size >= 1024**3:
        return f"{size / 1024**3:.1f} GiB"
    if size >= 1024**2:
        return f"{size / 1024**2:.1f} MiB"
    return f"{size} bytes"
