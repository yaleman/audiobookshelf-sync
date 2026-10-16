import json
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock, Mock

import aiohttp
import pytest
from aioaudiobookshelf.schema.audio import AudioTrack

from audiobookshelf_sync.api import _upload_sync_book, sync_items
from audiobookshelf_sync.config import AppConfig, ConfigFile
from audiobookshelf_sync.queue import QueueItem, QueueStatus
from audiobookshelf_sync.test import (
    FakeClient,
    FakeResponse,
    FakeSession,
    expanded_book,
)


def book(item_id: str, description: str = "source") -> dict[str, Any]:
    return {
        "id": item_id,
        "libraryId": "books",
        "mediaType": "book",
        "media": {
            "metadata": {
                "title": "Dune",
                "description": description,
                "authors": [{"id": item_id, "name": "Frank Herbert"}],
                "series": [{"id": item_id, "name": "Dune", "sequence": "1"}],
            },
            "tags": ["science fiction"],
        },
    }


class SyncClient(FakeClient):
    def __init__(self, url: str, items: list[dict[str, Any]]) -> None:
        super().__init__()
        self.session_config.url = url
        self.items = items
        self.patches: list[dict[str, Any]] = []

    async def get_all_libraries(self) -> list[Any]:
        return [
            SimpleNamespace(
                id_="books",
                name="Books",
                media_type="book",
                folders=[SimpleNamespace(id_="folder")],
            )
        ]

    async def _get(self, endpoint: str, params: Any = None) -> bytes:
        if endpoint == "/api/libraries/books/items":
            assert params == {"limit": 100, "page": 0}
            return json.dumps(
                {"results": self.items, "total": len(self.items)}
            ).encode()
        item_id = endpoint.rsplit("/", 1)[1]
        return json.dumps(
            next(item for item in self.items if item["id"] == item_id)
        ).encode()


@pytest.mark.anyio
@pytest.mark.parametrize("confirm", [True, False])
async def test_sync_confirms_metadata_overwrite(
    monkeypatch: pytest.MonkeyPatch, confirm: bool
) -> None:
    source = SyncClient("https://source", [book("source")])
    target = SyncClient("https://target", [book("target", "old")])
    prompts: list[str] = []

    def confirm_overwrite(prompt: str, *, default: bool) -> bool:
        assert default is False
        prompts.append(prompt)
        return confirm

    monkeypatch.setattr("audiobookshelf_sync.api.click.confirm", confirm_overwrite)
    config = AppConfig(
        config=ConfigFile(
            items=[
                QueueItem(
                    id="source",
                    library_id="books",
                    title="Dune",
                    author="Frank Herbert",
                )
            ]
        )
    )
    reports: list[str] = []
    await sync_items(
        source_client=source,
        target_client=target,
        target_library="test",
        app_config=config,
        reporter=reports.append,
    )
    assert len(prompts) == 1
    assert len(target.patches) == int(confirm)
    if confirm:
        assert target.patches[0]["metadata"]["authors"] == [{"name": "Frank Herbert"}]
        assert target.patches[0]["metadata"]["series"] == [
            {"name": "Dune", "sequence": "1"}
        ]
    assert config.config.items[0].status == (
        QueueStatus.SYNCHRONISED if confirm else QueueStatus.PENDING
    )
    if confirm:
        assert (
            ConfigFile.load(config.config_path).items[0].status
            == QueueStatus.SYNCHRONISED
        )


@pytest.mark.anyio
@pytest.mark.parametrize("count", [0, 1, 2])
async def test_sync_missing_identical_and_ambiguous_books(
    monkeypatch: pytest.MonkeyPatch, count: int
) -> None:
    source = SyncClient("https://source", [book("source")])
    target = SyncClient("https://target", [book("target") for _ in range(count)])
    upload = AsyncMock(
        side_effect=lambda *args, **kwargs: target.items.append(book("target"))
    )
    monkeypatch.setattr("audiobookshelf_sync.api._upload_sync_book", upload)
    config = AppConfig(
        config=ConfigFile(
            items=[
                QueueItem(
                    id="source",
                    library_id="books",
                    title="Dune",
                    author="Frank Herbert",
                )
            ]
        )
    )
    reports: list[str] = []
    sleep = AsyncMock()
    monkeypatch.setattr("audiobookshelf_sync.api.asyncio.sleep", sleep)
    target.session_config.session = cast(
        aiohttp.ClientSession,
        FakeSession(post_handler=lambda *args, **kwargs: FakeResponse(b"OK")),
    )
    if count == 2:
        with pytest.raises(ValueError, match="Sync failed"):
            await sync_items(
                source_client=source,
                target_client=target,
                target_library="test",
                app_config=config,
                reporter=reports.append,
            )
        assert "ambiguous" in reports[0]
    else:
        await sync_items(
            source_client=source,
            target_client=target,
            target_library="test",
            app_config=config,
            reporter=reports.append,
        )
    assert upload.await_count == int(count == 0)
    assert len(target.patches) == int(count == 0)
    if count != 2:
        assert (
            ConfigFile.load(config.config_path).items[0].status
            == QueueStatus.SYNCHRONISED
        )
    if count == 0:
        assert upload.await_args is not None
        assert upload.await_args.kwargs["reporter"] == reports.append


