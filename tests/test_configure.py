import json
from typing import Any


from audiobookshelf_sync.config import Config


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


def config(**overrides: object) -> Config:
    values: dict[str, object] = {
        "url": "https://source.example",
    }
    values.update(overrides)
    return Config.model_validate(values)
