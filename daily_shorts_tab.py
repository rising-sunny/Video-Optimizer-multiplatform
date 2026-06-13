"""
daily_shorts_tab.py — Tab de GUI para el pipeline de Daily Shorts.

Integra la funcionalidad de daily_short_pipeline.py en la interfaz PyQt6
del Video-Optimizer-multiplatform.
"""

import os
import sys
import json
import time
import shutil
import subprocess
from pathlib import Path
from datetime import datetime, timezone

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QTextEdit, QComboBox, QSpinBox, QGroupBox,
    QProgressBar, QScrollArea, QFrame, QSplitter, QFileDialog,
    QGridLayout, QSizePolicy, QApplication, QMessageBox, QCheckBox,
    QDateEdit, QDateTimeEdit, QDialog, QListWidget, QAbstractItemView,
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QTimer, QSize, QDate, QDateTime
from PyQt6.QtGui import QPixmap, QIcon, QFont

from subtitle_style_catalog import (
    DEFAULT_SUBTITLE_STYLE_LABEL,
    SUBTITLE_STYLE_LABELS,
    get_subtitle_style_label,
)

PROJECT_DIR = Path(__file__).resolve().parent


# ═══════════════════════════════════════════════════════════════════════════
# WORKER THREAD — ejecuta el pipeline sin bloquear la GUI
# ═══════════════════════════════════════════════════════════════════════════

class PipelineWorker(QThread):
    """Ejecuta el pipeline de Daily Shorts en un hilo separado."""

    step_started = pyqtSignal(int, str)       # (step_index, step_name)
    step_completed = pyqtSignal(int, str)      # (step_index, result_info)
    step_failed = pyqtSignal(int, str)         # (step_index, error_msg)
    log_message = pyqtSignal(str)              # log line
    pipeline_finished = pyqtSignal(dict)       # result dict
    pipeline_error = pyqtSignal(str)           # fatal error

    IMAGE_STEPS = [
        "Preparing draft",
        "Generating images",
        "Saving draft",
    ]
    SHORT_STEPS = [
        "Loading draft",
        "Validating images",
        "Assembling video (with subtitles)",
        "Generating metadata",
        "Saving summary",
    ]
    SHORT_STEPS_WITH_UPLOAD = SHORT_STEPS + ["Publishing to selected platforms"]
    STEPS = [
        "Preparing draft",
        "Generating images",
        "Saving draft",
        "Loading draft",
        "Validating images",
        "Assembling video (with subtitles)",
        "Generating metadata",
        "Saving summary",
        "Publishing to selected platforms",
    ]

    def __init__(self, mode="images", topic=None, voice_id=None, upload=False,
                 privacy_status="private", publish_at=None, upload_facebook=False,
                 upload_instagram=False,
                 facebook_video_state="PUBLISHED", facebook_publish_at=None, bgm_path=None,
                 image_provider="auto", visual_style=None, subtitle_style=None,
                 output_dir=None,
                 parent=None):
        super().__init__(parent)
        self.mode = mode
        self.topic = topic
        self.voice_id = voice_id
        self.upload_youtube = bool(upload)
        self.upload_facebook = bool(upload_facebook)
        self.upload_instagram = bool(upload_instagram)
        self.upload = self.upload_youtube or self.upload_facebook or self.upload_instagram
        self.privacy_status = privacy_status
        self.publish_at = publish_at
        self.facebook_video_state = str(facebook_video_state or "PUBLISHED").upper()
        self.facebook_publish_at = facebook_publish_at
        self.bgm_path = bgm_path
        self.image_provider = image_provider
        self.visual_style = visual_style
        self.subtitle_style = subtitle_style
        self.output_dir = Path(output_dir) if output_dir else None
        self._cancelled = False

    def _facebook_completion_label(self) -> str:
        if self.facebook_publish_at:
            return f"Facebook scheduled: {self.facebook_publish_at}"
        if self.facebook_video_state == "DRAFT":
            return "Facebook draft created"
        return "Facebook published"

    def _instagram_completion_label(self) -> str:
        if self.publish_at:
            return f"Instagram queued on VPS: {self.publish_at}"
        return "Instagram published"

    @classmethod
    def steps_for_mode(cls, mode: str, upload: bool = False, upload_facebook: bool = False,
                       upload_instagram: bool = False) -> list[str]:
        if mode == "short":
            return list(
                cls.SHORT_STEPS_WITH_UPLOAD
                if (upload or upload_facebook or upload_instagram)
                else cls.SHORT_STEPS
            )
        return list(cls.IMAGE_STEPS)

    def cancel(self):
        self._cancelled = True

    def run(self):
        try:
            self._run_pipeline()
        except Exception as e:
            import traceback
            traceback.print_exc()
            self.pipeline_error.emit(str(e))

    def _emit_step(self, idx, name):
        if self._cancelled:
            raise InterruptedError("Pipeline cancelled by user")
        total = len(self.steps_for_mode(self.mode, self.upload_youtube, self.upload_facebook, self.upload_instagram))
        self.step_started.emit(idx, name)
        self.log_message.emit(f"[Step {idx + 1}/{total}] {name}...")

    def _run_pipeline(self):
        if self.mode == "short":
            self._run_short_pipeline()
            return
        if self.mode == "images":
            self._run_image_pipeline()
            return

        start_time = time.time()

        # ── Init AI ──
        self.log_message.emit("Initializing AI clients...")
        from groq_client import GroqAiClient
        ai_client = GroqAiClient()

        # ── Output dir ──
        from daily_short_pipeline import create_output_dir, CHANNEL_CONFIG, get_used_titles
        output_dir = create_output_dir()
        self.log_message.emit(f"Output: {output_dir}")

        self.log_message.emit("Loading existing titles for deduplication...")
        used_titles = get_used_titles()
        if used_titles:
            self.log_message.emit(f"Loaded {len(used_titles)} existing titles")
        else:
            self.log_message.emit("No previous titles found")

        # ── Step 1: Trends ──
        self._emit_step(0, self.STEPS[0])
        if self.topic:
            trends = []
            ideas = []
            self.step_completed.emit(0, "Skipped (manual topic)")
        else:
            from daily_short_pipeline import detect_trends
            trends = detect_trends(ai_client)
            self.step_completed.emit(0, f"{len(trends)} trends found")

        # ── Step 2: Ideas ──
        self._emit_step(1, self.STEPS[1])
        if self.topic:
            self.step_completed.emit(1, "Skipped (manual topic)")
        else:
            from daily_short_pipeline import generate_video_ideas
            ideas = generate_video_ideas(trends, ai_client, used_titles=used_titles)
            self.step_completed.emit(1, f"{len(ideas)} ideas generated")

        # ── Step 3: Select best idea ──
        self._emit_step(2, self.STEPS[2])
        from daily_short_pipeline import select_best_idea
        try:
            idea = select_best_idea(ideas, forced_topic=self.topic, used_titles=used_titles)
        except ValueError as e:
            self.step_failed.emit(2, str(e))
            self.pipeline_error.emit(str(e))
            return
        self.step_completed.emit(2, idea.get("title", "?"))

        # Save idea
        idea_path = output_dir / "idea.json"
        with open(idea_path, "w", encoding="utf-8") as f:
            json.dump(idea, f, indent=2, ensure_ascii=False)

        # ── Step 4: Storyboard ──
        self._emit_step(3, self.STEPS[3])
        from daily_short_pipeline import generate_storyboard
        storyboard = generate_storyboard(idea, voice_id=self.voice_id,
                                          bgm_path=self.bgm_path,
                                          visual_style=self.visual_style,
                                          subtitle_style=self.subtitle_style)
        if not storyboard:
            self.step_failed.emit(3, "Storyboard generation failed")
            self.pipeline_error.emit("Could not generate storyboard")
            return
        seg_count = len(storyboard.get("segments", []))
        self.step_completed.emit(3, f"{seg_count} segments")

        # ── Step 5: Assemble video (with subtitles) ──
        self._emit_step(4, self.STEPS[4])
        from daily_short_pipeline import assemble_video
        video_path = assemble_video(storyboard, output_dir,
                                     image_provider=self.image_provider,
                                     visual_style=self.visual_style,
                                     subtitle_style=self.subtitle_style)
        if not video_path:
            self.step_failed.emit(4, "Video assembly failed")
            self.pipeline_error.emit("Could not assemble video")
            return
        self.step_completed.emit(4, "Video assembled with subtitles")

        # ── Step 6: Thumbnail ──
        self._emit_step(5, self.STEPS[5])
        thumbnail_path = None
        self.step_completed.emit(5, "Skipped for vertical Shorts")

        # ── Step 7: Metadata ──
        self._emit_step(6, self.STEPS[6])
        from daily_short_pipeline import generate_metadata, save_summary
        metadata = generate_metadata(storyboard, output_dir)
        if metadata:
            self.step_completed.emit(6, "Metadata ready")
        else:
            self.step_failed.emit(6, "Metadata failed (using fallback)")
            metadata = metadata or {}

        # ── Step 8: Save summary ──
        self._emit_step(7, self.STEPS[7])
        save_summary(output_dir, idea, video_path, thumbnail_path, metadata, storyboard)
        self.step_completed.emit(7, "Summary saved")

        # ── Step 9: Upload to YouTube (optional) ──
        upload_results = {}
        if self.upload:
            self._emit_step(8, self.STEPS[8])
            try:
                from daily_short_pipeline import upload_to_facebook, upload_to_instagram, upload_to_youtube

                failures = []
                completed = []

                if self.upload_youtube:
                    upload_results["youtube"] = upload_to_youtube(
                        output_dir,
                        privacy_status=self.privacy_status,
                        publish_at=self.publish_at,
                    )
                    if upload_results["youtube"]:
                        if self.publish_at:
                            completed.append(f"YouTube scheduled: {self.publish_at}")
                        else:
                            completed.append("YouTube uploaded")
                    else:
                        failures.append("YouTube upload failed")

                if self.upload_facebook:
                    upload_results["facebook"] = upload_to_facebook(
                        output_dir,
                        video_state=self.facebook_video_state,
                        publish_at=self.facebook_publish_at,
                    )
                    if upload_results["facebook"]:
                        completed.append(self._facebook_completion_label())
                    else:
                        failures.append("Facebook upload failed")

                if self.upload_instagram:
                    upload_results["instagram"] = upload_to_instagram(output_dir, publish_at=self.publish_at)
                    if upload_results["instagram"]:
                        completed.append(self._instagram_completion_label())
                    else:
                        failures.append("Instagram upload failed")

                if failures:
                    self.step_failed.emit(8, "; ".join(failures)[:120])
                elif completed:
                    self.step_completed.emit(8, " | ".join(completed)[:120])
            except Exception as e:
                self.step_failed.emit(8, str(e)[:60])

        elapsed = time.time() - start_time
        result = {
            "video_path": video_path,
            "thumbnail_path": thumbnail_path,
            "metadata": metadata,
            "output_dir": str(output_dir),
            "elapsed": elapsed,
            "topic": idea.get("title", ""),
            "upload_result": (
                upload_results.get("youtube")
                or upload_results.get("facebook")
                or upload_results.get("instagram")
            ),
            "upload_results": upload_results,
        }
        self.pipeline_finished.emit(result)

    def _load_existing_draft(self):
        from daily_short_pipeline import load_idea, load_storyboard

        if not self.output_dir:
            raise ValueError("Draft folder not provided")

        idea = load_idea(self.output_dir) or {}
        storyboard = load_storyboard(self.output_dir)
        if not storyboard:
            raise ValueError(f"Storyboard not found in draft: {self.output_dir}")
        return idea, storyboard

    def _run_image_pipeline(self):
        start_time = time.time()

        from daily_short_pipeline import prepare_short_draft, generate_images_for_draft

        self._emit_step(0, self.IMAGE_STEPS[0])
        if self.output_dir:
            output_dir = Path(self.output_dir)
            idea, storyboard = self._load_existing_draft()
            seg_count = len(storyboard.get("segments", []))
            self.step_completed.emit(0, f"{idea.get('title', output_dir.name)} ({seg_count} segments)")
        else:
            output_dir, idea, storyboard = prepare_short_draft(
                topic=self.topic,
                voice_id=self.voice_id,
                bgm_path=self.bgm_path,
                visual_style=self.visual_style,
                subtitle_style=self.subtitle_style,
            )
            self.output_dir = Path(output_dir)
            seg_count = len(storyboard.get("segments", []))
            self.step_completed.emit(0, f"{idea.get('title', output_dir.name)} ({seg_count} segments)")

        self._emit_step(1, self.IMAGE_STEPS[1])
        storyboard, draft_state = generate_images_for_draft(
            output_dir=output_dir,
            storyboard=storyboard,
            image_provider=self.image_provider,
            visual_style=self.visual_style,
        )
        ready_segments = draft_state.get("segments_ready", 0)
        total_segments = draft_state.get("segments_total", 0)
        missing_segments = draft_state.get("segments_missing", 0)
        info = f"{ready_segments}/{total_segments} ready"
        if missing_segments:
            info += f" ({missing_segments} pending)"
        self.step_completed.emit(1, info)

        self._emit_step(2, self.IMAGE_STEPS[2])
        self.step_completed.emit(2, draft_state.get("status", "saved").replace("_", " "))

        elapsed = time.time() - start_time
        self.pipeline_finished.emit({
            "mode": "images",
            "output_dir": str(output_dir),
            "elapsed": elapsed,
            "topic": idea.get("title", output_dir.name),
            "draft_state": draft_state,
            "storyboard": storyboard,
        })

    def _run_short_pipeline(self):
        start_time = time.time()

        from daily_short_pipeline import (
            assemble_video,
            generate_metadata,
            get_draft_state,
            get_storyboard_visual_status,
            save_pipeline_state,
            save_summary,
        )

        self._emit_step(0, self.SHORT_STEPS[0])
        output_dir = Path(self.output_dir) if self.output_dir else None
        if not output_dir:
            raise ValueError("No draft selected to generate the short")

        idea, storyboard = self._load_existing_draft()
        self.step_completed.emit(0, idea.get("title", output_dir.name))

        self._emit_step(1, self.SHORT_STEPS[1])
        visual_status = get_storyboard_visual_status(storyboard, output_dir)
        if visual_status.get("missing_segments_count", 0) > 0:
            missing = visual_status.get("missing_segments", [])
            preview = ", ".join(str(x) for x in missing[:8])
            if len(missing) > 8:
                preview += "..."
            error_msg = (
                f"Draft not ready. Missing images in {visual_status['missing_segments_count']} "
                f"segment(s): {preview}"
            )
            self.step_failed.emit(1, error_msg)
            self.pipeline_error.emit(error_msg)
            return
        self.step_completed.emit(1, f"{visual_status.get('total_segments', 0)} ready")

        self._emit_step(2, self.SHORT_STEPS[2])
        video_path = assemble_video(
            storyboard,
            output_dir,
            image_provider=self.image_provider,
            visual_style=self.visual_style,
            subtitle_style=self.subtitle_style or storyboard.get("_subtitle_style"),
            pregenerate_images=False,
            strict_existing_visuals=True,
        )
        if not video_path:
            self.step_failed.emit(2, "Video assembly failed")
            self.pipeline_error.emit("Could not assemble video")
            return
        save_pipeline_state(output_dir, status="video_ready", idea=idea, storyboard=storyboard,
                            video_path=video_path)
        self.step_completed.emit(2, "Video assembled")

        self._emit_step(3, self.SHORT_STEPS[3])
        metadata = generate_metadata(storyboard, output_dir) or {}
        self.step_completed.emit(3, "Metadata ready")

        self._emit_step(4, self.SHORT_STEPS[4])
        thumbnail_path = None
        save_summary(output_dir, idea, video_path, thumbnail_path, metadata, storyboard)
        self.step_completed.emit(4, "Summary saved")

        upload_results = {}
        if self.upload:
            self._emit_step(5, self.SHORT_STEPS_WITH_UPLOAD[5])
            try:
                from daily_short_pipeline import upload_to_facebook, upload_to_instagram, upload_to_youtube

                failures = []
                completed = []

                if self.upload_youtube:
                    upload_results["youtube"] = upload_to_youtube(
                        output_dir,
                        privacy_status=self.privacy_status,
                        publish_at=self.publish_at,
                    )
                    if upload_results["youtube"]:
                        if self.publish_at:
                            completed.append(f"YouTube scheduled: {self.publish_at}")
                        else:
                            completed.append("YouTube uploaded")
                    else:
                        failures.append("YouTube upload failed")

                if self.upload_facebook:
                    upload_results["facebook"] = upload_to_facebook(
                        output_dir,
                        video_state=self.facebook_video_state,
                        publish_at=self.facebook_publish_at,
                    )
                    if upload_results["facebook"]:
                        completed.append(self._facebook_completion_label())
                    else:
                        failures.append("Facebook upload failed")

                if self.upload_instagram:
                    upload_results["instagram"] = upload_to_instagram(output_dir, publish_at=self.publish_at)
                    if upload_results["instagram"]:
                        completed.append(self._instagram_completion_label())
                    else:
                        failures.append("Instagram upload failed")

                if failures:
                    self.step_failed.emit(5, "; ".join(failures)[:120])
                elif completed:
                    self.step_completed.emit(5, " | ".join(completed)[:120])
            except Exception as e:
                self.step_failed.emit(5, str(e)[:60])

        elapsed = time.time() - start_time
        self.pipeline_finished.emit({
            "mode": "short",
            "video_path": video_path,
            "thumbnail_path": thumbnail_path,
            "metadata": metadata,
            "output_dir": str(output_dir),
            "elapsed": elapsed,
            "topic": idea.get("title", output_dir.name),
            "upload_result": (
                upload_results.get("youtube")
                or upload_results.get("facebook")
                or upload_results.get("instagram")
            ),
            "upload_results": upload_results,
            "draft_state": get_draft_state(output_dir),
        })