@pytest.mark.anyio
@pytest.mark.parametrize("with_cover", [False, True])
@pytest.mark.parametrize("upload_status", [200, 500])
async def test_upload_streams_tracks_and_cover(
    with_cover: bool, upload_status: int
) -> None:
    session = FakeSession(
        {
            "https://source/track": b"track",
            "https://source/track-two": b"track-two",
            "https://source/api/items/source/cover?raw=1&format=jpeg": b"cover",
        }
    )
    posted: list[str] = []

    def post(url: str, *, data: Any, **kwargs: Any) -> FakeResponse:
        posted.append(url)
        fields = {options["name"]: value for options, headers, value in data._fields}
        assert fields["library"] == "books"
        assert fields["folder"] == "folder"
        assert fields["1"].read() == b"track"
        assert fields["2"].read() == b"track-two"
        if with_cover:
            assert fields["cover"].read() == b"cover"
        else:
            assert "cover" not in fields
        return FakeResponse(b"OK", status=upload_status)

    source = FakeClient(
        url="https://source",
        session=session,
        books={
            "source": expanded_book(
                "source",
                tracks=[
                    AudioTrack(
                        index=0,
                        start_offset=0,
                        duration=1,
                        title="Track",
                        content_url="/track",
                        metadata=None,
                    ),
                    AudioTrack(
                        index=1,
                        start_offset=1,
                        duration=1,
                        title="Track Two",
                        content_url="/track-two",
                        metadata=None,
                    ),
                ],
            )
        },
    )
    target = FakeClient(url="https://target/", session=FakeSession(post_handler=post))
    library = SimpleNamespace(
        id_="books", name="Books", folders=[SimpleNamespace(id_="folder")]
    )
    item = book("source")
    if with_cover:
        item["media"]["coverPath"] = "/source/cover.jpg"
    reports: list[str] = []
    if upload_status == 500:
        with pytest.raises(RuntimeError, match="HTTP 500"):
            await _upload_sync_book(
                source, target, item, library, reporter=reports.append
            )
    else:
        await _upload_sync_book(source, target, item, library, reporter=reports.append)
    assert posted == ["https://target/api/upload"]
    expected_urls = ["https://source/track", "https://source/track-two"]
    if with_cover:
        expected_urls.append("https://source/api/items/source/cover?raw=1&format=jpeg")
    assert session.requested_urls == expected_urls
    total = 2 + int(with_cover)
    expected_reports = [
        f"Downloading file 1/{total}: 01 Track.mp3",
        f"Prepared file 1/{total}: 01 Track.mp3",
        f"Downloading file 2/{total}: 02 Track Two.mp3",
        f"Prepared file 2/{total}: 02 Track Two.mp3",
    ]
    if with_cover:
        expected_reports.extend(
            [
                "Downloading file 3/3: cover.jpg",
                "Prepared file 3/3: cover.jpg",
            ]
        )
    expected_reports.append(f"Uploading {total} file(s) to Books")
    if upload_status == 200:
        expected_reports.append(f"Uploaded {total}/{total} file(s)")
    assert reports == expected_reports


