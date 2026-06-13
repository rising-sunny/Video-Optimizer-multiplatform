"""Initial tables

Revision ID: 001
Revises: None
Create Date: 2026-03-28
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("email", sa.String(255), unique=True, nullable=False, index=True),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("display_name", sa.String(100), server_default=""),
        sa.Column("is_active", sa.Boolean(), server_default="true"),
        sa.Column("credits_remaining", sa.Integer(), server_default="5"),
        sa.Column("plan", sa.String(20), server_default="free"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_table(
        "projects",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False, index=True),
        sa.Column("title", sa.String(200), server_default="Untitled"),
        sa.Column("topic", sa.String(500), server_default=""),
        sa.Column("category", sa.String(100), server_default="general"),
        sa.Column("language", sa.String(10), server_default="es"),
        sa.Column("duration_preset", sa.Integer(), server_default="60"),
        sa.Column("platform", sa.String(20), server_default="youtube_short"),
        sa.Column("voice_id", sa.String(200), server_default="es-ES-AlvaroNeural"),
        sa.Column("subtitle_style", sa.String(30), server_default="capcut"),
        sa.Column("image_provider", sa.String(20), server_default="recraft"),
        sa.Column("storyboard_data", JSONB(), nullable=True),
        sa.Column("status", sa.String(20), server_default="draft"),
        sa.Column("output_video_path", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_table(
        "jobs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("project_id", sa.String(36), sa.ForeignKey("projects.id"), nullable=False, index=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False, index=True),
        sa.Column("job_type", sa.String(30), nullable=False),
        sa.Column("status", sa.String(20), server_default="queued"),
        sa.Column("progress", sa.Integer(), server_default="0"),
        sa.Column("celery_task_id", sa.String(100), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("result", JSONB(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_table(
        "credit_usage",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False, index=True),
        sa.Column("project_id", sa.String(36), sa.ForeignKey("projects.id"), nullable=True),
        sa.Column("action", sa.String(50), nullable=False),
        sa.Column("credits_used", sa.Integer(), server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("credit_usage")
    op.drop_table("jobs")
    op.drop_table("projects")
    op.drop_table("users")
