from __future__ import annotations

from collections.abc import Callable
import re
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

from audiobookshelf_sync.queue import (
    QUEUE_FILE,
    QueueStatus,
    load_queue,
    mark_done,
    mark_downloading,
    mark_failed,
    save_queue,
)


UNSAFE_PATH_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
Reporter = Callable[[str], None]


def sanitize_path_part(value: str) -> str:
    sanitized = UNSAFE_PATH_CHARS.sub("_", value).strip().rstrip(".")
    sanitized = re.sub(r"_\s+_", "_ ", sanitized)
    sanitized = re.sub(r"_+", "_", sanitized)
    sanitized = sanitized.strip("_")
    return sanitized or "untitled"


async def download_pending_items(
    *,
    client: Any,
    queue_path: Path = QUEUE_FILE,
    download_dir: Path,
    reporter: Reporter | None = None,
) -> None:
    report = reporter or _ignore_progress
    queue = load_queue(queue_path)
    report(f"Queue file: {queue_path.name}")
    report(f"Download directory: {relative_to_queue(queue_path, download_dir)}")
    processed_count = 0
    done_count = 0
    failed_count = 0

    for item in queue.items:
        if item.status == QueueStatus.DONE:
            report(f"Skipping done: {item.title}")
            continue

        processed_count += 1
        report(f"Starting: {item.title} - {item.author}")
        mark_downloading(item)
        save_queue(queue_path, queue)
        output_dir = download_dir / sanitize_path_part(f"{item.author} - {item.title}")
        try:
            report(f"Fetching metadata: {item.title}")
            book = await client.get_library_item_book(book_id=item.id, expanded=True)
            output_dir.mkdir(parents=True, exist_ok=True)
            tracks = list(book.media.tracks)
            report(
                f"Downloading {len(tracks)} track(s) to "
                f"{relative_to_queue(queue_path, output_dir)}"
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
            mark_done(item, output_dir=relative_to_queue(queue_path, output_dir))
            done_count += 1
            report(f"Done: {item.title}")
        except Exception as error:  # noqa: BLE001 - record the queue failure and continue.
            mark_failed(item, error)
            failed_count += 1
            report(f"Failed: {item.title}: {error}")
        save_queue(queue_path, queue)

    if processed_count == 0:
        report("No pending downloads.")
    else:
        report(
            f"Processed {processed_count} item(s): "
            f"{done_count} done, {failed_count} failed"
        )


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


async def download_track(*, client: Any, content_url: str, destination: Path) -> None:
    url = resolve_content_url(client.session_config.url, content_url)
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


def resolve_content_url(base_url: str, content_url: str) -> str:
    return urljoin(f"{base_url.rstrip('/')}/", content_url.lstrip("/"))


def relative_to_queue(queue_path: Path, output_dir: Path) -> Path:
    try:
        return output_dir.relative_to(queue_path.parent)
    except ValueError:
        return output_dir


def _suffix_for_mime_type(mime_type: str | None) -> str:
    if mime_type == "audio/mp4":
        return ".m4a"
    if mime_type == "audio/ogg":
        return ".ogg"
    if mime_type == "audio/flac":
        return ".flac"
    return ".mp3"


def _ignore_progress(message: str) -> None:
    _ = message
