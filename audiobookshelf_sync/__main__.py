import json
import uuid
from pydantic import BaseModel, model_validator, Field
from typing import List, Dict, Any, Optional
import sys
import asyncio
import aiohttp
from logging import getLogger, Logger
import click
from aioaudiobookshelf import SessionConfiguration, get_user_client_by_token
from aioaudiobookshelf.exceptions import ApiError, NotFoundError

from audiobookshelf_sync.config import Config


class SearchResultAuthor(BaseModel):
    id: str
    library_id: uuid.UUID = Field(..., alias="libraryId")
    name: str
    description: Optional[str] = None
    image_path: Optional[str] = Field(None, alias="imagePath")
    asin: Optional[str] = None
    added_at: Optional[int] = Field(None, alias="addedAt")
    updated_at: Optional[int] = Field(None, alias="updatedAt")

    @model_validator(mode="before")
    def validate_input(cls, input: Dict[str, Any]) -> Dict[str, Any]:
        print(json.dumps(input, indent=4))
        return input


class SearchResultBook(BaseModel):
    id: str
    ino: str
    # oldLibrar: Optional[str] = None
    library_id: uuid.UUID = Field(..., alias="libraryId")
    folder_id: Optional[str] = Field(None, alias="folderId")
    path: Optional[str] = None
    rel_path: Optional[str] = Field(None, alias="relPath")
    is_file: Optional[bool] = Field(False, alias="isFile")
    mtime_ms: Optional[int] = Field(None, alias="mtimeMs")
    ctime_ms: Optional[int] = Field(None, alias="ctimeMs")
    birthtime: Optional[int] = None
    added_at: Optional[int] = Field(None, alias="addedAt")
    updated_at: Optional[int] = Field(None, alias="updatedAt")
    last_scan: Optional[int] = Field(None, alias="lastScan")
    scan_version: Optional[int] = Field(None, alias="scanVersi")
    is_missing: Optional[int] = Field(None, alias="isMissing")
    is_invalid: Optional[int] = Field(None, alias="isInvalid")
    media_type: Optional[str] = Field(None, alias="mediaType")

    @model_validator(mode="before")
    def validate_input(cls, input: Dict[str, Any]) -> Dict[str, Any]:
        return input["libraryItem"]


class SearchResult(BaseModel):
    book: List[SearchResultBook]
    authors: List[SearchResultAuthor]


async def do_search(
    logger: Logger, config: Config, args: list[str], limit: int
) -> None:
    logger.info("Doing search!")

    async with aiohttp.ClientSession() as session:
        client = await get_user_client_by_token(
            session_config=SessionConfiguration(
                session=session,
                url=config.url,
                logger=logger,
                pagination_items_per_page=30,
                token=config.token,
            ),
        )

        for library in await client.get_all_libraries():
            logger.info(f"Library: {library.name} ({library.id_})")
            try:
                res = await client._get(
                    f"/api/libraries/{library.id_}/search",
                    params={"q": " ".join(args), "limit": limit},
                )
                searchresult = SearchResult.model_validate_json(res)
                # logger.info(searchresult.model_dump_json(indent=4))
                print(searchresult.model_dump_json(indent=4))
            except ApiError as e:
                logger.error(f"Error fetching items for library {library.name}: {e}")
            except NotFoundError as e:
                logger.error(f"Library {library.name} not found {e=} {library.id_=}")


async def async_main(
    logger: Logger, config: Config, command: str, args: list[str], limit: int
) -> None:

    if command == "search":
        await do_search(logger, config, args, limit=limit)
    else:
        logger.error(f"Unknown command: {command}")
        sys.exit(1)


@click.command()
@click.argument("command")
@click.option("--limit", default=25, help="Limit the number of search results")
@click.argument("args", nargs=-1)
def main(command: str, limit: int, args: list[str]) -> None:
    logger = getLogger("audiobookshelf_sync")
    logger.setLevel("DEBUG")
    config = Config.model_validate({})
    asyncio.run(async_main(logger, config, command, args=args, limit=limit))


if __name__ == "__main__":
    main()