@pytest.mark.anyio
@pytest.mark.parametrize(
    "outcome", ["indexed", "pending", "ambiguous", "scan_denied", "scan_timeout"]
)
async def test_sync_scans_once_after_all_uploads_and_waits_for_indexing(
    monkeypatch: pytest.MonkeyPatch, outcome: str
) -> None:
    first = book("first")
    second = book("second")
    second["media"]["metadata"]["title"] = "Dune Messiah"
    source = SyncClient("https://source", [first, second])
    target = SyncClient("https://target", [])
    uploaded: list[str] = []
    reads = 0
    scans: list[str] = []

    async def upload(*args: Any, **kwargs: Any) -> None:
        uploaded.append(args[2]["id"])

    def scan(url: str, **kwargs: Any) -> FakeResponse:
        assert uploaded == ["first", "second"]
        assert reads == 1
        assert kwargs["headers"] == {"Authorization": "Bearer token"}
        scans.append(url)
        if outcome == "scan_denied":
            raise aiohttp.ClientResponseError(
                request_info=Mock(), history=(), status=403, message="Forbidden"
            )
        if outcome == "scan_timeout":
            raise TimeoutError("Scan timed out")
        return FakeResponse(b"OK")

    async def inventory(client: Any, library_id: str) -> list[dict[str, Any]]:
        nonlocal reads
        reads += 1
        if reads == 1:
            return []
        assert uploaded == ["first", "second"]
        assert scans == ["https://target/api/libraries/books/scan"]
        if reads == 2 or outcome == "pending":
            return []
        target.items = [first, second]
        if outcome == "ambiguous":
            target.items.append(book("duplicate"))
        return target.items

    target.session_config.session = cast(
        aiohttp.ClientSession, FakeSession(post_handler=scan)
    )
    monkeypatch.setattr("audiobookshelf_sync.api._upload_sync_book", upload)
    monkeypatch.setattr("audiobookshelf_sync.api._sync_library_items", inventory)
    sleep = AsyncMock()
    monkeypatch.setattr("audiobookshelf_sync.api.asyncio.sleep", sleep)
    monkeypatch.setattr("audiobookshelf_sync.api.SYNC_INDEX_ATTEMPTS", 2)
    config = AppConfig(
        config=ConfigFile(
            items=[
                QueueItem(
                    id=item["id"],
                    library_id="books",
                    title=item["media"]["metadata"]["title"],
                    author="Frank Herbert",
                )
                for item in [first, second, first]
            ]
        )
    )
    reports: list[str] = []
    if outcome == "ambiguous":
        with pytest.raises(ValueError, match="Sync failed for 1 item"):
            await sync_items(
                source_client=source,
                target_client=target,
                target_library="Books",
                app_config=config,
                reporter=reports.append,
            )
    else:
        await sync_items(
            source_client=source,
            target_client=target,
            target_library="Books",
            app_config=config,
            reporter=reports.append,
        )
    assert uploaded == ["first", "second"]
    assert scans == ["https://target/api/libraries/books/scan"]
    assert reads == 3
    assert sleep.await_count == 2
    sleep.assert_awaited_with(5)
    assert "Already uploaded; awaiting indexing: Dune" in reports
    if outcome == "pending":
        assert all(item.status == QueueStatus.PENDING for item in config.config.items)
        assert target.patches == []
        assert sum("indexing still pending" in report for report in reports) == 2
        assert not any(report.startswith("Failed:") for report in reports)
    elif outcome == "ambiguous":
        assert any("multiple target matches" in report for report in reports)
        assert "Synced: Dune Messiah" in reports
        assert [item.status for item in config.config.items] == [
            QueueStatus.PENDING,
            QueueStatus.SYNCHRONISED,
            QueueStatus.PENDING,
        ]
        assert len(target.patches) == 1
    else:
        assert "Synced: Dune" in reports
        assert "Synced: Dune Messiah" in reports
        assert len(target.patches) == 2
        assert all(
            item.status == QueueStatus.SYNCHRONISED
            for item in ConfigFile.load(config.config_path).items
        )
        if outcome in {"scan_denied", "scan_timeout"}:
            assert any("Could not request scan" in report for report in reports)


@pytest.mark.anyio
async def test_sync_skips_persisted_synchronised_items_until_reset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    item = QueueItem(
        id="source", library_id="books", title="Dune", author="Frank Herbert"
    )
    item.mark_synchronised()
    config = AppConfig(config=ConfigFile(items=[item]))
    config.save()
    reloaded = AppConfig()
    source = SyncClient("https://source", [book("source")])
    target = SyncClient("https://target", [book("target")])
    get_source = AsyncMock(wraps=source._get)
    get_target = AsyncMock(wraps=target._get)
    monkeypatch.setattr(source, "_get", get_source)
    monkeypatch.setattr(target, "_get", get_target)
    reports: list[str] = []
    await sync_items(
        source_client=source,
        target_client=target,
        target_library="Books",
        app_config=reloaded,
        reporter=reports.append,
    )
    get_source.assert_not_awaited()
    get_target.assert_not_awaited()
    assert reports == ["Skipping synchronised: Dune", "No pending items to sync."]
    reloaded.config.reset_item("source")
    await sync_items(
        source_client=source,
        target_client=target,
        target_library="Books",
        app_config=reloaded,
        reporter=reports.append,
    )
    assert get_source.await_count == 1
    assert (
        ConfigFile.load(reloaded.config_path).items[0].status
        == QueueStatus.SYNCHRONISED
    )


