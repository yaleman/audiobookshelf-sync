from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Config(BaseSettings):
    url: str
    token: str
    download_dir: str = Field("./downloads")

    model_config = SettingsConfigDict(env_prefix="AUDIOBOOKSHELF_")
