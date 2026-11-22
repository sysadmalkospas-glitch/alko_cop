from contextlib import asynccontextmanager

from fastapi import FastAPI

from .api import agent
from .config import get_settings
from .db import init_engine


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    init_engine(settings.database_url)
    settings.screenshot_dir.mkdir(parents=True, exist_ok=True)
    yield


app = FastAPI(title="AlkoCop server", version="0.1.0", lifespan=lifespan)
app.include_router(agent.router)


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}
