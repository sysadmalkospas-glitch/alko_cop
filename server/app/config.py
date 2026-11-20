from functools import lru_cache
from pathlib import Path

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


@lru_cache
def get_settings() -> Settings:
    return Settings()
