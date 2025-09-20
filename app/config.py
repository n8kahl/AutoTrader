from pydantic_settings import BaseSettings
from pydantic import Field


class Settings(BaseSettings):
    tradier_access_token: str = Field(default="", alias="TRADIER_ACCESS_TOKEN")
    tradier_env: str = Field(default="sandbox", alias="TRADIER_ENV")
    tradier_account_id: str = Field(default="", alias="TRADIER_ACCOUNT_ID")
    polygon_api_key: str = Field(default="", alias="POLYGON_API_KEY")

    dry_run: int = Field(default=1, alias="DRY_RUN")
    scan_interval_sec: int = Field(default=30, alias="SCAN_INTERVAL_SEC")
    port: int = Field(default=8080, alias="PORT")

    class Config:
        env_file = ".env"
        case_sensitive = False


def settings() -> Settings:
    return Settings()  # loads from environment/.env

