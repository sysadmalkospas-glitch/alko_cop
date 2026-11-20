from contextlib import asynccontextmanager

from fastapi import FastAPI

from . import models  # noqa: F401  (регистрирует таблицы)
from .api import agent
from .config import get_settings
from .db import Base, init_engine


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    engine = init_engine(settings.database_url)
    # На этапе каркаса таблицы создаются автоматически.
    # Миграции (Alembic) подключим, когда схема стабилизируется.
    Base.metadata.create_all(engine)
    settings.screenshot_dir.mkdir(parents=True, exist_ok=True)
    yield


app = FastAPI(title="AlkoCop server", version="0.1.0", lifespan=lifespan)
app.include_router(agent.router)


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}
