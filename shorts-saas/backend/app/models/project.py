import uuid
from datetime import datetime, timezone

from sqlalchemy import String, Integer, DateTime, ForeignKey, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), index=True)
    title: Mapped[str] = mapped_column(String(200), default="Untitled")
    topic: Mapped[str] = mapped_column(String(500), default="")
    category: Mapped[str] = mapped_column(String(100), default="general")
    language: Mapped[str] = mapped_column(String(10), default="es")
    duration_preset: Mapped[int] = mapped_column(Integer, default=60)
    platform: Mapped[str] = mapped_column(String(20), default="youtube_short")
    voice_id: Mapped[str] = mapped_column(String(200), default="es-ES-AlvaroNeural")
    subtitle_style: Mapped[str] = mapped_column(String(30), default="capcut")
    image_provider: Mapped[str] = mapped_column(String(20), default="recraft")
    storyboard_data: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="draft")
    output_video_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    user = relationship("User", back_populates="projects")
    jobs = relationship("Job", back_populates="project", lazy="selectin")
