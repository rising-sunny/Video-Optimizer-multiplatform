"""Project CRUD and pipeline trigger endpoints."""

from fastapi import APIRouter, Depends, HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_current_user
from app.models.user import User
from app.models.project import Project
from app.models.job import Job
from app.schemas.project import (
    GenerateStoryboardRequest,
    ImportJsonRequest,
    ProjectCreate,
    ProjectResponse,
    ProjectUpdate,
)
from app.schemas.job import JobResponse

router = APIRouter()


@router.get("", response_model=list[ProjectResponse])
async def list_projects(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Project)
        .where(Project.user_id == user.id)
        .order_by(Project.created_at.desc())
    )
    return result.scalars().all()


@router.post("", response_model=ProjectResponse, status_code=status.HTTP_201_CREATED)
async def create_project(
    req: ProjectCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    project = Project(user_id=user.id, **req.model_dump())
    db.add(project)
    await db.commit()
    await db.refresh(project)
    return project


@router.get("/{project_id}", response_model=ProjectResponse)
async def get_project(
    project_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    project = await _get_user_project(project_id, user.id, db)
    return project


@router.put("/{project_id}", response_model=ProjectResponse)
async def update_project(
    project_id: str,
    req: ProjectUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    project = await _get_user_project(project_id, user.id, db)
    for key, value in req.model_dump(exclude_unset=True).items():
        setattr(project, key, value)
    await db.commit()
    await db.refresh(project)
    return project


@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_project(
    project_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    project = await _get_user_project(project_id, user.id, db)
    await db.delete(project)
    await db.commit()


# --- Pipeline triggers ---


@router.post("/{project_id}/generate-storyboard", response_model=JobResponse)
async def generate_storyboard(
    project_id: str,
    req: GenerateStoryboardRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    project = await _get_user_project(project_id, user.id, db)
    return await _create_job(
        db,
        project,
        user,
        "generate_storyboard",
        {
            "topic": req.topic,
            "category": req.category,
            "language": req.language,
            "duration": req.duration,
            "voice_id": project.voice_id,
        },
    )


@router.post("/{project_id}/import-json", response_model=JobResponse)
async def import_json(
    project_id: str,
    req: ImportJsonRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    project = await _get_user_project(project_id, user.id, db)
    return await _create_job(
        db,
        project,
        user,
        "import_json",
        {
            "script_json": req.script_json,
            "voice_id": req.voice_id,
            "language": req.language,
            "max_duration": req.max_duration,
        },
    )


@router.post("/{project_id}/generate-images", response_model=JobResponse)
async def generate_images(
    project_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    project = await _get_user_project(project_id, user.id, db)
    if not project.storyboard_data:
        raise HTTPException(400, "No storyboard data. Generate storyboard first.")
    return await _create_job(
        db,
        project,
        user,
        "generate_images",
        {"image_provider": project.image_provider},
    )


@router.post("/{project_id}/generate-tts", response_model=JobResponse)
async def generate_tts(
    project_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    project = await _get_user_project(project_id, user.id, db)
    if not project.storyboard_data:
        raise HTTPException(400, "No storyboard data. Generate storyboard first.")
    return await _create_job(
        db,
        project,
        user,
        "generate_tts",
        {
            "voice_id": project.voice_id,
            "language": project.language,
            "elevenlabs_api_key": user.elevenlabs_api_key or "",
        },
    )


@router.post("/{project_id}/assemble", response_model=JobResponse)
async def assemble_video(
    project_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    project = await _get_user_project(project_id, user.id, db)
    if not project.storyboard_data:
        raise HTTPException(400, "No storyboard data.")
    return await _create_job(
        db,
        project,
        user,
        "assemble_video",
        {
            "subtitle_style": project.subtitle_style,
            "platform": project.platform,
        },
    )


@router.post("/{project_id}/scenes/{scene_idx}/upload")
async def upload_scene_media(
    project_id: str,
    scene_idx: int,
    file: UploadFile,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    import os
    from app.config import settings

    project = await _get_user_project(project_id, user.id, db)
    media_dir = os.path.join(settings.media_dir, user.id, project_id, "uploads")
    os.makedirs(media_dir, exist_ok=True)

    ext = os.path.splitext(file.filename)[1] if file.filename else ".jpg"
    filename = f"scene_{scene_idx}{ext}"
    filepath = os.path.join(media_dir, filename)

    content = await file.read()
    with open(filepath, "wb") as f:
        f.write(content)

    # Update storyboard_data if it exists
    if project.storyboard_data and "segments" in project.storyboard_data:
        segments = project.storyboard_data["segments"]
        if 0 <= scene_idx < len(segments):
            segments[scene_idx]["image_path"] = filepath
            segments[scene_idx]["media_source"] = "upload"
            await db.commit()

    return {"filename": filename, "path": filepath, "scene_idx": scene_idx}


# --- Helpers ---


async def _get_user_project(
    project_id: str, user_id: str, db: AsyncSession
) -> Project:
    result = await db.execute(
        select(Project).where(Project.id == project_id, Project.user_id == user_id)
    )
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


async def _create_job(
    db: AsyncSession,
    project: Project,
    user: User,
    job_type: str,
    params: dict,
) -> Job:
    from workers.celery_app import celery_app

    job = Job(
        project_id=project.id,
        user_id=user.id,
        job_type=job_type,
        status="queued",
    )
    db.add(job)
    await db.commit()
    await db.refresh(job)

    # Dispatch Celery task
    task_name = f"workers.tasks.{job_type}"
    result = celery_app.send_task(
        task_name,
        kwargs={
            "job_id": job.id,
            "project_id": project.id,
            "user_id": user.id,
            "params": params,
        },
    )
    job.celery_task_id = result.id
    await db.commit()

    return job
