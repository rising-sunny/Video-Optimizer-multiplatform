"""Job status and progress endpoints."""

import redis
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.dependencies import get_current_user
from app.models.job import Job
from app.models.user import User
from app.schemas.job import JobResponse

router = APIRouter()

_redis = redis.Redis.from_url(settings.redis_url, decode_responses=True)


@router.get("/{job_id}", response_model=JobResponse)
async def get_job(
    job_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Job).where(Job.id == job_id, Job.user_id == user.id)
    )
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    # Get recent logs from Redis
    logs = _redis.lrange(f"job:{job_id}:logs", -20, -1) or []

    return JobResponse(
        id=job.id,
        project_id=job.project_id,
        job_type=job.job_type,
        status=job.status,
        progress=job.progress,
        error_message=job.error_message,
        result=job.result,
        started_at=job.started_at,
        completed_at=job.completed_at,
        created_at=job.created_at,
        logs=logs,
    )
