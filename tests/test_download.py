from pathlib import Path

import pytest
from aioaudiobookshelf.schema.audio import AudioTrack
from aioaudiobookshelf.schema.file import FileMetadata

from audiobookshelf_sync.config import AppConfig, ConfigFile
from audiobookshelf_sync.download import download_pending_items, sanitize_path_part
from audiobookshelf_sync.queue import QueueStatus
from audiobookshelf_sync.test import FakeClient, FakeSession, expanded_book


@pytest.fixture
def download_session() -> FakeSession:
    return FakeSession(
        {
            "https://abs.example/audio/book-1/track-1.mp3": b"track-one",
            "https://abs.example/audio/book-1/track-2.mp3": b"track-two",
        }
    )


@pytest.fixture
def download_client(download_session: FakeSession) -> FakeClient:
    tracks = [
        AudioTrack(
            index=0,
            start_offset=0,
            duration=1,
            title="Track One",
            content_url="/audio/book-1/track-1.mp3",
            metadata=FileMetadata(
                filename="01 Track One.mp3",
                ext=".mp3",
                path="/books/01 Track One.mp3",
                relative_path="01 Track One.mp3",
                size=9,
                changed_time_ms=0,
            ),
        ),
        AudioTrack(
            index=1,
            start_offset=1,
            duration=1,
            title="Track Two",
            content_url="/audio/book-1/track-2.mp3",
            metadata=None,
        ),
    ]
    return FakeClient(
        books={"book-1": expanded_book("book-1", tracks=tracks)},
        session=download_session,
    )


def test_sanitize_path_part_removes_unsafe_characters() -> None:
    assert sanitize_path_part('Bad/Name: "Book"?') == "Bad_Name_ Book"


@pytest.mark.anyio
async def test_download_pending_items_writes_tracks_and_marks_done(
    tmp_path: Path,
    download_client: FakeClient,
) -> None:
    config_path = tmp_path / "audiobookshelf-sync.json"
    appconfig = AppConfig(
        config_path=config_path,
        download_dir=tmp_path / "downloads",
        config=ConfigFile.load(config_path),
    )
    appconfig.config.add_pending_item(
        item_id="book-1",
        library_id="library-1",
        title="Example Book",
        author="Example Author",
    )
    appconfig.config.save(config_path)
    await download_pending_items(
        client=download_client,
        app_config=appconfig,
    )

    loaded = ConfigFile.load(config_path)
    assert loaded.items[0].status == QueueStatus.DONE
    assert loaded.items[0].output_dir == "downloads/Example Author - Example Book"
    assert (
        tmp_path / "downloads" / "Example Author - Example Book" / "01 Track One.mp3"
    ).read_bytes() == b"track-one"
    assert (
        tmp_path / "downloads" / "Example Author - Example Book" / "02 Track Two.mp3"
    ).read_bytes() == b"track-two"
    assert not list(
        (tmp_path / "downloads" / "Example Author - Example Book").glob("*.part")
    )


