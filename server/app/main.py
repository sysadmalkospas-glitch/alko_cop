from contextlib import asynccontextmanager

from fastapi import FastAPI

from .api import agent, directories, work_schedules
from .auth import router as auth_router
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
app.include_router(auth_router)
app.include_router(work_schedules.router)
app.include_router(directories.router)


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}
