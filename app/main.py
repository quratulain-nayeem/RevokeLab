import os
from contextlib import asynccontextmanager
from fastapi.responses import RedirectResponse
from dotenv import load_dotenv
from fastapi import FastAPI
from starlette.middleware.sessions import SessionMiddleware

from . import auth, models, projects, realtime
from .database import Base, engine

load_dotenv()

session_secret = os.getenv("REVOKELAB_SESSION_SECRET")
if not session_secret:
    raise RuntimeError("REVOKELAB_SESSION_SECRET is not configured")


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    yield


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
    https_only=False,
    max_age=3600,
)

app.include_router(auth.router)
app.include_router(projects.router)
app.include_router(realtime.router)
@app.get("/", include_in_schema=False)
def home():
    return RedirectResponse(url="/docs")
@app.get("/health")
def health() -> dict[str, str]:
    return {
        "status": "ok",
        "service": "revokelab",
    }