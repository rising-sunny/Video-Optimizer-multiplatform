"""FastAPI application entry point."""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.config import settings
from app.api import auth, projects, jobs, tts, media


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: ensure media directory exists
    import os
    os.makedirs(settings.media_dir, exist_ok=True)
    yield
    # Shutdown


app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    lifespan=lifespan,
)

# CORS for frontend dev
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000", "*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# API routes
app.include_router(auth.router, prefix="/api/auth", tags=["auth"])
app.include_router(projects.router, prefix="/api/projects", tags=["projects"])
app.include_router(jobs.router, prefix="/api/jobs", tags=["jobs"])
app.include_router(tts.router, prefix="/api/tts", tags=["tts"])
app.include_router(media.router, prefix="/api/media", tags=["media"])


@app.get("/api/health")
async def health():
    return {"status": "ok", "service": settings.app_name}
