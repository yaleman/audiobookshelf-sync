from typing import Optional
from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Config(BaseSettings):
    url: str
    token: Optional[str] = None
    username: Optional[str] = None
    password: Optional[str] = None

    download_dir: str = Field("./downloads")
    model_config = SettingsConfigDict(env_prefix="AUDIOBOOKSHELF_")

    @model_validator(mode="after")
    def check_if_token_or_username_password(self) -> "Config":
        if self.token is None and (self.username is None or self.password is None):
            raise ValueError("Either token or username/password must be provided.")
        return self
