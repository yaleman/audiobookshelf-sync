from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from urllib.parse import urljoin

from aioaudiobookshelf.schema.library import LibraryItemExpandedBook

from audiobookshelf_sync.api import (
    AudiobookshelfClient,
    download_track,
    sanitize_path_part,
    track_filename,
)

from .config import AppConfig
from .queue import QueueStatus

Reporter = Callable[[str], None]


async def download_pending_items(
    *,
    client: AudiobookshelfClient,
    app_config: AppConfig,
    reporter: Reporter | None = None,
) -> None:
    report = reporter or _ignore_progress
    report(
        f"Download directory: {relative_to_queue(app_config.config_path, app_config.download_dir)}"
    )
    processed_count = 0
    done_count = 0
    failed_count = 0

    assert app_config.config is not None, "AppConfig must have a loaded ConfigFile"
    for item_id in [item.id for item in app_config.config.items]:
        item = app_config.config.find_item(item_id)
        if item is None:
            continue
        if item.status == QueueStatus.DONE or (
            item.status == QueueStatus.SYNCHRONISED and item.downloaded_at is not None
        ):
            report(f"Skipping done: {item.title}")
            continue

        processed_count += 1
        report(f"Starting: {item.title} - {item.author}")
        item.mark_downloading()
        app_config.save_download_state(item, status=QueueStatus.DOWNLOADING)
        output_dir = app_config.download_dir / sanitize_path_part(
            f"{item.author} - {item.title}"
        )
        try:
            report(f"Fetching metadata: {item.title}")
            book = await client.get_library_item_book(book_id=item.id, expanded=True)
            assert isinstance(book, LibraryItemExpandedBook)
            output_dir.mkdir(parents=True, exist_ok=True)
            tracks = list(book.media.tracks)
            report(
                f"Downloading {len(tracks)} track(s) to "
                f"{relative_to_queue(app_config.config_path, output_dir)}"
            )
            for track_number, track in enumerate(tracks, start=1):
                filename = track_filename(track, track_number=track_number)
                destination = output_dir / filename
                if destination.exists():
                    report(
                        f"Skipping existing track {track_number}/{len(tracks)}: "
                        f"{filename}"
                    )
                    continue
                report(f"Downloading track {track_number}/{len(tracks)}: {filename}")
                await download_track(
                    client=client,
                    content_url=track.content_url,
                    destination=destination,
                )
                report(f"Finished track {track_number}/{len(tracks)}: {filename}")
            item.mark_done(
                output_dir=relative_to_queue(app_config.config_path, output_dir)
            )
            status = QueueStatus.DONE
            done_count += 1
            report(f"Done: {item.title}")
        except Exception as error:  # noqa: BLE001 - record the queue failure and continue.
            item.mark_failed(error)
            status = QueueStatus.FAILED
            failed_count += 1
            report(f"Failed: {item.title}: {error}")
        app_config.save_download_state(item, status=status)

    if processed_count == 0:
        report("No pending downloads.")
    else:
        report(
            f"Processed {processed_count} item(s): "
            f"{done_count} done, {failed_count} failed"
        )


def resolve_content_url(base_url: str, content_url: str) -> str:
    return urljoin(f"{base_url.rstrip('/')}/", content_url.lstrip("/"))


def relative_to_queue(config_path: Path, output_dir: Path) -> Path:
    try:
        return output_dir.relative_to(config_path.parent)
    except ValueError:
        return output_dir


def _ignore_progress(message: str) -> None:
    _ = message
