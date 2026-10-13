from pathlib import Path

from audiobookshelf_sync.config import ConfigFile
from audiobookshelf_sync.queue import (
    QueueItem,
    QueueStatus,
)


def test_load_queue_creates_empty_queue_for_missing_file(tmp_path: Path) -> None:
    queue = ConfigFile.load(tmp_path / "audiobookshelf-sync.json")

    assert queue.version == ConfigFile().version
    assert queue.items == []


def test_queue_round_trip_preserves_items(tmp_path: Path) -> None:
    config_path = tmp_path / "audiobookshelf-sync.json"
    config = ConfigFile.load(config_path)
    config.add_pending_item(
        item_id="book-1",
        library_id="library-1",
        title="Example Book",
        author="Example Author",
    )

    config.save(config_path)
    loaded = ConfigFile.load(config_path)

    assert len(loaded.items) == 1
    assert loaded.items[0].id == "book-1"
    assert loaded.items[0].status == QueueStatus.PENDING


def test_add_pending_item_does_not_duplicate_existing_item() -> None:
    config = ConfigFile.load(Path("missing.json"))

    first = config.add_pending_item(
        item_id="book-1",
        library_id="library-1",
        title="Example Book",
        author="Example Author",
    )
    second = config.add_pending_item(
        item_id="book-1",
        library_id="library-1",
        title="Changed Title",
        author="Changed Author",
    )

    assert first is second
    assert len(config.items) == 1
    assert config.items[0].title == "Example Book"


def test_status_transitions_update_queue_item() -> None:
    item = QueueItem(
        id="book-1",
        library_id="library-1",
        title="Example Book",
        author="Example Author",
    )

    item.mark_downloading()
    assert item.status == QueueStatus.DOWNLOADING
    assert item.error is None

    item.mark_failed(RuntimeError("network failed"))
    assert item.status == QueueStatus.FAILED
    assert item.error == "network failed"

    item.mark_done(output_dir=Path("downloads/Example Book"))
    assert item.status == QueueStatus.DONE
    assert item.output_dir == "downloads/Example Book"
    assert item.downloaded_at is not None
    assert item.error is None


def test_remove_item_deletes_matching_queue_item() -> None:
    queue = ConfigFile.load(Path("missing.json"))
    queue.add_pending_item(
        item_id="book-1",
        library_id="library-1",
        title="Example Book",
        author="Example Author",
    )
    queue.add_pending_item(
        item_id="book-2",
        library_id="library-1",
        title="Other Book",
        author="Other Author",
    )

    removed = queue.remove_item("book-1")

    assert removed is not None
    assert removed.id == "book-1"
    assert [item.id for item in queue.items] == ["book-2"]
    assert not Path("audiobookshelf-sync.json").exists()


def test_reset_item_marks_item_pending_and_clears_download_state() -> None:
    item = QueueItem(
        id="book-1",
        library_id="library-1",
        title="Example Book",
        author="Example Author",
    )
    item.mark_done(output_dir=Path("downloads/Example Book"))
    item.error = "old error"
    queue = ConfigFile.load(Path("missing.json"))
    queue.items.append(item)

    reset = queue.reset_item("book-1")

    assert reset is item
    assert item.status == QueueStatus.PENDING
    assert item.downloaded_at is None
    assert item.output_dir is None
    assert item.error is None
    assert not Path("audiobookshelf-sync.json").exists()


def test_synchronised_status_round_trips_and_can_be_reset(tmp_path: Path) -> None:
    item = QueueItem(
        id="book",
        library_id="books",
        title="Example",
        author="Author",
        error="old error",
    )
    item.mark_synchronised()
    assert item.status == QueueStatus.SYNCHRONISED
    assert item.error is None
    path = tmp_path / "queue.json"
    ConfigFile(items=[item]).save(path)
    loaded = ConfigFile.load(path)
    assert loaded.items[0].status == QueueStatus.SYNCHRONISED
    loaded.reset_item("book")
    assert loaded.items[0].status == QueueStatus.PENDING
