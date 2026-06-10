import json
from dataclasses import dataclass

import pytest

from audiobookshelf_sync.api import (
    BrowseEntry,
    BrowseMode,
    list_books,
    list_books_for_entry,
    list_browse_entries,
    search_books,
)


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


class FakeBrowseClient:
    async def get_all_libraries(self) -> list[FakeLibrary]:
        return [
            FakeLibrary(id_="books", name="Books", media_type="book"),
            FakeLibrary(id_="other-books", name="Other Books", media_type="book"),
            FakeLibrary(id_="podcasts", name="Podcasts", media_type="podcast"),
        ]

    async def _get(
        self, endpoint: str, params: dict[str, str | int] | None = None
    ) -> bytes:
        if endpoint == "/api/libraries/books/items":
            assert params == {
                "minified": 1,
                "limit": 2,
                "page": 1,
                "sort": "media.metadata.title",
            }
            return json.dumps(
                {
                    "total": 3,
                    "limit": 2,
                    "page": 1,
                    "results": [
                        {
                            "id": "book-3",
                            "libraryId": "books",
                            "mediaType": "book",
                            "size": 1234,
                            "media": {
                                "duration": 1800.0,
                                "metadata": {
                                    "title": "Children of Dune",
                                    "authorName": "Frank Herbert",
                                },
                            },
                        }
                    ],
                }
            ).encode()
        if endpoint == "/api/libraries/other-books/items":
            assert params == {
                "minified": 1,
                "limit": 2,
                "page": 1,
                "sort": "media.metadata.title",
            }
            return json.dumps(
                {"total": 0, "limit": 2, "page": 1, "results": []}
            ).encode()
        raise AssertionError(f"Unexpected endpoint: {endpoint}")


class FakeBrowseEntryClient:
    async def get_all_libraries(self) -> list[FakeLibrary]:
        return [
            FakeLibrary(id_="books", name="Books", media_type="book"),
            FakeLibrary(id_="other-books", name="Other Books", media_type="book"),
            FakeLibrary(id_="podcasts", name="Podcasts", media_type="podcast"),
        ]

    async def _get(
        self, endpoint: str, params: dict[str, str | int] | None = None
    ) -> bytes:
        if endpoint == "/api/libraries/books/series":
            assert params == {"minified": 1, "limit": 25, "page": 0}
            return json.dumps(
                {
                    "total": 1,
                    "limit": 25,
                    "page": 0,
                    "results": [
                        {
                            "id": "series-1",
                            "name": "Dune",
                            "books": [{"id": "book-1"}, {"id": "book-2"}],
                        }
                    ],
                }
            ).encode()
        if endpoint == "/api/libraries/other-books/series":
            assert params == {"minified": 1, "limit": 25, "page": 0}
            return json.dumps(
                {
                    "total": 1,
                    "limit": 25,
                    "page": 0,
                    "results": [
                        {"id": "series-2", "name": "Dune", "books": [{"id": "book-3"}]}
                    ],
                }
            ).encode()
        if endpoint == "/api/libraries/books/collections":
            assert params == {"minified": 1, "limit": 25, "page": 0}
            return json.dumps(
                {
                    "total": 1,
                    "limit": 25,
                    "page": 0,
                    "results": [
                        {
                            "id": "collection-1",
                            "name": "Favorites",
                            "books": [{"id": "book-1"}],
                        }
                    ],
                }
            ).encode()
        if endpoint == "/api/libraries/other-books/collections":
            assert params == {"minified": 1, "limit": 25, "page": 0}
            return json.dumps(
                {"total": 0, "limit": 25, "page": 0, "results": []}
            ).encode()
        if endpoint == "/api/libraries/books/authors":
            return json.dumps(
                {
                    "authors": [
                        {"id": "author-1", "name": "Frank Herbert", "numBooks": 2}
                    ]
                }
            ).encode()
        if endpoint == "/api/libraries/other-books/authors":
            return json.dumps(
                {
                    "authors": [
                        {"id": "author-2", "name": "Frank Herbert", "numBooks": 1}
                    ]
                }
            ).encode()
        if endpoint == "/api/libraries/books/narrators":
            return json.dumps(
                {"narrators": [{"id": "narrator-1", "name": "Simon Vance", "numBooks": 2}]}
            ).encode()
        if endpoint == "/api/libraries/other-books/narrators":
            return json.dumps({"narrators": []}).encode()
        raise AssertionError(f"Unexpected endpoint: {endpoint}")


class FakeEntryBooksClient:
    async def get_all_libraries(self) -> list[FakeLibrary]:
        return [FakeLibrary(id_="books", name="Books", media_type="book")]

    async def _get(
        self, endpoint: str, params: dict[str, str | int] | None = None
    ) -> bytes:
        if endpoint == "/api/series/series-1":
            return json.dumps(
                {
                    "id": "series-1",
                    "name": "Dune",
                    "books": [
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


@pytest.mark.anyio
async def test_list_books_filters_to_book_libraries_and_maps_page_results() -> None:
    page = await list_books(FakeBrowseClient(), page=1, limit=2)

    assert page.total == 3
    assert [item.id for item in page.items] == ["book-3"]
    assert page.items[0].library_name == "Books"
    assert page.items[0].title == "Children of Dune"


@pytest.mark.anyio
async def test_list_browse_entries_keeps_duplicate_names_per_library() -> None:
    page = await list_browse_entries(
        FakeBrowseEntryClient(), mode=BrowseMode.SERIES, page=0, limit=25
    )

    assert page.total == 2
    assert page.items == [
        BrowseEntry(
            mode=BrowseMode.SERIES,
            id="series-1",
            name="Dune",
            library_id="books",
            library_name="Books",
            count=2,
        ),
        BrowseEntry(
            mode=BrowseMode.SERIES,
            id="series-2",
            name="Dune",
            library_id="other-books",
            library_name="Other Books",
            count=1,
        ),
    ]


@pytest.mark.anyio
async def test_list_browse_entries_loads_collections_authors_and_narrators() -> None:
    client = FakeBrowseEntryClient()

    collections = await list_browse_entries(
        client, mode=BrowseMode.COLLECTIONS, page=0, limit=25
    )
    authors = await list_browse_entries(
        client, mode=BrowseMode.AUTHORS, page=0, limit=25
    )
    narrators = await list_browse_entries(
        client, mode=BrowseMode.NARRATORS, page=0, limit=25
    )

    assert [entry.name for entry in collections.items] == ["Favorites"]
    assert [entry.name for entry in authors.items] == [
        "Frank Herbert",
        "Frank Herbert",
    ]
    assert [entry.name for entry in narrators.items] == ["Simon Vance"]


@pytest.mark.anyio
async def test_list_books_for_series_entry_maps_books_to_queueable_results() -> None:
    entry = BrowseEntry(
        mode=BrowseMode.SERIES,
        id="series-1",
        name="Dune",
        library_id="books",
        library_name="Books",
        count=1,
    )

    results = await list_books_for_entry(FakeEntryBooksClient(), entry=entry)

    assert [result.id for result in results] == ["book-1"]
    assert results[0].title == "Dune"
    assert results[0].author == "Frank Herbert"
