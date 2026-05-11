from __future__ import annotations

import asyncio
from logging import Logger, getLogger
from pathlib import Path

import aiohttp
import click

from audiobookshelf_sync.api import get_client
from audiobookshelf_sync.config import Config
from audiobookshelf_sync.download import download_pending_items
from audiobookshelf_sync.queue import QUEUE_FILE
from audiobookshelf_sync.tui import SearchQueueApp


@click.group()
def main() -> None:
    """Search Audiobookshelf and download queued books."""


@main.command()
@click.option("--limit", default=25, show_default=True, help="Limit search results.")
def search(limit: int) -> None:
    """Open the interactive search TUI."""
    logger = getLogger("audiobookshelf_sync")
    config = Config.model_validate({})
    asyncio.run(run_search(config=config, limit=limit, logger=logger))


@main.command()
def download() -> None:
    """Download all pending queue items."""
    logger = getLogger("audiobookshelf_sync")
    config = Config.model_validate({})
    asyncio.run(run_download(config=config, logger=logger))


async def run_search(*, config: Config, limit: int, logger: Logger) -> None:
    async with aiohttp.ClientSession() as session:
        client = await get_client(session, config, logger)
        app = SearchQueueApp(client=client, queue_path=QUEUE_FILE, limit=limit)
        await app.run_async()


async def run_download(*, config: Config, logger: Logger) -> None:
    async with aiohttp.ClientSession() as session:
        client = await get_client(session, config, logger)
        await download_pending_items(
            client=client,
            queue_path=QUEUE_FILE,
            download_dir=Path(config.download_dir),
            reporter=click.echo,
        )


if __name__ == "__main__":
    main()
