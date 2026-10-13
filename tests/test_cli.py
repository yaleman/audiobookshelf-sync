from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

import pytest
from click.testing import CliRunner

from audiobookshelf_sync.__main__ import main
from audiobookshelf_sync.api import BookSearchResult, BrowsePage
from audiobookshelf_sync.config import AppConfig, ConfigFile
from audiobookshelf_sync.tui import ResultItem, SearchQueueApp


def test_configure_list_target_libraries_help() -> None:
    result = CliRunner().invoke(main, ["--help"])

    assert result.exit_code == 0
    assert "Audiobookshelf" in result.output


def test_search_uses_environment_config_path_for_queue_edits(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "custom" / "config.json"
    config = ConfigFile.model_validate(
        {
            "servers": {"https://source.example": {"token": "test-token"}},
            "default_source": "https://source.example",
        }
    )
    config.save(path)
    monkeypatch.setenv("AUDIOBOOKSHELF_CONFIG_PATH", str(path))
    monkeypatch.setattr(
        "audiobookshelf_sync.__main__.get_client", AsyncMock(return_value=object())
    )
    opened_paths: list[Path] = []

    async def list_books(*args: Any, **kwargs: Any) -> BrowsePage[BookSearchResult]:
        return BrowsePage(items=[], total=0)

    async def run_app(app: SearchQueueApp) -> None:
        opened_paths.append(app.queue_path)
        app.list_books_func = list_books
        async with app.run_test():
            await app.add_result_item(
                ResultItem(
                    BookSearchResult(
                        id="book",
                        library_id="books",
                        library_name="Books",
                        title="Example",
                        author="Author",
                        duration=None,
                        size=None,
                    ),
                )
            )

    monkeypatch.setattr(SearchQueueApp, "run_async", run_app)
    result = CliRunner().invoke(main, ["search"])
    assert result.exit_code == 0, result.output
    assert opened_paths == [path]
    assert [item.id for item in ConfigFile.load(path).items] == ["book"]
    assert [item.id for item in AppConfig().config.items] == ["book"]
    assert not (tmp_path / "audiobookshelf-sync.json").exists()
