from __future__ import annotations

import json
from collections.abc import AsyncIterator
from dataclasses import dataclass
from logging import Logger
from typing import Any, Protocol

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
            if mapped is not None:
                results.append(mapped)
    return results


def _library_media_type(library: Any) -> str:
    media_type = getattr(library, "media_type", None)
    if media_type is None:
        media_type = getattr(library, "mediaType", "")
    return str(getattr(media_type, "value", media_type))


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
