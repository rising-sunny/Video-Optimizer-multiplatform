"""Celery tasks that wrap the core desktop modules for web operation."""

import json
import os
import traceback
from datetime import datetime, timezone

import redis
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from workers.celery_app import celery_app
from workers.video_config_override import configure_for_project

# Sync SQLAlchemy for Celery workers (async not needed here)
DATABASE_URL = os.getenv(
    "DATABASE_URL", "postgresql://shorts:shorts@postgres:5432/shorts"
)
_engine = create_engine(DATABASE_URL)
_SessionLocal = sessionmaker(bind=_engine)

REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")
_redis = redis.Redis.from_url(REDIS_URL, decode_responses=True)


def _log(job_id: str, message: str):
    """Push log line to Redis for real-time progress."""
    _redis.rpush(f"job:{job_id}:logs", message)
    _redis.ltrim(f"job:{job_id}:logs", -100, -1)  # Keep last 100 lines
    _redis.expire(f"job:{job_id}:logs", 3600)  # 1 hour TTL
    print(f"[Job {job_id}] {message}")


def _update_job(job_id: str, **kwargs):
    """Update job row in PostgreSQL."""
    from app.models.job import Job

    with _SessionLocal() as db:
        job = db.query(Job).filter(Job.id == job_id).first()
        if job:
            for k, v in kwargs.items():
                setattr(job, k, v)
            db.commit()


def _update_project(project_id: str, **kwargs):
    """Update project row in PostgreSQL."""
    from app.models.project import Project

    with _SessionLocal() as db:
        project = db.query(Project).filter(Project.id == project_id).first()
        if project:
            for k, v in kwargs.items():
                setattr(project, k, v)
            db.commit()


def _get_project_storyboard(project_id: str) -> dict | None:
    from app.models.project import Project

    with _SessionLocal() as db:
        project = db.query(Project).filter(Project.id == project_id).first()
        return project.storyboard_data if project else None


@celery_app.task(name="workers.tasks.generate_storyboard", bind=True)
def generate_storyboard(self, job_id: str, project_id: str, user_id: str, params: dict):
    """Generate storyboard using AutoVideoGenerator."""
    _update_job(job_id, status="running", started_at=datetime.now(timezone.utc))
    _log(job_id, "Starting storyboard generation...")

    try:
        project_dir = configure_for_project(user_id, project_id)
        _log(job_id, f"Project dir: {project_dir}")

        from core.auto_video_generator_v2 import AutoVideoGenerator

        generator = AutoVideoGenerator(parent_window=None)
        generator.log = lambda msg: _log(job_id, msg)

        result = generator.generate_storyboard_data(
            topic=params["topic"],
            category=params.get("category", "general"),
            platform="youtube_short",
            custom_duration=params.get("duration", 60),
            voice_id=params.get("voice_id", "es-ES-AlvaroNeural"),
            language=params.get("language", "es"),
        )

        # Save storyboard to project
        _update_project(
            project_id,
            storyboard_data=result,
            status="storyboard_ready",
            topic=params["topic"],
        )
        _update_job(
            job_id,
            status="completed",
            progress=100,
            completed_at=datetime.now(timezone.utc),
            result={"segments_count": len(result.get("segments", []))},
        )
        _log(job_id, "Storyboard generation completed!")

    except Exception as e:
        _update_job(
            job_id,
            status="failed",
            error_message=str(e),
            completed_at=datetime.now(timezone.utc),
        )
        _log(job_id, f"ERROR: {e}")
        _log(job_id, traceback.format_exc())
        raise


