import json
from dataclasses import dataclass

import pytest

from audiobookshelf_sync.api import search_books


@dataclass
class FakeLibrary:
    id_: str
    name: str
    media_type: str


class FakeClient:
    async def get_all_libraries(self) -> list[FakeLibrary]:
        return [
            FakeLibrary(id_="books", name="Books", media_type="book"),
            FakeLibrary(id_="podcasts", name="Podcasts", media_type="podcast"),
        ]

    async def _get(
        self, endpoint: str, params: dict[str, str | int] | None = None
    ) -> bytes:
        assert endpoint == "/api/libraries/books/search"
        assert params == {"q": "dune", "limit": 25}
        return json.dumps(
            {
                "book": [
                    {
                        "libraryItem": {
                            "id": "book-1",
                            "libraryId": "books",
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


class FakeAuthorClient:
    def __init__(self) -> None:
        self.endpoints: list[str] = []

    async def get_all_libraries(self) -> list[FakeLibrary]:
        return [
            FakeLibrary(id_="books", name="Books", media_type="book"),
            FakeLibrary(id_="podcasts", name="Podcasts", media_type="podcast"),
        ]

    async def _get(
        self, endpoint: str, params: dict[str, str | int] | None = None
    ) -> bytes:
        self.endpoints.append(endpoint)
        if endpoint == "/api/libraries/books/search":
            assert params == {"q": "herbert", "limit": 25}
            return json.dumps(
                {
                    "book": [],
                    "authors": [
                        {
                            "id": "author-1",
                            "name": "Frank Herbert",
                            "numBooks": 1,
                        }
                    ],
                }
            ).encode()
        if endpoint == "/api/authors/author-1?include=items":
            return json.dumps(
                {
                    "id": "author-1",
                    "name": "Frank Herbert",
                    "libraryItems": [
                        {
                            "id": "book-1",
                            "libraryId": "books",
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
                    ],
                }
            ).encode()
        raise AssertionError(f"Unexpected endpoint: {endpoint}")


class FakeDuplicateAuthorClient(FakeAuthorClient):
    async def _get(
        self, endpoint: str, params: dict[str, str | int] | None = None
    ) -> bytes:
        self.endpoints.append(endpoint)
        if endpoint == "/api/libraries/books/search":
            assert params == {"q": "dune", "limit": 25}
            return json.dumps(
                {
                    "book": [
                        {
                            "libraryItem": {
                                "id": "book-1",
                                "libraryId": "books",
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
                    "authors": [
                        {
                            "id": "author-1",
                            "name": "Frank Herbert",
                            "numBooks": 1,
                        }
                    ],
                }
            ).encode()
        if endpoint == "/api/authors/author-1?include=items":
            return json.dumps(
                {
                    "id": "author-1",
                    "name": "Frank Herbert",
                    "libraryItems": [
                        {
                            "id": "book-1",
                            "libraryId": "books",
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
                    ],
                }
            ).encode()
        raise AssertionError(f"Unexpected endpoint: {endpoint}")


@pytest.mark.anyio
async def test_search_books_filters_to_book_libraries_and_maps_results() -> None:
    results = await search_books(FakeClient(), query="dune", limit=25)

    assert len(results) == 1
    assert results[0].id == "book-1"
    assert results[0].library_id == "books"
    assert results[0].library_name == "Books"
    assert results[0].title == "Dune"
    assert results[0].author == "Frank Herbert"
    assert results[0].duration == 3600.0
    assert results[0].size == 1234


@pytest.mark.anyio
async def test_search_books_expands_author_matches_into_book_results() -> None:
    client = FakeAuthorClient()

    results = await search_books(client, query="herbert", limit=25)

    assert [result.id for result in results] == ["book-1"]
    assert results[0].library_id == "books"
    assert results[0].library_name == "Books"
    assert results[0].title == "Dune"
    assert results[0].author == "Frank Herbert"
    assert client.endpoints == [
        "/api/libraries/books/search",
        "/api/authors/author-1?include=items",
    ]


@pytest.mark.anyio
async def test_search_books_deduplicates_direct_and_author_results() -> None:
    results = await search_books(FakeDuplicateAuthorClient(), query="dune", limit=25)

    assert [result.id for result in results] == ["book-1"]