@pytest.mark.anyio
async def test_download_pending_items_marks_failed_and_continues(
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "audiobookshelf-sync.json"
    config = ConfigFile.load(config_path)
    config.add_pending_item(
        item_id="book-1",
        library_id="library-1",
        title="Example Book",
        author="Example Author",
    )
    config.save(config_path)
    appconfig = AppConfig(config=config, download_dir=tmp_path / "downloads")
    await download_pending_items(
        client=FakeClient(fail=True),
        app_config=appconfig,
    )

    loaded = ConfigFile.load(config_path)
    assert loaded.items[0].status == QueueStatus.FAILED
    assert loaded.items[0].error == "boom"


@pytest.fixture(scope="function")
def app_config(tmp_path: Path) -> AppConfig:
    assert tmp_path.exists()
    config_path = tmp_path / "audiobookshelf-sync.json"
    config = AppConfig(config_path=config_path, download_dir=tmp_path / "downloads")
    config.save()
    return config


@pytest.mark.anyio
async def test_download_pending_items_reports_progress(
    app_config: AppConfig,
    download_client: FakeClient,
) -> None:
    app_config.config.add_pending_item(
        item_id="book-1",
        library_id="library-1",
        title="Example Book",
        author="Example Author",
    )
    app_config.save()
    messages: list[str] = []

    await download_pending_items(
        client=download_client,
        app_config=app_config,
        reporter=messages.append,
    )

    assert messages == [
        "Download directory: downloads",
        "Starting: Example Book - Example Author",
        "Fetching metadata: Example Book",
        "Downloading 2 track(s) to downloads/Example Author - Example Book",
        "Downloading track 1/2: 01 Track One.mp3",
        "Finished track 1/2: 01 Track One.mp3",
        "Downloading track 2/2: 02 Track Two.mp3",
        "Finished track 2/2: 02 Track Two.mp3",
        "Done: Example Book",
        "Processed 1 item(s): 1 done, 0 failed",
    ]


@pytest.mark.anyio
async def test_download_pending_items_skips_existing_track_files(
    tmp_path: Path,
    download_client: FakeClient,
    download_session: FakeSession,
) -> None:
    config_path = tmp_path / "audiobookshelf-sync.json"
    config_file = ConfigFile.load(config_path)
    config_file.add_pending_item(
        item_id="book-1",
        library_id="library-1",
        title="Example Book",
        author="Example Author",
    )
    config_file.save(config_path)
    appconfig = AppConfig(download_dir=tmp_path / "downloads", config=config_file)

    output_dir = tmp_path / "downloads" / "Example Author - Example Book"
    output_dir.mkdir(parents=True)
    existing_track = output_dir / "01 Track One.mp3"
    existing_track.write_bytes(b"already-here")
    stale_part = output_dir / "02 Track Two.mp3.part"
    stale_part.write_bytes(b"stale")
    del download_session.responses["https://abs.example/audio/book-1/track-1.mp3"]
    messages: list[str] = []

    await download_pending_items(
        client=download_client,
        app_config=appconfig,
        reporter=messages.append,
    )

    loaded = ConfigFile.load(config_path)
    assert loaded.items[0].status == QueueStatus.DONE
    assert existing_track.read_bytes() == b"already-here"
    assert (output_dir / "02 Track Two.mp3").read_bytes() == b"track-two"
    assert not stale_part.exists()
    assert download_session.requested_urls == [
        "https://abs.example/audio/book-1/track-2.mp3"
    ]
    assert "Skipping existing track 1/2: 01 Track One.mp3" in messages


@pytest.mark.anyio
@pytest.mark.parametrize("existing_tracks", [False, True])
@pytest.mark.parametrize("fail", [False, True])
async def test_download_preserves_synchronised_status_and_records_download_result(
    app_config: AppConfig,
    download_client: FakeClient,
    download_session: FakeSession,
    existing_tracks: bool,
    fail: bool,
) -> None:
    item = app_config.config.add_pending_item(
        "book-1", "library-1", "Example Book", "Example Author"
    )
    item.mark_synchronised()
    app_config.save()
    output = app_config.download_dir / "Example Author - Example Book"
    if existing_tracks:
        output.mkdir(parents=True)
        (output / "01 Track One.mp3").write_bytes(b"track-one")
        (output / "02 Track Two.mp3").write_bytes(b"track-two")
    download_client.fail = fail
    await download_pending_items(client=download_client, app_config=app_config)
    saved = ConfigFile.load(app_config.config_path).items[0]
    assert saved.status == QueueStatus.SYNCHRONISED
    if fail:
        assert saved.error == "boom"
        assert saved.downloaded_at is None
    else:
        assert saved.error is None
        assert saved.downloaded_at is not None
        assert saved.output_dir == "downloads/Example Author - Example Book"
        assert (output / "01 Track One.mp3").read_bytes() == b"track-one"
        assert (output / "02 Track Two.mp3").read_bytes() == b"track-two"
        assert len(download_session.requested_urls) == (0 if existing_tracks else 2)
        download_client.fail = True
        messages: list[str] = []
        await download_pending_items(
            client=download_client, app_config=app_config, reporter=messages.append
        )
        assert "Skipping done: Example Book" in messages
        assert (
            ConfigFile.load(app_config.config_path).items[0].status
            == QueueStatus.SYNCHRONISED
        )


@pytest.mark.anyio
@pytest.mark.parametrize("fail", [False, True])
@pytest.mark.parametrize("remove_active", [False, True])
async def test_download_merges_results_with_concurrent_sync_and_config_edits(
    app_config: AppConfig,
    download_client: FakeClient,
    monkeypatch: pytest.MonkeyPatch,
    fail: bool,
    remove_active: bool,
) -> None:
    app_config.config.add_pending_item(
        "book-1", "books", "Example Book", "Example Author"
    )
    app_config.config.add_pending_item("removed", "books", "Removed", "Author")
    app_config.save()
    original_get = download_client.get_library_item_book
    download_client.fail = fail
    fetched: list[str] = []

    async def get_with_external_changes(*, book_id: str, expanded: bool = False):
        fetched.append(book_id)
        latest = ConfigFile.load(app_config.config_path)
        active = latest.find_item("book-1")
        assert active is not None
        active.mark_synchronised()
        active.title = "Edited title"
        latest.remove_item("removed")
        if remove_active:
            latest.remove_item("book-1")
        latest.add_pending_item("new", "books", "New book", "Author")
        server_config = ConfigFile.model_validate(
            {
                "servers": {"https://new.example": {"token": "new-token"}},
                "default_target": "https://new.example",
            }
        )
        latest.servers = server_config.servers
        latest.default_target = server_config.default_target
        latest.save(app_config.config_path)
        return await original_get(book_id=book_id, expanded=expanded)

    monkeypatch.setattr(
        download_client, "get_library_item_book", get_with_external_changes
    )
    await download_pending_items(client=download_client, app_config=app_config)
    saved = ConfigFile.load(app_config.config_path)
    assert fetched == ["book-1"]
    assert saved.find_item("removed") is None
    new = saved.find_item("new")
    assert new is not None
    assert new.status == QueueStatus.PENDING
    assert saved.default_target == "https://new.example"
    assert saved.servers["https://new.example"].token == "new-token"
    active = saved.find_item("book-1")
    if remove_active:
        assert active is None
    else:
        assert active is not None
        assert active.status == QueueStatus.SYNCHRONISED
        assert active.title == "Edited title"
        if fail:
            assert active.error == "boom"
            assert active.downloaded_at is None
        else:
            assert active.error is None
            assert active.downloaded_at is not None
            assert active.output_dir == "downloads/Example Author - Example Book"
    assert app_config.config == saved


@pytest.mark.anyio
async def test_download_start_preserves_sync_completed_after_config_load(
    app_config: AppConfig, download_client: FakeClient
) -> None:
    app_config.config.add_pending_item(
        "book-1", "books", "Example Book", "Example Author"
    )
    app_config.save()
    latest = ConfigFile.load(app_config.config_path)
    latest.items[0].mark_synchronised()
    latest.add_pending_item("new", "books", "New book", "Author")
    latest.save(app_config.config_path)
    states: list[QueueStatus] = []

    def report(message: str) -> None:
        if message.startswith("Fetching metadata:"):
            states.append(ConfigFile.load(app_config.config_path).items[0].status)

    await download_pending_items(
        client=download_client, app_config=app_config, reporter=report
    )
    assert states == [QueueStatus.SYNCHRONISED]
    saved = ConfigFile.load(app_config.config_path)
    assert saved.items[0].status == QueueStatus.SYNCHRONISED
    assert saved.find_item("new") is not None


@pytest.mark.anyio
@pytest.mark.parametrize("fail", [False, True])
async def test_download_does_not_restore_sync_status_after_explicit_reset(
    app_config: AppConfig,
    download_client: FakeClient,
    monkeypatch: pytest.MonkeyPatch,
    fail: bool,
) -> None:
    app_config.config.add_pending_item(
        "book-1", "books", "Example Book", "Example Author"
    ).mark_synchronised()
    app_config.save()
    original_get = download_client.get_library_item_book
    download_client.fail = fail

    async def get_after_reset(*, book_id: str, expanded: bool = False):
        latest = ConfigFile.load(app_config.config_path)
        latest.reset_item(book_id)
        latest.save(app_config.config_path)
        return await original_get(book_id=book_id, expanded=expanded)

    monkeypatch.setattr(download_client, "get_library_item_book", get_after_reset)
    await download_pending_items(client=download_client, app_config=app_config)
    saved = ConfigFile.load(app_config.config_path).items[0]
    assert saved.status == (QueueStatus.FAILED if fail else QueueStatus.DONE)
    assert saved.error == ("boom" if fail else None)
    assert (saved.downloaded_at is not None) == (not fail)