@celery_app.task(name="workers.tasks.import_json", bind=True)
def import_json(self, job_id: str, project_id: str, user_id: str, params: dict):
    """Import user-provided JSON script."""
    _update_job(job_id, status="running", started_at=datetime.now(timezone.utc))
    _log(job_id, "Importing JSON script...")

    try:
        project_dir = configure_for_project(user_id, project_id)

        from core.auto_video_generator_v2 import AutoVideoGenerator

        generator = AutoVideoGenerator(parent_window=None)
        generator.log = lambda msg: _log(job_id, msg)

        result = generator.process_manual_json(
            json_data=params["script_json"],
            voice_id=params.get("voice_id", "es-ES-AlvaroNeural"),
            language=params.get("language", "es"),
            rate="+0%",
            max_duration=params.get("max_duration", 60),
        )

        _update_project(project_id, storyboard_data=result, status="storyboard_ready")
        _update_job(
            job_id,
            status="completed",
            progress=100,
            completed_at=datetime.now(timezone.utc),
            result={"segments_count": len(result.get("segments", []))},
        )
        _log(job_id, "JSON import completed!")

    except Exception as e:
        _update_job(
            job_id,
            status="failed",
            error_message=str(e),
            completed_at=datetime.now(timezone.utc),
        )
        _log(job_id, f"ERROR: {e}")
        raise


@celery_app.task(name="workers.tasks.generate_images", bind=True)
def generate_images(self, job_id: str, project_id: str, user_id: str, params: dict):
    """Generate images for scenes that don't have media."""
    _update_job(job_id, status="running", started_at=datetime.now(timezone.utc))
    _log(job_id, "Generating images for missing scenes...")

    try:
        project_dir = configure_for_project(user_id, project_id)
        storyboard = _get_project_storyboard(project_id)
        if not storyboard or "segments" not in storyboard:
            raise ValueError("No storyboard data found")

        segments = storyboard["segments"]
        provider = params.get("image_provider", "recraft")
        scenes_to_generate = [
            (i, seg)
            for i, seg in enumerate(segments)
            if not seg.get("image_path") or seg.get("media_source") != "upload"
        ]

        _log(job_id, f"Generating {len(scenes_to_generate)} images with {provider}")

        for idx, (i, seg) in enumerate(scenes_to_generate):
            prompt = seg.get("visual_prompt", seg.get("text", ""))[:500]
            _log(job_id, f"Scene {i+1}: {prompt[:80]}...")

            try:
                downloads_dir = project_dir / "downloads"
                downloads_dir.mkdir(parents=True, exist_ok=True)
                output_file = str(downloads_dir / f"scene_{i}.jpg")

                if provider == "fal_ai":
                    from core.fal_ai_client import FalAiClient
                    import requests as req

                    client = FalAiClient()
                    image_url = client.generate_image(
                        prompt=prompt,
                        width=1080,
                        height=1920,
                    )
                    if image_url:
                        img_resp = req.get(image_url, timeout=30)
                        img_resp.raise_for_status()
                        with open(output_file, "wb") as f:
                            f.write(img_resp.content)
                        image_path = output_file
                    else:
                        raise ValueError(f"Fal.ai returned no URL: {client.last_error}")
                else:
                    from core.recraft_client import RecraftClient

                    client = RecraftClient()
                    result = client.generate_image(
                        prompt=prompt,
                        width=1080,
                        height=1920,
                        output_path=output_file,
                    )
                    if result and result.get("path"):
                        image_path = result["path"]
                    else:
                        raise ValueError("Recraft returned no image")

                segments[i]["image_path"] = str(image_path)
                segments[i]["media_source"] = "ai_generated"
            except Exception as img_err:
                _log(job_id, f"Warning: Failed to generate scene {i+1}: {img_err}")

            progress = int((idx + 1) / len(scenes_to_generate) * 100)
            _update_job(job_id, progress=progress)

        storyboard["segments"] = segments
        _update_project(project_id, storyboard_data=storyboard)
        _update_job(
            job_id,
            status="completed",
            progress=100,
            completed_at=datetime.now(timezone.utc),
            result={"images_generated": len(scenes_to_generate)},
        )
        _log(job_id, "Image generation completed!")

    except Exception as e:
        _update_job(
            job_id,
            status="failed",
            error_message=str(e),
            completed_at=datetime.now(timezone.utc),
        )
        _log(job_id, f"ERROR: {e}")
        raise


