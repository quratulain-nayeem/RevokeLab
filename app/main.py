import asyncio
import os
from contextlib import asynccontextmanager, suppress

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from starlette.middleware.sessions import SessionMiddleware

from worker import run_worker

from . import auth, experiments, models, projects, realtime
from .database import Base, engine

load_dotenv()

session_secret = os.getenv("REVOKELAB_SESSION_SECRET")
if not session_secret:
    raise RuntimeError("REVOKELAB_SESSION_SECRET is not configured")


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    worker_task = None

    if os.getenv("REVOKELAB_RUN_WORKER", "false").lower() == "true":
        worker_task = asyncio.create_task(run_worker(once=False))

    try:
        yield
    finally:
        if worker_task:
            worker_task.cancel()
            with suppress(asyncio.CancelledError):
                await worker_task


app = FastAPI(
    title="RevokeLab",
    description="Tests whether access survives after permission removal.",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    SessionMiddleware,
    secret_key=session_secret,
    same_site="lax",
    https_only=(
        os.getenv("REVOKELAB_SECURE_COOKIES", "false").lower() == "true"
    ),
    max_age=3600,
)

app.include_router(auth.router)
app.include_router(projects.router)
app.include_router(experiments.router)
app.include_router(realtime.router)


@app.get("/", include_in_schema=False)
def home():
    return RedirectResponse(url="/docs")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "revokelab"}