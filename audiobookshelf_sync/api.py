from __future__ import annotations

import asyncio
import json
import re
from base64 import b64encode
from collections.abc import Awaitable, Callable
from contextlib import ExitStack
from dataclasses import dataclass
from enum import StrEnum
from logging import Logger
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, Protocol
from urllib.parse import quote, urljoin

import aiohttp
import click
from aioaudiobookshelf import (
    SessionConfiguration,
    get_user_client,
    get_user_client_by_token,
)
from aioaudiobookshelf.schema.library import LibraryItemBook, LibraryItemExpandedBook

from audiobookshelf_sync.config import AppConfig, Server
from audiobookshelf_sync.queue import QueueItem, QueueStatus

UNSAFE_PATH_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def sanitize_path_part(value: str) -> str:
    sanitized = UNSAFE_PATH_CHARS.sub("_", value).strip().rstrip(".")
    sanitized = re.sub(r"_\s+_", "_ ", sanitized)
    sanitized = re.sub(r"_+", "_", sanitized)
    sanitized = sanitized.strip("_")
    return sanitized or "untitled"


@dataclass(frozen=True)
class BookSearchResult:
    id: str
    library_id: str
    library_name: str
    title: str
    author: str
    duration: float | None
    size: int | None
    author_last_first: str | None = None
    added_at: int | None = None
    published_year: int | None = None
    author_known: bool = True


class BookSort(StrEnum):
    AUTHOR_FIRST_LAST = "author_first_last"
    AUTHOR_LAST_FIRST = "author_last_first"
    TITLE = "title"
    ADDED_AT = "added_at"
    PUBLISH_YEAR = "publish_year"

    @property
    def api_field(self) -> str:
        return {
            BookSort.AUTHOR_FIRST_LAST: "media.metadata.authorName",
            BookSort.AUTHOR_LAST_FIRST: "media.metadata.authorNameLF",
            BookSort.TITLE: "media.metadata.title",
            BookSort.ADDED_AT: "addedAt",
            BookSort.PUBLISH_YEAR: "media.metadata.publishedYear",
        }[self]


def sort_books(
    books: list[BookSearchResult], *, sort: BookSort, descending: bool
) -> list[BookSearchResult]:
    def primary(book: BookSearchResult) -> str | int | None:
        match sort:
            case BookSort.AUTHOR_FIRST_LAST:
                return (book.author.casefold() or None) if book.author_known else None
            case BookSort.AUTHOR_LAST_FIRST:
                return (
                    book.author_last_first.casefold()
                    if book.author_last_first
                    else None
                )
            case BookSort.TITLE:
                return book.title.casefold() or None
            case BookSort.ADDED_AT:
                return book.added_at
            case BookSort.PUBLISH_YEAR:
                return book.published_year

    ordered = sorted(books, key=lambda book: (book.title.casefold(), book.id))
    known = [book for book in ordered if primary(book) is not None]
    unknown = [book for book in ordered if primary(book) is None]
    if sort in (BookSort.ADDED_AT, BookSort.PUBLISH_YEAR):
        known.sort(key=lambda book: int(primary(book) or 0), reverse=descending)
    else:
        known.sort(key=lambda book: str(primary(book) or ""), reverse=descending)
    return [*known, *unknown]


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
    session_config: SessionConfiguration

    async def get_all_libraries(self) -> list[Any]: ...

    async def _get(
        self, endpoint: str, params: dict[str, str | int] | None = None
    ) -> bytes: ...

    async def _patch(self, endpoint: str, data: dict[str, Any]) -> bytes: ...

    async def get_library_item_book(
        self, *, book_id: str, expanded: bool = False
    ) -> LibraryItemBook | LibraryItemExpandedBook: ...


async def get_client(
    session: aiohttp.ClientSession, config: Server, logger: Logger
) -> AudiobookshelfClient:
    assert config.url is not None
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
            author_response = await client._get(
                f"/api/authors/{author_id}?include=items"
            )
            author_payload = json.loads(author_response)
            for raw_item in author_payload.get("libraryItems", []):
                mapped = _map_book_result(raw_item, library_name=library.name)
                if mapped is not None and mapped.id not in seen_item_ids:
                    results.append(mapped)
                    seen_item_ids.add(mapped.id)
    return results


