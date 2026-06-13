"""Media file serving and download endpoints."""

import os

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.dependencies import get_current_user
from app.models.project import Project
from app.models.user import User

router = APIRouter()


@router.get("/projects/{project_id}/download")
async def download_video(
    project_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Project).where(Project.id == project_id, Project.user_id == user.id)
    )
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(404, "Project not found")
    if not project.output_video_path or not os.path.exists(project.output_video_path):
        raise HTTPException(404, "Video not ready or not found")

    return FileResponse(
        project.output_video_path,
        media_type="video/mp4",
        filename=f"{project.title or 'video'}.mp4",
    )


@router.get("/{user_id}/{project_id}/{path:path}")
async def serve_media(
    user_id: str,
    project_id: str,
    path: str,
    user: User = Depends(get_current_user),
):
    if user.id != user_id:
        raise HTTPException(403, "Forbidden")

    filepath = os.path.join(settings.media_dir, user_id, project_id, path)
    # Prevent path traversal
    real_path = os.path.realpath(filepath)
    media_root = os.path.realpath(settings.media_dir)
    if not real_path.startswith(media_root):
        raise HTTPException(403, "Invalid path")

    if not os.path.exists(real_path):
        raise HTTPException(404, "File not found")

    return FileResponse(real_path)
