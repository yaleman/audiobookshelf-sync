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
    SYNCHRONISED = "synchronised"
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

    def reset(self) -> "QueueItem":
        self.status = QueueStatus.PENDING
        self.downloaded_at = None
        self.output_dir = None
        self.error = None
        return self

    def mark_downloading(self) -> None:
        if self.status != QueueStatus.SYNCHRONISED:
            self.status = QueueStatus.DOWNLOADING
        self.error = None

    def mark_done(self, *, output_dir: Path) -> None:
        if self.status != QueueStatus.SYNCHRONISED:
            self.status = QueueStatus.DONE
        self.output_dir = output_dir.as_posix()
        self.downloaded_at = datetime.now(UTC)
        self.error = None

    def mark_failed(self, error: BaseException) -> None:
        if self.status != QueueStatus.SYNCHRONISED:
            self.status = QueueStatus.FAILED
        self.error = str(error)

    def mark_synchronised(self) -> None:
        self.status = QueueStatus.SYNCHRONISED
        self.error = None
