from __future__ import annotations

from collections.abc import Awaitable, Callable
from pathlib import Path

from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Footer, Header, Input, Label, ListItem, ListView, Static

from audiobookshelf_sync.api import BookSearchResult, search_books
from audiobookshelf_sync.queue import (
    QUEUE_FILE,
    QueueItem,
    add_pending_item,
    load_queue,
    remove_item,
    reset_item,
    save_queue,
)


class ResultItem(ListItem):
    def __init__(self, result: BookSearchResult, *, selected: bool = False) -> None:
        self.display_text = format_result(result, selected=selected)
        super().__init__(Label(self.display_text))
        self.result = result


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
        ("a", "add_selected", "Add selected"),
        ("d", "remove_queue_item", "Remove"),
        ("delete", "remove_queue_item", "Remove"),
        ("r", "reset_queue_item", "Reset"),
        ("q", "quit", "Quit"),
    ]

    def __init__(
        self,
        *,
        client: object,
        queue_path: Path = QUEUE_FILE,
        limit: int,
        search_func: Callable[..., Awaitable[list[BookSearchResult]]] = search_books,
    ) -> None:
        super().__init__()
        self.client = client
        self.queue_path = queue_path
        self.limit = limit
        self.search_func = search_func
        self.results: list[BookSearchResult] = []

    def compose(self) -> ComposeResult:
        yield Header()
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
        self.query_one("#query", Input).focus()

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        query = event.value.strip()
        if not query:
            self.set_status("Enter a search query.")
            return
        self.set_status(f"Searching for {query}...")
        results = await self.search_func(self.client, query=query, limit=self.limit)
        self.results = results
        await self.refresh_results()
        if results:
            self.query_one("#results", ListView).focus()
        self.set_status(
            f"Found {len(results)} result(s). Press Enter or a to queue the selected book."
        )

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

    async def on_list_view_selected(self, event: ListView.Selected) -> None:
        if event.list_view.id == "results":
            event.stop()
            await self.add_result_item(event.item)

    async def action_add_selected(self) -> None:
        result_list = self.query_one("#results", ListView)
        await self.add_result_item(result_list.highlighted_child)

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
        self.query_one("#status", Static).update(message)


def format_result(result: BookSearchResult, *, selected: bool = False) -> str:
    marker = "[x]" if selected else "[ ]"
    parts = [f"{marker} {result.title}", result.author, result.library_name]
    if result.duration is not None:
        parts.append(format_duration(result.duration))
    if result.size is not None:
        parts.append(format_size(result.size))
    return " - ".join(parts)


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
