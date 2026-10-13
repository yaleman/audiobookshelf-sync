import json
from collections.abc import AsyncIterator, Callable
from copy import deepcopy
from dataclasses import dataclass
from typing import Any, cast

from aioaudiobookshelf.client.session_configuration import SessionConfiguration
from aioaudiobookshelf.schema.audio import AudioTrack
from aioaudiobookshelf.schema.book import BookExpanded, BookMetadataExpanded
from aioaudiobookshelf.schema.library import LibraryItemBook, LibraryItemExpandedBook
from aiohttp import ClientSession


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
        pass

    async def read(self) -> bytes:
        return self.body

    @property
    def content(self) -> "FakeResponse":
        return self

    async def iter_chunked(self, size: int) -> AsyncIterator[bytes]:
        for offset in range(0, len(self.body), size):
            yield self.body[offset : offset + size]


class FakeSession:
    def __init__(
        self,
        responses: dict[str, bytes] | None = None,
        *,
        post_handler: Callable[..., FakeResponse] | None = None,
    ) -> None:
        self.responses = responses if responses is not None else {}
        self.requested_urls: list[str] = []
        self.post_handler = post_handler

    def get(self, url: str, **kwargs: Any) -> FakeResponse:
        self.requested_urls.append(url)
        return FakeResponse(self.responses[url])

    def post(self, url: str, **kwargs: Any) -> FakeResponse:
        if self.post_handler is None:
            raise AssertionError(f"Unexpected POST: {url}")
        return self.post_handler(url, **kwargs)


def expanded_book(book_id: str, *, tracks: list[AudioTrack]) -> LibraryItemExpandedBook:
    return LibraryItemExpandedBook(
        id_=book_id,
        ino="0",
        library_id="books",
        folder_id="folder",
        path=f"/books/{book_id}",
        relative_path=book_id,
        is_file=False,
        modified_time_ms=0,
        changed_time_ms=0,
        created_time_ms=0,
        added_at=0,
        updated_at=0,
        is_missing=False,
        is_invalid=False,
        library_files=[],
        size=0,
        media=BookExpanded(
            library_item_id=book_id,
            metadata=BookMetadataExpanded(
                title="Example Book",
                genres=[],
                explicit=False,
                authors=[],
                narrators=[],
                series=[],
                title_ignore_prefix="Example Book",
                author_name="Example Author",
                author_name_lf="Author, Example",
                narrator_name="",
                series_name="",
            ),
            audio_files=[],
            chapters=[],
            duration=sum(track.duration for track in tracks),
            size=0,
            tracks=tracks,
        ),
    )


@dataclass
class FakeLibrary:
    id_: str
    name: str
    media_type: str


class FakeClient:
    def __init__(
        self,
        fail: bool = False,
        *,
        session: FakeSession | None = None,
        url: str = "https://abs.example",
        books: dict[str, LibraryItemBook | LibraryItemExpandedBook] | None = None,
    ) -> None:
        self.session_config = SessionConfiguration(
            url=url,
            session=cast(
                ClientSession, session if session is not None else FakeSession()
            ),
            token="token",
        )
        self.books = books if books is not None else {}
        self.items: list[dict[str, Any]] = []
        self.patches: list[dict[str, Any]] = []
        self.fail = fail

    async def get_library_item_book(
        self, *, book_id: str, expanded: bool = False
    ) -> LibraryItemBook | LibraryItemExpandedBook:
        if self.fail:
            raise RuntimeError("boom")
        book = self.books[book_id]
        if expanded and not isinstance(book, LibraryItemExpandedBook):
            raise AssertionError(f"Book {book_id} is not expanded")
        return book

    async def get_all_libraries(self) -> list[FakeLibrary]:
        return [
            FakeLibrary(id_="books", name="Books", media_type="book"),
            FakeLibrary(id_="other-books", name="Other Books", media_type="book"),
            FakeLibrary(id_="podcasts", name="Podcasts", media_type="podcast"),
        ]

    async def _get(
        self, endpoint: str, params: dict[str, str | int] | None = None
    ) -> bytes:
        if endpoint.startswith("/api/libraries/") and endpoint.endswith("/search"):
            assert params == {"q": "dune", "limit": 25}
            library = endpoint.split("/")[3]
            return json.dumps(
                {
                    "book": [
                        {
                            "libraryItem": {
                                "id": "book-1",
                                "libraryId": library,
                                "mediaType": "book",
                                "size": 1234,
                                "media": {
                                    "duration": 3600.0,
                                    "metadata": {
                                        "title": "Dune",
                                        "authorName": "Frank Herbert",
                                    },
                                },
                            }
                        }
                    ],
                    "authors": [],
                }
            ).encode()
        raise ValueError(f"Unhandled search {endpoint=} {params=}")

    async def _patch(self, endpoint: str, data: dict[str, Any]) -> bytes:
        item = next(
            item for item in self.items if endpoint == f"/api/items/{item['id']}/media"
        )
        self.patches.append(deepcopy(data))
        item["media"].update(deepcopy(data))
        return b"{}"