@pytest.mark.anyio
async def test_sync_does_not_mark_synchronised_when_metadata_verification_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = SyncClient("https://source", [book("source")])
    target = SyncClient("https://target", [book("target", "old")])
    monkeypatch.setattr(target, "_patch", AsyncMock(return_value=b"{}"))
    monkeypatch.setattr(
        "audiobookshelf_sync.api.click.confirm", lambda *args, **kwargs: True
    )
    config = AppConfig(
        config=ConfigFile(
            items=[
                QueueItem(
                    id="source",
                    library_id="books",
                    title="Dune",
                    author="Frank Herbert",
                )
            ]
        )
    )
    config.save()
    with pytest.raises(ValueError, match="Sync failed"):
        await sync_items(
            source_client=source,
            target_client=target,
            target_library="Books",
            app_config=config,
            reporter=lambda message: None,
        )
    assert config.config.items[0].status == QueueStatus.PENDING
    assert ConfigFile.load(config.config_path).items[0].status == QueueStatus.PENDING


@pytest.mark.anyio
@pytest.mark.parametrize("scenario", ["identical", "overwrite", "upload"])
async def test_sync_status_save_preserves_concurrent_config_edits(
    monkeypatch: pytest.MonkeyPatch, scenario: str
) -> None:
    config = AppConfig(
        config=ConfigFile(
            items=[
                QueueItem(
                    id="source",
                    library_id="books",
                    title="Dune",
                    author="Frank Herbert",
                ),
                QueueItem(
                    id="removed",
                    library_id="books",
                    title="Removed",
                    author="Author",
                    status=QueueStatus.SYNCHRONISED,
                ),
            ]
        )
    )
    config.save()
    source = SyncClient("https://source", [book("source")])
    target = SyncClient(
        "https://target",
        []
        if scenario == "upload"
        else [book("target", "old" if scenario == "overwrite" else "source")],
    )
    original_get = source._get

    async def get_with_external_edit(endpoint: str, params: Any = None) -> bytes:
        latest = ConfigFile.load(config.config_path)
        latest.remove_item("removed")
        latest.add_pending_item("new", "books", "New book", "Author")
        latest.items[0].title = "Edited locally"
        changed = ConfigFile.model_validate(
            {
                "servers": {"https://changed.example": {"token": "new-token"}},
                "default_source": "https://changed.example",
            }
        )
        latest.servers = changed.servers
        latest.default_source = changed.default_source
        latest.save(config.config_path)
        return await original_get(endpoint, params)

    monkeypatch.setattr(source, "_get", get_with_external_edit)
    monkeypatch.setattr(
        "audiobookshelf_sync.api.click.confirm", lambda *args, **kwargs: True
    )
    monkeypatch.setattr("audiobookshelf_sync.api.asyncio.sleep", AsyncMock())
    monkeypatch.setattr(
        "audiobookshelf_sync.api._upload_sync_book",
        AsyncMock(
            side_effect=lambda *args, **kwargs: target.items.append(book("target"))
        ),
    )
    target.session_config.session = cast(
        aiohttp.ClientSession,
        FakeSession(post_handler=lambda *args, **kwargs: FakeResponse(b"OK")),
    )
    await sync_items(
        source_client=source,
        target_client=target,
        target_library="Books",
        app_config=config,
        reporter=lambda message: None,
    )
    saved = ConfigFile.load(config.config_path)
    assert [item.id for item in saved.items] == ["source", "new"]
    assert saved.items[0].status == QueueStatus.SYNCHRONISED
    assert saved.items[0].title == "Edited locally"
    assert saved.items[1].status == QueueStatus.PENDING
    assert saved.default_source == "https://changed.example"
    assert saved.servers["https://changed.example"].token == "new-token"


@pytest.mark.anyio
@pytest.mark.parametrize("confirm", [False, True])
async def test_sync_uses_async_overwrite_confirmation(
    monkeypatch: pytest.MonkeyPatch, confirm: bool
) -> None:
    source = SyncClient("https://source", [book("source")])
    target = SyncClient("https://target", [book("target", "old")])
    confirmation = AsyncMock(return_value=confirm)
    terminal_prompt = Mock(
        side_effect=AssertionError("Terminal confirmation must not run")
    )
    monkeypatch.setattr("audiobookshelf_sync.api.click.confirm", terminal_prompt)
    config = AppConfig(
        config=ConfigFile(
            items=[
                QueueItem(
                    id="source",
                    library_id="books",
                    title="Dune",
                    author="Frank Herbert",
                )
            ]
        )
    )
    await sync_items(
        source_client=source,
        target_client=target,
        target_library="Books",
        app_config=config,
        reporter=lambda message: None,
        confirm_overwrite=confirmation,
    )
    confirmation.assert_awaited_once_with("Overwrite target metadata for 'Dune'?")
    terminal_prompt.assert_not_called()
    assert len(target.patches) == int(confirm)
