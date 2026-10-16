from __future__ import annotations

import asyncio
from logging import Logger, getLogger
from pathlib import Path

import aiohttp
import click
import pydantic

from audiobookshelf_sync.api import get_client, sync_items
from audiobookshelf_sync.config import AppConfig, Server
from audiobookshelf_sync.download import download_pending_items
from audiobookshelf_sync.tui import SearchQueueApp

LOGGER = getLogger("audiobookshelf_sync")


@click.group(invoke_without_command=True)
@click.pass_context
def main(ctx: click.Context) -> None:
    """Search Audiobookshelf and download queued books."""

    # default to search TUI if no subcommand is provided
    if ctx.invoked_subcommand is None:
        search()


@main.command()
@click.option("--limit", default=25, show_default=True, help="Limit search results.")
@click.option("--source", help="Specify the source server to use.")
def search(limit: int, source: str | None = None) -> None:
    """Open the interactive search TUI."""
    try:
        app_config = AppConfig.model_validate({})
    except pydantic.ValidationError as e:
        click.echo(f"Configuration validation error: {e}", err=True)
        exit(1)
    source = source or app_config.default_source()
    assert source is not None
    if source not in app_config.config.servers:
        click.echo(f"Source server '{source}' not found in configuration.", err=True)
        exit(1)

    asyncio.run(
        run_search(
            server=app_config.config.servers[source],
            config_path=app_config.config_path,
            limit=limit,
            logger=LOGGER,
        )
    )


@main.command()
@click.option("--source", help="Specify the source server to use.")
def download(source: str | None = None) -> None:
    """Download all pending queue items."""
    try:
        app_config = AppConfig.model_validate({})
    except pydantic.ValidationError as e:
        click.echo(f"Configuration validation error: {e}", err=True)
        exit(1)
    source = source or app_config.default_source()
    assert source is not None
    if source not in app_config.config.servers:
        click.echo(f"Source server '{source}' not found in configuration.", err=True)
        exit(1)
    asyncio.run(
        run_download(
            server=app_config.config.servers[source], config=app_config, logger=LOGGER
        )
    )


@main.command()
@click.option("--source", help="Specify the source server to use.")
@click.option("--target", help="Specify the target server to use.")
@click.option("--target-library", help="Specify the target library name to use.")
def sync(
    source: str | None = None,
    target: str | None = None,
    target_library: str | None = None,
) -> None:
    """Sync items between source and target servers."""
    try:
        app_config = AppConfig.model_validate({})
    except pydantic.ValidationError as e:
        click.echo(f"Configuration validation error: {e}", err=True)
        exit(1)

    if app_config.default_source() is None and source is None:
        raise ValueError("No source specified.")
    source = source or app_config.default_source()
    target = target or app_config.default_target()
    if target is None:
        raise ValueError("No target specified.")
    if source not in app_config.config.servers:
        raise ValueError(f"Source server '{source}' not found in configuration.")
    if target not in app_config.config.servers:
        raise ValueError(f"Target server '{target}' not found in configuration.")
    source_server = app_config.config.servers[source]
    target_server = app_config.config.servers[target]

    target_library = target_library or target_server.target_library
    assert source_server is not None
    assert target_server is not None
    assert target_library is not None
    asyncio.run(
        run_sync(
            source=source_server,
            target=target_server,
            target_library=target_library,
            config=app_config,
            logger=LOGGER,
        )
    )


@main.group()
def configure() -> None:
    """Inspect configuration values from Audiobookshelf targets."""


@configure.command("dump-config")
def dump_config() -> None:
    """Dump the current configuration."""
    try:
        app_config = AppConfig.model_validate({})
    except pydantic.ValidationError as e:
        click.echo(f"Configuration validation error: {e}", err=True)
        exit(1)
    click.echo(app_config.model_dump_json(indent=2))


async def run_search(
    *, server: Server, config_path: Path, limit: int, logger: Logger
) -> None:
    async with aiohttp.ClientSession() as session:
        client = await get_client(session, server, logger)
        app = SearchQueueApp(client=client, queue_path=config_path, limit=limit)
        await app.run_async()


async def run_download(*, server: Server, config: AppConfig, logger: Logger) -> None:
    async with aiohttp.ClientSession() as session:
        client = await get_client(session, server, logger)
        await download_pending_items(
            client=client,
            app_config=config,
            reporter=click.echo,
        )


async def run_sync(
    *,
    source: Server,
    target: Server,
    target_library: str,
    config: AppConfig,
    logger: Logger,
) -> None:
    async with aiohttp.ClientSession() as session:
        source_client = await get_client(session, source, logger)
        target_client = await get_client(session, target, logger)
        await sync_items(
            source_client=source_client,
            target_client=target_client,
            target_library=target_library,
            app_config=config,
            reporter=click.echo,
        )


if __name__ == "__main__":
    main()