@celery_app.task(name="workers.tasks.generate_tts", bind=True)
def generate_tts(self, job_id: str, project_id: str, user_id: str, params: dict):
    """Generate TTS narration for all segments."""
    _update_job(job_id, status="running", started_at=datetime.now(timezone.utc))
    _log(job_id, "Generating TTS narration...")

    try:
        project_dir = configure_for_project(user_id, project_id)
        storyboard = _get_project_storyboard(project_id)
        if not storyboard or "segments" not in storyboard:
            raise ValueError("No storyboard data found")

        from core.tts_generator import TextToSpeechGenerator

        tts = TextToSpeechGenerator()

        # BYOK: override ElevenLabs key if user provided their own
        user_el_key = params.get("elevenlabs_api_key", "")
        if user_el_key:
            tts.elevenlabs_key = user_el_key
            _log(job_id, "Using user's ElevenLabs API key (BYOK)")

        # Combine all segment text for single narration
        full_text = " ".join(seg.get("text", "") for seg in storyboard["segments"])
        voice_id = params.get("voice_id", "es-ES-AlvaroNeural")
        language = params.get("language", "es")

        _log(job_id, f"Voice: {voice_id}, Language: {language}")
        _log(job_id, f"Text length: {len(full_text)} chars")

        audio_dir = project_dir / "audio"
        audio_dir.mkdir(parents=True, exist_ok=True)
        output_file = str(audio_dir / "narration.mp3")

        audio_path = tts.generate_narration(
            script=full_text,
            filename=output_file,
            voice_id=voice_id,
            language=language,
        )

        storyboard["narration_path"] = str(audio_path)
        storyboard["audio_path"] = str(audio_path)
        storyboard.pop("tts_outdated", None)  # Clear outdated flag after regeneration
        _update_project(project_id, storyboard_data=storyboard)
        _update_job(
            job_id,
            status="completed",
            progress=100,
            completed_at=datetime.now(timezone.utc),
            result={"audio_path": str(audio_path)},
        )
        _log(job_id, "TTS generation completed!")

    except Exception as e:
        _update_job(
            job_id,
            status="failed",
            error_message=str(e),
            completed_at=datetime.now(timezone.utc),
        )
        _log(job_id, f"ERROR: {e}")
        raise


@celery_app.task(name="workers.tasks.assemble_video", bind=True)
def assemble_video(self, job_id: str, project_id: str, user_id: str, params: dict):
    """Assemble final video from storyboard data."""
    _update_job(job_id, status="running", started_at=datetime.now(timezone.utc))
    _log(job_id, "Assembling video...")

    try:
        project_dir = configure_for_project(user_id, project_id)
        storyboard = _get_project_storyboard(project_id)
        if not storyboard:
            raise ValueError("No storyboard data found")

        from core.auto_video_generator_v2 import AutoVideoGenerator

        generator = AutoVideoGenerator(parent_window=None)
        generator.log = lambda msg: _log(job_id, msg)

        # Activate dynamic subtitles (normally done by GUI)
        try:
            from dynamic_subtitle_wrapper import patch_subtitle_generation
            patch_subtitle_generation(generator, params.get("subtitle_style", "capcut"))
            _log(job_id, "Dynamic subtitles activated (Whisper sync)")
        except Exception as sub_err:
            _log(job_id, f"Warning: Could not activate dynamic subtitles: {sub_err}")

        _log(job_id, "Calling assemble_video_from_storyboard...")

        result = generator.assemble_video_from_storyboard(
            storyboard_data=storyboard,
            platform=params.get("platform", "youtube_short"),
            add_subtitles=True,
            subtitle_style=params.get("subtitle_style", "capcut"),
            image_provider=storyboard.get("image_provider", "recraft"),
        )

        # Result is a dict with 'video_path' key
        if isinstance(result, dict):
            output_path = result.get("video_path", str(project_dir / "output" / "final.mp4"))
        elif isinstance(result, str):
            output_path = result
        else:
            output_path = str(project_dir / "output" / "final.mp4")

        _update_project(project_id, output_video_path=output_path, status="completed")
        _update_job(
            job_id,
            status="completed",
            progress=100,
            completed_at=datetime.now(timezone.utc),
            result={"output_path": output_path},
        )
        _log(job_id, f"Video assembled: {output_path}")

    except Exception as e:
        _update_project(project_id, status="failed")
        _update_job(
            job_id,
            status="failed",
            error_message=str(e),
            completed_at=datetime.now(timezone.utc),
        )
        _log(job_id, f"ERROR: {e}")
        _log(job_id, traceback.format_exc())
        raise
