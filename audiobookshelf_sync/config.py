from typing import Optional
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Config(BaseSettings):
    url: str
    token: Optional[str] = None
    username: Optional[str] = None
    password: Optional[str] = None

    upload_url: Optional[str] = None
    upload_token: Optional[str] = None

    download_dir: str = Field("./downloads")

    model_config = SettingsConfigDict(env_prefix="AUDIOBOOKSHELF_")
