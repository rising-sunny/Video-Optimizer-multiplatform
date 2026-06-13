from datetime import datetime
from typing import Any

from pydantic import BaseModel


class ProjectCreate(BaseModel):
    title: str = "Untitled"
    topic: str = ""
    category: str = "general"
    language: str = "es"
    duration_preset: int = 60
    platform: str = "youtube_short"
    voice_id: str = "es-ES-AlvaroNeural"
    subtitle_style: str = "capcut"
    image_provider: str = "recraft"


class ProjectUpdate(BaseModel):
    title: str | None = None
    topic: str | None = None
    category: str | None = None
    language: str | None = None
    duration_preset: int | None = None
    voice_id: str | None = None
    subtitle_style: str | None = None
    image_provider: str | None = None
    storyboard_data: dict[str, Any] | None = None


class ProjectResponse(BaseModel):
    id: str
    title: str
    topic: str
    category: str
    language: str
    duration_preset: int
    platform: str
    voice_id: str
    subtitle_style: str
    image_provider: str
    storyboard_data: dict[str, Any] | None
    status: str
    output_video_path: str | None
    created_at: datetime
    updated_at: datetime


class GenerateStoryboardRequest(BaseModel):
    topic: str
    category: str = "general"
    language: str = "es"
    duration: int = 60


class ImportJsonRequest(BaseModel):
    script_json: dict[str, Any]
    voice_id: str = "es-ES-AlvaroNeural"
    language: str = "es"
    max_duration: int = 60
