from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, Field


QUEUE_FILE = Path("audiobookshelf-sync.json")


class QueueStatus(StrEnum):
    PENDING = "pending"
    DOWNLOADING = "downloading"
    DONE = "done"
    FAILED = "failed"


class QueueItem(BaseModel):
    id: str
    library_id: str
    title: str
    author: str
    status: QueueStatus = QueueStatus.PENDING
    added_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    downloaded_at: datetime | None = None
    output_dir: str | None = None
    error: str | None = None


class DownloadQueue(BaseModel):
    version: int = 1
    items: list[QueueItem] = Field(default_factory=list)


def load_queue(path: Path = QUEUE_FILE) -> DownloadQueue:
    if not path.exists():
        return DownloadQueue()
    return DownloadQueue.model_validate_json(path.read_text())


def save_queue(path: Path, queue: DownloadQueue) -> None:
    if path.parent != Path("."):
        path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_name(f".{path.name}.tmp")
    temporary_path.write_text(queue.model_dump_json(indent=2) + "\n")
    temporary_path.replace(path)


def find_item(queue: DownloadQueue, item_id: str) -> QueueItem | None:
    return next((item for item in queue.items if item.id == item_id), None)


def add_pending_item(
    queue: DownloadQueue,
    *,
    item_id: str,
    library_id: str,
    title: str,
    author: str,
) -> QueueItem:
    existing = find_item(queue, item_id)
    if existing is not None:
        return existing

    item = QueueItem(
        id=item_id,
        library_id=library_id,
        title=title,
        author=author,
    )
    queue.items.append(item)
    return item


def mark_downloading(item: QueueItem) -> None:
    item.status = QueueStatus.DOWNLOADING
    item.error = None


def mark_done(item: QueueItem, *, output_dir: Path) -> None:
    item.status = QueueStatus.DONE
    item.output_dir = output_dir.as_posix()
    item.downloaded_at = datetime.now(UTC)
    item.error = None


def mark_failed(item: QueueItem, error: BaseException) -> None:
    item.status = QueueStatus.FAILED
    item.error = str(error)


def remove_item(queue: DownloadQueue, item_id: str) -> QueueItem | None:
    item = find_item(queue, item_id)
    if item is None:
        return None
    queue.items.remove(item)
    return item


def reset_item(queue: DownloadQueue, item_id: str) -> QueueItem | None:
    item = find_item(queue, item_id)
    if item is None:
        return None
    item.status = QueueStatus.PENDING
    item.downloaded_at = None
    item.output_dir = None
    item.error = None
    return item
