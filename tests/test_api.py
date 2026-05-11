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
