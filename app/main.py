from contextlib import asynccontextmanager
from pathlib import Path
from alembic import command
from alembic.config import Config
from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.config import ROOT, settings
from app.pipeline.runner import runner
from app.api import projects, versions, events


@asynccontextmanager
async def lifespan(app):
    command.upgrade(Config(str(ROOT / "alembic.ini")), "head")
    runner.recover()
    yield
    await runner.close()


app = FastAPI(title="Starling 网文续写", lifespan=lifespan)
app.include_router(projects.router, prefix="/api")
app.include_router(versions.router, prefix="/api")
app.include_router(events.router, prefix="/api")


@app.get("/api/health")
def health():
    return {"status": "ok", "mode": settings.mode, "model": {role: settings.connections[name].model if name in settings.connections else "unconfigured" for role, name in settings.models.items()}, "channels": settings.channels, "target_words": settings.target_words, "trope_vocab": settings.trope_vocab}


dist = ROOT / "frontend/dist"
if dist.exists():
    app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

    @app.get("/")
    def index():
        return FileResponse(dist / "index.html")
