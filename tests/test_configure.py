import json
from pathlib import Path
from contextlib import contextmanager
from tempfile import NamedTemporaryFile

import pytest
from typing import Any

from audiobookshelf_sync.config import AppConfig, ConfigFile


class FakeResponse:
    async def __aenter__(self) -> "FakeResponse":
        return self

    async def __aexit__(self, *args: object) -> None:
        return None

    def raise_for_status(self) -> None:
        return None

    async def read(self) -> bytes:
        return json.dumps(
            {
                "libraries": [
                    {
                        "id": "lib-1",
                        "name": "Audiobooks",
                        "folders": [
                            {
                                "id": "folder-1",
                                "fullPath": "/media/audiobooks",
                                "libraryId": "lib-1",
                            }
                        ],
                    },
                    {
                        "id": "lib-2",
                        "name": "Podcasts",
                        "folders": [
                            {
                                "id": "folder-2",
                                "fullPath": "/media/podcasts",
                                "libraryId": "lib-2",
                            }
                        ],
                    },
                ]
            }
        ).encode()


class FakeSession:
    def __init__(self) -> None:
        self.gets: list[dict[str, Any]] = []

    def get(self, url: str, **kwargs: Any) -> FakeResponse:
        self.gets.append({"url": url, **kwargs})
        return FakeResponse()


def config(**overrides: object) -> AppConfig:
    values: dict[str, object] = {
        "url": "https://source.example",
    }
    values.update(overrides)
    return AppConfig.model_validate(values)


def test_server_parser() -> None:
    input_config = {"servers": {"https://example.com": {"token": "example-token"}}}

    cfg = ConfigFile.model_validate(input_config)
    assert "https://example.com" in cfg.servers
    server = cfg.servers["https://example.com"]
    assert server.token == "example-token"


@pytest.mark.parametrize("file_exists", [False, True])
def test_app_config_preserves_explicit_config_with_custom_path(
    tmp_path: Path, file_exists: bool
) -> None:
    path = tmp_path / "custom.json"
    if file_exists:
        ConfigFile().save(path)
    supplied = ConfigFile()
    supplied.add_pending_item("book", "books", "Example", "Author")
    config = AppConfig(config_path=path, config=supplied)
    assert config.config is supplied
    assert [item.id for item in config.config.items] == ["book"]
    config.save()
    assert [item.id for item in ConfigFile.load(path).items] == ["book"]


def test_app_config_loads_custom_path_when_no_config_is_supplied(
    tmp_path: Path,
) -> None:
    path = tmp_path / "custom.json"
    saved = ConfigFile()
    saved.add_pending_item("book", "books", "Example", "Author")
    saved.save(path)
    assert AppConfig(config_path=path).config == saved


@pytest.mark.parametrize("existing_mode", [None, 0o600, 0o644])
def test_config_credentials_are_restricted_before_writing_and_after_replacement(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, existing_mode: int | None
) -> None:
    path = tmp_path / "config.json"
    if existing_mode is not None:
        path.write_text("{}")
        path.chmod(existing_mode)
    temporary_paths: list[Path] = []

    @contextmanager
    def checked_temporary_file(**kwargs: Any):
        with NamedTemporaryFile(**kwargs) as handle:
            temporary = Path(handle.name)
            temporary_paths.append(temporary)
            assert temporary.stat().st_mode & 0o777 == 0o600
            assert temporary.read_bytes() == b""
            yield handle

    monkeypatch.setattr(
        "audiobookshelf_sync.config.NamedTemporaryFile", checked_temporary_file
    )
    config = ConfigFile.model_validate(
        {"servers": {"https://example.com": {"token": "test-token"}}}
    )
    config.save(path)
    assert path.stat().st_mode & 0o777 == 0o600
    assert ConfigFile.load(path) == config
    assert temporary_paths
    assert all(not temporary.exists() for temporary in temporary_paths)


def test_unchanged_config_credentials_have_permissions_tightened(
    tmp_path: Path,
) -> None:
    path = tmp_path / "config.json"
    config = ConfigFile()
    config.save(path)
    path.chmod(0o644)
    assert config.save(path) is False
    assert path.stat().st_mode & 0o777 == 0o600


def test_sync_status_save_does_not_resurrect_a_removed_item(tmp_path: Path) -> None:
    path = tmp_path / "config.json"
    original = ConfigFile()
    item = original.add_pending_item("removed", "books", "Removed", "Author")
    config = AppConfig(config_path=path, config=original)
    config.save()
    ConfigFile().save(path)
    config.mark_synchronised([item])
    assert ConfigFile.load(path).items == []
    assert config.config.items == []
