from __future__ import annotations

import json
from base64 import b64encode
from collections.abc import AsyncIterator
from dataclasses import dataclass
from enum import StrEnum
from logging import Logger
from typing import Any, Protocol
from urllib.parse import quote

import aiohttp
from aioaudiobookshelf import (
    SessionConfiguration,
    get_user_client_by_token,
    get_user_client,
)

from audiobookshelf_sync.config import Config


@dataclass(frozen=True)
class BookSearchResult:
    id: str
    library_id: str
    library_name: str
    title: str
    author: str
    duration: float | None
    size: int | None


class BrowseMode(StrEnum):
    BOOKS = "books"
    SERIES = "series"
    COLLECTIONS = "collections"
    AUTHORS = "authors"
    NARRATORS = "narrators"


@dataclass(frozen=True)
class BrowseEntry:
    mode: BrowseMode
    id: str
    name: str
    library_id: str
    library_name: str
    count: int


@dataclass(frozen=True)
class BrowsePage[T]:
    items: list[T]
    total: int


class AudiobookshelfClient(Protocol):
    async def get_all_libraries(self) -> list[Any]: ...

    async def _get(
        self, endpoint: str, params: dict[str, str | int] | None = None
    ) -> bytes: ...


async def get_client(
    session: aiohttp.ClientSession, config: Config, logger: Logger
) -> Any:
    if config.token is not None:
        return await get_user_client_by_token(
            session_config=SessionConfiguration(
                session=session,
                url=config.url,
                logger=logger,
                pagination_items_per_page=30,
                token=config.token,
            ),
        )
    elif config.username is not None and config.password is not None:
        return await get_user_client(
            session_config=SessionConfiguration(
                session=session,
                url=config.url,
                logger=logger,
                pagination_items_per_page=30,
            ),
            username=config.username,
            password=config.password,
        )
    else:
        raise ValueError(
            "Invalid configuration: either token or username/password must be provided"
        )


async def iter_client(config: Config, logger: Logger) -> AsyncIterator[Any]:
    async with aiohttp.ClientSession() as session:
        yield await get_client(session, config, logger)


async def search_books(
    client: AudiobookshelfClient, *, query: str, limit: int
) -> list[BookSearchResult]:
    results: list[BookSearchResult] = []
    seen_item_ids: set[str] = set()
    for library in await client.get_all_libraries():
        if _library_media_type(library) != "book":
            continue
        response = await client._get(
            f"/api/libraries/{library.id_}/search",
            params={"q": query, "limit": limit},
        )
        payload = json.loads(response)
        for raw_result in payload.get("book", []):
            mapped = _map_book_result(raw_result, library_name=library.name)
            if mapped is not None and mapped.id not in seen_item_ids:
                results.append(mapped)
                seen_item_ids.add(mapped.id)
        for author in payload.get("authors", []):
            author_id = author.get("id")
            if not author_id:
                continue
            author_response = await client._get(f"/api/authors/{author_id}?include=items")
            author_payload = json.loads(author_response)
            for raw_item in author_payload.get("libraryItems", []):
                mapped = _map_book_result(raw_item, library_name=library.name)
                if mapped is not None and mapped.id not in seen_item_ids:
                    results.append(mapped)
                    seen_item_ids.add(mapped.id)
    return results


async def list_books(
    client: AudiobookshelfClient, *, page: int, limit: int
) -> BrowsePage[BookSearchResult]:
    results: list[BookSearchResult] = []
    total = 0
    seen_item_ids: set[str] = set()
    for library in await _book_libraries(client):
        response = await client._get(
            f"/api/libraries/{library.id_}/items",
            params={
                "minified": 1,
                "limit": limit,
                "page": page,
                "sort": "media.metadata.title",
            },
        )
        payload = json.loads(response)
        total += int(payload.get("total", 0))
        _append_mapped_books(
            results,
            payload.get("results", []),
            library_name=library.name,
            seen_item_ids=seen_item_ids,
        )
    return BrowsePage(items=results, total=total)


async def list_browse_entries(
    client: AudiobookshelfClient, *, mode: BrowseMode, page: int, limit: int
) -> BrowsePage[BrowseEntry]:
    if mode == BrowseMode.BOOKS:
        raise ValueError("Use list_books for book browsing.")

    results: list[BrowseEntry] = []
    total = 0
    for library in await _book_libraries(client):
        if mode in (BrowseMode.SERIES, BrowseMode.COLLECTIONS):
            page_result = await _list_paged_group_entries(
                client, library=library, mode=mode, page=page, limit=limit
            )
            results.extend(page_result.items)
            total += page_result.total
        elif mode == BrowseMode.AUTHORS:
            response = await client._get(f"/api/libraries/{library.id_}/authors")
            payload = json.loads(response)
            raw_entries = payload.get("authors", [])
            total += len(raw_entries)
            results.extend(
                _map_raw_entries(
                    raw_entries,
                    mode=mode,
                    library_id=library.id_,
                    library_name=library.name,
                    page=page,
                    limit=limit,
                )
            )
        elif mode == BrowseMode.NARRATORS:
            response = await client._get(f"/api/libraries/{library.id_}/narrators")
            payload = json.loads(response)
            raw_entries = payload.get("narrators", [])
            total += len(raw_entries)
            results.extend(
                _map_raw_entries(
                    raw_entries,
                    mode=mode,
                    library_id=library.id_,
                    library_name=library.name,
                    page=page,
                    limit=limit,
                )
            )
    return BrowsePage(items=results, total=total)