async def list_books(
    client: AudiobookshelfClient,
    *,
    page: int,
    limit: int,
    sort: BookSort = BookSort.ADDED_AT,
    descending: bool = True,
) -> BrowsePage[BookSearchResult]:
    results: list[BookSearchResult] = []
    total = 0
    seen_item_ids: set[str] = set()
    for library in await _book_libraries(client):
        response = await client._get(
            f"/api/libraries/{library.id_}/items",
            params={
                "minified": 1,
                "limit": (page + 1) * limit,
                "page": 0,
                "sort": sort.api_field,
                "desc": int(descending),
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
    ordered = sort_books(results, sort=sort, descending=descending)
    return BrowsePage(items=ordered[page * limit : (page + 1) * limit], total=total)


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
        author_last_first=metadata.get("authorNameLF"),
        added_at=item.get("addedAt"),
        published_year=_published_year(metadata.get("publishedYear")),
        author_known=bool(metadata.get("authorName") or metadata.get("authors")),
    )


def _published_year(value: object) -> int | None:
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdecimal():
        return int(value)
    return None


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


@dataclass
class PendingUpload:
    source: dict[str, Any]
    title: str
    library_id: str
    items: list[QueueItem]


SYNC_INDEX_ATTEMPTS = 60
SYNC_INDEX_POLL_INTERVAL = 5


async def sync_items(
    *,
    source_client: AudiobookshelfClient,
    target_client: AudiobookshelfClient,
    target_library: str,
    app_config: AppConfig,
    reporter: Callable[[str], None],
    confirm_overwrite: Callable[[str], Awaitable[bool]] | None = None,
) -> None:
    if not app_config.config.items:
        reporter("No queued items to sync.")
        return
    items = []
    for item in app_config.config.items:
        if item.status == QueueStatus.SYNCHRONISED:
            reporter(f"Skipping synchronised: {item.title}")
        else:
            items.append(item)
    if not items:
        reporter("No pending items to sync.")
        return
    if source_client.session_config.url.rstrip(
        "/"
    ) == target_client.session_config.url.rstrip("/"):
        raise ValueError("Source and target must be different servers.")
    libraries = await _book_libraries(target_client)
    inventory = {
        library.id_: await _sync_library_items(target_client, library.id_)
        for library in libraries
    }
    failures = 0
    uploads: list[PendingUpload] = []
    for queued in items:
        try:
            source = json.loads(
                await source_client._get(
                    f"/api/items/{queued.id}", params={"expanded": 1}
                )
            )
            if source.get("mediaType") != "book":
                raise ValueError("Only books can be synced.")
            media = _sync_media(source)
            if not media["metadata"].get("title"):
                raise ValueError("Source book has no title.")
            matches = [
                item
                for items in inventory.values()
                for item in items
                if _same_book(source, item)
            ]
            if len(matches) > 1:
                raise ValueError(
                    "Multiple target books match; refusing an ambiguous overwrite."
                )
            if matches:
                target = json.loads(
                    await target_client._get(f"/api/items/{matches[0]['id']}")
                )
                target_media = _sync_media(target)
                if media == target_media:
                    app_config.mark_synchronised([queued])
                    reporter(f"Already synced: {queued.title}")
                    continue
                reporter(
                    f"Metadata changes for {queued.title}: {', '.join(key for key in media if media[key] != target_media[key])}"
                )
                prompt = f"Overwrite target metadata for '{queued.title}'?"
                confirmed = (
                    await confirm_overwrite(prompt)
                    if confirm_overwrite is not None
                    else click.confirm(prompt, default=False)
                )
                if not confirmed:
                    reporter(f"Skipped: {queued.title}")
                    continue
            else:
                pending_upload = next(
                    (upload for upload in uploads if _same_book(source, upload.source)),
                    None,
                )
                if pending_upload is not None:
                    pending_upload.items.append(queued)
                    reporter(f"Already uploaded; awaiting indexing: {queued.title}")
                    continue
                destinations = [
                    library for library in libraries if target_library == library.name
                ]
                if not destinations and len(libraries) == 1:
                    destinations = libraries
                if len(destinations) != 1 or len(destinations[0].folders) != 1:
                    raise ValueError(
                        "A unique target book library and folder are required."
                    )
                library = destinations[0]
                reporter(f"Uploading: {queued.title} to {library.name}")
                await _upload_sync_book(
                    source_client, target_client, source, library, reporter=reporter
                )
                uploads.append(
                    PendingUpload(source, queued.title, library.id_, [queued])
                )
                reporter(f"Uploaded; awaiting indexing: {queued.title}")
                continue
            updated = await _apply_sync_metadata(target_client, target, media)
            for items in inventory.values():
                for index, item in enumerate(items):
                    if item["id"] == updated["id"]:
                        items[index] = updated
            app_config.mark_synchronised([queued])
            reporter(f"Synced: {queued.title}")
        except Exception as error:  # noqa: BLE001 - report item failures and continue the queue.
            if isinstance(error, click.Abort):
                raise
            failures += 1
            reporter(f"Failed: {queued.title}: {error}")
    if uploads:
        failures += await _finish_uploaded_books(
            target_client, uploads, app_config, reporter
        )
    if failures:
        raise ValueError(f"Sync failed for {failures} item(s).")


async def _apply_sync_metadata(
    client: AudiobookshelfClient, target: dict[str, Any], media: dict[str, Any]
) -> dict[str, Any]:
    await client._patch(f"/api/items/{target['id']}/media", data=media)
    updated = json.loads(await client._get(f"/api/items/{target['id']}"))
    if _sync_media(updated) != media:
        raise ValueError("Target metadata does not match the source after updating.")
    return updated


async def _finish_uploaded_books(
    client: AudiobookshelfClient,
    uploads: list[PendingUpload],
    app_config: AppConfig,
    reporter: Callable[[str], None],
) -> int:
    reporter("Uploads complete. Requesting target library scans.")
    config = client.session_config
    for library_id in dict.fromkeys(upload.library_id for upload in uploads):
        try:
            async with config.session.post(
                f"{config.url.rstrip('/')}/api/libraries/{quote(library_id, safe='')}/scan",
                headers=config.headers,
                ssl=config.verify_ssl,
                timeout=config.timeout,
            ) as response:
                response.raise_for_status()
                await response.read()
            reporter(f"Scan requested: {library_id}")
        except (aiohttp.ClientError, TimeoutError) as error:
            reporter(
                f"Could not request scan for {library_id}: {error}. Waiting for indexing."
            )
    reporter(f"Waiting for {len(uploads)} book(s) to be indexed (up to 5 minutes).")
    failures = 0
    pending = list(uploads)
    for _ in range(SYNC_INDEX_ATTEMPTS):
        await asyncio.sleep(SYNC_INDEX_POLL_INTERVAL)
        inventory: dict[str, list[dict[str, Any]]] = {}
        for upload in list(pending):
            try:
                if upload.library_id not in inventory:
                    inventory[upload.library_id] = await _sync_library_items(
                        client, upload.library_id
                    )
                matches = [
                    item
                    for item in inventory[upload.library_id]
                    if _same_book(upload.source, item)
                ]
                if not matches:
                    continue
                if len(matches) > 1:
                    raise ValueError("Uploaded book has multiple target matches.")
                await _apply_sync_metadata(
                    client, matches[0], _sync_media(upload.source)
                )
                app_config.mark_synchronised(upload.items)
                reporter(f"Synced: {upload.title}")
            except Exception as error:  # noqa: BLE001 - finish other accepted uploads.
                if isinstance(error, click.Abort):
                    raise
                failures += 1
                reporter(f"Failed: {upload.title}: {error}")
            pending.remove(upload)
        if not pending:
            break
    for upload in pending:
        reporter(
            f"Uploaded; indexing still pending: {upload.title}. "
            "Run sync again after indexing finishes to apply metadata."
        )
    return failures


async def _sync_library_items(client: Any, library_id: str) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    page = 0
    while True:
        payload = json.loads(
            await client._get(
                f"/api/libraries/{library_id}/items",
                params={"limit": 100, "page": page},
            )
        )
        batch = payload.get("results", [])
        items.extend(batch)
        if len(items) >= payload.get("total", len(items)):
            return items
        if not batch:
            raise ValueError(
                "Target library pagination ended before all items were returned."
            )
        page += 1


def _sync_media(item: dict[str, Any]) -> dict[str, Any]:
    media = item["media"]
    raw = media["metadata"]
    fields = (
        "title",
        "subtitle",
        "narrators",
        "genres",
        "publishedYear",
        "publishedDate",
        "publisher",
        "description",
        "isbn",
        "asin",
        "language",
        "explicit",
    )
    metadata = {key: raw[key] for key in fields if key in raw}
    metadata["authors"] = [
        {"name": author["name"]} for author in raw.get("authors", [])
    ]
    metadata["series"] = [
        {"name": series["name"], "sequence": series.get("sequence")}
        for series in raw.get("series", [])
    ]
    return {"metadata": metadata, "tags": media.get("tags") or []}


def _same_book(source: dict[str, Any], target: dict[str, Any]) -> bool:
    if target.get("mediaType") != "book":
        return False
    left, right = source["media"]["metadata"], target["media"]["metadata"]
    for key in ("asin", "isbn"):
        if left.get(key) and right.get(key):
            return (
                str(left[key]).strip().casefold() == str(right[key]).strip().casefold()
            )
    return bool(left.get("title")) and (
        str(left["title"]).strip().casefold(),
        _author_name(left).strip().casefold(),
    ) == (
        str(right.get("title", "")).strip().casefold(),
        _author_name(right).strip().casefold(),
    )


async def _upload_sync_book(
    source_client: AudiobookshelfClient,
    target_client: AudiobookshelfClient,
    source: dict[str, Any],
    library: Any,
    *,
    reporter: Callable[[str], None],
) -> None:
    book = await source_client.get_library_item_book(
        book_id=source["id"], expanded=True
    )
    if not isinstance(book, LibraryItemExpandedBook):
        raise ValueError("Source book is not an expanded library item.")
    if not book.media.tracks:
        raise ValueError("Source book has no audio tracks.")
    has_cover = bool(source["media"].get("coverPath"))
    file_count = len(book.media.tracks) + int(has_cover)
    with (
        TemporaryDirectory(prefix="audiobookshelf-sync-") as directory,
        ExitStack() as files,
    ):
        form = aiohttp.FormData()
        form.add_field("title", source["media"]["metadata"]["title"])
        form.add_field("author", _author_name(source["media"]["metadata"]))
        form.add_field("library", library.id_)
        form.add_field("folder", library.folders[0].id_)
        for number, track in enumerate(book.media.tracks, start=1):
            filename = track_filename(track, track_number=number)
            destination = Path(directory) / f"{number}-{filename}"
            reporter(f"Downloading file {number}/{file_count}: {filename}")
            await download_track(
                client=source_client,
                content_url=track.content_url,
                destination=destination,
            )
            reporter(f"Prepared file {number}/{file_count}: {filename}")
            form.add_field(
                str(number),
                files.enter_context(destination.open("rb")),
                filename=f"{number:04d}-{filename}",
            )
        if has_cover:
            reporter(f"Downloading file {file_count}/{file_count}: cover.jpg")
            cover_path = Path(directory) / "cover.jpg"
            await download_track(
                client=source_client,
                content_url=f"/api/items/{source['id']}/cover?raw=1&format=jpeg",
                destination=cover_path,
            )
            reporter(f"Prepared file {file_count}/{file_count}: cover.jpg")
            form.add_field(
                "cover",
                files.enter_context(cover_path.open("rb")),
                filename="cover.jpg",
                content_type="image/jpeg",
            )
        config = target_client.session_config
        reporter(f"Uploading {file_count} file(s) to {library.name}")
        async with config.session.post(
            f"{config.url.rstrip('/')}/api/upload",
            data=form,
            headers=config.headers,
            ssl=config.verify_ssl,
            timeout=config.timeout,
        ) as response:
            response.raise_for_status()
            await response.read()
        reporter(f"Uploaded {file_count}/{file_count} file(s)")


async def download_track(
    *, client: AudiobookshelfClient, content_url: str, destination: Path
) -> None:
    url = urljoin(f"{client.session_config.url.rstrip('/')}/", content_url.lstrip("/"))
    temporary_destination = destination.with_suffix(destination.suffix + ".part")
    async with client.session_config.session.get(
        url,
        ssl=client.session_config.verify_ssl,
        headers=client.session_config.headers,
        timeout=client.session_config.timeout,
    ) as response:
        response.raise_for_status()
        with temporary_destination.open("wb") as handle:
            async for chunk in response.content.iter_chunked(1024 * 256):
                if chunk:
                    handle.write(chunk)
    temporary_destination.replace(destination)


def _suffix_for_mime_type(mime_type: str | None) -> str:
    if mime_type == "audio/mp4":
        return ".m4a"
    if mime_type == "audio/ogg":
        return ".ogg"
    if mime_type == "audio/flac":
        return ".flac"
    return ".mp3"


def track_filename(track: Any, *, track_number: int) -> str:
    metadata = getattr(track, "metadata", None)
    metadata_filename = (
        getattr(metadata, "filename", None) if metadata is not None else None
    )
    if metadata_filename:
        return sanitize_path_part(str(metadata_filename))

    title = getattr(track, "title", None) or f"Track {track_number}"
    suffix = _suffix_for_mime_type(getattr(track, "mime_type", None))
    return f"{track_number:02d} {sanitize_path_part(str(title))}{suffix}"
