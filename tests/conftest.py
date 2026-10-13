from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def isolate_working_directory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"
