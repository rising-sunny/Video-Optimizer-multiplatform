from datetime import datetime
from typing import Any

from pydantic import BaseModel


class JobResponse(BaseModel):
    id: str
    project_id: str
    job_type: str
    status: str
    progress: int
    error_message: str | None
    result: dict[str, Any] | None
    started_at: datetime | None
    completed_at: datetime | None
    created_at: datetime
    logs: list[str] = []