async def list_books_for_entry(
    client: AudiobookshelfClient, *, entry: BrowseEntry
) -> list[BookSearchResult]:
    raw_items: list[dict[str, Any]]
    if entry.mode == BrowseMode.SERIES:
        response = await client._get(f"/api/series/{entry.id}")
        raw_items = json.loads(response).get("books", [])
    elif entry.mode == BrowseMode.COLLECTIONS:
        response = await client._get(f"/api/collections/{entry.id}")
        raw_items = json.loads(response).get("books", [])
    elif entry.mode == BrowseMode.AUTHORS:
        response = await client._get(f"/api/authors/{entry.id}?include=items")
        raw_items = json.loads(response).get("libraryItems", [])
    elif entry.mode == BrowseMode.NARRATORS:
        raw_items = await _list_books_for_narrator(client, entry=entry)
    else:
        raw_items = []

    results: list[BookSearchResult] = []
    _append_mapped_books(
        results,
        raw_items,
        library_name=entry.library_name,
        seen_item_ids=set(),
        library_id=entry.library_id,
    )
    return results


def _library_media_type(library: Any) -> str:
    media_type = getattr(library, "media_type", None)
    if media_type is None:
        media_type = getattr(library, "mediaType", "")
    return str(getattr(media_type, "value", media_type))


async def _book_libraries(client: AudiobookshelfClient) -> list[Any]:
    return [
        library
        for library in await client.get_all_libraries()
        if _library_media_type(library) == "book"
    ]


async def _list_paged_group_entries(
    client: AudiobookshelfClient,
    *,
    library: Any,
    mode: BrowseMode,
    page: int,
    limit: int,
) -> BrowsePage[BrowseEntry]:
    endpoint_name = "series" if mode == BrowseMode.SERIES else "collections"
    response = await client._get(
        f"/api/libraries/{library.id_}/{endpoint_name}",
        params={"minified": 1, "limit": limit, "page": page},
    )
    payload = json.loads(response)
    return BrowsePage(
        items=_map_raw_entries(
            payload.get("results", []),
            mode=mode,
            library_id=library.id_,
            library_name=library.name,
            page=0,
            limit=limit,
        ),
        total=int(payload.get("total", 0)),
    )


def _map_raw_entries(
    raw_entries: list[dict[str, Any]],
    *,
    mode: BrowseMode,
    library_id: str,
    library_name: str,
    page: int,
    limit: int,
) -> list[BrowseEntry]:
    start = page * limit
    stop = start + limit
    entries: list[BrowseEntry] = []
    for raw_entry in raw_entries[start:stop]:
        entry_id = raw_entry.get("id")
        name = raw_entry.get("name")
        if not entry_id or not name:
            continue
        entries.append(
            BrowseEntry(
                mode=mode,
                id=str(entry_id),
                name=str(name),
                library_id=library_id,
                library_name=library_name,
                count=_entry_count(raw_entry),
            )
        )
    return entries


def _entry_count(raw_entry: dict[str, Any]) -> int:
    num_books = raw_entry.get("numBooks")
    if isinstance(num_books, int):
        return num_books
    books = raw_entry.get("books")
    if isinstance(books, list):
        return len(books)
    return 0


async def _list_books_for_narrator(
    client: AudiobookshelfClient, *, entry: BrowseEntry
) -> list[dict[str, Any]]:
    raw_items: list[dict[str, Any]] = []
    page = 0
    limit = 50
    filter_value = _filter_string("narrators", entry.name)
    while True:
        response = await client._get(
            f"/api/libraries/{entry.library_id}/items",
            params={
                "minified": 1,
                "limit": limit,
                "page": page,
                "filter": filter_value,
                "sort": "media.metadata.title",
            },
        )
        payload = json.loads(response)
        page_items = payload.get("results", [])
        raw_items.extend(page_items)
        total = int(payload.get("total", len(raw_items)))
        if not page_items or len(raw_items) >= total:
            return raw_items
        page += 1


def _filter_string(group: str, value: str) -> str:
    encoded = quote(b64encode(value.encode()).decode())
    return f"{group}.{encoded}"


def _append_mapped_books(
    results: list[BookSearchResult],
    raw_items: list[dict[str, Any]],
    *,
    library_name: str,
    seen_item_ids: set[str],
    library_id: str | None = None,
) -> None:
    for raw_item in raw_items:
        mapped = _map_book_result(raw_item, library_name=library_name)
        if mapped is None or mapped.id in seen_item_ids:
            continue
        if library_id is not None and mapped.library_id != library_id:
            continue
        results.append(mapped)
        seen_item_ids.add(mapped.id)


def _map_book_result(
    raw_result: dict[str, Any], *, library_name: str
) -> BookSearchResult | None:
    item = raw_result.get("libraryItem", raw_result)
    if item.get("mediaType") != "book":
        return None

    media = item.get("media", {})
    metadata = media.get("metadata", {})
    title = (
        metadata.get("title") or item.get("relPath") or item.get("path") or item["id"]
    )
    author = _author_name(metadata)

    return BookSearchResult(
        id=item["id"],
        library_id=item["libraryId"],
        library_name=library_name,
        title=title,
        author=author,
        duration=media.get("duration"),
        size=item.get("size") or media.get("size"),
    )


def _author_name(metadata: dict[str, Any]) -> str:
    author_name = metadata.get("authorName")
    if author_name:
        return str(author_name)
    authors = metadata.get("authors") or []
    names = [
        str(author["name"])
        for author in authors
        if isinstance(author, dict) and author.get("name")
    ]
    return ", ".join(names) if names else "Unknown Author"
