"""Application settings, loaded from environment / .env."""

from functools import lru_cache
from pathlib import Path

from pydantic import computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(BACKEND_DIR.parent / ".env", BACKEND_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Application
    app_env: str = "development"
    secret_key: str = "change-me-to-a-long-random-string"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 60
    cors_origins: str = "http://localhost:5173"

    # Database. DATABASE_URL wins if set; otherwise built from MYSQL_* parts.
    database_url: str | None = None
    mysql_host: str = "localhost"
    mysql_port: int = 3306
    mysql_db: str = "validito"
    mysql_user: str = "validito"
    mysql_password: str = "validito"

    # Queue
    redis_url: str = "redis://localhost:6379/0"
    celery_task_always_eager: bool = False  # run tasks inline (dev / tests)

    # Storage
    storage_dir: Path = BACKEND_DIR / "storage"
    max_upload_mb: int = 25

    # OCR / ML
    ocr_languages: str = "en"
    ocr_use_gpu: bool = False
    spacy_model: str = "en_core_web_sm"
    ml_model_dir: Path = BACKEND_DIR / "app" / "ml" / "artifacts"

    # Routing
    auto_approve_confidence: float = 0.85

    @computed_field  # type: ignore[prop-decorator]
    @property
    def sqlalchemy_url(self) -> str:
        if self.database_url:
            return self.database_url
        return (
            f"mysql+pymysql://{self.mysql_user}:{self.mysql_password}"
            f"@{self.mysql_host}:{self.mysql_port}/{self.mysql_db}?charset=utf8mb4"
        )

    @computed_field  # type: ignore[prop-decorator]
    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @computed_field  # type: ignore[prop-decorator]
    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024


@lru_cache
def get_settings() -> Settings:
    return Settings()
