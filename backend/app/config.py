from functools import lru_cache
from pydantic import AnyHttpUrl, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file='.env', extra='ignore')

    app_name: str = 'Tsiino Herbarium Validator'
    app_env: str = 'development'
    cors_origins: str = 'http://localhost:8000,https://tsiinohiiwiida.net'
    database_url: str = Field(..., alias='DATABASE_URL')
    max_upload_mb: int = 20
    job_retention_hours: int = 24
    validator_default_country: str = 'Brasil'

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(',') if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
