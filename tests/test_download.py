from dataclasses import dataclass
from pathlib import Path

import pytest

from audiobookshelf_sync.download import download_pending_items, sanitize_path_part
from audiobookshelf_sync.queue import (
    QueueStatus,
    add_pending_item,
    load_queue,
    save_queue,
)


@dataclass
class FakeMetadata:
    filename: str


@dataclass
class FakeTrack:
    index: int
    title: str
    content_url: str
    metadata: FakeMetadata | None = None


@dataclass
class FakeMedia:
    tracks: list[FakeTrack]


@dataclass
class FakeBook:
    media: FakeMedia


class FakeResponse:
    def __init__(self, body: bytes, status: int = 200) -> None:
        self.body = body
        self.status = status

    def raise_for_status(self) -> None:
        if self.status >= 400:
            raise RuntimeError(f"HTTP {self.status}")

    async def __aenter__(self) -> "FakeResponse":
        return self

    async def __aexit__(self, *args: object) -> None:
        return None

    @property
    def content(self) -> "FakeResponse":
        return self

    async def _chunks(self, size: int):
        yield self.body[:size]
        yield self.body[size:]

    def iter_chunked(self, size: int):
        return self._chunks(size)


class FakeSession:
    def __init__(self, responses: dict[str, bytes]) -> None:
        self.responses = responses
        self.requested_urls: list[str] = []

    def get(self, url: str, **kwargs: object) -> FakeResponse:
        self.requested_urls.append(url)
        return FakeResponse(self.responses[url])


class FakeSessionConfig:
    def __init__(self, session: FakeSession) -> None:
        self.session = session
        self.url = "https://abs.example"
        self.headers = {"Authorization": "Bearer token"}
        self.verify_ssl = True
        self.timeout = None


class FakeClient:
    def __init__(self, session: FakeSession, fail: bool = False) -> None:
        self.session_config = FakeSessionConfig(session)
        self.fail = fail

    async def get_library_item_book(
        self, *, book_id: str, expanded: bool = False
    ) -> FakeBook:
        assert expanded is True
        if self.fail:
            raise RuntimeError("boom")
        return FakeBook(
            media=FakeMedia(
                tracks=[
                    FakeTrack(
                        index=0,
                        title="Track One",
                        content_url="/audio/book-1/track-1.mp3",
                        metadata=FakeMetadata(filename="01 Track One.mp3"),
                    ),
                    FakeTrack(
                        index=1,
                        title="Track Two",
                        content_url="/audio/book-1/track-2.mp3",
                    ),
                ]
            )
        )


def test_sanitize_path_part_removes_unsafe_characters() -> None:
    assert sanitize_path_part('Bad/Name: "Book"?') == "Bad_Name_ Book"


@pytest.mark.anyio
async def test_download_pending_items_writes_tracks_and_marks_done(
    tmp_path: Path,
) -> None:
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
    session = FakeSession(
        {
            "https://abs.example/audio/book-1/track-1.mp3": b"track-one",
            "https://abs.example/audio/book-1/track-2.mp3": b"track-two",
        }
    )

    await download_pending_items(
        client=FakeClient(session),
        queue_path=queue_path,
        download_dir=tmp_path / "downloads",
    )

    loaded = load_queue(queue_path)
    assert loaded.items[0].status == QueueStatus.DONE
    assert loaded.items[0].output_dir == "downloads/Example Author - Example Book"
    assert (
        tmp_path / "downloads" / "Example Author - Example Book" / "01 Track One.mp3"
    ).read_bytes() == b"track-one"
    assert (
        tmp_path / "downloads" / "Example Author - Example Book" / "02 Track Two.mp3"
    ).read_bytes() == b"track-two"
    assert not list((tmp_path / "downloads" / "Example Book").glob("*.part"))


@pytest.mark.anyio
async def test_download_pending_items_marks_failed_and_continues(
    tmp_path: Path,
) -> None:
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

    await download_pending_items(
        client=FakeClient(FakeSession({}), fail=True),
        queue_path=queue_path,
        download_dir=tmp_path / "downloads",
    )

    loaded = load_queue(queue_path)
    assert loaded.items[0].status == QueueStatus.FAILED
    assert loaded.items[0].error == "boom"


@pytest.mark.anyio
async def test_download_pending_items_reports_progress(tmp_path: Path) -> None:
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
    session = FakeSession(
        {
            "https://abs.example/audio/book-1/track-1.mp3": b"track-one",
            "https://abs.example/audio/book-1/track-2.mp3": b"track-two",
        }
    )
    messages: list[str] = []

    await download_pending_items(
        client=FakeClient(session),
        queue_path=queue_path,
        download_dir=tmp_path / "downloads",
        reporter=messages.append,
    )

    assert messages == [
        "Queue file: audiobookshelf-sync.json",
        "Download directory: downloads",
        "Starting: Example Book - Example Author",
        "Fetching metadata: Example Book",
        "Downloading 2 track(s) to downloads/Example Author - Example Book",
        "Downloading track 1/2: 01 Track One.mp3",
        "Finished track 1/2: 01 Track One.mp3",
        "Downloading track 2/2: 02 Track Two.mp3",
        "Finished track 2/2: 02 Track Two.mp3",
        "Done: Example Book",
        "Processed 1 item(s): 1 done, 0 failed",
    ]


@pytest.mark.anyio
async def test_download_pending_items_skips_existing_track_files(
    tmp_path: Path,
) -> None:
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
    output_dir = tmp_path / "downloads" / "Example Author - Example Book"
    output_dir.mkdir(parents=True)
    existing_track = output_dir / "01 Track One.mp3"
    existing_track.write_bytes(b"already-here")
    stale_part = output_dir / "02 Track Two.mp3.part"
    stale_part.write_bytes(b"stale")
    session = FakeSession(
        {
            "https://abs.example/audio/book-1/track-2.mp3": b"track-two",
        }
    )
    messages: list[str] = []

    await download_pending_items(
        client=FakeClient(session),
        queue_path=queue_path,
        download_dir=tmp_path / "downloads",
        reporter=messages.append,
    )

    loaded = load_queue(queue_path)
    assert loaded.items[0].status == QueueStatus.DONE
    assert existing_track.read_bytes() == b"already-here"
    assert (output_dir / "02 Track Two.mp3").read_bytes() == b"track-two"
    assert not stale_part.exists()
    assert session.requested_urls == ["https://abs.example/audio/book-1/track-2.mp3"]
    assert "Skipping existing track 1/2: 01 Track One.mp3" in messages
