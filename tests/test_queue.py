from pathlib import Path

from audiobookshelf_sync.queue import (
    QueueItem,
    QueueStatus,
    add_pending_item,
    load_queue,
    mark_done,
    mark_failed,
    mark_downloading,
    remove_item,
    reset_item,
    save_queue,
)


def test_load_queue_creates_empty_queue_for_missing_file(tmp_path: Path) -> None:
    queue = load_queue(tmp_path / "audiobookshelf-sync.json")

    assert queue.version == 1
    assert queue.items == []


def test_queue_round_trip_preserves_items(tmp_path: Path) -> None:
    queue_path = tmp_path / "audiobookshelf-sync.json"
    queue = load_queue(queue_path)
    add_pending_item(
        queue,
        item_id="book-1",
        library_id="library-1",
        title="Example Book",
        author="Example Author",
    )

    save_queue(queue_path, queue)
    loaded = load_queue(queue_path)

    assert len(loaded.items) == 1
    assert loaded.items[0].id == "book-1"
    assert loaded.items[0].status == QueueStatus.PENDING


def test_add_pending_item_does_not_duplicate_existing_item() -> None:
    queue = load_queue(Path("missing.json"))

    first = add_pending_item(
        queue,
        item_id="book-1",
        library_id="library-1",
        title="Example Book",
        author="Example Author",
    )
    second = add_pending_item(
        queue,
        item_id="book-1",
        library_id="library-1",
        title="Changed Title",
        author="Changed Author",
    )

    assert first is second
    assert len(queue.items) == 1
    assert queue.items[0].title == "Example Book"


def test_status_transitions_update_queue_item() -> None:
    item = QueueItem(
        id="book-1",
        library_id="library-1",
        title="Example Book",
        author="Example Author",
    )

    mark_downloading(item)
    assert item.status == QueueStatus.DOWNLOADING
    assert item.error is None

    mark_failed(item, RuntimeError("network failed"))
    assert item.status == QueueStatus.FAILED
    assert item.error == "network failed"

    mark_done(item, output_dir=Path("downloads/Example Book"))
    assert item.status == QueueStatus.DONE
    assert item.output_dir == "downloads/Example Book"
    assert item.downloaded_at is not None
    assert item.error is None


def test_remove_item_deletes_matching_queue_item() -> None:
    queue = load_queue(Path("missing.json"))
    add_pending_item(
        queue,
        item_id="book-1",
        library_id="library-1",
        title="Example Book",
        author="Example Author",
    )
    add_pending_item(
        queue,
        item_id="book-2",
        library_id="library-1",
        title="Other Book",
        author="Other Author",
    )

    removed = remove_item(queue, "book-1")

    assert removed is not None
    assert removed.id == "book-1"
    assert [item.id for item in queue.items] == ["book-2"]


def test_reset_item_marks_item_pending_and_clears_download_state() -> None:
    item = QueueItem(
        id="book-1",
        library_id="library-1",
        title="Example Book",
        author="Example Author",
    )
    mark_done(item, output_dir=Path("downloads/Example Book"))
    item.error = "old error"
    queue = load_queue(Path("missing.json"))
    queue.items.append(item)

    reset = reset_item(queue, "book-1")

    assert reset is item
    assert item.status == QueueStatus.PENDING
    assert item.downloaded_at is None
    assert item.output_dir is None
    assert item.error is None
