from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Настройки сервера. Берутся из переменных окружения с префиксом ALKOCOP_."""

    model_config = SettingsConfigDict(env_prefix="ALKOCOP_", env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://alkocop:alkocop@localhost:5432/alkocop"
    # Каталог, куда складываются файлы скриншотов.
    screenshot_dir: Path = Path("data/screenshots")
    # Общий ключ, по которому новый агент регистрируется на сервере.
    # Задаётся при установке и прописывается в установщик агента.
    enroll_key: str = "change-me"
    # Максимальный размер одного скриншота, байт.
    max_screenshot_bytes: int = 5 * 1024 * 1024
    daily_totals_interval_seconds: int = Field(default=300, ge=1)
    # Сессии веб-кабинета. Secure-cookie по умолчанию требует HTTPS.
    auth_cookie_secure: bool = True
    auth_session_ttl_seconds: int = Field(default=43200, ge=60, le=604800)
    auth_login_attempt_limit: int = Field(default=5, ge=1, le=100)
    auth_ip_attempt_limit: int = Field(default=30, ge=1, le=1000)
    auth_login_window_seconds: int = Field(default=900, ge=60, le=86400)


@lru_cache
def get_settings() -> Settings:
    return Settings()