# ═══════════════════════════════════════════════════════════════════════════
# HISTORY CARD — widget para mostrar un short generado
# ═══════════════════════════════════════════════════════════════════════════

def _parse_publish_datetime(value: str):
    """Parse ISO 8601 publish_at values into timezone-aware datetimes."""
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed
    except Exception:
        return None


def _format_publish_datetime(value: str) -> str:
    """Format publish_at using local timezone when possible."""
    parsed = _parse_publish_datetime(value)
    if not parsed:
        return value or "Unknown"
    return parsed.astimezone().strftime("%Y-%m-%d %H:%M")


def _format_publish_job_label(job: dict) -> str:
    title = str(job.get("title") or Path(job.get("folder") or "").name or "Untitled").strip()
    platforms = []
    if job.get("youtube"):
        platforms.append(f"YT:{job.get('privacy', 'private')}")
    if job.get("facebook"):
        platforms.append("FB")
    if job.get("instagram"):
        platforms.append("IG")
    platform_text = "+".join(platforms) or "No platform"
    publish_at = str(job.get("publish_at") or "").strip()
    when = _format_publish_datetime(publish_at) if publish_at else "Now"
    return f"{when} | {platform_text} | {title}"


def _dedupe_upload_records(records: list[dict]) -> list[dict]:
    deduped = []
    seen = set()
    for record in records or []:
        key = (
            str(record.get("video_id") or ""),
            str(record.get("uploaded_at") or ""),
            str(record.get("publish_at") or ""),
            str(record.get("url") or ""),
            str(record.get("permalink_url") or ""),
            str(record.get("platform") or ""),
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(record)
    return deduped


class PublishPlanWorker(QThread):
    """Upload/schedule an arbitrary list of already generated shorts."""

    step_started = pyqtSignal(int, str)
    step_completed = pyqtSignal(int, str)
    step_failed = pyqtSignal(int, str)
    log_message = pyqtSignal(str)
    pipeline_finished = pyqtSignal(dict)
    pipeline_error = pyqtSignal(str)

    def __init__(self, jobs: list[dict], parent=None):
        super().__init__(parent)
        self.jobs = list(jobs or [])
        self._cancelled = False

    @staticmethod
    def steps_for_jobs(jobs: list[dict]) -> list[str]:
        return [_format_publish_job_label(job) for job in jobs or []]

    def cancel(self):
        self._cancelled = True

    def run(self):
        start_time = time.time()
        completed_jobs = 0
        failed_jobs = []
        results = []

        try:
            from daily_short_pipeline import upload_to_facebook, upload_to_instagram, upload_to_youtube

            for idx, job in enumerate(self.jobs):
                if self._cancelled:
                    raise InterruptedError("Publish plan cancelled by user")

                label = _format_publish_job_label(job)
                self.step_started.emit(idx, label)
                self.log_message.emit(f"[Publish {idx + 1}/{len(self.jobs)}] {label}")

                folder = Path(job.get("folder") or "")
                publish_at = str(job.get("publish_at") or "").strip() or None
                privacy = str(job.get("privacy") or "private")
                job_results = {}
                parts = []
                failures = []

                if job.get("youtube"):
                    yt_result = upload_to_youtube(folder, privacy_status=privacy, publish_at=publish_at)
                    job_results["youtube"] = yt_result
                    if yt_result:
                        parts.append(f"YouTube {'scheduled' if publish_at else 'uploaded'}")
                    else:
                        failures.append("YouTube upload failed")

                if job.get("facebook"):
                    fb_result = upload_to_facebook(folder, video_state="PUBLISHED", publish_at=publish_at)
                    job_results["facebook"] = fb_result
                    if fb_result:
                        parts.append(f"Facebook {'scheduled' if publish_at else 'published'}")
                    else:
                        failures.append("Facebook upload failed")

                if job.get("instagram"):
                    ig_result = upload_to_instagram(folder, publish_at=publish_at)
                    job_results["instagram"] = ig_result
                    if ig_result:
                        parts.append(f"Instagram {'queued on VPS' if publish_at else 'published'}")
                    else:
                        failures.append("Instagram publish failed")

                if failures:
                    failed_jobs.append({"job": job, "error": "; ".join(failures)})
                    self.step_failed.emit(idx, "; ".join(failures)[:120])
                else:
                    completed_jobs += 1
                    self.step_completed.emit(idx, " | ".join(parts)[:120] or "Done")

                results.append({"job": job, "results": job_results})

        except InterruptedError as e:
            self.pipeline_error.emit(str(e))
            return
        except Exception as e:
            self.pipeline_error.emit(str(e))
            return

        elapsed = time.time() - start_time
        self.pipeline_finished.emit(
            {
                "mode": "publish",
                "elapsed": elapsed,
                "jobs_total": len(self.jobs),
                "jobs_completed": completed_jobs,
                "jobs_failed": failed_jobs,
                "job_results": results,
            }
        )


class PublishPlanDialog(QDialog):
    """Build a custom immediate/scheduled publish plan for selected videos."""

    def __init__(self, video_items: list[dict], default_privacy: str = "private",
                 default_youtube: bool = True, default_facebook: bool = False,
                 default_instagram: bool = False, parent=None):
        super().__init__(parent)
        self.video_items = list(video_items or [])
        self.jobs = []
        self.setWindowTitle("Publish / Schedule Selected Shorts")
        self.resize(780, 520)
        self._build_ui(default_privacy=default_privacy,
                       default_youtube=default_youtube,
                       default_facebook=default_facebook,
                       default_instagram=default_instagram)

    def _build_ui(self, default_privacy: str, default_youtube: bool,
                  default_facebook: bool, default_instagram: bool):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)

        help_label = QLabel(
            "Create a custom publishing plan for the selected shorts.\n"
            "Use 'All selected videos' to publish a full group on the same day, or pick one video to repeat it on different dates.\n"
            "Tip: select a job below to load it back into the form, then update only that video.\n"
            "You can also Ctrl/Shift-select multiple jobs below and apply the same publish date/time to all of them.\n"
            "Scheduled Instagram jobs are queued for the VPS scheduler and published there at the target time."
        )
        help_label.setWordWrap(True)
        help_label.setStyleSheet("color: #b8b8b8;")
        layout.addWidget(help_label)

        source_row = QHBoxLayout()
        source_row.addWidget(QLabel("Source:"))
        self.source_combo = QComboBox()
        self.source_combo.addItem(f"All selected videos ({len(self.video_items)})", "__all__")
        for item in self.video_items:
            self.source_combo.addItem(item.get("title") or Path(item.get("folder") or "").name, item.get("folder"))
        source_row.addWidget(self.source_combo, stretch=1)
        layout.addLayout(source_row)
        self.source_combo.currentIndexChanged.connect(self._refresh_metadata_preview)

        platform_row = QHBoxLayout()
        platform_row.addWidget(QLabel("Platforms:"))
        self.youtube_check = QCheckBox("YouTube")
        self.youtube_check.setChecked(bool(default_youtube))
        self.youtube_check.toggled.connect(self._refresh_metadata_preview)
        platform_row.addWidget(self.youtube_check)
        self.facebook_check = QCheckBox("Facebook")
        self.facebook_check.setChecked(bool(default_facebook))
        self.facebook_check.toggled.connect(self._refresh_metadata_preview)
        platform_row.addWidget(self.facebook_check)
        self.instagram_check = QCheckBox("Instagram")
        self.instagram_check.setChecked(bool(default_instagram))
        self.instagram_check.toggled.connect(self._refresh_metadata_preview)
        platform_row.addWidget(self.instagram_check)
        platform_row.addSpacing(14)
        platform_row.addWidget(QLabel("YT privacy:"))
        self.privacy_combo = QComboBox()
        self.privacy_combo.addItem("Private", "private")
        self.privacy_combo.addItem("Unlisted", "unlisted")
        self.privacy_combo.addItem("Public", "public")
        default_index = max(0, self.privacy_combo.findData(default_privacy))
        self.privacy_combo.setCurrentIndex(default_index)
        self.privacy_combo.setEnabled(self.youtube_check.isChecked())
        self.youtube_check.toggled.connect(self.privacy_combo.setEnabled)
        platform_row.addWidget(self.privacy_combo)
        platform_row.addStretch()
        layout.addLayout(platform_row)

        schedule_row = QHBoxLayout()
        schedule_row.addWidget(QLabel("Publish at (local time):"))
        self.publish_at_edit = QDateTimeEdit()
        self.publish_at_edit.setCalendarPopup(True)
        self.publish_at_edit.setDisplayFormat("yyyy-MM-dd HH:mm")
        self.publish_at_edit.setMinimumDateTime(QDateTime.currentDateTime())
        self.publish_at_edit.setDateTime(QDateTime.currentDateTime().addSecs(3600))
        schedule_row.addWidget(self.publish_at_edit)

        btn_add_now = QPushButton("Add Immediate Job")
        btn_add_now.clicked.connect(lambda: self._add_jobs(immediate=True))
        schedule_row.addWidget(btn_add_now)

        btn_add_scheduled = QPushButton("Add Scheduled Job")
        btn_add_scheduled.clicked.connect(lambda: self._add_jobs(immediate=False))
        schedule_row.addWidget(btn_add_scheduled)
        layout.addLayout(schedule_row)

        preview_label = QLabel("Metadata preview")
        preview_label.setStyleSheet("font-weight: bold; color: #d8d8d8;")
        layout.addWidget(preview_label)

        self.metadata_preview = QTextEdit()
        self.metadata_preview.setReadOnly(True)
        self.metadata_preview.setMinimumHeight(140)
        self.metadata_preview.setStyleSheet(
            "QTextEdit { background: #1f2329; color: #d6dde8; border: 1px solid #36404a; border-radius: 6px; }"
        )
        layout.addWidget(self.metadata_preview)

        self.jobs_list = QListWidget()
        self.jobs_list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.jobs_list.itemSelectionChanged.connect(self._on_job_selection_changed)
        layout.addWidget(self.jobs_list, stretch=1)

        manage_row = QHBoxLayout()
        btn_update_scheduled = QPushButton("Update Selected Scheduled")
        btn_update_scheduled.clicked.connect(lambda: self._update_selected_job(immediate=False))
        manage_row.addWidget(btn_update_scheduled)

        btn_update_immediate = QPushButton("Update Selected Immediate")
        btn_update_immediate.clicked.connect(lambda: self._update_selected_job(immediate=True))
        manage_row.addWidget(btn_update_immediate)

        btn_remove = QPushButton("Remove Selected Job")
        btn_remove.clicked.connect(self._remove_selected_job)
        manage_row.addWidget(btn_remove)

        btn_clear = QPushButton("Clear Plan")
        btn_clear.clicked.connect(self._clear_jobs)
        manage_row.addWidget(btn_clear)
        manage_row.addStretch()
        layout.addLayout(manage_row)

        bottom_row = QHBoxLayout()
        bottom_row.addStretch()
        btn_cancel = QPushButton("Cancel")
        btn_cancel.clicked.connect(self.reject)
        bottom_row.addWidget(btn_cancel)

        btn_run = QPushButton("Run Publish Plan")
        btn_run.setObjectName("accent")
        btn_run.clicked.connect(self._accept_plan)
        bottom_row.addWidget(btn_run)
        layout.addLayout(bottom_row)
        self._refresh_metadata_preview()

    def _resolve_selected_sources(self) -> list[dict]:
        source_data = self.source_combo.currentData()
        if source_data == "__all__":
            return list(self.video_items)
        return [item for item in self.video_items if item.get("folder") == source_data]

    def _current_publish_at(self) -> str:
        timestamp = int(self.publish_at_edit.dateTime().toSecsSinceEpoch())
        return datetime.fromtimestamp(timestamp, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    @staticmethod
    def _safe_read_json(path: Path) -> dict:
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    def _find_video_item(self, folder: str) -> dict | None:
        folder = str(folder or "")
        return next((item for item in self.video_items if str(item.get("folder") or "") == folder), None)

    def _load_platform_metadata(self, folder: str) -> tuple[dict, dict, dict]:
        folder_path = Path(folder)
        base_meta = self._safe_read_json(folder_path / "metadata.json")
        youtube_meta = self._safe_read_json(folder_path / "youtube_metadata.json")
        facebook_meta = self._safe_read_json(folder_path / "facebook_metadata.json")
        instagram_meta = self._safe_read_json(folder_path / "instagram_metadata.json")

        item = self._find_video_item(folder) or {}
        summary = item.get("summary") or {}
        platform_metadata = summary.get("platform_metadata", {}) or {}
        if not youtube_meta:
            youtube_meta = platform_metadata.get("youtube", {}) or base_meta or summary.get("metadata", {}) or {}
        if not facebook_meta:
            facebook_meta = platform_metadata.get("facebook", {}) or base_meta or summary.get("metadata", {}) or {}
        if not instagram_meta:
            instagram_meta = platform_metadata.get("instagram", {}) or facebook_meta or base_meta or summary.get("metadata", {}) or {}
        return youtube_meta, facebook_meta, instagram_meta

    def _refresh_metadata_preview(self, *_args):
        source_data = self.source_combo.currentData()
        if source_data == "__all__":
            titles = [str(item.get("title") or Path(item.get("folder") or "").name) for item in self.video_items[:8]]
            extra = max(0, len(self.video_items) - len(titles))
            text = [
                "Metadata preview is per-video.",
                "Choose a specific source or click a job below to inspect the exact title and description that will be published.",
                "",
                f"Current group: {len(self.video_items)} selected video(s)",
            ]
            if titles:
                text.append("Examples:")
                text.extend(f"- {title}" for title in titles)
            if extra:
                text.append(f"... and {extra} more")
            self.metadata_preview.setPlainText("\n".join(text))
            return

        folder = str(source_data or "")
        if not folder:
            self.metadata_preview.setPlainText("Choose a source video to preview its metadata.")
            return

        youtube_meta, facebook_meta, instagram_meta = self._load_platform_metadata(folder)
        blocks = []

        if self.youtube_check.isChecked():
            title = str(youtube_meta.get("title") or "").strip()
            description = str(youtube_meta.get("description") or "").strip()
            tags = youtube_meta.get("tags") or []
            blocks.append("[YouTube]")
            blocks.append(f"Title: {title or '(missing)'}")
            blocks.append("")
            blocks.append("Description:")
            blocks.append(description or "(missing)")
            if tags:
                if not isinstance(tags, list):
                    tags = [str(tags)]
                blocks.append("")
                blocks.append("Tags:")
                blocks.append(", ".join(str(tag) for tag in tags))

        if self.facebook_check.isChecked():
            if blocks:
                blocks.extend(["", ""])
            title = str(facebook_meta.get("title") or "").strip()
            description = str(facebook_meta.get("description") or "").strip()
            blocks.append("[Facebook]")
            blocks.append(f"Title: {title or '(missing)'}")
            blocks.append("")
            blocks.append("Description:")
            blocks.append(description or "(missing)")

        if self.instagram_check.isChecked():
            if blocks:
                blocks.extend(["", ""])
            title = str(instagram_meta.get("title") or "").strip()
            description = str(instagram_meta.get("description") or "").strip()
            blocks.append("[Instagram]")
            blocks.append(f"Title: {title or '(missing)'}")
            blocks.append("")
            blocks.append("Description:")
            blocks.append(description or "(missing)")

        if not blocks:
            blocks.append("Select at least one platform to preview its metadata.")

        self.metadata_preview.setPlainText("\n".join(blocks))

    def _job_from_form(self, immediate: bool, existing_job: dict | None = None) -> dict | None:
        if not self.youtube_check.isChecked() and not self.facebook_check.isChecked() and not self.instagram_check.isChecked():
            QMessageBox.warning(self, "Publish Plan", "Select at least one platform.")
            return None

        source_data = self.source_combo.currentData()
        source_item = None
        if source_data != "__all__":
            source_item = next((item for item in self.video_items if item.get("folder") == source_data), None)
        elif existing_job:
            source_item = {
                "folder": existing_job.get("folder"),
                "title": existing_job.get("title"),
            }

        if not source_item:
            QMessageBox.warning(
                self,
                "Publish Plan",
                "Choose one source video to edit this job, or select a job first so its source is loaded.",
            )
            return None

        return {
            "folder": source_item.get("folder"),
            "title": source_item.get("title") or Path(source_item.get("folder") or "").name,
            "youtube": self.youtube_check.isChecked(),
            "facebook": self.facebook_check.isChecked(),
            "instagram": self.instagram_check.isChecked(),
            "privacy": self.privacy_combo.currentData() or "private",
            "publish_at": None if immediate else self._current_publish_at(),
        }

    def _selected_job_rows(self) -> list[int]:
        rows = sorted({index.row() for index in self.jobs_list.selectedIndexes()})
        return [row for row in rows if 0 <= row < len(self.jobs)]

    def _refresh_jobs_list(self):
        current_row = self.jobs_list.currentRow()
        self.jobs_list.blockSignals(True)
        self.jobs_list.clear()
        for job in self.jobs:
            self.jobs_list.addItem(_format_publish_job_label(job))
        self.jobs_list.blockSignals(False)
        if self.jobs:
            if 0 <= current_row < len(self.jobs):
                self.jobs_list.setCurrentRow(current_row)
            else:
                self.jobs_list.setCurrentRow(len(self.jobs) - 1)

    def _load_job_into_form(self, job: dict):
        folder = str(job.get("folder") or "")
        combo_index = self.source_combo.findData(folder)
        if combo_index >= 0:
            self.source_combo.setCurrentIndex(combo_index)
        self.youtube_check.setChecked(bool(job.get("youtube")))
        self.facebook_check.setChecked(bool(job.get("facebook")))
        self.instagram_check.setChecked(bool(job.get("instagram")))
        privacy_index = self.privacy_combo.findData(job.get("privacy") or "private")
        if privacy_index >= 0:
            self.privacy_combo.setCurrentIndex(privacy_index)

        publish_at = str(job.get("publish_at") or "").strip()
        parsed = _parse_publish_datetime(publish_at)
        if parsed:
            self.publish_at_edit.setDateTime(QDateTime.fromSecsSinceEpoch(int(parsed.timestamp())))

    def _add_jobs(self, immediate: bool):
        if not self.youtube_check.isChecked() and not self.facebook_check.isChecked() and not self.instagram_check.isChecked():
            QMessageBox.warning(self, "Publish Plan", "Select at least one platform.")
            return

        sources = self._resolve_selected_sources()
        if not sources:
            QMessageBox.warning(self, "Publish Plan", "Select at least one source video.")
            return

        publish_at = None if immediate else self._current_publish_at()
        privacy = self.privacy_combo.currentData() or "private"

        for item in sources:
            job = {
                "folder": item.get("folder"),
                "title": item.get("title"),
                "youtube": self.youtube_check.isChecked(),
                "facebook": self.facebook_check.isChecked(),
                "instagram": self.instagram_check.isChecked(),
                "privacy": privacy,
                "publish_at": publish_at,
            }
            self.jobs.append(job)
        self._refresh_jobs_list()

    def _remove_selected_job(self):
        rows = self._selected_job_rows()
        if not rows:
            return
        for row in reversed(rows):
            del self.jobs[row]
        self._refresh_jobs_list()

    def _clear_jobs(self):
        self.jobs.clear()
        self._refresh_jobs_list()

    def _update_selected_job(self, immediate: bool):
        rows = self._selected_job_rows()
        if not rows:
            QMessageBox.information(self, "Publish Plan", "Select one or more jobs in the plan first.")
            return
        if len(rows) == 1:
            row = rows[0]
            updated_job = self._job_from_form(immediate=immediate, existing_job=self.jobs[row])
            if not updated_job:
                return
            self.jobs[row] = updated_job
        else:
            if not self.youtube_check.isChecked() and not self.facebook_check.isChecked() and not self.instagram_check.isChecked():
                QMessageBox.warning(self, "Publish Plan", "Select at least one platform.")
                return
            publish_at = None if immediate else self._current_publish_at()
            privacy = self.privacy_combo.currentData() or "private"
            for row in rows:
                existing_job = self.jobs[row]
                self.jobs[row] = {
                    "folder": existing_job.get("folder"),
                    "title": existing_job.get("title") or Path(existing_job.get("folder") or "").name,
                    "youtube": self.youtube_check.isChecked(),
                    "facebook": self.facebook_check.isChecked(),
                    "instagram": self.instagram_check.isChecked(),
                    "privacy": privacy,
                    "publish_at": publish_at,
                }
        self._refresh_jobs_list()
        if rows:
            self.jobs_list.setCurrentRow(rows[0])
            for row in rows[1:]:
                item = self.jobs_list.item(row)
                if item:
                    item.setSelected(True)

    def _on_job_selection_changed(self):
        rows = self._selected_job_rows()
        if not rows:
            return
        self._load_job_into_form(self.jobs[rows[0]])

    def _accept_plan(self):
        if not self.jobs:
            QMessageBox.information(self, "Publish Plan", "Add at least one job to the plan.")
            return
        self.accept()

    def get_jobs(self) -> list[dict]:
        return list(self.jobs)


class ShortCard(QFrame):
    """Tarjeta visual para un Short generado previamente."""

    def __init__(self, summary_data: dict, folder_path: str, selected: bool = False,
                 selection_changed=None, parent=None):
        super().__init__(parent)
        self.summary = summary_data
        self.folder = folder_path
        self._selection_changed = selection_changed
        self._selected = bool(selected)
        self.setFrameStyle(QFrame.Shape.StyledPanel)
        self.setStyleSheet("""
            ShortCard {
                background: #2b2b2b;
                border: 1px solid #404040;
                border-radius: 8px;
                padding: 8px;
            }
            ShortCard:hover {
                border-color: #14a085;
            }
        """)
        self._build_ui()

    def _build_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(12)

        # Thumbnail placeholder
        thumb_label = QLabel()
        thumb_label.setFixedSize(80, 142)  # 9:16 aspect
        thumb_label.setStyleSheet("background: #1a1a1a; border-radius: 4px;")
        thumb_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        thumb_path = self.summary.get("thumbnail_path")
        if thumb_path and os.path.exists(str(thumb_path)):
            pix = QPixmap(str(thumb_path))
            if not pix.isNull():
                thumb_label.setPixmap(pix.scaled(
                    80, 142, Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation
                ))
        else:
            thumb_label.setText("No\nThumb")
            thumb_label.setStyleSheet(
                "background: #1a1a1a; border-radius: 4px; color: #666; font-size: 9pt;")
        layout.addWidget(thumb_label)

        # Info
        info_layout = QVBoxLayout()
        info_layout.setSpacing(4)

        platform_metadata = self.summary.get("platform_metadata", {}) or {}
        youtube_metadata = platform_metadata.get("youtube", {}) or self.summary.get("metadata", {}) or {}
        title = self.summary.get("topic", youtube_metadata.get("title", "Untitled"))
        title_row = QHBoxLayout()
        self.select_check = QCheckBox("Select")
        self.select_check.setChecked(self._selected)
        self.select_check.toggled.connect(self._on_selection_toggled)
        title_row.addWidget(self.select_check, stretch=0)

        title_label = QLabel(title)
        title_label.setStyleSheet("font-weight: bold; font-size: 10pt; color: #e0e0e0;")
        title_label.setWordWrap(True)
        title_row.addWidget(title_label, stretch=1)
        info_layout.addLayout(title_row)

        date_str = self.summary.get("generated_at", "")[:16].replace("T", " ")
        segs = self.summary.get("segments_count", "?")
        detail = QLabel(f"{date_str}  |  {segs} segments")
        detail.setStyleSheet("color: #888; font-size: 9pt;")
        info_layout.addWidget(detail)

        info_layout.addStretch()

        # Buttons
        btn_row = QHBoxLayout()
        btn_row.setSpacing(6)

        btn_open = QPushButton("Open Folder")
        btn_open.setFixedHeight(28)
        btn_open.clicked.connect(self._open_folder)
        btn_row.addWidget(btn_open)

        btn_play = QPushButton("Play")
        btn_play.setFixedHeight(28)
        btn_play.clicked.connect(self._play_video)
        btn_row.addWidget(btn_play)

        btn_copy_meta = QPushButton("Copy Metadata")
        btn_copy_meta.setFixedHeight(28)
        btn_copy_meta.clicked.connect(self._copy_metadata)
        btn_row.addWidget(btn_copy_meta)

        youtube_upload = self._load_upload_data("upload_result.json")
        facebook_upload = self._load_upload_data("facebook_upload_result.json")
        instagram_upload = self._load_upload_data("instagram_upload_result.json")

        if youtube_upload and youtube_upload.get("url"):
            btn_yt = QPushButton("View on YT")
            btn_yt.setFixedHeight(28)
            btn_yt.setStyleSheet("color: #14a085;")
            btn_yt.setToolTip(youtube_upload.get("url", ""))
            btn_yt.clicked.connect(lambda checked=False, u=youtube_upload.get("url", ""): self._open_url(u))
            btn_row.addWidget(btn_yt)
        else:
            self.btn_upload_youtube = QPushButton("Upload YT")
            self.btn_upload_youtube.setFixedHeight(28)
            self.btn_upload_youtube.setStyleSheet("""
                QPushButton { background-color: #c0392b; color: white; border-radius: 4px; padding: 0 10px; }
                QPushButton:hover { background-color: #e74c3c; }
                QPushButton:disabled { background-color: #555; color: #999; }
            """)
            self.btn_upload_youtube.clicked.connect(self._upload_to_youtube)
            btn_row.addWidget(self.btn_upload_youtube)

        facebook_url = ""
        if facebook_upload:
            facebook_url = facebook_upload.get("url", "") or facebook_upload.get("permalink_url", "")
        if facebook_url:
            btn_fb = QPushButton("View on FB")
            btn_fb.setFixedHeight(28)
            btn_fb.setStyleSheet("color: #3498db;")
            btn_fb.setToolTip(facebook_url)
            btn_fb.clicked.connect(lambda checked=False, u=facebook_url: self._open_url(u))
            btn_row.addWidget(btn_fb)
        else:
            self.btn_upload_facebook = QPushButton("Upload FB")
            self.btn_upload_facebook.setFixedHeight(28)
            self.btn_upload_facebook.setStyleSheet("""
                QPushButton { background-color: #1877f2; color: white; border-radius: 4px; padding: 0 10px; }
                QPushButton:hover { background-color: #2d88ff; }
                QPushButton:disabled { background-color: #555; color: #999; }
            """)
            self.btn_upload_facebook.clicked.connect(self._upload_to_facebook)
            btn_row.addWidget(self.btn_upload_facebook)

        instagram_url = ""
        if instagram_upload:
            instagram_url = instagram_upload.get("url", "") or instagram_upload.get("permalink_url", "")
        if instagram_url:
            btn_ig = QPushButton("View on IG")
            btn_ig.setFixedHeight(28)
            btn_ig.setStyleSheet("color: #ff6ea8;")
            btn_ig.setToolTip(instagram_url)
            btn_ig.clicked.connect(lambda checked=False, u=instagram_url: self._open_url(u))
            btn_row.addWidget(btn_ig)
        elif instagram_upload and instagram_upload.get("scheduled"):
            btn_ig = QPushButton("IG Scheduled")
            btn_ig.setFixedHeight(28)
            btn_ig.setEnabled(False)
            btn_ig.setStyleSheet("color: #ff93c2; font-weight: bold;")
            btn_ig.setToolTip(str(instagram_upload.get("publish_at") or "Scheduled on VPS"))
            btn_row.addWidget(btn_ig)
        else:
            self.btn_upload_instagram = QPushButton("Upload IG")
            self.btn_upload_instagram.setFixedHeight(28)
            self.btn_upload_instagram.setStyleSheet("""
                QPushButton { background-color: #c13584; color: white; border-radius: 4px; padding: 0 10px; }
                QPushButton:hover { background-color: #d24b95; }
                QPushButton:disabled { background-color: #555; color: #999; }
            """)
            self.btn_upload_instagram.clicked.connect(self._upload_to_instagram)
            btn_row.addWidget(self.btn_upload_instagram)

        btn_row.addStretch()
        info_layout.addLayout(btn_row)

        layout.addLayout(info_layout, stretch=1)

    def _open_folder(self):
        folder = self.folder.replace("/", "\\")
        os.startfile(folder)

    def _play_video(self):
        vp = self.summary.get("video_path", "")
        if vp and os.path.exists(str(vp)):
            os.startfile(str(vp))

    def _load_upload_data(self, filename: str) -> dict | None:
        upload_result_path = Path(self.folder) / filename
        if not upload_result_path.exists():
            return None
        try:
            with open(upload_result_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return None

    @staticmethod
    def _open_url(url: str):
        if url:
            os.startfile(url)

    def _on_selection_toggled(self, checked):
        self._selected = bool(checked)
        if callable(self._selection_changed):
            self._selection_changed(self.folder, self._selected)

    def _copy_metadata(self):
        platform_metadata = self.summary.get("platform_metadata", {}) or {}
        youtube_meta = platform_metadata.get("youtube", {}) or self.summary.get("metadata", {}) or {}
        facebook_meta = platform_metadata.get("facebook", {}) or {}
        instagram_meta = platform_metadata.get("instagram", {}) or {}
        text_parts = []
        if youtube_meta:
            text_parts.append("[YouTube]")
            if youtube_meta.get("title"):
                text_parts.append(f"Title: {youtube_meta['title']}")
            if youtube_meta.get("description"):
                text_parts.append(f"\nDescription:\n{youtube_meta['description']}")
            if youtube_meta.get("tags"):
                tags = youtube_meta["tags"] if isinstance(youtube_meta["tags"], list) else [youtube_meta["tags"]]
                text_parts.append(f"\nTags: {', '.join(tags)}")
        if facebook_meta:
            if text_parts:
                text_parts.append("\n")
            text_parts.append("[Facebook]")
            if facebook_meta.get("title"):
                text_parts.append(f"Title: {facebook_meta['title']}")
            if facebook_meta.get("description"):
                text_parts.append(f"\nDescription:\n{facebook_meta['description']}")
        if instagram_meta:
            if text_parts:
                text_parts.append("\n")
            text_parts.append("[Instagram]")
            if instagram_meta.get("title"):
                text_parts.append(f"Title: {instagram_meta['title']}")
            if instagram_meta.get("description"):
                text_parts.append(f"\nDescription:\n{instagram_meta['description']}")
        if text_parts:
            QApplication.clipboard().setText("\n".join(text_parts))

    def _upload_to_youtube(self):
        """Upload this short to YouTube as private."""
        reply = QMessageBox.question(
            self, "Upload to YouTube",
            f"Upload this short to YouTube as PRIVATE?\n\n"
            f"Topic: {self.summary.get('topic', '?')}\n"
            f"Folder: {self.folder}",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        self.btn_upload_youtube.setEnabled(False)
        self.btn_upload_youtube.setText("Uploading...")

        class UploadWorker(QThread):
            finished = pyqtSignal(bool, str)

            def __init__(self, folder, parent=None):
                super().__init__(parent)
                self.folder = folder

            def run(self):
                try:
                    from youtube_uploader import upload_from_metadata
                    result = upload_from_metadata(self.folder, privacy_status="private")
                    self.finished.emit(True, result.get("url", ""))
                except Exception as e:
                    self.finished.emit(False, str(e))

        self._upload_worker = UploadWorker(self.folder, parent=self)
        self._upload_worker.finished.connect(self._on_upload_finished)
        self._upload_worker.start()

    def _on_upload_finished(self, success, msg):
        if success:
            self.btn_upload_youtube.setText("Uploaded!")
            self.btn_upload_youtube.setStyleSheet("color: #14a085; font-weight: bold;")
            self.btn_upload_youtube.setToolTip(msg)
            QMessageBox.information(self, "Upload Complete",
                                    f"Video uploaded successfully!\n\n{msg}")
        else:
            self.btn_upload_youtube.setEnabled(True)
            self.btn_upload_youtube.setText("Upload YT")
            QMessageBox.warning(self, "Upload Failed",
                                f"Could not upload video:\n{msg}")

    def _upload_to_facebook(self):
        reply = QMessageBox.question(
            self, "Upload to Facebook",
            f"Publish this short to your Facebook Page now?\n\n"
            f"Topic: {self.summary.get('topic', '?')}\n"
            f"Folder: {self.folder}",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        self.btn_upload_facebook.setEnabled(False)
        self.btn_upload_facebook.setText("Publishing...")

        class FacebookUploadWorker(QThread):
            finished = pyqtSignal(bool, str)

            def __init__(self, folder, parent=None):
                super().__init__(parent)
                self.folder = folder

            def run(self):
                try:
                    from facebook_uploader import upload_from_metadata
                    result = upload_from_metadata(self.folder, video_state="PUBLISHED")
                    self.finished.emit(True, result.get("url", "") or result.get("status", "published"))
                except Exception as e:
                    self.finished.emit(False, str(e))

        self._facebook_upload_worker = FacebookUploadWorker(self.folder, parent=self)
        self._facebook_upload_worker.finished.connect(self._on_facebook_upload_finished)
        self._facebook_upload_worker.start()

    def _on_facebook_upload_finished(self, success, msg):
        if success:
            self.btn_upload_facebook.setText("Published!")
            self.btn_upload_facebook.setStyleSheet("color: #3498db; font-weight: bold;")
            self.btn_upload_facebook.setToolTip(msg)
            QMessageBox.information(self, "Facebook Upload Complete",
                                    f"Video published successfully on Facebook.\n\n{msg}")
        else:
            self.btn_upload_facebook.setEnabled(True)
            self.btn_upload_facebook.setText("Upload FB")
            QMessageBox.warning(self, "Facebook Upload Failed",
                                f"Could not publish video:\n{msg}")

    def _upload_to_instagram(self):
        reply = QMessageBox.question(
            self, "Upload to Instagram",
            f"Publish this short to Instagram Reels now?\n\n"
            f"Topic: {self.summary.get('topic', '?')}\n"
            f"Folder: {self.folder}",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        self.btn_upload_instagram.setEnabled(False)
        self.btn_upload_instagram.setText("Publishing...")

        class InstagramUploadWorker(QThread):
            finished = pyqtSignal(bool, str)

            def __init__(self, folder, parent=None):
                super().__init__(parent)
                self.folder = folder

            def run(self):
                try:
                    from instagram_uploader import upload_from_metadata
                    result = upload_from_metadata(self.folder)
                    self.finished.emit(True, result.get("url", "") or result.get("status", "published"))
                except Exception as e:
                    self.finished.emit(False, str(e))

        self._instagram_upload_worker = InstagramUploadWorker(self.folder, parent=self)
        self._instagram_upload_worker.finished.connect(self._on_instagram_upload_finished)
        self._instagram_upload_worker.start()

    def _on_instagram_upload_finished(self, success, msg):
        if success:
            self.btn_upload_instagram.setText("Published!")
            self.btn_upload_instagram.setStyleSheet("color: #ff6ea8; font-weight: bold;")
            self.btn_upload_instagram.setToolTip(msg)
            QMessageBox.information(self, "Instagram Upload Complete",
                                    f"Video published successfully on Instagram.\n\n{msg}")
        else:
            self.btn_upload_instagram.setEnabled(True)
            self.btn_upload_instagram.setText("Upload IG")
            QMessageBox.warning(self, "Instagram Upload Failed",
                                f"Could not publish video:\n{msg}")


class DraftCard(QFrame):
    """Tarjeta visual para drafts pendientes o listos para ensamblar."""

    STATUS_LABELS = {
        "draft": "Draft created",
        "storyboard_ready": "Storyboard ready",
        "images_partial": "Images pending",
        "images_ready": "Ready for short",
        "video_ready": "Video ready",
        "completed": "Completed",
    }

    STATUS_COLORS = {
        "storyboard_ready": "#b58900",
        "images_partial": "#e67e22",
        "images_ready": "#14a085",
        "video_ready": "#2d89ef",
        "completed": "#14a085",
    }

    def __init__(self, draft_data: dict, folder_path: str, selected: bool = False,
                 selection_changed=None, parent=None):
        super().__init__(parent)
        self.draft = draft_data or {}
        self.folder = folder_path
        self._selection_changed = selection_changed
        self._selected = bool(selected)
        self.setFrameStyle(QFrame.Shape.StyledPanel)
        self.setStyleSheet("""
            DraftCard {
                background: #252525;
                border: 1px solid #404040;
                border-radius: 8px;
                padding: 8px;
            }
            DraftCard:hover {
                border-color: #14a085;
            }
        """)
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(6)

        status_key = self.draft.get("status", "draft")
        status_label = self.STATUS_LABELS.get(status_key, status_key.replace("_", " ").title())
        status_color = self.STATUS_COLORS.get(status_key, "#888")

        title_row = QHBoxLayout()
        self.select_check = QCheckBox("Select")
        self.select_check.setChecked(self._selected)
        self.select_check.toggled.connect(self._on_selection_toggled)
        title_row.addWidget(self.select_check, stretch=0)

        title = QLabel(self.draft.get("topic", Path(self.folder).name))
        title.setStyleSheet("font-weight: bold; font-size: 10pt; color: #e0e0e0;")
        title.setWordWrap(True)
        title_row.addWidget(title, stretch=1)

        badge = QLabel(status_label)
        badge.setStyleSheet(
            f"background: {status_color}; color: white; border-radius: 10px; padding: 2px 8px; font-size: 8.5pt;"
        )
        title_row.addWidget(badge, stretch=0)
        layout.addLayout(title_row)

        ready = self.draft.get("segments_ready", 0)
        total = self.draft.get("segments_total", 0)
        missing = self.draft.get("segments_missing", 0)
        created_at = (self.draft.get("created_at") or "")[:16].replace("T", " ")

        detail = QLabel(f"{created_at}  |  Images ready: {ready}/{total}")
        detail.setStyleSheet("color: #999; font-size: 8.8pt;")
        layout.addWidget(detail)

        subtitle_style = self.draft.get("subtitle_style")
        if subtitle_style:
            subtitle_label = QLabel(f"Subtitles: {get_subtitle_style_label(subtitle_style)}")
            subtitle_label.setWordWrap(True)
            subtitle_label.setStyleSheet("color: #8fb1ff; font-size: 8.6pt;")
            layout.addWidget(subtitle_label)

        if missing:
            missing_segments = self.draft.get("missing_segments", [])
            preview = ", ".join(str(x) for x in missing_segments[:8])
            if len(missing_segments) > 8:
                preview += "..."
            pending = QLabel(f"Pending segments: {preview}")
            pending.setStyleSheet("color: #e67e22; font-size: 8.8pt;")
            layout.addWidget(pending)

        note = (self.draft.get("note") or "").strip()
        if note:
            note_label = QLabel(note)
            note_label.setWordWrap(True)
            note_label.setStyleSheet("color: #888; font-size: 8.7pt;")
            layout.addWidget(note_label)

        btn_row = QHBoxLayout()
        btn_open = QPushButton("Open Folder")
        btn_open.setFixedHeight(28)
        btn_open.clicked.connect(self._open_folder)
        btn_row.addWidget(btn_open)

        btn_row.addStretch()
        layout.addLayout(btn_row)

    def _open_folder(self):
        folder = self.folder.replace("/", "\\")
        os.startfile(folder)

    def _on_selection_toggled(self, checked):
        self._selected = bool(checked)
        if callable(self._selection_changed):
            self._selection_changed(self.folder, self._selected)


# ═══════════════════════════════════════════════════════════════════════════
# TAB PRINCIPAL — Daily Shorts
# ═══════════════════════════════════════════════════════════════════════════

class ScheduledPostCard(QFrame):
    """Tarjeta simple para Shorts programados pendientes de publicarse."""

    def __init__(self, summary_data: dict, folder_path: str, upload_data: dict,
                 platform: str = "youtube", parent=None):
        super().__init__(parent)
        self.summary = summary_data
        self.folder = folder_path
        self.upload_data = upload_data or {}
        self.platform = str(platform or "youtube").lower()
        self.setFrameStyle(QFrame.Shape.StyledPanel)
        self.setStyleSheet("""
            ScheduledPostCard {
                background: #23313a;
                border: 1px solid #32515b;
                border-radius: 8px;
                padding: 8px;
            }
            ScheduledPostCard:hover {
                border-color: #14a085;
            }
        """)
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(6)

        platform_metadata = self.summary.get("platform_metadata", {}) or {}
        selected_metadata = (
            platform_metadata.get(self.platform, {})
            or platform_metadata.get("youtube", {})
            or self.summary.get("metadata", {})
            or {}
        )
        title = selected_metadata.get("title") or self.summary.get("topic", "Untitled")
        title_label = QLabel(title)
        title_label.setStyleSheet("font-weight: bold; font-size: 10pt; color: #e0e0e0;")
        title_label.setWordWrap(True)
        layout.addWidget(title_label)

        if self.platform == "facebook":
            platform_label = "Facebook Reel"
        elif self.platform == "instagram":
            platform_label = "Instagram Reel"
        else:
            platform_label = "YouTube Short"
        platform_chip = QLabel(platform_label)
        if self.platform == "facebook":
            platform_chip.setStyleSheet("color: #79a8ff; font-size: 8.5pt; font-weight: bold;")
        elif self.platform == "instagram":
            platform_chip.setStyleSheet("color: #ff93c2; font-size: 8.5pt; font-weight: bold;")
        else:
            platform_chip.setStyleSheet("color: #7ed6c1; font-size: 8.5pt; font-weight: bold;")
        layout.addWidget(platform_chip)

        publish_at = self.upload_data.get("publish_at")
        publish_label = QLabel(f"Publishes: {_format_publish_datetime(publish_at)}")
        publish_label.setStyleSheet("color: #7ed6c1; font-size: 9pt;")
        publish_label.setToolTip(publish_at or "")
        layout.addWidget(publish_label)

        uploaded_at = self.upload_data.get("uploaded_at", "")
        status_value = self.upload_data.get("status", "private")
        queued_locally = str(status_value).lower().startswith("queued")
        time_label = "Queued" if queued_locally else "Uploaded"
        status_label = QLabel(
            f"{time_label}: {uploaded_at.replace('T', ' ')}  |  Status: {status_value}"
        )
        status_label.setStyleSheet("color: #9fb3bb; font-size: 8.5pt;")
        layout.addWidget(status_label)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(6)

        btn_open = QPushButton("Open Folder")
        btn_open.setFixedHeight(28)
        btn_open.clicked.connect(self._open_folder)
        btn_row.addWidget(btn_open)

        url = self.upload_data.get("url", "") or self.upload_data.get("permalink_url", "")
        if self.platform == "facebook":
            view_label = "View on FB"
        elif self.platform == "instagram":
            view_label = "View on IG"
        else:
            view_label = "View on YT"
        btn_view = QPushButton(view_label)
        btn_view.setFixedHeight(28)
        btn_view.setEnabled(bool(url))
        btn_view.setToolTip(url)
        btn_view.clicked.connect(lambda checked, u=url: os.startfile(u) if u else None)
        btn_row.addWidget(btn_view)

        btn_row.addStretch()
        layout.addLayout(btn_row)

    def _open_folder(self):
        folder = self.folder.replace("/", "\\")
        os.startfile(folder)


class DailyShortsTab(QWidget):
    """Tab para producción de YouTube Shorts diarios."""

    def __init__(self, parent_gui):
        super().__init__()
        self.parent_gui = parent_gui
        self.worker = None
        self._step_labels = []
        self._current_mode = "images"
        self._task_queue = []
        self._active_task = None
        self._current_upload = False
        self._current_upload_youtube = False
        self._current_upload_facebook = False
        self._current_upload_instagram = False
        self._selected_draft_folders = set()
        self._selected_history_folders = set()
        self._draft_records = {}
        self._history_records = {}
        self._current_privacy = "private"
        self._requested_count = 0
        self._pending_short_drafts = 0
        self._schedule_presets = [
            ("1 week (12 shorts)", 12),
            ("3 days (6 shorts)", 6),
            ("1 day (2 shorts)", 2),
            ("Custom", None),
        ]
        self._build_ui()
        # Load history after UI is ready
        QTimer.singleShot(300, lambda: self._load_history(force_sync=True))

    def _build_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(14, 14, 14, 14)
        main_layout.setSpacing(10)

        # ── Title ──
        title = QLabel("Daily Shorts Studio")
        title.setStyleSheet("font-size: 16pt; font-weight: bold;")
        main_layout.addWidget(title)

        subtitle = QLabel(
            "Generate Daily Shorts in two phases: first create the draft images, "
            "then assemble the final short with subtitles and metadata."
        )
        subtitle.setWordWrap(True)
        subtitle.setStyleSheet("color: #b3b3b3;")
        main_layout.addWidget(subtitle)

        # ── Splitter: Config+Pipeline left | History right ──
        splitter = QSplitter(Qt.Orientation.Horizontal)

        # ════════════════════════════════════
        # LEFT PANEL: Config + Pipeline (scrollable)
        # ════════════════════════════════════
        left_scroll = QScrollArea()
        left_scroll.setWidgetResizable(True)
        left_scroll.setStyleSheet("QScrollArea { border: none; }")
        left_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(0, 0, 4, 0)
        left_layout.setSpacing(8)

        # ── Config Group ──
        config_group = QGroupBox("Configuration")
        config_grid = QGridLayout(config_group)
        config_grid.setSpacing(6)
        config_grid.setContentsMargins(8, 12, 8, 8)

        # Topic
        config_grid.addWidget(QLabel("Topic:"), 0, 0)
        self.topic_input = QLineEdit()
        self.topic_input.setPlaceholderText("Leave empty for automatic trend detection")
        config_grid.addWidget(self.topic_input, 0, 1, 1, 2)

        # Voice
        config_grid.addWidget(QLabel("Voice:"), 1, 0)
        voice_row = QHBoxLayout()
        self.voice_combo = QComboBox()
        self.voice_combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.voice_combo.addItem("Loading voices...")
        self.voice_combo.setEnabled(False)
        voice_row.addWidget(self.voice_combo, stretch=1)

        self.btn_preview_voice = QPushButton("Preview")
        self.btn_preview_voice.setFixedWidth(80)
        self.btn_preview_voice.setFixedHeight(28)
        self.btn_preview_voice.setEnabled(False)
        self.btn_preview_voice.setToolTip("Listen to a sample of the selected voice")
        self.btn_preview_voice.clicked.connect(self._preview_voice)
        voice_row.addWidget(self.btn_preview_voice)

        config_grid.addLayout(voice_row, 1, 1, 1, 2)

        # Voice data cache
        self._voices_data = {}
        self._voice_loader = None
        QTimer.singleShot(500, self._load_voices)

        # Count
        config_grid.addWidget(QLabel("Count:"), 2, 0)
        count_row = QHBoxLayout()
        self.count_spin = QSpinBox()
        self.count_spin.setRange(1, 60)
        self.count_spin.setValue(1)
        self.count_spin.setToolTip("Number of Shorts to generate in batch")
        self.count_spin.setFixedWidth(80)
        count_row.addWidget(self.count_spin)

        self.schedule_preset_combo = QComboBox()
        for label, value in self._schedule_presets:
            self.schedule_preset_combo.addItem(label, value)
        self.schedule_preset_combo.setCurrentIndex(0)
        self.schedule_preset_combo.setEnabled(False)
        self.schedule_preset_combo.setToolTip(
            "Batch preset for auto-scheduling.\n"
            "1 week = 12 shorts, 3 days = 6 shorts, 1 day = 2 shorts.\n"
            "Choose Custom to keep the count editable."
        )
        self.schedule_preset_combo.currentIndexChanged.connect(self._on_schedule_preset_changed)
        count_row.addWidget(QLabel("Preset:"))
        count_row.addWidget(self.schedule_preset_combo, stretch=1)
        count_row.addStretch()
        config_grid.addLayout(count_row, 2, 1, 1, 2)

        # Short batch behavior
        config_grid.addWidget(QLabel("Short batch:"), 3, 0)
        self.partial_short_batch_check = QCheckBox("Use ready drafts only when batch is incomplete")
        self.partial_short_batch_check.setChecked(True)
        self.partial_short_batch_check.setToolTip(
            "If some drafts are still missing images, Generate Short will continue with the ready ones.\n"
            "Disable this to wait until the full requested batch is ready."
        )
        config_grid.addWidget(self.partial_short_batch_check, 3, 1, 1, 2)

        # Duration display
        config_grid.addWidget(QLabel("Duration:"), 4, 0)
        self.duration_label = QLabel("~45s (configured in pipeline)")
        self.duration_label.setStyleSheet("color: #888;")
        config_grid.addWidget(self.duration_label, 4, 1, 1, 2)

        # Subtitle style
        config_grid.addWidget(QLabel("Subtitles:"), 5, 0)
        self.subtitle_style_combo = QComboBox()
        self.subtitle_style_combo.addItems(SUBTITLE_STYLE_LABELS)
        self.subtitle_style_combo.setToolTip(
            "Choose the subtitle style burned into the final short."
        )
        try:
            from daily_short_pipeline import CHANNEL_CONFIG

            default_subtitle = get_subtitle_style_label(CHANNEL_CONFIG.get("subtitle_style"))
        except Exception:
            default_subtitle = DEFAULT_SUBTITLE_STYLE_LABEL
        default_index = self.subtitle_style_combo.findText(default_subtitle)
        if default_index >= 0:
            self.subtitle_style_combo.setCurrentIndex(default_index)
        config_grid.addWidget(self.subtitle_style_combo, 5, 1, 1, 2)

        # BGM (background music)
        config_grid.addWidget(QLabel("BGM:"), 6, 0)
        bgm_row = QHBoxLayout()
        self.bgm_path_input = QLineEdit()
        self.bgm_path_input.setPlaceholderText("No BGM (auto-search via Jamendo)")
        self.bgm_path_input.setReadOnly(True)
        bgm_row.addWidget(self.bgm_path_input, stretch=1)

        self.btn_bgm_browse = QPushButton("Browse")
        self.btn_bgm_browse.setFixedWidth(70)
        self.btn_bgm_browse.setFixedHeight(28)
        self.btn_bgm_browse.clicked.connect(self._browse_bgm)
        bgm_row.addWidget(self.btn_bgm_browse)

        self.btn_bgm_clear = QPushButton("X")
        self.btn_bgm_clear.setFixedWidth(28)
        self.btn_bgm_clear.setFixedHeight(28)
        self.btn_bgm_clear.setToolTip("Remove BGM selection (use auto)")
        self.btn_bgm_clear.clicked.connect(self._clear_bgm)
        bgm_row.addWidget(self.btn_bgm_clear)

        config_grid.addLayout(bgm_row, 6, 1, 1, 2)

        # Image provider
        config_grid.addWidget(QLabel("Images:"), 7, 0)
        img_row = QHBoxLayout()
        self.recraft_check = QCheckBox("Recraft AI")
        self.recraft_check.setChecked(True)
        self.recraft_check.setToolTip(
            "When enabled, uses Recraft AI to generate images for each segment.\n"
            "When disabled, only uses real images from Openverse/Wikimedia."
        )
        self.recraft_check.toggled.connect(self._on_recraft_toggled)
        img_row.addWidget(self.recraft_check)

        self.style_combo = QComboBox()
        self.style_combo.setToolTip("Recraft visual style for generated images")
        try:
            from recraft_style_catalog import RECRAFT_STYLE_OPTIONS
            self.style_combo.addItems(RECRAFT_STYLE_OPTIONS)
        except ImportError:
            self.style_combo.addItems([
                "Photorealism", "Illustration", "3D render", "Noir",
                "Watercolor", "Any style",
            ])
        # Default to Photorealism
        idx = self.style_combo.findText("Photorealism")
        if idx >= 0:
            self.style_combo.setCurrentIndex(idx)
        img_row.addWidget(self.style_combo, stretch=1)

        config_grid.addLayout(img_row, 7, 1, 1, 2)

        # Upload platforms
        config_grid.addWidget(QLabel("Upload:"), 8, 0)
        upload_row = QHBoxLayout()
        self.upload_youtube_check = QCheckBox("YouTube")
        self.upload_youtube_check.setChecked(False)
        self.upload_youtube_check.setToolTip("Upload the final short to YouTube.")
        self.upload_youtube_check.toggled.connect(self._on_upload_toggled)
        upload_row.addWidget(self.upload_youtube_check)

        self.upload_facebook_check = QCheckBox("Facebook Page")
        self.upload_facebook_check.setChecked(False)
        self.upload_facebook_check.setToolTip(
            "Publish the final short as a Facebook Page Reel using the Meta Graph API.\n"
            "Requires FACEBOOK_PAGE_ACCESS_TOKEN or FACEBOOK_USER_ACCESS_TOKEN + FACEBOOK_PAGE_ID in .env.\n"
            "When Auto-schedule is enabled, Facebook reels are scheduled experimentally with the same publish slot used for YouTube."
        )
        self.upload_facebook_check.toggled.connect(self._on_upload_toggled)
        upload_row.addWidget(self.upload_facebook_check)

        self.upload_instagram_check = QCheckBox("Instagram")
        self.upload_instagram_check.setChecked(False)
        self.upload_instagram_check.setToolTip(
            "Publish the final short to Instagram Reels.\n"
            "Requires an Instagram professional account linked to the Page,\n"
            "a valid Meta user token with instagram_content_publish,\n"
            "and Cloudinary credentials for temporary public video hosting.\n"
            "When Auto-schedule is enabled, Instagram jobs are queued for the VPS scheduler."
        )
        self.upload_instagram_check.toggled.connect(self._on_upload_toggled)
        upload_row.addWidget(self.upload_instagram_check)

        self.privacy_combo = QComboBox()
        self.privacy_combo.addItem("Private", "private")
        self.privacy_combo.addItem("Unlisted", "unlisted")
        self.privacy_combo.addItem("Public", "public")
        self.privacy_combo.setFixedWidth(100)
        self.privacy_combo.setEnabled(False)
        self.privacy_combo.setToolTip("YouTube privacy status")
        upload_row.addWidget(self.privacy_combo)

        config_grid.addLayout(upload_row, 8, 1, 1, 2)

        # Schedule publishing
        config_grid.addWidget(QLabel("Schedule:"), 9, 0)
        schedule_row = QHBoxLayout()
        self.schedule_check = QCheckBox("Auto-schedule (12PM + 6PM ET, Mon-Sat)")
        self.schedule_check.setChecked(False)
        self.schedule_check.setToolTip(
            "Schedule shorts at optimal times: 12 PM and 6 PM Eastern Time.\n"
            "In batch mode, fills 2 slots per day (up to 2 shorts/day).\n"
            "Use the preset selector to fill 1 day, 3 days, or 1 week automatically.\n"
            "Start date defines the first day to begin filling slots.\n"
            "Skips Sundays automatically.\n"
            "Applies to the selected upload platforms.\n"
            "Facebook scheduling is experimental but supported by the Meta Reels API."
        )
        self.schedule_check.toggled.connect(self._on_schedule_toggled)
        schedule_row.addWidget(self.schedule_check)

        config_grid.addLayout(schedule_row, 9, 1, 1, 2)

        config_grid.addWidget(QLabel("Start date:"), 10, 0)
        self.schedule_start_date = QDateEdit()
        self.schedule_start_date.setCalendarPopup(True)
        self.schedule_start_date.setDisplayFormat("yyyy-MM-dd")
        self.schedule_start_date.setMinimumDate(QDate.currentDate())
        self.schedule_start_date.setDate(QDate.currentDate().addDays(1))
        self.schedule_start_date.setEnabled(False)
        self.schedule_start_date.setToolTip(
            "First day to begin scheduling publications.\n"
            "The first slot starts at 12 PM ET on that day when available.\n"
            "If the selected date is Sunday, scheduling starts on Monday."
        )
        config_grid.addWidget(self.schedule_start_date, 10, 1, 1, 2)

        left_layout.addWidget(config_group)

        # ── Action Buttons ──
        btn_row = QHBoxLayout()

        self.btn_generate_images = QPushButton("Generate Images")
        self.btn_generate_images.setObjectName("accent")
        self.btn_generate_images.setFixedHeight(36)
        self.btn_generate_images.setStyleSheet("""
            QPushButton#accent {
                background-color: #14a085;
                color: white;
                font-weight: bold;
                font-size: 11pt;
                border-radius: 6px;
                padding: 4px 16px;
            }
            QPushButton#accent:hover { background-color: #17b894; }
            QPushButton#accent:disabled { background-color: #555; color: #999; }
        """)
        self.btn_generate_images.clicked.connect(self._start_image_generation)
        btn_row.addWidget(self.btn_generate_images, stretch=2)

        self.btn_generate = QPushButton("Generate Short")
        self.btn_generate.setFixedHeight(36)
        self.btn_generate.setStyleSheet("""
            QPushButton {
                background-color: #2d89ef;
                color: white;
                font-weight: bold;
                font-size: 11pt;
                border-radius: 6px;
                padding: 4px 16px;
            }
            QPushButton:hover { background-color: #3b97ff; }
            QPushButton:disabled { background-color: #555; color: #999; }
        """)
        self.btn_generate.clicked.connect(self._start_short_generation)
        btn_row.addWidget(self.btn_generate, stretch=2)

        self.btn_cancel = QPushButton("Cancel")
        self.btn_cancel.setFixedHeight(36)
        self.btn_cancel.setEnabled(False)
        self.btn_cancel.setStyleSheet("""
            QPushButton {
                background-color: #c0392b;
                color: white;
                font-weight: bold;
                border-radius: 6px;
                padding: 8px 16px;
            }
            QPushButton:hover { background-color: #e74c3c; }
            QPushButton:disabled { background-color: #555; color: #999; }
        """)
        self.btn_cancel.clicked.connect(self._cancel_pipeline)
        btn_row.addWidget(self.btn_cancel, stretch=1)

        left_layout.addLayout(btn_row)

        # ── Pipeline Progress ──
        progress_group = QGroupBox("Pipeline Progress")
        progress_layout = QVBoxLayout(progress_group)
        progress_layout.setSpacing(3)
        progress_layout.setContentsMargins(8, 12, 8, 6)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 9)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setFormat("Ready")
        self.progress_bar.setStyleSheet("""
            QProgressBar {
                border: 1px solid #404040;
                border-radius: 4px;
                text-align: center;
                height: 24px;
                background: #1a1a1a;
                color: #e0e0e0;
            }
            QProgressBar::chunk {
                background-color: #14a085;
                border-radius: 3px;
            }
        """)
        progress_layout.addWidget(self.progress_bar)

        # Step indicators
        self._step_labels = []
        self.progress_steps_layout = QVBoxLayout()
        self.progress_steps_layout.setSpacing(3)
        progress_layout.addLayout(self.progress_steps_layout)
        self._configure_step_labels(PipelineWorker.steps_for_mode("images"))

        left_layout.addWidget(progress_group)

        # ── Log Output ──
        log_group = QGroupBox("Log")
        log_layout = QVBoxLayout(log_group)
        self.log_output = QTextEdit()
        self.log_output.setReadOnly(True)
        self.log_output.setMaximumHeight(120)
        self.log_output.setStyleSheet(
            "background: #1a1a1a; color: #aaa; font-family: Consolas, monospace; font-size: 9pt;")
        log_layout.addWidget(self.log_output)
        left_layout.addWidget(log_group)

        left_layout.addStretch()

        # ════════════════════════════════════
        # RIGHT PANEL: History
        # ════════════════════════════════════
        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(8)

        selection_group = QGroupBox("Selection Actions")
        selection_layout = QVBoxLayout(selection_group)
        selection_layout.setContentsMargins(8, 12, 8, 8)
        selection_layout.setSpacing(6)

        self.selection_status_label = QLabel("Drafts selected: 0 | Videos selected: 0")
        self.selection_status_label.setStyleSheet("color: #a9b7c6;")
        selection_layout.addWidget(self.selection_status_label)

        draft_actions_row = QHBoxLayout()
        self.btn_select_all_drafts = QPushButton("Select All Drafts")
        self.btn_select_all_drafts.setFixedHeight(28)
        self.btn_select_all_drafts.clicked.connect(self._select_all_drafts)
        draft_actions_row.addWidget(self.btn_select_all_drafts)

        self.btn_clear_drafts = QPushButton("Clear Drafts")
        self.btn_clear_drafts.setFixedHeight(28)
        self.btn_clear_drafts.clicked.connect(self._clear_draft_selection)
        draft_actions_row.addWidget(self.btn_clear_drafts)

        self.btn_generate_selected = QPushButton("Generate Selected Shorts")
        self.btn_generate_selected.setFixedHeight(28)
        self.btn_generate_selected.clicked.connect(self._generate_selected_shorts)
        draft_actions_row.addWidget(self.btn_generate_selected)

        self.btn_delete_drafts = QPushButton("Delete Selected Drafts")
        self.btn_delete_drafts.setFixedHeight(28)
        self.btn_delete_drafts.clicked.connect(self._delete_selected_drafts)
        draft_actions_row.addWidget(self.btn_delete_drafts)
        selection_layout.addLayout(draft_actions_row)

        video_actions_row = QHBoxLayout()
        self.btn_select_all_videos = QPushButton("Select All Videos")
        self.btn_select_all_videos.setFixedHeight(28)
        self.btn_select_all_videos.clicked.connect(self._select_all_history)
        video_actions_row.addWidget(self.btn_select_all_videos)

        self.btn_clear_videos = QPushButton("Clear Videos")
        self.btn_clear_videos.setFixedHeight(28)
        self.btn_clear_videos.clicked.connect(self._clear_history_selection)
        video_actions_row.addWidget(self.btn_clear_videos)

        self.btn_publish_plan = QPushButton("Publish / Schedule Selected")
        self.btn_publish_plan.setFixedHeight(28)
        self.btn_publish_plan.clicked.connect(self._open_publish_planner_for_selected)
        video_actions_row.addWidget(self.btn_publish_plan)
        selection_layout.addLayout(video_actions_row)

        right_layout.addWidget(selection_group)

        drafts_group = QGroupBox("Drafts / Pending")
        drafts_group.setMaximumHeight(240)
        drafts_layout = QVBoxLayout(drafts_group)
        drafts_layout.setContentsMargins(8, 12, 8, 8)
        drafts_layout.setSpacing(6)

        self.drafts_scroll = QScrollArea()
        self.drafts_scroll.setWidgetResizable(True)
        self.drafts_scroll.setStyleSheet("QScrollArea { border: none; }")
        self.drafts_container = QWidget()
        self.drafts_layout = QVBoxLayout(self.drafts_container)
        self.drafts_layout.setContentsMargins(0, 0, 0, 0)
        self.drafts_layout.setSpacing(8)
        self.drafts_layout.addStretch()
        self.drafts_scroll.setWidget(self.drafts_container)
        drafts_layout.addWidget(self.drafts_scroll)
        right_layout.addWidget(drafts_group)

        scheduled_group = QGroupBox("Scheduled Publications")
        scheduled_group.setMaximumHeight(260)
        scheduled_layout = QVBoxLayout(scheduled_group)
        scheduled_layout.setContentsMargins(8, 12, 8, 8)
        scheduled_layout.setSpacing(6)

        self.scheduled_scroll = QScrollArea()
        self.scheduled_scroll.setWidgetResizable(True)
        self.scheduled_scroll.setStyleSheet("QScrollArea { border: none; }")
        self.scheduled_container = QWidget()
        self.scheduled_layout = QVBoxLayout(self.scheduled_container)
        self.scheduled_layout.setContentsMargins(0, 0, 0, 0)
        self.scheduled_layout.setSpacing(8)
        self.scheduled_layout.addStretch()
        self.scheduled_scroll.setWidget(self.scheduled_container)
        scheduled_layout.addWidget(self.scheduled_scroll)
        right_layout.addWidget(scheduled_group)

        history_header = QHBoxLayout()
        history_title = QLabel("History")
        history_title.setStyleSheet("font-size: 12pt; font-weight: bold;")
        history_header.addWidget(history_title)

        self.btn_refresh = QPushButton("Refresh")
        self.btn_refresh.setFixedHeight(28)
        self.btn_refresh.clicked.connect(lambda _checked=False: self._load_history(force_sync=True))
        history_header.addWidget(self.btn_refresh)

        btn_open_dir = QPushButton("Open Folder")
        btn_open_dir.setFixedHeight(28)
        btn_open_dir.clicked.connect(self._open_shorts_dir)
        history_header.addWidget(btn_open_dir)

        right_layout.addLayout(history_header)

        # Scrollable history
        self.history_scroll = QScrollArea()
        self.history_scroll.setWidgetResizable(True)
        self.history_scroll.setStyleSheet("QScrollArea { border: none; }")
        self.history_container = QWidget()
        self.history_layout = QVBoxLayout(self.history_container)
        self.history_layout.setContentsMargins(0, 0, 0, 0)
        self.history_layout.setSpacing(8)
        self.history_layout.addStretch()
        self.history_scroll.setWidget(self.history_container)
        right_layout.addWidget(self.history_scroll)

        # ── Add panels to splitter ──
        left_scroll.setWidget(left_widget)
        splitter.addWidget(left_scroll)
        splitter.addWidget(right_widget)
        splitter.setSizes([500, 400])

        main_layout.addWidget(splitter, stretch=1)
        self._update_selection_status()

    def _configure_step_labels(self, step_names):
        while self.progress_steps_layout.count():
            item = self.progress_steps_layout.takeAt(0)
            child_layout = item.layout()
            if child_layout:
                while child_layout.count():
                    child_item = child_layout.takeAt(0)
                    if child_item.widget():
                        child_item.widget().deleteLater()
                continue
            if item.widget():
                item.widget().deleteLater()

        self._step_labels = []
        for i, name in enumerate(step_names):
            step_row = QHBoxLayout()
            indicator = QLabel("  ")
            indicator.setFixedWidth(22)
            indicator.setAlignment(Qt.AlignmentFlag.AlignCenter)
            indicator.setStyleSheet(
                "background: #333; border-radius: 3px; color: #666; font-size: 9pt;")
            step_row.addWidget(indicator)

            label = QLabel(f"{i + 1}. {name}")
            label.setStyleSheet("color: #888; font-size: 9pt;")
            step_row.addWidget(label, stretch=1)

            status = QLabel("")
            status.setStyleSheet("color: #666; font-size: 8pt;")
            status.setAlignment(Qt.AlignmentFlag.AlignRight)
            step_row.addWidget(status)

            self.progress_steps_layout.addLayout(step_row)
            self._step_labels.append((indicator, label, status))

        self.progress_bar.setRange(0, max(1, len(step_names)))
        self.progress_bar.setValue(0)
        self.progress_bar.setFormat("Ready")

    # ─── Voice Loading ─────────────────────────────────────────────────

    def _load_voices(self):
        """Load TTS voices in a background thread."""
        if self._voice_loader and self._voice_loader.isRunning():
            return

        class VoiceLoader(QThread):
            voices_loaded = pyqtSignal(dict)
            error = pyqtSignal(str)

            def run(self):
                try:
                    from tts_generator import TextToSpeechGenerator
                    tts = TextToSpeechGenerator()
                    voices = tts.get_cached_or_fallback_voices() or {}
                    live_voices = tts.get_available_voices() or {}
                    if live_voices:
                        voices.update(live_voices)
                    self.voices_loaded.emit(voices)
                except Exception as e:
                    self.error.emit(str(e))

        self._voice_loader = VoiceLoader(parent=self)
        self._voice_loader.voices_loaded.connect(self._on_voices_loaded)
        self._voice_loader.error.connect(self._on_voices_error)
        self._voice_loader.start()

    def _on_voices_loaded(self, voices: dict):
        """Populate voice combo with loaded voices."""
        self._voices_data = voices
        self.voice_combo.clear()

        # Filter to English voices and sort by provider+name
        from daily_short_pipeline import CHANNEL_CONFIG
        default_voice = CHANNEL_CONFIG.get("default_voice", "en-US-GuyNeural")
        default_idx = 0

        english_voices = []
        for display_name, info in voices.items():
            if not isinstance(info, dict):
                continue
            voice_id = str(info.get("id", "")).strip()
            lang = str(info.get("language", "")).lower()
            provider = str(info.get("provider", "")).lower()
            friendly_name = str(display_name or info.get("name") or voice_id).strip()
            if not voice_id:
                continue
            # Include English voices (en-*) — they're the ones the channel uses
            if lang.startswith("en") or voice_id.lower().startswith("en-"):
                english_voices.append((friendly_name, voice_id, provider, info))

        # Sort: Edge-TTS first, then by display name
        english_voices.sort(key=lambda x: (
            0 if x[2] == "edge-tts" else 1,
            x[0]
        ))

        for i, (display_name, voice_id, provider, info) in enumerate(english_voices):
            self.voice_combo.addItem(display_name, userData=voice_id)
            combo_index = self.voice_combo.count() - 1
            tooltip = f"{display_name}\nID: {voice_id}"
            if provider:
                tooltip += f"\nProvider: {provider}"
            self.voice_combo.setItemData(combo_index, tooltip, Qt.ItemDataRole.ToolTipRole)
            if voice_id == default_voice:
                default_idx = i

        if not english_voices:
            # Fallback: add common voices manually
            for v in ["en-US-GuyNeural", "en-US-AriaNeural", "en-US-JennyNeural",
                       "en-US-DavisNeural", "en-GB-RyanNeural"]:
                self.voice_combo.addItem(v, userData=v)

        self.voice_combo.setCurrentIndex(default_idx)
        self.voice_combo.setEnabled(True)
        self.btn_preview_voice.setEnabled(True)

    def _on_voices_error(self, error: str):
        """Fallback if voice loading fails."""
        self.voice_combo.clear()
        for v in ["en-US-GuyNeural", "en-US-AriaNeural", "en-US-JennyNeural",
                   "en-US-DavisNeural", "en-US-TonyNeural", "en-GB-RyanNeural",
                   "en-GB-SoniaNeural", "en-AU-WilliamNeural"]:
            self.voice_combo.addItem(v, userData=v)
        self.voice_combo.setEnabled(True)
        self.btn_preview_voice.setEnabled(True)

    def _preview_voice(self):
        """Play a sample of the selected voice."""
        voice_id = self.voice_combo.currentData()
        if not voice_id:
            voice_id = self.voice_combo.currentText().strip()
        if not voice_id or voice_id == "Loading voices...":
            return

        self.btn_preview_voice.setEnabled(False)
        self.btn_preview_voice.setText("Playing...")

        class PreviewWorker(QThread):
            finished = pyqtSignal(bool, str)

            def __init__(self, vid, parent=None):
                super().__init__(parent)
                self.vid = vid

            def run(self):
                try:
                    from tts_generator import TextToSpeechGenerator
                    tts = TextToSpeechGenerator()
                    ok = tts.play_voice_sample(self.vid, "en")
                    self.finished.emit(ok, "" if ok else "Could not play sample")
                except Exception as e:
                    self.finished.emit(False, str(e))

        self._preview_worker = PreviewWorker(voice_id, parent=self)
        self._preview_worker.finished.connect(self._on_preview_done)
        self._preview_worker.start()

    def _on_preview_done(self, success: bool, error: str):
        """Re-enable preview button after playback."""
        self.btn_preview_voice.setEnabled(True)
        self.btn_preview_voice.setText("Preview")
        if not success and error:
            QMessageBox.warning(self, "Voice Preview", f"Could not play voice sample:\n{error}")

    # ─── BGM Selection ───────────────────────────────────────────────

    def _browse_bgm(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Select Background Music",
            "", "Audio Files (*.mp3 *.wav *.ogg *.m4a *.aac);;All Files (*)"
        )
        if path:
            self.bgm_path_input.setText(path)
            self.bgm_path_input.setToolTip(path)

    def _clear_bgm(self):
        self.bgm_path_input.clear()
        self.bgm_path_input.setToolTip("")

    def _on_recraft_toggled(self, checked):
        self.style_combo.setEnabled(checked)

    def _on_schedule_toggled(self, checked):
        if checked:
            if (
                not self.upload_youtube_check.isChecked()
                and not self.upload_facebook_check.isChecked()
                and not self.upload_instagram_check.isChecked()
            ):
                self.upload_youtube_check.setChecked(True)
        self._sync_schedule_controls()
        self._on_upload_toggled(False)

    def _on_schedule_preset_changed(self, _index):
        self._sync_schedule_controls()

    def _sync_schedule_controls(self):
        schedule_enabled = self.schedule_check.isChecked()
        self.schedule_preset_combo.setEnabled(schedule_enabled)
        self.schedule_start_date.setEnabled(schedule_enabled)

        if not schedule_enabled:
            self.count_spin.setEnabled(True)
            self.count_spin.setToolTip("Number of Shorts to generate in batch")
            return

        preset_count = self.schedule_preset_combo.currentData()
        if preset_count is None:
            self.count_spin.setEnabled(True)
            self.count_spin.setToolTip("Custom number of Shorts to generate in batch")
            return

        self.count_spin.setValue(int(preset_count))
        self.count_spin.setEnabled(False)
        self.count_spin.setToolTip("Count locked by the selected scheduling preset")

    def _on_upload_toggled(self, checked):
        _ = checked
        youtube_enabled = self.upload_youtube_check.isChecked()
        facebook_enabled = self.upload_facebook_check.isChecked()
        instagram_enabled = self.upload_instagram_check.isChecked()
        self.privacy_combo.setEnabled(youtube_enabled)
        if self.schedule_check.isChecked() and not (youtube_enabled or facebook_enabled or instagram_enabled):
            self.schedule_check.setChecked(False)

    def _normalize_folder(self, folder: str) -> str:
        return str(Path(folder))

    def _update_selection_status(self):
        draft_count = len(self._selected_draft_folders)
        history_count = len(self._selected_history_folders)
        ready_selected = sum(
            1
            for folder in self._selected_draft_folders
            if (self._draft_records.get(folder) or {}).get("status") in {"images_ready", "video_ready"}
        )
        self.selection_status_label.setText(
            f"Drafts selected: {draft_count} ({ready_selected} ready) | Videos selected: {history_count}"
        )
        self.btn_clear_drafts.setEnabled(draft_count > 0)
        self.btn_delete_drafts.setEnabled(draft_count > 0)
        self.btn_generate_selected.setEnabled(ready_selected > 0)
        self.btn_clear_videos.setEnabled(history_count > 0)
        self.btn_publish_plan.setEnabled(history_count > 0)
        self.btn_select_all_drafts.setEnabled(bool(self._draft_records))
        self.btn_select_all_videos.setEnabled(bool(self._history_records))

    def _on_draft_selection_changed(self, folder: str, selected: bool):
        key = self._normalize_folder(folder)
        if selected:
            self._selected_draft_folders.add(key)
        else:
            self._selected_draft_folders.discard(key)
        self._update_selection_status()

    def _on_history_selection_changed(self, folder: str, selected: bool):
        key = self._normalize_folder(folder)
        if selected:
            self._selected_history_folders.add(key)
        else:
            self._selected_history_folders.discard(key)
        self._update_selection_status()

    def _select_all_drafts(self):
        self._selected_draft_folders = set(self._draft_records.keys())
        self._load_history()

    def _clear_draft_selection(self):
        self._selected_draft_folders.clear()
        self._load_history()

    def _select_all_history(self):
        self._selected_history_folders = set(self._history_records.keys())
        self._load_history()

    def _clear_history_selection(self):
        self._selected_history_folders.clear()
        self._load_history()

    def _generate_selected_shorts(self):
        selected = list(self._selected_draft_folders)
        if not selected:
            QMessageBox.information(self, "Daily Shorts", "Select at least one draft first.")
            return
        self._start_batch("short", selected_folders=selected)

    def _delete_selected_drafts(self):
        if self.worker and self.worker.isRunning():
            QMessageBox.information(self, "Daily Shorts", "Wait for the current task to finish first.")
            return
        selected = sorted(self._selected_draft_folders)
        if not selected:
            QMessageBox.information(self, "Daily Shorts", "Select at least one draft to delete.")
            return

        reply = QMessageBox.question(
            self,
            "Delete Drafts",
            f"Delete {len(selected)} selected draft(s)?\n\nThis removes the entire draft folders from daily_shorts.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        shorts_root = (PROJECT_DIR / "daily_shorts").resolve()
        deleted = 0
        failed = []
        for folder in selected:
            target = Path(folder).resolve()
            try:
                target.relative_to(shorts_root)
            except Exception:
                failed.append(f"{target} (outside daily_shorts)")
                continue
            if not target.exists():
                continue
            try:
                shutil.rmtree(target)
                deleted += 1
            except Exception as e:
                failed.append(f"{target.name}: {e}")

        self._selected_draft_folders.clear()
        self._load_history()
        self._log(f"Deleted {deleted} draft(s).")
        if failed:
            QMessageBox.warning(
                self,
                "Delete Drafts",
                "Some drafts could not be deleted:\n\n" + "\n".join(failed[:8]),
            )

    def _selected_history_items(self) -> list[dict]:
        items = []
        for folder in sorted(self._selected_history_folders):
            record = self._history_records.get(folder) or {}
            summary = record.get("summary") or {}
            platform_metadata = summary.get("platform_metadata", {}) or {}
            youtube_meta = platform_metadata.get("youtube", {}) or summary.get("metadata", {}) or {}
            title = youtube_meta.get("title") or summary.get("topic") or Path(folder).name
            items.append({"folder": folder, "title": title, "summary": summary})
        return items

    def _open_publish_planner_for_selected(self):
        if self.worker and self.worker.isRunning():
            QMessageBox.information(self, "Publish Plan", "Wait for the current task to finish first.")
            return
        selected_items = self._selected_history_items()
        if not selected_items:
            QMessageBox.information(self, "Publish Plan", "Select at least one generated short first.")
            return

        dialog = PublishPlanDialog(
            selected_items,
            default_privacy=self.privacy_combo.currentData() or "private",
            default_youtube=(
                self.upload_youtube_check.isChecked()
                or (not self.upload_facebook_check.isChecked() and not self.upload_instagram_check.isChecked())
            ),
            default_facebook=self.upload_facebook_check.isChecked(),
            default_instagram=self.upload_instagram_check.isChecked(),
            parent=self,
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        jobs = dialog.get_jobs()
        if jobs:
            self._start_publish_plan(jobs)

    def _start_image_generation(self):
        self._start_batch("images")

    def _start_short_generation(self):
        self._start_batch("short")

    def _start_publish_plan(self, jobs: list[dict]):
        if self.worker and self.worker.isRunning():
            return

        if not jobs:
            QMessageBox.information(self, "Publish Plan", "No publish jobs to run.")
            return

        self._current_mode = "publish"
        self._task_queue = []
        self._active_task = None
        self._current_count = 0
        self._total_count = len(jobs)
        self._requested_count = len(jobs)
        self._pending_short_drafts = 0

        self.log_output.clear()
        self.btn_generate_images.setEnabled(False)
        self.btn_generate.setEnabled(False)
        self.btn_cancel.setEnabled(True)

        step_names = PublishPlanWorker.steps_for_jobs(jobs)
        self._configure_step_labels(step_names)
        self._reset_progress()
        self._log(f"Starting publish plan with {len(jobs)} job(s)")

        self.worker = PublishPlanWorker(jobs, parent=self)
        self.worker.step_started.connect(self._on_step_started)
        self.worker.step_completed.connect(self._on_step_completed)
        self.worker.step_failed.connect(self._on_step_failed)
        self.worker.log_message.connect(self._log)
        self.worker.pipeline_finished.connect(self._on_pipeline_finished)
        self.worker.pipeline_error.connect(self._on_pipeline_error)
        self.worker.start()

    def _start_batch(self, mode: str, selected_folders: list[str] | None = None):
        if self.worker and self.worker.isRunning():
            return

        normalized_selected = [self._normalize_folder(folder) for folder in (selected_folders or [])]
        count = len(normalized_selected) if normalized_selected else self.count_spin.value()
        topic = self.topic_input.text().strip() or None
        voice = self.voice_combo.currentData() or self.voice_combo.currentText().strip() or None
        short_batch_info = self._summarize_short_batch(count, selected_folders=normalized_selected) if mode == "short" else None

        task_queue = self._build_task_queue(mode, count, selected_folders=normalized_selected)
        if not task_queue:
            if mode == "short":
                available_ready = short_batch_info.get("ready_count", 0) if short_batch_info else 0
                pending_count = short_batch_info.get("pending_count", 0) if short_batch_info else 0
                if available_ready and not self.partial_short_batch_check.isChecked():
                    QMessageBox.information(
                        self,
                        "Daily Shorts",
                        f"Only {available_ready} draft(s) are ready right now, but the batch requests {count}.\n\n"
                        "Enable 'Use ready drafts only when batch is incomplete' to generate the available shorts now, "
                        "or finish the missing images first.",
                    )
                    return
                QMessageBox.information(
                    self,
                    "Daily Shorts",
                    "There are no drafts with all images ready yet.\n\nGenerate or resume images first."
                    if not pending_count
                    else f"There are no ready drafts yet.\n\n{pending_count} draft(s) are still pending images. "
                         "Generate or resume images first.",
                )
            else:
                QMessageBox.warning(self, "Daily Shorts", "No drafts available to process.")
            return

        self._current_mode = mode
        self._task_queue = task_queue
        self._active_task = None
        self._current_count = 0
        self._total_count = len(task_queue)
        self._requested_count = count
        self._pending_short_drafts = short_batch_info.get("pending_count", 0) if short_batch_info else 0
        self._current_topic = topic
        self._current_voice = voice
        self._current_bgm = self.bgm_path_input.text().strip() or None
        self._current_image_provider = "recraft" if self.recraft_check.isChecked() else "manual"
        self._current_visual_style = self.style_combo.currentText() if self.recraft_check.isChecked() else None
        self._current_subtitle_style = self.subtitle_style_combo.currentText().strip() or None
        self._current_upload_youtube = self.upload_youtube_check.isChecked() if mode == "short" else False
        self._current_upload_facebook = self.upload_facebook_check.isChecked() if mode == "short" else False
        self._current_privacy = self.privacy_combo.currentData() or "private"
        self._current_schedule = self.schedule_check.isChecked() if mode == "short" else False
        self._current_upload_instagram = (
            self.upload_instagram_check.isChecked()
            if mode == "short"
            else False
        )
        if mode == "short" and self._current_schedule and self._current_upload_instagram:
            self._log("Instagram scheduled posts will be queued for VPS execution at publish time.")
        self._current_upload = (
            self._current_upload_youtube
            or self._current_upload_facebook
            or self._current_upload_instagram
        )

        selected_start_date = self.schedule_start_date.date()
        self._current_schedule_start_date = (
            f"{selected_start_date.year():04d}-{selected_start_date.month():02d}-{selected_start_date.day():02d}"
            if self._current_schedule else None
        )

        self.log_output.clear()
        self.btn_generate_images.setEnabled(False)
        self.btn_generate.setEnabled(False)
        self.btn_cancel.setEnabled(True)

        step_names = PipelineWorker.steps_for_mode(
            mode,
            self._current_upload_youtube,
            self._current_upload_facebook,
            self._current_upload_instagram,
        )
        self._configure_step_labels(step_names)
        self._reset_progress()

        if mode == "images":
            new_count = sum(1 for task in task_queue if task.get("kind") == "new")
            resume_count = len(task_queue) - new_count
            self._log(
                f"Starting image generation batch ({len(task_queue)} draft(s), "
                f"{resume_count} resume, {new_count} new)"
            )
        else:
            if normalized_selected:
                skipped = count - len(task_queue)
                if skipped > 0:
                    self._log(
                        f"Selected {count} draft(s); {len(task_queue)} are ready for Generate Short and {skipped} still need images."
                    )
                self._log(f"Starting selected short batch ({len(task_queue)} draft(s))")
            else:
                if short_batch_info and len(task_queue) < count:
                    self._log(
                        f"Only {len(task_queue)}/{count} requested drafts are ready. "
                        f"{short_batch_info['pending_count']} draft(s) remain pending images, so Generate Short will continue with the ready ones."
                    )
                self._log(f"Starting short assembly batch ({len(task_queue)} ready draft(s))")

        self._run_next_task()

    def _build_task_queue(self, mode: str, requested_count: int,
                          selected_folders: list[str] | None = None) -> list[dict]:
        drafts, _entries = self._scan_short_entries()
        requested_count = max(1, int(requested_count))
        selected_filter = {self._normalize_folder(folder) for folder in (selected_folders or [])}

        if mode == "images":
            pending = [item for item in drafts if item[1].get("status") in {"storyboard_ready", "images_partial", "draft"}]
            if selected_filter:
                pending = [item for item in pending if self._normalize_folder(item[0]) in selected_filter]
            pending.sort(key=lambda item: item[1].get("created_at") or item[1].get("output_dir", ""))

            tasks = [{"kind": "existing", "output_dir": folder, "state": state} for folder, state in pending[:requested_count]]
            while len(tasks) < requested_count:
                tasks.append({"kind": "new"})
            return tasks

        summary = self._summarize_short_batch(requested_count, selected_folders=selected_folders)
        ready = summary["ready"]
        if selected_filter:
            return [{"kind": "existing", "output_dir": folder, "state": state} for folder, state in ready]
        if not self.partial_short_batch_check.isChecked() and len(ready) < requested_count:
            return []
        return [{"kind": "existing", "output_dir": folder, "state": state} for folder, state in ready[:requested_count]]

    def _summarize_short_batch(self, requested_count: int,
                               selected_folders: list[str] | None = None) -> dict:
        drafts, _entries = self._scan_short_entries()
        requested_count = max(1, int(requested_count))
        selected_filter = {self._normalize_folder(folder) for folder in (selected_folders or [])}
        ready = [item for item in drafts if item[1].get("status") in {"images_ready", "video_ready"}]
        pending = [item for item in drafts if item[1].get("status") in {"storyboard_ready", "images_partial", "draft"}]
        if selected_filter:
            ready = [item for item in ready if self._normalize_folder(item[0]) in selected_filter]
            pending = [item for item in pending if self._normalize_folder(item[0]) in selected_filter]
        ready.sort(key=lambda item: item[1].get("created_at") or item[1].get("output_dir", ""))
        pending.sort(key=lambda item: item[1].get("created_at") or item[1].get("output_dir", ""))
        return {
            "requested_count": requested_count,
            "ready": ready,
            "pending": pending,
            "ready_count": len(ready),
            "pending_count": len(pending),
        }

    def _run_next_task(self):
        if not self._task_queue:
            self._on_batch_complete()
            return

        self._current_count += 1
        self._active_task = self._task_queue.pop(0)

        if self._total_count > 1:
            self._log(f"\n--- Item {self._current_count}/{self._total_count} ---")

        self._reset_progress()

        publish_at = None
        if self._current_mode == "short" and self._current_schedule:
            try:
                from youtube_uploader import get_next_optimal_publish_time
                publish_at = get_next_optimal_publish_time(
                    slot_index=self._current_count - 1,
                    start_date=self._current_schedule_start_date,
                )
                self._log(f"Scheduled publish: {_format_publish_datetime(publish_at)}")
            except Exception as e:
                self._log(f"Warning: could not compute schedule: {e}")

        output_dir = self._active_task.get("output_dir")
        if self._current_mode == "images" and output_dir:
            self._log(f"Resuming draft images: {output_dir}")
        elif self._current_mode == "short" and output_dir:
            self._log(f"Generating short from draft: {output_dir}")

        self.worker = PipelineWorker(
            mode=self._current_mode,
            topic=self._current_topic if self._current_mode == "images" else None,
            voice_id=self._current_voice,
            upload=self._current_upload_youtube,
            privacy_status=self._current_privacy,
            publish_at=publish_at,
            upload_facebook=self._current_upload_facebook,
            upload_instagram=self._current_upload_instagram,
            facebook_publish_at=publish_at if (self._current_schedule and self._current_upload_facebook) else None,
            bgm_path=self._current_bgm,
            image_provider=self._current_image_provider,
            visual_style=self._current_visual_style,
            subtitle_style=self._current_subtitle_style,
            output_dir=output_dir,
            parent=self,
        )
        self.worker.step_started.connect(self._on_step_started)
        self.worker.step_completed.connect(self._on_step_completed)
        self.worker.step_failed.connect(self._on_step_failed)
        self.worker.log_message.connect(self._log)
        self.worker.pipeline_finished.connect(self._on_pipeline_finished)
        self.worker.pipeline_error.connect(self._on_pipeline_error)
        self.worker.start()

    # ─── Pipeline Control ─────────────────────────────────────────────

    def _start_pipeline(self):
        """Compat wrapper for older signal connections."""
        self._start_image_generation()

    def _run_next_short(self):
        """Compat wrapper for older callbacks."""
        self._run_next_task()

    def _cancel_pipeline(self):
        if self.worker and self.worker.isRunning():
            self.worker.cancel()
            self._task_queue = []
            self._log("Cancelling pipeline...")
            self.btn_cancel.setEnabled(False)

    def _reset_progress(self):
        self.progress_bar.setValue(0)
        self.progress_bar.setFormat("Starting...")
        for indicator, label, status in self._step_labels:
            indicator.setText("  ")
            indicator.setStyleSheet(
                "background: #333; border-radius: 3px; color: #666; font-size: 9pt;")
            label.setStyleSheet("color: #888; font-size: 9pt;")
            status.setText("")

    # ─── Pipeline Signals ─────────────────────────────────────────────

    def _on_step_started(self, idx, name):
        if idx < len(self._step_labels):
            indicator, label, status = self._step_labels[idx]
            indicator.setText("...")
            indicator.setStyleSheet(
                "background: #2980b9; border-radius: 3px; color: white; font-size: 9pt;")
            label.setStyleSheet("color: #e0e0e0; font-weight: bold; font-size: 9pt;")
            status.setText("running")
            status.setStyleSheet("color: #2980b9; font-size: 8pt;")
        total = max(1, len(self._step_labels))
        self.progress_bar.setFormat(f"Step {idx + 1}/{total}: {name}")

    def _on_step_completed(self, idx, info):
        if idx < len(self._step_labels):
            indicator, label, status = self._step_labels[idx]
            indicator.setText("OK")
            indicator.setStyleSheet(
                "background: #14a085; border-radius: 3px; color: white; font-size: 9pt; font-weight: bold;")
            label.setStyleSheet("color: #14a085; font-size: 9pt;")
            status.setText(info)
            status.setStyleSheet("color: #888; font-size: 8pt;")
        self.progress_bar.setValue(idx + 1)

    def _on_step_failed(self, idx, error):
        if idx < len(self._step_labels):
            indicator, label, status = self._step_labels[idx]
            indicator.setText("!!")
            indicator.setStyleSheet(
                "background: #e67e22; border-radius: 3px; color: white; font-size: 9pt; font-weight: bold;")
            label.setStyleSheet("color: #e67e22; font-size: 9pt;")
            status.setText(error)
            status.setStyleSheet("color: #e67e22; font-size: 8pt;")
        self.progress_bar.setValue(idx + 1)
        self._log(f"Warning: {error}")

    def _on_pipeline_finished(self, result):
        elapsed = result.get("elapsed", 0)
        minutes = int(elapsed // 60)
        seconds = int(elapsed % 60)
        total = max(1, len(self._step_labels))
        self.progress_bar.setValue(total)
        self.progress_bar.setFormat(f"Done! ({minutes}m {seconds}s)")
        if result.get("mode") == "images":
            draft_state = result.get("draft_state") or {}
            ready = draft_state.get("segments_ready", 0)
            total_segments = draft_state.get("segments_total", 0)
            missing = draft_state.get("segments_missing", 0)
            self._log(f"Draft updated: {result.get('topic', '?')}")
            self._log(f"Folder: {result.get('output_dir', '?')}")
            self._log(f"Images ready: {ready}/{total_segments}")
            if missing:
                self._log("Some images are still pending. You can resume later with Generate Images.")
        elif result.get("mode") == "publish":
            total_jobs = result.get("jobs_total", 0)
            completed_jobs = result.get("jobs_completed", 0)
            failed_jobs = result.get("jobs_failed", []) or []
            self._log(f"Publish plan completed: {completed_jobs}/{total_jobs} job(s) succeeded")
            if failed_jobs:
                for failed in failed_jobs[:8]:
                    self._log(f"Publish warning: {failed.get('error', 'Unknown error')}")
        else:
            self._log(f"Short generated: {result.get('topic', '?')}")
            self._log(f"Video: {result.get('video_path', '?')}")
        self._log(f"Time: {minutes}m {seconds}s")

        if self._task_queue:
            QTimer.singleShot(1000, self._run_next_task)
        else:
            self._on_batch_complete()

    def _on_batch_complete(self):
        self._task_queue = []
        self._active_task = None
        self.worker = None
        self.btn_generate_images.setEnabled(True)
        self.btn_generate.setEnabled(True)
        self.btn_cancel.setEnabled(False)
        total = self._total_count
        if total > 1:
            if self._current_mode == "images":
                self._log(f"\nBatch complete: {self._current_count}/{total} draft(s) processed")
            elif self._current_mode == "publish":
                self._log(f"\nPublish plan complete: {total} job(s) processed")
            else:
                if self._requested_count > total:
                    self._log(
                        f"\nBatch complete: {self._current_count}/{self._requested_count} requested short(s) generated. "
                        f"{self._pending_short_drafts} draft(s) are still pending images."
                    )
                else:
                    self._log(f"\nBatch complete: {self._current_count}/{total} short(s) generated")
        self._load_history()

    def _on_pipeline_error(self, error):
        self.progress_bar.setFormat(f"Error: {error[:50]}")
        self._log(f"PIPELINE ERROR: {error}")
        self._task_queue = []
        self._active_task = None
        self.worker = None
        self.btn_generate_images.setEnabled(True)
        self.btn_generate.setEnabled(True)
        self.btn_cancel.setEnabled(False)
        self._load_history()

    def _log(self, msg):
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.log_output.append(f"[{timestamp}] {msg}")
        # Auto-scroll to bottom
        sb = self.log_output.verticalScrollBar()
        sb.setValue(sb.maximum())

    # ─── History ──────────────────────────────────────────────────────

    def _clear_cards(self, layout):
        while layout.count() > 1:  # keep the stretch
            item = layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

    def _set_layout_placeholder(self, layout, text):
        lbl = QLabel(text)
        lbl.setStyleSheet("color: #666; padding: 12px;")
        lbl.setWordWrap(True)
        layout.insertWidget(0, lbl)

    def _load_upload_records_for_folder(self, folder: str, base_filename: str, platform: str) -> list[dict]:
        folder_path = Path(folder)
        base_path = folder_path / base_filename
        name = Path(base_filename)
        candidate_paths = []
        if base_path.exists():
            candidate_paths.append(base_path)
        candidate_paths.extend(sorted(folder_path.glob(f"{name.stem}_*{name.suffix}"), reverse=True))

        records = []
        for path in candidate_paths:
            try:
                with open(path, "r", encoding="utf-8") as f:
                    payload = json.load(f)
            except Exception:
                continue
            payload["platform"] = platform
            payload["source_file"] = path.name
            records.append(payload)
        return _dedupe_upload_records(records)

    def _sync_uploaded_entries(self, entries):
        folders = [
            folder
            for folder, _summary, upload_data in entries
            if upload_data and upload_data.get("video_id")
        ]
        if not folders:
            return {}

        try:
            from youtube_uploader import sync_upload_result_files

            return sync_upload_result_files(folders)
        except Exception as e:
            self._log(f"[WARN] Could not refresh YouTube schedule data: {e}")
            return {}

    def _scan_short_entries(self, sync_youtube=False):
        shorts_dir = PROJECT_DIR / "daily_shorts"
        drafts = []
        entries = []

        if not shorts_dir.exists():
            return drafts, entries

        try:
            from daily_short_pipeline import get_draft_state
        except Exception:
            get_draft_state = None

        for day_dir in sorted(shorts_dir.iterdir(), reverse=True):
            if not day_dir.is_dir():
                continue

            summary_file = day_dir / "summary.json"
            if summary_file.exists():
                try:
                    with open(summary_file, "r", encoding="utf-8") as f:
                        summary = json.load(f)
                    upload_data = None
                    upload_result_file = day_dir / "upload_result.json"
                    if upload_result_file.exists():
                        try:
                            with open(upload_result_file, "r", encoding="utf-8") as f:
                                upload_data = json.load(f)
                        except Exception:
                            upload_data = None
                    entries.append((str(day_dir), summary, upload_data))
                except Exception:
                    pass
                continue

            if not get_draft_state:
                continue

            if (day_dir / "storyboard.json").exists() or (day_dir / "pipeline_state.json").exists():
                try:
                    drafts.append((str(day_dir), get_draft_state(day_dir)))
                except Exception:
                    pass

        if sync_youtube and entries:
            synced_entries = self._sync_uploaded_entries(entries)
            if synced_entries:
                entries = [
                    (folder, summary, synced_entries.get(folder, upload_data))
                    for folder, summary, upload_data in entries
                ]

        return drafts, entries

    def _load_drafts(self, drafts):
        self._clear_cards(self.drafts_layout)

        if not drafts:
            self._set_layout_placeholder(self.drafts_layout, "No pending Daily Shorts drafts.")
            return

        drafts.sort(key=lambda item: item[1].get("updated_at") or item[1].get("created_at") or "", reverse=True)
        for i, (folder, draft_state) in enumerate(drafts[:40]):
            card = DraftCard(
                draft_state,
                folder,
                selected=self._normalize_folder(folder) in self._selected_draft_folders,
                selection_changed=self._on_draft_selection_changed,
            )
            self.drafts_layout.insertWidget(i, card)

    def _load_scheduled_posts(self, entries):
        self._clear_cards(self.scheduled_layout)

        now_utc = datetime.now(timezone.utc)
        scheduled_entries = []
        for folder, summary, upload_data in entries:
            platform_uploads = []
            platform_uploads.extend(
                ("youtube", payload)
                for payload in self._load_upload_records_for_folder(folder, "upload_result.json", "youtube")
            )
            platform_uploads.extend(
                ("facebook", payload)
                for payload in self._load_upload_records_for_folder(folder, "facebook_upload_result.json", "facebook")
            )
            platform_uploads.extend(
                ("instagram", payload)
                for payload in self._load_upload_records_for_folder(folder, "instagram_upload_result.json", "instagram")
            )

            for platform, platform_upload in platform_uploads:
                if not platform_upload or not platform_upload.get("scheduled"):
                    continue
                publish_dt = _parse_publish_datetime(platform_upload.get("publish_at"))
                if publish_dt and publish_dt > now_utc:
                    scheduled_entries.append((publish_dt, platform, folder, summary, platform_upload))

        if not scheduled_entries:
            self._set_layout_placeholder(self.scheduled_layout, "No scheduled Daily Shorts pending publication.")
            return

        scheduled_entries.sort(key=lambda item: item[0])
        for i, (_publish_dt, platform, folder, summary, upload_data) in enumerate(scheduled_entries[:30]):
            card = ScheduledPostCard(summary, folder, upload_data, platform=platform)
            self.scheduled_layout.insertWidget(i, card)

    def _load_history(self, force_sync=False):
        """Scan daily_shorts/ directory and load all summaries."""
        self._clear_cards(self.drafts_layout)
        self._clear_cards(self.scheduled_layout)
        self._clear_cards(self.history_layout)

        shorts_dir = PROJECT_DIR / "daily_shorts"
        if not shorts_dir.exists():
            self._draft_records = {}
            self._history_records = {}
            self._selected_draft_folders.clear()
            self._selected_history_folders.clear()
            self._set_layout_placeholder(self.drafts_layout, "No pending Daily Shorts drafts.")
            self._set_layout_placeholder(self.scheduled_layout, "No scheduled Daily Shorts pending publication.")
            self._set_layout_placeholder(self.history_layout, "No shorts generated yet")
            self._update_selection_status()
            return

        drafts, entries = self._scan_short_entries(sync_youtube=force_sync)
        self._draft_records = {self._normalize_folder(folder): state for folder, state in drafts}
        self._history_records = {
            self._normalize_folder(folder): {"summary": summary, "upload_data": upload_data}
            for folder, summary, upload_data in entries
        }
        self._selected_draft_folders.intersection_update(self._draft_records.keys())
        self._selected_history_folders.intersection_update(self._history_records.keys())
        self._load_drafts(drafts)

        if not entries:
            self._set_layout_placeholder(self.scheduled_layout, "No scheduled Daily Shorts pending publication.")
            self._set_layout_placeholder(self.history_layout, "No shorts found in daily_shorts/")
            self._update_selection_status()
            return

        self._load_scheduled_posts(entries)

        for i, (folder, summary, _upload_data) in enumerate(entries[:50]):
            card = ShortCard(
                summary,
                folder,
                selected=self._normalize_folder(folder) in self._selected_history_folders,
                selection_changed=self._on_history_selection_changed,
            )
            self.history_layout.insertWidget(i, card)
        self._update_selection_status()

    def _open_shorts_dir(self):
        shorts_dir = str(PROJECT_DIR / "daily_shorts")
        if os.path.exists(shorts_dir):
            os.startfile(shorts_dir)
        else:
            self._log("daily_shorts/ directory does not exist yet")
