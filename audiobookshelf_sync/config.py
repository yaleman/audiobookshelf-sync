import logging
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any, Optional
from urllib.parse import urlparse

from pydantic import BaseModel, Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from .queue import QUEUE_FILE, QueueItem, QueueStatus


class Server(BaseModel):
    url: Optional[str] = Field(
        None, description="Set from the key of the config dict", skip=True
    )
    token: Optional[str] = None
    username: Optional[str] = None
    password: Optional[str] = None

    target_library: Optional[str] = None

    @model_validator(mode="after")
    def check_if_token_or_username_password(self) -> "Server":
        if self.token is None and (self.username is None or self.password is None):
            raise ValueError("Either token or username/password must be provided.")
        return self

    @model_validator(mode="after")
    def check_url(self) -> "Server":
        if not self.url:
            raise ValueError("URL must be provided.")
        parsed_url = urlparse(self.url)
        if not urlparse(self.url).scheme:
            raise ValueError("URL must have a valid scheme (http or https).")
        if not parsed_url.netloc:
            raise ValueError("URL must have a valid network location/hostname.")
        return self


class ConfigFile(BaseModel):
    servers: dict[str, Server] = Field(default_factory=dict)
    version: int = 2

    default_source: Optional[str] = None
    default_target: Optional[str] = None

    items: list[QueueItem] = Field(default_factory=list)

    @model_validator(mode="before")
    def set_url_from_keys(value: dict[str, Any]) -> dict[str, Any]:
        for url, server in value.get("servers", {}).items():
            if "url" not in server or server["url"] is None:
                server["url"] = url
        return value

    @model_validator(mode="after")
    def check_version(self) -> "ConfigFile":
        if self.version != 2:
            raise ValueError("Version must be 2")
        return self

    @model_validator(mode="after")
    def check_default_source_and_target(self) -> "ConfigFile":
        if self.default_source is not None and self.default_source not in self.servers:
            raise ValueError("Default source must be one of the configured servers.")
        if self.default_target is not None and self.default_target not in self.servers:
            raise ValueError("Default target must be one of the configured servers.")
        return self

    @classmethod
    def load(
        cls, path: Path, logger: logging.Logger = logging.getLogger(__name__)
    ) -> "ConfigFile":
        if not path.exists():
            logger.warning("Config file does not exist at %s, using default.", path)
            return ConfigFile()
        return cls.model_validate_json(path.read_text())

    def save(
        self, path: Path, logger: logging.Logger = logging.getLogger(__name__)
    ) -> bool:

        if path.parent != Path("."):
            path.parent.mkdir(parents=True, exist_ok=True)

        file_contents = self.model_dump_json(
            indent=2, exclude_none=True, exclude_defaults=True
        )

        try:
            if path.exists() and path.read_text(encoding="utf-8") == file_contents:
                path.chmod(0o600)
                return False
        except Exception as error:
            logger.error(
                "Error reading config file at %s: stat=%s %s",
                path,
                path.stat() if path.exists() else None,
                error,
            )
            raise error

        temporary_path: Path | None = None
        try:
            with NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                prefix=f".{path.name}.",
                dir=path.parent,
                delete=False,
            ) as handle:
                temporary_path = Path(handle.name)
                handle.write(file_contents)
            temporary_path.replace(path)
        finally:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)
        return True

    def find_item(self, item_id: str) -> QueueItem | None:
        return next((item for item in self.items if item.id == item_id), None)

    def add_pending_item(
        self,
        item_id: str,
        library_id: str,
        title: str,
        author: str,
    ) -> QueueItem:
        existing = self.find_item(item_id)
        if existing is not None:
            return existing

        item = QueueItem(
            id=item_id,
            library_id=library_id,
            title=title,
            author=author,
        )
        self.items.append(item)
        return item

    def remove_item(self, item_id: str) -> QueueItem | None:
        item = self.find_item(item_id)
        if item is None:
            return None
        self.items.remove(item)
        return item

    def item_index(self, item_id: str) -> int | None:
        for index, item in enumerate(self.items):
            if item.id == item_id:
                return index
        return None

    def reset_item(self, item_id: str) -> QueueItem | None:
        item_index = self.item_index(item_id)
        if item_index is None:
            return None
        return self.items[item_index].reset()


class AppConfig(BaseSettings):
    download_dir: Path = Field(Path("./downloads"))
    config_path: Path = Field(Path(QUEUE_FILE))
    model_config = SettingsConfigDict(
        env_prefix="AUDIOBOOKSHELF_",
    )
    config: ConfigFile = Field(default_factory=lambda: ConfigFile.load(QUEUE_FILE))

    @model_validator(mode="before")
    def validate_config(cls, values: dict) -> dict:
        if "config_path" in values and "config" not in values:
            values["config"] = ConfigFile.load(Path(values["config_path"]))
        return values

    def save(self, path: Path | None = None) -> None:
        if self.config is not None:
            self.config.save(path or self.config_path)
        else:
            raise ValueError("Config isn't part of this object!")

    def default_source(self) -> str | None:
        return self.config.default_source

    def _latest_config(self) -> ConfigFile:
        return (
            ConfigFile.load(self.config_path)
            if self.config_path.exists()
            else self.config.model_copy(deep=True)
        )

    def save_download_state(self, item: QueueItem, *, status: QueueStatus) -> None:
        latest = self._latest_config()
        queued = latest.find_item(item.id)
        if queued is not None:
            if queued.status != QueueStatus.SYNCHRONISED:
                queued.status = status
            queued.error = item.error
            if item.downloaded_at is not None:
                queued.downloaded_at = item.downloaded_at
                queued.output_dir = item.output_dir
        latest.save(self.config_path)
        self.config = latest

    def mark_synchronised(self, items: list[QueueItem]) -> None:
        latest = self._latest_config()
        item_ids = {item.id for item in items}
        for queued in latest.items:
            if queued.id in item_ids:
                queued.mark_synchronised()
        latest.save(self.config_path)
        self.config = latest

    def default_target(self) -> str | None:
        return self.config.default_target
