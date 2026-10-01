"""
Dedicated metadata generation tab for YouTube, Facebook, Instagram, and X.
Uses Groq as primary model and exposes per-field copy actions.
"""

import json
import re
from pathlib import Path
from typing import Dict, List

from PyQt6.QtCore import QThread, pyqtSignal, Qt
from PyQt6.QtWidgets import (
    QApplication,
    QComboBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from ai.groq_client import GroqAiClient


class MetadataGenerationWorker(QThread):
    finished = pyqtSignal(str, dict)  # platform, payload
    error = pyqtSignal(str)
    progress = pyqtSignal(str)

    def __init__(self, platform_name: str, context: Dict, groq_client: GroqAiClient):
        super().__init__()
        self.platform_name = platform_name
        self.context = context
        self.groq_client = groq_client

    def run(self):
        try:
            prompt = self._build_prompt()
            self.progress.emit(f"Generating metadata with Groq for {self.platform_name}...")

            response = None
            if self.groq_client and self.groq_client.client:
                response = self.groq_client._generate(prompt)

            if not response:
                self.progress.emit("Groq unavailable, using local fallback metadata.")
                payload = self._fallback_payload()
                self.finished.emit(self.platform_name, payload)
                return

            payload = self._parse_payload(response)
            if self.platform_name == "x":
                payload = self._expand_x_thread_if_needed(payload)
            self.finished.emit(self.platform_name, payload)
        except Exception as e:
            self.error.emit(str(e))

    def _get_priority_tags(self, category: str) -> List[str]:
        """Return priority tags based on channel performance data by category."""
        category_lower = (category or "").lower()
        tag_map = {
            "eventos naturales": [
                "earthquake", "volcanic eruption", "natural disaster", "geology",
                "magnitude", "tsunami", "extreme weather", "catastrophe",
            ],
            "ciencia": [
                "quantum computing", "space", "NASA", "physics",
                "technology breakthrough", "science news", "discovery", "research",
            ],
            "tecnología": [
                "quantum computing", "space", "NASA", "physics",
                "technology breakthrough", "science news", "discovery", "research",
            ],
            "historia": [
                "ancient history", "world war", "military history", "historical mystery",
                "civilization", "archaeology", "ancient civilization", "empire",
            ],
            "historia militar": [
                "world war", "military history", "naval battle", "WWII",
                "war strategy", "military operation", "battlefield", "combat",
            ],
            "misterios": [
                "conspiracy theory", "government secrets", "declassified", "cold war",
                "covert operation", "mystery", "unexplained", "investigation",
            ],
            "conspiraciones": [
                "conspiracy theory", "government secrets", "declassified", "cold war",
                "covert operation", "cover up", "classified", "secret program",
            ],
            "actualidad": [
                "breaking news", "science news", "latest discovery", "2024", "2025",
                "technology", "current events", "trending",
            ],
        }
        for key, tags in tag_map.items():
            if key in category_lower:
                return tags
        return [
            "documentary", "history", "mystery", "science", "facts",
            "educational", "explained", "short documentary",
        ]

    # Topics that are generic app/default values and should not be passed to the LLM
    _GENERIC_TOPICS = frozenset({
        "video", "video optimizer", "documentary", "short", "shorts",
        "youtube", "facebook", "instagram", "reels", "content",
        "proyecto", "project", "untitled", "",
    })

    def _context_json(self) -> str:
        raw_topic = (self.context.get("topic") or "").strip()
        # If topic is a generic/app-default value, omit it so the LLM derives
        # the subject exclusively from the script content.
        topic = "" if raw_topic.lower() in self._GENERIC_TOPICS else raw_topic
        compact = {
            "topic": topic,
            "category": self.context.get("category", ""),
            "language": self.context.get("language", "es"),
            "duration_seconds": self.context.get("duration_seconds", 0),
            "video_format": self.context.get("video_format", "16:9"),
            "video_formats": self.context.get("video_formats", []),
            "script_preview": (self.context.get("script", "") or "")[:4500],
            "segment_count": self.context.get("segment_count", 0),
        }
        return json.dumps(compact, ensure_ascii=False, indent=2)

    def _build_prompt(self) -> str:
        context_block = self._context_json()
        if self.platform_name == "youtube":
            category = self.context.get("category", "").strip().lower()
            tag_pool = self._get_priority_tags(category)
            tag_instruction = (
                f'- PRIORITY TAGS to include when relevant: {", ".join(tag_pool)}'
                if tag_pool
                else ""
            )
            return f"""
You are a senior YouTube SEO strategist specializing in Shorts (28-132 seconds).
Return ONLY valid JSON.

PROJECT CONTEXT:
{context_block}

TASK:
Generate high-performance YouTube metadata. ALL output (title, description, tags) MUST be in ENGLISH regardless of any other language context. This is a global English-language YouTube channel.

TITLE FORMULA (MANDATORY — follow this structure):
[Specific Event or Person] + [Concrete Number/Stat] + [Consequence or Tension] + [Impact Emoji]
Examples of titles that work:
- "Strongest Earthquake Ever Recorded  9.5 Magnitude"
- "Comet Hit Jupiter  600 Million Nuclear Bombs"
- "CIA's $800M Mission: Recovering Soviet Sub K-129"
- "The Man Who Saved the World From Nuclear War ️"

TITLE ANTI-PATTERNS (NEVER do these):
- Do NOT start with "Uncovering..." or "Uncover..." — overused, loses impact.
- Do NOT use vague formulas like "Secrets Revealed", "The Truth About..." without a specific number or data point.
- Do NOT write generic titles without a concrete hook: "Uncover Atlantis" = bad, "Atlantis: The Civilization That Vanished in 24 Hours " = good.
- ALWAYS include at least one concrete number, date, or measurable fact in the title.
- ALWAYS include 1-2 impact emojis (️️️️️).

STRICT REQUIREMENTS:
- title length: 45-70 chars, specific and curiosity-driven, no clickbait lies.
- description: 2-4 concise paragraphs, strong hook in first 140 chars (this is the YouTube preview line — make it count), include value proposition and CTA.
- tags: 12-18 relevant tags, no duplicates, plain words (without #). Mix broad discovery tags with specific niche tags.
{tag_instruction}

RESPONSE JSON SCHEMA:
{{
  "title": "string",
  "description": "string",
  "tags": ["tag1", "tag2", "tag3"]
}}
"""
        if self.platform_name == "facebook":
            return f"""
You are a senior Facebook Reels copy strategist for the page "Stunning Revelations".
Return ONLY valid JSON.

PROJECT CONTEXT:
{context_block}

TASK:
Generate dedicated Facebook Reel metadata in ENGLISH.

STRICT REQUIREMENTS:
- title: 45-90 chars, strong curiosity, documentary tone, no fake urgency.
- title must feel DIFFERENT from a YouTube SEO title even if it covers the same subject.
- description: max 3 short blocks.
- block 1: strongest hook or unsettling fact from the script.
- block 2: 1-2 concise context sentences grounded in the script.
- block 3: comment CTA plus 3-5 relevant hashtags max.
- avoid "subscribe to the channel", "watch until the end", and oversized hashtag lists.

RESPONSE JSON SCHEMA:
{{
  "title": "string",
  "description": "string"
}}
"""
        if self.platform_name == "instagram":
            return f"""
You are a senior Instagram Reels copy strategist for the account "Stunning Revelations".
Return ONLY valid JSON.

PROJECT CONTEXT:
{context_block}

TASK:
Generate dedicated Instagram Reel metadata in ENGLISH.

STRICT REQUIREMENTS:
- title: 35-80 chars, curiosity-driven, mobile-friendly, documentary tone.
- title should feel native to Instagram and less SEO-heavy than YouTube.
- description: max 2 short blocks.
- block 1: strongest hook or reveal from the script.
- block 2: concise context + comment CTA + 4-6 relevant hashtags max.
- avoid links, "subscribe", "watch until the end", and hashtag spam.

RESPONSE JSON SCHEMA:
{{
  "title": "string",
  "description": "string"
}}
"""
        return f"""
You are a social media strategist for X (Twitter) threads.
Return ONLY valid JSON.

PROJECT CONTEXT:
{context_block}

TASK:
Generate a thread in the same language as the script.

STRICT REQUIREMENTS:
- 8-14 posts.
- each post must be between 240 and 280 characters.
- hard limit: never exceed 280 characters.
- use the available character limit aggressively (target 260-280 chars in every post).
- post 1: hook, posts 2..N-1: progressive value, post N: CTA.
- keep informational progression and avoid repetition.
- avoid hashtags unless absolutely necessary.

RESPONSE JSON SCHEMA:
{{
  "thread": ["post 1", "post 2", "post 3"]
}}
"""

    def _extract_json_text(self, text: str) -> str:
        raw = (text or "").strip()
        if raw.startswith("```"):
            raw = raw.replace("```json", "").replace("```", "").strip()
        first = raw.find("{")
        last = raw.rfind("}")
        if first >= 0 and last > first:
            return raw[first:last + 1]
        return raw

    def _parse_json_resilient(self, text: str) -> Dict:
        extracted = self._extract_json_text(text)

        try:
            return json.loads(extracted)
        except Exception:
            pass

        try:
            import json_repair  # type: ignore

            repaired = json_repair.repair_json(extracted, return_objects=True)
            if isinstance(repaired, dict):
                return repaired
        except Exception:
            pass

        # Last effort: remove control chars and retry.
        cleaned = re.sub(r"[\x00-\x08\x0B\x0C\x0E-\x1F]", "", extracted)
        return json.loads(cleaned)

    def _normalize_list(self, values, limit: int = 20) -> List[str]:
        result = []
        for item in values or []:
            text = str(item).strip()
            if not text:
                continue
            if text not in result:
                result.append(text)
            if len(result) >= limit:
                break
        return result

    def _clip_to_x_limit(self, text: str, max_chars: int = 280) -> str:
        value = str(text or "").strip()
        if len(value) <= max_chars:
            return value
        clipped = value[:max_chars]
        last_space = clipped.rfind(" ")
        if last_space >= 220:
            clipped = clipped[:last_space]
        return clipped.rstrip(" .,!?:;-")

    def _normalize_x_thread(self, values, limit: int = 16) -> List[str]:
        normalized = []
        for item in values or []:
            text = self._clip_to_x_limit(item, max_chars=280)
            if not text:
                continue
            if text not in normalized:
                normalized.append(text)
            if len(normalized) >= limit:
                break
        return normalized

    def _expand_x_thread_if_needed(self, payload: Dict) -> Dict:
        thread = self._normalize_x_thread(payload.get("thread", []), limit=16)
        if not thread:
            return {"thread": []}

        long_posts = sum(1 for post in thread if len(post) >= 240)
        needs_expansion = len(thread) < 8 or long_posts < max(1, int(len(thread) * 0.7))
        if not needs_expansion:
            return {"thread": thread}

        if not (self.groq_client and self.groq_client.client):
            return {"thread": thread}

        self.progress.emit("Expanding X thread to maximize character usage...")
        context_block = self._context_json()
        expansion_prompt = f"""
You are rewriting an X thread to maximize quality and character usage.
Return ONLY valid JSON.

PROJECT CONTEXT:
{context_block}

CURRENT THREAD:
{json.dumps(thread, ensure_ascii=False, indent=2)}

REWRITE RULES:
- Output 8-14 posts.
- Every post between 240 and 280 characters.
- Hard cap: 280 characters.
- Keep same topic and progression, remove repetition.
- Post 1 must hook strongly, final post must include CTA.

JSON:
{{
  "thread": ["post 1", "post 2"]
}}
"""
        try:
            expanded_response = self.groq_client._generate(expansion_prompt)
            if expanded_response:
                expanded_payload = self._parse_payload(expanded_response)
                expanded_thread = self._normalize_x_thread(expanded_payload.get("thread", []), limit=16)
                if expanded_thread:
                    return {"thread": expanded_thread}
        except Exception:
            pass

        return {"thread": thread}

    def _parse_payload(self, response: str) -> Dict:
        payload = self._parse_json_resilient(response)
        if self.platform_name == "youtube":
            return {
                "title": str(payload.get("title", "")).strip(),
                "description": str(payload.get("description", "")).strip(),
                "tags": self._normalize_list(payload.get("tags", []), limit=18),
            }
        if self.platform_name in {"facebook", "instagram"}:
            return {
                "title": str(payload.get("title", "")).strip(),
                "description": str(payload.get("description", "")).strip(),
            }
        return {
            "thread": self._normalize_x_thread(payload.get("thread", []), limit=16),
        }

    def _fallback_payload(self) -> Dict:
        topic = (self.context.get("topic") or "Video").strip()
        script = (self.context.get("script") or "").strip()
        preview = script[:280] if script else f"Contenido sobre {topic}."
        if self.platform_name == "youtube":
            return {
                "title": f"{topic}: key facts and context",
                "description": f"{preview}\n\nIf this topic interests you, leave a comment and follow for more.",
                "tags": [topic, "history", "documentary", "analysis"],
            }
        if self.platform_name == "facebook":
            # Sin '#Mystery' (angulo descartado) ni marca fija: al publicar, facebook_metadata
            # agrega los hashtags investigados y la marca de la pagina real.
            from publish.facebook_metadata import trim_at_boundary
            return {
                "title": topic,
                "description": (
                    f"{trim_at_boundary(script, 260) or preview}\n\nWhat do you think really happened?\n\n"
                    "#History"
                ),
            }
        if self.platform_name == "instagram":
            # Igual que Facebook: los hashtags investigados y la marca de la cuenta real los
            # agrega instagram_uploader al publicar.
            from publish.facebook_metadata import trim_at_boundary
            return {
                "title": topic,
                "description": (
                    f"{trim_at_boundary(script, 320) or preview}\n\nWhat do you think really happened?\n\n"
                    "#History"
                ),
            }
        return {
            "thread": [
                self._clip_to_x_limit(
                    f"¿Qué pasaría si la historia de {topic} fuera más compleja de lo que te contaron? "
                    f"En este hilo te dejo el contexto clave, decisiones críticas y consecuencias reales para "
                    f"entender por qué este tema sigue importando hoy.",
                    280
                ),
                self._clip_to_x_limit(
                    f"{preview} Este punto conecta con decisiones políticas, sociales y culturales que cambiaron "
                    f"la narrativa pública. Lo importante no es solo el dato aislado, sino cómo se encadena con "
                    f"eventos posteriores y qué revela sobre el periodo completo.",
                    280
                ),
                self._clip_to_x_limit(
                    f"Si quieres la versión completa con cronología, fuentes y análisis de impacto, "
                    f"responde a este hilo y lo publico como segunda parte con más detalle por tramo.",
                    280
                ),
            ]
        }


class FacebookUploadWorker(QThread):
    finished = pyqtSignal(dict)
    error = pyqtSignal(str)
    progress = pyqtSignal(str)

    def __init__(self, video_path: str, title: str, description: str,
                 video_state: str = "PUBLISHED", result_path: str = None):
        super().__init__()
        self.video_path = video_path
        self.title = title
        self.description = description
        self.video_state = video_state
        self.result_path = result_path

    def run(self):
        try:
            from publish.facebook_uploader import save_upload_result, upload_video

            self.progress.emit("Publishing current video to Facebook Page...")
            result = upload_video(
                video_path=self.video_path,
                title=self.title,
                description=self.description,
                video_state=self.video_state,
            )
            if self.result_path:
                save_upload_result(
                    result_path=self.result_path,
                    upload_result=result,
                    title=self.title,
                    description=self.description,
                    video_state=self.video_state,
                )
            self.finished.emit(result)
        except Exception as e:
            self.error.emit(str(e))


class InstagramUploadWorker(QThread):
    finished = pyqtSignal(dict)
    error = pyqtSignal(str)
    progress = pyqtSignal(str)

    def __init__(self, video_path: str, title: str, description: str, result_path: str = None):
        super().__init__()
        self.video_path = video_path
        self.title = title
        self.description = description
        self.result_path = result_path

    def run(self):
        try:
            from publish.instagram_uploader import save_upload_result, upload_video

            self.progress.emit("Publishing current video to Instagram Reels...")
            result = upload_video(
                video_path=self.video_path,
                title=self.title,
                description=self.description,
            )
            if self.result_path:
                save_upload_result(
                    result_path=self.result_path,
                    upload_result=result,
                    title=self.title,
                    description=self.description,
                    caption=f"{self.title}\n\n{self.description}".strip(),
                )
            self.finished.emit(result)
        except Exception as e:
            self.error.emit(str(e))


class PlatformMetadataTab(QWidget):
    def __init__(self, parent_gui):
        super().__init__()
        self.parent_gui = parent_gui
        self.groq_client = GroqAiClient()
        self.worker = None
        self.facebook_upload_worker = None
        self.instagram_upload_worker = None
        self._x_thread_edits: List[QTextEdit] = []
        self._queue_platforms: List[str] = []
        self._queued_context: Dict = {}
        self._batch_generation_active = False
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)

        title = QLabel("Metadata Studio")
        title.setStyleSheet("font-size: 16pt; font-weight: bold;")
        layout.addWidget(title)

        subtitle = QLabel(
            "Dedicated metadata generation with Groq for YouTube, Facebook, Instagram, and X."
        )
        subtitle.setWordWrap(True)
        subtitle.setStyleSheet("color: #b3b3b3;")
        layout.addWidget(subtitle)

        self.status_label = QLabel("Ready")
        self.status_label.setStyleSheet("color: #14a085; font-weight: bold;")
        layout.addWidget(self.status_label)

        self.btn_generate_selected = QPushButton("Generate Metadata For Selected Format(s)")
        self.btn_generate_selected.setObjectName("accent")
        self.btn_generate_selected.clicked.connect(self.generate_metadata_for_selected_formats)
        layout.addWidget(self.btn_generate_selected)

        tabs = QTabWidget()
        tabs.addTab(self._create_youtube_tab(), "YouTube")
        tabs.addTab(self._create_x_tab(), "X Thread")
        tabs.addTab(self._create_facebook_tab(), "Facebook Reel")
        tabs.addTab(self._create_instagram_tab(), "Instagram Reel")
        layout.addWidget(tabs)

    def _create_youtube_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)

        self.btn_generate_youtube = QPushButton("Generate YouTube Metadata (Groq)")
        self.btn_generate_youtube.setObjectName("accent")
        self.btn_generate_youtube.clicked.connect(lambda: self.generate_metadata("youtube"))
        layout.addWidget(self.btn_generate_youtube)

        group = QGroupBox("YouTube Fields")
        group_layout = QVBoxLayout(group)

        self.yt_title = QLineEdit()
        self.yt_title.setReadOnly(True)
        self.yt_title.setPlaceholderText("Title")
        group_layout.addWidget(QLabel("Title"))
        group_layout.addWidget(self.yt_title)

        title_buttons = QHBoxLayout()
        btn_copy_title = QPushButton("Copy Title")
        btn_copy_title.clicked.connect(lambda: self._copy_text(self.yt_title.text(), "Title copied"))
        title_buttons.addWidget(btn_copy_title)
        title_buttons.addStretch()
        group_layout.addLayout(title_buttons)

        self.yt_description = QTextEdit()
        self.yt_description.setReadOnly(True)
        self.yt_description.setMinimumHeight(160)
        group_layout.addWidget(QLabel("Description"))
        group_layout.addWidget(self.yt_description)

        desc_buttons = QHBoxLayout()
        btn_copy_desc = QPushButton("Copy Description")
        btn_copy_desc.clicked.connect(
            lambda: self._copy_text(self.yt_description.toPlainText(), "Description copied")
        )
        desc_buttons.addWidget(btn_copy_desc)
        desc_buttons.addStretch()
        group_layout.addLayout(desc_buttons)

        self.yt_tags = QTextEdit()
        self.yt_tags.setReadOnly(True)
        self.yt_tags.setMinimumHeight(100)
        group_layout.addWidget(QLabel("Tags"))
        group_layout.addWidget(self.yt_tags)

        tags_buttons = QHBoxLayout()
        btn_copy_tags = QPushButton("Copy Tags")
        btn_copy_tags.clicked.connect(lambda: self._copy_text(self.yt_tags.toPlainText(), "Tags copied"))
        tags_buttons.addWidget(btn_copy_tags)
        tags_buttons.addStretch()
        group_layout.addLayout(tags_buttons)

        layout.addWidget(group)
        return tab

    def _create_x_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)

        self.btn_generate_x = QPushButton("Generate X Thread Metadata (Groq)")
        self.btn_generate_x.setObjectName("accent")
        self.btn_generate_x.clicked.connect(lambda: self.generate_metadata("x"))
        layout.addWidget(self.btn_generate_x)

        top_buttons = QHBoxLayout()
        btn_copy_all = QPushButton("Copy Full Thread")
        btn_copy_all.clicked.connect(self._copy_full_thread)
        top_buttons.addWidget(btn_copy_all)
        top_buttons.addStretch()
        layout.addLayout(top_buttons)

        self.x_scroll = QScrollArea()
        self.x_scroll.setWidgetResizable(True)
        self.x_container = QWidget()
        self.x_layout = QVBoxLayout(self.x_container)
        self.x_layout.setContentsMargins(6, 6, 6, 6)
        self.x_layout.setSpacing(8)
        self.x_scroll.setWidget(self.x_container)
        layout.addWidget(self.x_scroll)

        self._render_x_thread([])
        return tab

    def _create_facebook_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)

        info = QLabel(
            "Publish the current vertical short directly to your Facebook Page as a Reel.\n"
            "Auth uses FACEBOOK_PAGE_ACCESS_TOKEN or FACEBOOK_USER_ACCESS_TOKEN + FACEBOOK_PAGE_ID from .env."
        )
        info.setWordWrap(True)
        info.setStyleSheet("color: #b3b3b3;")
        layout.addWidget(info)

        self.btn_generate_facebook = QPushButton("Generate Facebook Metadata (Groq)")
        self.btn_generate_facebook.setObjectName("accent")
        self.btn_generate_facebook.clicked.connect(lambda: self.generate_metadata("facebook"))
        layout.addWidget(self.btn_generate_facebook)

        self.fb_auth_status = QLabel("Facebook auth not checked yet.")
        self.fb_auth_status.setStyleSheet("color: #888;")
        layout.addWidget(self.fb_auth_status)

        top_row = QHBoxLayout()
        self.btn_prefill_facebook = QPushButton("Prefill From Context")
        self.btn_prefill_facebook.clicked.connect(self._prefill_facebook_from_context)
        top_row.addWidget(self.btn_prefill_facebook)

        self.btn_copy_youtube_to_facebook = QPushButton("Use YouTube Metadata")
        self.btn_copy_youtube_to_facebook.clicked.connect(self._copy_youtube_to_facebook)
        top_row.addWidget(self.btn_copy_youtube_to_facebook)

        self.btn_check_facebook_auth = QPushButton("Check Facebook Auth")
        self.btn_check_facebook_auth.clicked.connect(self._check_facebook_auth)
        top_row.addWidget(self.btn_check_facebook_auth)
        top_row.addStretch()
        layout.addLayout(top_row)

        group = QGroupBox("Facebook Reel Fields")
        group_layout = QVBoxLayout(group)

        self.fb_title = QLineEdit()
        self.fb_title.setPlaceholderText("Facebook Reel title")
        group_layout.addWidget(QLabel("Title"))
        group_layout.addWidget(self.fb_title)

        title_buttons = QHBoxLayout()
        btn_copy_fb_title = QPushButton("Copy Title")
        btn_copy_fb_title.clicked.connect(lambda: self._copy_text(self.fb_title.text(), "Facebook title copied"))
        title_buttons.addWidget(btn_copy_fb_title)
        title_buttons.addStretch()
        group_layout.addLayout(title_buttons)

        self.fb_description = QTextEdit()
        self.fb_description.setMinimumHeight(180)
        self.fb_description.setPlaceholderText("Facebook Reel description")
        group_layout.addWidget(QLabel("Description"))
        group_layout.addWidget(self.fb_description)

        desc_buttons = QHBoxLayout()
        btn_copy_fb_desc = QPushButton("Copy Description")
        btn_copy_fb_desc.clicked.connect(
            lambda: self._copy_text(self.fb_description.toPlainText(), "Facebook description copied")
        )
        desc_buttons.addWidget(btn_copy_fb_desc)
        desc_buttons.addStretch()
        group_layout.addLayout(desc_buttons)

        state_row = QHBoxLayout()
        state_row.addWidget(QLabel("Publish state"))
        self.fb_state_combo = QComboBox()
        self.fb_state_combo.addItem("Published", "PUBLISHED")
        self.fb_state_combo.addItem("Draft", "DRAFT")
        self.fb_state_combo.setToolTip(
            "Published creates a public Facebook Reel.\n"
            "Draft uploads the Reel without publishing it publicly."
        )
        state_row.addWidget(self.fb_state_combo)
        state_row.addStretch()
        group_layout.addLayout(state_row)

        layout.addWidget(group)

        actions = QHBoxLayout()
        self.btn_upload_facebook = QPushButton("Upload Current Video to Facebook")
        self.btn_upload_facebook.setObjectName("accent")
        self.btn_upload_facebook.clicked.connect(self._upload_current_video_to_facebook)
        actions.addWidget(self.btn_upload_facebook)
        actions.addStretch()
        layout.addLayout(actions)
        layout.addStretch()
        return tab

    def _create_instagram_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)

        info = QLabel(
            "Publish the current vertical short directly to Instagram Reels.\n"
            "Requires an Instagram professional account linked to the Facebook Page,\n"
            "a valid Meta user token with instagram_content_publish, and Cloudinary credentials."
        )
        info.setWordWrap(True)
        info.setStyleSheet("color: #b3b3b3;")
        layout.addWidget(info)

        self.btn_generate_instagram = QPushButton("Generate Instagram Metadata (Groq)")
        self.btn_generate_instagram.setObjectName("accent")
        self.btn_generate_instagram.clicked.connect(lambda: self.generate_metadata("instagram"))
        layout.addWidget(self.btn_generate_instagram)

        self.ig_auth_status = QLabel("Instagram auth not checked yet.")
        self.ig_auth_status.setStyleSheet("color: #888;")
        layout.addWidget(self.ig_auth_status)

        top_row = QHBoxLayout()
        self.btn_prefill_instagram = QPushButton("Prefill From Context")
        self.btn_prefill_instagram.clicked.connect(self._prefill_instagram_from_context)
        top_row.addWidget(self.btn_prefill_instagram)

        self.btn_copy_facebook_to_instagram = QPushButton("Use Facebook Metadata")
        self.btn_copy_facebook_to_instagram.clicked.connect(self._copy_facebook_to_instagram)
        top_row.addWidget(self.btn_copy_facebook_to_instagram)

        self.btn_check_instagram_auth = QPushButton("Check Instagram Auth")
        self.btn_check_instagram_auth.clicked.connect(self._check_instagram_auth)
        top_row.addWidget(self.btn_check_instagram_auth)
        top_row.addStretch()
        layout.addLayout(top_row)

        group = QGroupBox("Instagram Reel Fields")
        group_layout = QVBoxLayout(group)

        self.ig_title = QLineEdit()
        self.ig_title.setPlaceholderText("Instagram Reel title")
        group_layout.addWidget(QLabel("Title"))
        group_layout.addWidget(self.ig_title)

        ig_title_buttons = QHBoxLayout()
        btn_copy_ig_title = QPushButton("Copy Title")
        btn_copy_ig_title.clicked.connect(lambda: self._copy_text(self.ig_title.text(), "Instagram title copied"))
        ig_title_buttons.addWidget(btn_copy_ig_title)
        ig_title_buttons.addStretch()
        group_layout.addLayout(ig_title_buttons)

        self.ig_description = QTextEdit()
        self.ig_description.setMinimumHeight(180)
        self.ig_description.setPlaceholderText("Instagram Reel caption body")
        group_layout.addWidget(QLabel("Description"))
        group_layout.addWidget(self.ig_description)

        ig_desc_buttons = QHBoxLayout()
        btn_copy_ig_desc = QPushButton("Copy Description")
        btn_copy_ig_desc.clicked.connect(
            lambda: self._copy_text(self.ig_description.toPlainText(), "Instagram description copied")
        )
        ig_desc_buttons.addWidget(btn_copy_ig_desc)
        ig_desc_buttons.addStretch()
        group_layout.addLayout(ig_desc_buttons)

        layout.addWidget(group)

        actions = QHBoxLayout()
        self.btn_upload_instagram = QPushButton("Upload Current Video to Instagram")
        self.btn_upload_instagram.setObjectName("accent")
        self.btn_upload_instagram.clicked.connect(self._upload_current_video_to_instagram)
        actions.addWidget(self.btn_upload_instagram)
        actions.addStretch()
        layout.addLayout(actions)
        layout.addStretch()
        return tab

    def _copy_youtube_to_facebook(self):
        self.fb_title.setText(self.yt_title.text().strip())
        self.fb_description.setPlainText(self.yt_description.toPlainText().strip())
        self.status_label.setText("Facebook fields filled from YouTube metadata.")
        self.status_label.setStyleSheet("color: #14a085; font-weight: bold;")

    def _prefill_facebook_from_context(self):
        context = self._collect_context()
        topic = str(context.get("topic") or "").strip()
        script = str(context.get("script") or "").strip()
        description = script[:800].strip()
        if len(script) > 800:
            description = description.rstrip() + "..."

        if topic and not self.fb_title.text().strip():
            self.fb_title.setText(topic)
        if description and not self.fb_description.toPlainText().strip():
            self.fb_description.setPlainText(description)

        if not topic and not description:
            QMessageBox.warning(self, "No context", "No project context found to prefill Facebook fields.")
            return

        self.status_label.setText("Facebook fields prefilled from the current project.")
        self.status_label.setStyleSheet("color: #14a085; font-weight: bold;")

    def _copy_facebook_to_instagram(self):
        self.ig_title.setText(self.fb_title.text().strip() or self.yt_title.text().strip())
        self.ig_description.setPlainText(
            self.fb_description.toPlainText().strip() or self.yt_description.toPlainText().strip()
        )
        self.status_label.setText("Instagram fields filled from Facebook metadata.")
        self.status_label.setStyleSheet("color: #14a085; font-weight: bold;")

    def _prefill_instagram_from_context(self):
        context = self._collect_context()
        topic = str(context.get("topic") or "").strip()
        script = str(context.get("script") or "").strip()
        description = script[:700].strip()
        if len(script) > 700:
            description = description.rstrip() + "..."

        if topic and not self.ig_title.text().strip():
            self.ig_title.setText(topic)
        if description and not self.ig_description.toPlainText().strip():
            self.ig_description.setPlainText(description)

        if not topic and not description:
            QMessageBox.warning(self, "No context", "No project context found to prefill Instagram fields.")
            return

        self.status_label.setText("Instagram fields prefilled from the current project.")
        self.status_label.setStyleSheet("color: #14a085; font-weight: bold;")

    def _check_facebook_auth(self):
        try:
            from publish.facebook_uploader import check_auth

            auth = check_auth()
            if auth.get("authenticated"):
                page_name = auth.get("page_name") or "Facebook Page"
                page_id = auth.get("page_id") or "unknown"
                self.fb_auth_status.setText(f"Connected to {page_name} ({page_id})")
                self.fb_auth_status.setStyleSheet("color: #14a085;")
            else:
                self.fb_auth_status.setText(f"Facebook auth error: {auth.get('error', 'Unknown error')}")
                self.fb_auth_status.setStyleSheet("color: #e74c3c;")
        except Exception as e:
            self.fb_auth_status.setText(f"Facebook auth error: {e}")
            self.fb_auth_status.setStyleSheet("color: #e74c3c;")

    def _check_instagram_auth(self):
        try:
            from publish.instagram_uploader import check_auth

            auth = check_auth()
            if auth.get("authenticated"):
                username = auth.get("instagram_username") or auth.get("instagram_name") or "Instagram account"
                ig_user_id = auth.get("ig_user_id") or "unknown"
                quota_total = auth.get("quota_total")
                quota_usage = auth.get("quota_usage")
                quota_text = ""
                if quota_total is not None and quota_usage is not None:
                    quota_text = f" | quota {quota_usage}/{quota_total}"
                cloudinary_ok = auth.get("cloudinary_authenticated")
                if cloudinary_ok:
                    self.ig_auth_status.setText(
                        f"Connected to @{username} ({ig_user_id}){quota_text} | Cloudinary ready"
                    )
                    self.ig_auth_status.setStyleSheet("color: #14a085;")
                else:
                    cloudinary_error = auth.get("cloudinary_error") or "Cloudinary not configured"
                    self.ig_auth_status.setText(
                        f"Connected to @{username} ({ig_user_id}){quota_text} | Cloudinary missing: {cloudinary_error}"
                    )
                    self.ig_auth_status.setStyleSheet("color: #f39c12;")
            else:
                self.ig_auth_status.setText(f"Instagram auth error: {auth.get('error', 'Unknown error')}")
                self.ig_auth_status.setStyleSheet("color: #e74c3c;")
        except Exception as e:
            self.ig_auth_status.setText(f"Instagram auth error: {e}")
            self.ig_auth_status.setStyleSheet("color: #e74c3c;")

    def _resolve_project_video_context(self) -> Dict:
        auto_tab = getattr(self.parent_gui, "auto_video_tab", None)
        project_path = getattr(auto_tab, "current_project_path", None) if auto_tab else None
        project_data = None
        generated_video_data = {}
        video_path = None

        if auto_tab and hasattr(auto_tab, "get_current_project_data"):
            try:
                project_data = auto_tab.get_current_project_data()
            except Exception:
                project_data = None

        if auto_tab and isinstance(getattr(auto_tab, "last_generated_video_data", None), dict):
            generated_video_data = dict(auto_tab.last_generated_video_data or {})

        if isinstance(project_data, dict):
            generated_video_data = dict(project_data.get("generated_video_data") or generated_video_data or {})

        candidate_paths = [
            generated_video_data.get("video_path"),
            generated_video_data.get("teaser_video_path"),
        ]

        base_dir = None
        if project_path:
            project_candidate = Path(project_path)
            base_dir = project_candidate if project_candidate.is_dir() else project_candidate.parent

        for candidate in candidate_paths:
            if not candidate:
                continue
            candidate_path = Path(candidate)
            if not candidate_path.is_absolute() and base_dir:
                candidate_path = (base_dir / candidate_path).resolve()
            if candidate_path.exists():
                video_path = str(candidate_path)
                break

        return {
            "project_path": project_path,
            "project_data": project_data or {},
            "generated_video_data": generated_video_data,
            "video_path": video_path,
        }

    def _upload_current_video_to_facebook(self):
        if self.facebook_upload_worker and self.facebook_upload_worker.isRunning():
            QMessageBox.warning(self, "Process running", "Wait for the current Facebook upload to finish.")
            return

        title = self.fb_title.text().strip() or self.yt_title.text().strip()
        description = self.fb_description.toPlainText().strip() or self.yt_description.toPlainText().strip()
        if not title:
            context = self._collect_context()
            title = str(context.get("topic") or "").strip()

        video_context = self._resolve_project_video_context()
        video_path = video_context.get("video_path")
        if not video_path:
            QMessageBox.warning(
                self,
                "No generated video",
                "No generated video was found for the current project.\n\nGenerate or load a short first.",
            )
            return

        context = self._collect_context()
        if "9:16" not in (context.get("video_formats") or []) and "9:16" not in str(context.get("video_format") or ""):
            reply = QMessageBox.question(
                self,
                "Vertical format not detected",
                "The current project does not look like a 9:16 short.\n"
                "Facebook Reel publishing works best with vertical shorts.\n\nContinue anyway?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return

        project_path = video_context.get("project_path")
        result_path = None
        if project_path:
            project_candidate = Path(project_path)
            result_path = str((project_candidate if project_candidate.is_dir() else project_candidate.parent) / "facebook_upload_result.json")

        self.btn_upload_facebook.setEnabled(False)
        self.btn_upload_facebook.setText("Publishing...")
        self.status_label.setText("Publishing current video to Facebook...")
        self.status_label.setStyleSheet("color: #f39c12; font-weight: bold;")

        self.facebook_upload_worker = FacebookUploadWorker(
            video_path=video_path,
            title=title,
            description=description,
            video_state=self.fb_state_combo.currentData() or "PUBLISHED",
            result_path=result_path,
        )
        self.facebook_upload_worker.progress.connect(self._log)
        self.facebook_upload_worker.finished.connect(self._on_facebook_upload_finished)
        self.facebook_upload_worker.error.connect(self._on_facebook_upload_error)
        self.facebook_upload_worker.start()

    def _on_facebook_upload_finished(self, payload: Dict):
        self.btn_upload_facebook.setEnabled(True)
        self.btn_upload_facebook.setText("Upload Current Video to Facebook")
        page_name = payload.get("page_name") or "Facebook Page"
        url = payload.get("url") or payload.get("status") or "Published"
        self.fb_auth_status.setText(f"Last Facebook upload: {page_name}")
        self.fb_auth_status.setStyleSheet("color: #14a085;")
        self.status_label.setText("Facebook upload completed.")
        self.status_label.setStyleSheet("color: #14a085; font-weight: bold;")
        self._log(f"[Facebook] Upload completed: {url}")
        QMessageBox.information(self, "Facebook Upload Complete", f"Video uploaded successfully.\n\n{url}")

    def _on_facebook_upload_error(self, error_message: str):
        self.btn_upload_facebook.setEnabled(True)
        self.btn_upload_facebook.setText("Upload Current Video to Facebook")
        self.status_label.setText("Facebook upload failed.")
        self.status_label.setStyleSheet("color: #e74c3c; font-weight: bold;")
        self._log(f"[Facebook] Error: {error_message}")
        QMessageBox.critical(self, "Facebook Upload Error", error_message)

    def _upload_current_video_to_instagram(self):
        if self.instagram_upload_worker and self.instagram_upload_worker.isRunning():
            QMessageBox.warning(self, "Process running", "Wait for the current Instagram upload to finish.")
            return

        title = self.ig_title.text().strip() or self.fb_title.text().strip() or self.yt_title.text().strip()
        description = (
            self.ig_description.toPlainText().strip()
            or self.fb_description.toPlainText().strip()
            or self.yt_description.toPlainText().strip()
        )
        if not title:
            context = self._collect_context()
            title = str(context.get("topic") or "").strip()

        video_context = self._resolve_project_video_context()
        video_path = video_context.get("video_path")
        if not video_path:
            QMessageBox.warning(
                self,
                "No generated video",
                "No generated video was found for the current project.\n\nGenerate or load a short first.",
            )
            return

        context = self._collect_context()
        if "9:16" not in (context.get("video_formats") or []) and "9:16" not in str(context.get("video_format") or ""):
            reply = QMessageBox.question(
                self,
                "Vertical format not detected",
                "The current project does not look like a 9:16 short.\n"
                "Instagram Reel publishing works best with vertical shorts.\n\nContinue anyway?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return

        project_path = video_context.get("project_path")
        result_path = None
        if project_path:
            project_candidate = Path(project_path)
            result_path = str((project_candidate if project_candidate.is_dir() else project_candidate.parent) / "instagram_upload_result.json")

        self.btn_upload_instagram.setEnabled(False)
        self.btn_upload_instagram.setText("Publishing...")
        self.status_label.setText("Publishing current video to Instagram...")
        self.status_label.setStyleSheet("color: #f39c12; font-weight: bold;")

        self.instagram_upload_worker = InstagramUploadWorker(
            video_path=video_path,
            title=title,
            description=description,
            result_path=result_path,
        )
        self.instagram_upload_worker.progress.connect(self._log)
        self.instagram_upload_worker.finished.connect(self._on_instagram_upload_finished)
        self.instagram_upload_worker.error.connect(self._on_instagram_upload_error)
        self.instagram_upload_worker.start()

    def _on_instagram_upload_finished(self, payload: Dict):
        self.btn_upload_instagram.setEnabled(True)
        self.btn_upload_instagram.setText("Upload Current Video to Instagram")
        username = payload.get("instagram_username") or payload.get("instagram_name") or "Instagram"
        url = payload.get("url") or payload.get("status") or "Published"
        self.ig_auth_status.setText(f"Last Instagram upload: @{username}")
        self.ig_auth_status.setStyleSheet("color: #14a085;")
        self.status_label.setText("Instagram upload completed.")
        self.status_label.setStyleSheet("color: #14a085; font-weight: bold;")
        self._log(f"[Instagram] Upload completed: {url}")
        QMessageBox.information(self, "Instagram Upload Complete", f"Video uploaded successfully.\n\n{url}")

    def _on_instagram_upload_error(self, error_message: str):
        self.btn_upload_instagram.setEnabled(True)
        self.btn_upload_instagram.setText("Upload Current Video to Instagram")
        self.status_label.setText("Instagram upload failed.")
        self.status_label.setStyleSheet("color: #e74c3c; font-weight: bold;")
        self._log(f"[Instagram] Error: {error_message}")
        QMessageBox.critical(self, "Instagram Upload Error", error_message)

    def _set_generating(self, is_generating: bool):
        self.btn_generate_youtube.setEnabled(not is_generating)
        self.btn_generate_facebook.setEnabled(not is_generating)
        self.btn_generate_instagram.setEnabled(not is_generating)
        self.btn_generate_x.setEnabled(not is_generating)
        self.btn_generate_selected.setEnabled(not is_generating)

    def _log(self, message: str):
        if hasattr(self.parent_gui, "log"):
            self.parent_gui.log(message)

    def _targets_for_video_format(self, video_format: str) -> List[str]:
        format_tokens = self._expand_video_formats(video_format)
        targets: List[str] = []
        for fmt in format_tokens:
            if fmt == "16:9" and "youtube" not in targets:
                targets.append("youtube")
            elif fmt == "9:16":
                if "youtube" not in targets:
                    targets.append("youtube")
                if "facebook" not in targets:
                    targets.append("facebook")
                if "instagram" not in targets:
                    targets.append("instagram")
            elif fmt == "1:1" and "x" not in targets:
                targets.append("x")
        return targets

    def _expand_video_formats(self, video_format: str) -> List[str]:
        fmt = str(video_format or "").strip().lower().replace(" ", "")
        normalized = (
            fmt
            .replace("·", "+")
            .replace("|", "+")
            .replace("/", "+")
            .replace("_", "+")
            .replace(",", "+")
        )
        token_set = {token for token in normalized.split("+") if token}

        single_vertical_aliases = {
            "9:16",
            "reels",
            "reel",
            "tiktok",
            "short",
            "shorts",
            "youtubeshort",
            "youtube+short",
        }
        single_square_aliases = {"1:1", "x", "xsquare", "x_square", "square"}
        single_horizontal_aliases = {"16:9", "youtube", "horizontal"}

        if normalized in single_vertical_aliases:
            return ["9:16"]
        if normalized in single_square_aliases:
            return ["1:1"]
        if normalized in single_horizontal_aliases:
            return ["16:9"]

        formats: List[str] = []
        if "16:9" in normalized or "horizontal" in normalized or "youtube" in token_set:
            formats.append("16:9")
        if (
            "1:1" in normalized
            or "square" in normalized
            or "x" in token_set
            or "xsquare" in token_set
            or "x_square" in token_set
        ):
            formats.append("1:1")
        if (
            "9:16" in normalized
            or "vertical" in normalized
            or "reel" in normalized
            or "short" in normalized
            or "tiktok" in normalized
        ):
            formats.append("9:16")

        unique_formats: List[str] = []
        for item in formats:
            if item not in unique_formats:
                unique_formats.append(item)
        return unique_formats

    def _collect_context(self) -> Dict:
        topic = ""
        category = ""
        language = "es"
        duration_seconds = 0
        video_format = "16:9"
        video_formats = ["16:9"]
        script = ""
        segments = []

        if hasattr(self.parent_gui, "topic_input"):
            topic = self.parent_gui.topic_input.text().strip()
        if hasattr(self.parent_gui, "category_combo"):
            category = self.parent_gui.category_combo.currentText().strip()

        auto_tab = getattr(self.parent_gui, "auto_video_tab", None)
        if auto_tab:
            try:
                if hasattr(auto_tab, "lang_en") and auto_tab.lang_en.isChecked():
                    language = "en"
            except Exception:
                pass
            try:
                if hasattr(auto_tab, "duration_slider"):
                    duration_seconds = int(auto_tab.duration_slider.value())
            except Exception:
                pass
            try:
                if hasattr(auto_tab, "get_selected_video_format"):
                    video_format = auto_tab.get_selected_video_format()
            except Exception:
                pass
            try:
                if hasattr(auto_tab, "get_selected_video_formats"):
                    selected_formats = auto_tab.get_selected_video_formats()
                    if selected_formats:
                        video_formats = selected_formats
            except Exception:
                pass

            project_data = None
            if hasattr(auto_tab, "get_current_project_data"):
                try:
                    project_data = auto_tab.get_current_project_data()
                except Exception:
                    project_data = None

            if project_data:
                config = project_data.get("config", {})
                storyboard = project_data.get("storyboard", {})
                topic = config.get("topic", topic) or storyboard.get("topic", topic)
                category = config.get("category", category) or storyboard.get("category", category)
                language = config.get("language", language) or language
                duration_seconds = config.get("duration", duration_seconds) or duration_seconds
                video_format = config.get("video_format", video_format) or video_format
                expanded_formats = self._expand_video_formats(video_format)
                if expanded_formats:
                    video_formats = expanded_formats
                elif (not isinstance(video_formats, list)) or (not video_formats):
                    video_formats = [video_format]
                script = storyboard.get("script", "") or project_data.get("script", "")
                segments = storyboard.get("segments", []) or project_data.get("segments", [])

        if not script and segments:
            parts = []
            for seg in segments:
                text = (
                    seg.get("text")
                    or seg.get("narration_text")
                    or seg.get("narration")
                    or ""
                )
                text = str(text).strip()
                if text:
                    parts.append(text)
            script = " ".join(parts)

        expanded_formats = self._expand_video_formats(video_format)
        if expanded_formats:
            video_formats = expanded_formats
        elif not video_formats:
            video_formats = [video_format]

        return {
            "topic": topic,
            "category": category,
            "language": language,
            "duration_seconds": duration_seconds,
            "video_format": video_format,
            "video_formats": video_formats,
            "script": script,
            "segment_count": len(segments),
        }

    def generate_metadata_for_selected_formats(self):
        if self.worker and self.worker.isRunning():
            QMessageBox.warning(self, "Process running", "Wait for the current metadata generation to finish.")
            return

        context = self._collect_context()
        if not context.get("topic") and not context.get("script"):
            QMessageBox.warning(
                self,
                "No context",
                "No topic/project context found. Fill the topic first or load a project.",
            )
            return

        targets = self._targets_for_video_format(context.get("video_format", "16:9"))
        if not targets:
            QMessageBox.information(
                self,
                "No supported metadata target",
                "El formato seleccionado no tiene metadata soportada. Metadata Studio solo genera para YouTube, Facebook, Instagram y X.",
            )
            return

        self._queue_platforms = targets[1:]
        self._queued_context = context
        self._batch_generation_active = len(targets) > 1

        if self._batch_generation_active:
            self._log(f"[Metadata] Batch generation: {' -> '.join(targets)}")

        self.generate_metadata(targets[0], context=context, queued=True)

    def generate_metadata(self, platform_name: str, context: Dict = None, queued: bool = False):
        if self.worker and self.worker.isRunning() and not queued:
            QMessageBox.warning(self, "Process running", "Wait for the current metadata generation to finish.")
            return

        if context is None:
            context = self._collect_context()
        if not context.get("topic") and not context.get("script"):
            QMessageBox.warning(
                self,
                "No context",
                "No topic/project context found. Fill the topic first or load a project.",
            )
            return
        if platform_name not in {"youtube", "facebook", "instagram", "x"}:
            QMessageBox.warning(
                self,
                "Unsupported platform",
                f"Metadata Studio no soporta '{platform_name}'.",
            )
            return

        self._set_generating(True)
        self.status_label.setText(f"Generating {platform_name} metadata...")
        self.status_label.setStyleSheet("color: #f39c12; font-weight: bold;")
        self._log(f"[Metadata] Groq generation started: {platform_name}")

        self.worker = MetadataGenerationWorker(platform_name, context, self.groq_client)
        self.worker.progress.connect(self._log)
        self.worker.finished.connect(self._on_generation_finished)
        self.worker.error.connect(self._on_generation_error)
        self.worker.start()

    def _on_generation_finished(self, platform_name: str, payload: Dict):
        if platform_name == "youtube":
            self.yt_title.setText(payload.get("title", ""))
            self.yt_description.setPlainText(payload.get("description", ""))
            tags = payload.get("tags", [])
            self.yt_tags.setPlainText(", ".join(tags))
        elif platform_name == "facebook":
            self.fb_title.setText(payload.get("title", ""))
            self.fb_description.setPlainText(payload.get("description", ""))
        elif platform_name == "instagram":
            self.ig_title.setText(payload.get("title", ""))
            self.ig_description.setPlainText(payload.get("description", ""))
        else:
            thread_parts = payload.get("thread", [])
            self._render_x_thread(thread_parts)

        self._log(f"[Metadata] Completed: {platform_name}")

        if self._queue_platforms:
            next_platform = self._queue_platforms.pop(0)
            self.status_label.setText(f"Metadata generated for {platform_name}. Continuing with {next_platform}...")
            self.status_label.setStyleSheet("color: #f39c12; font-weight: bold;")
            self.generate_metadata(next_platform, context=self._queued_context, queued=True)
            return

        self._batch_generation_active = False
        self._queued_context = {}
        self._set_generating(False)
        self.status_label.setText(f"Metadata generated for {platform_name}.")
        self.status_label.setStyleSheet("color: #14a085; font-weight: bold;")

    def _on_generation_error(self, error_message: str):
        self._queue_platforms = []
        self._queued_context = {}
        self._batch_generation_active = False
        self._set_generating(False)
        self.status_label.setText("Metadata generation failed.")
        self.status_label.setStyleSheet("color: #e74c3c; font-weight: bold;")
        self._log(f"[Metadata] Error: {error_message}")
        QMessageBox.critical(self, "Metadata error", error_message)

    def _render_x_thread(self, parts: List[str]):
        while self.x_layout.count():
            item = self.x_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()

        self._x_thread_edits = []
        if not parts:
            empty = QLabel("No thread generated yet.")
            empty.setStyleSheet("color: #b3b3b3;")
            self.x_layout.addWidget(empty)
            self.x_layout.addStretch()
            return

        for idx, part in enumerate(parts, start=1):
            post_len = len(part or "")
            box = QGroupBox(f"Post {idx} · {post_len}/280")
            box_layout = QVBoxLayout(box)
            post_edit = QTextEdit()
            post_edit.setReadOnly(True)
            post_edit.setPlainText(part)
            post_edit.setMinimumHeight(90)
            box_layout.addWidget(post_edit)

            length_hint = QLabel(
                " Longitud sólida para X"
                if post_len >= 240
                else "️ Post corto para X (ideal: 240-280 caracteres)"
            )
            length_hint.setStyleSheet(
                "color: #14a085; font-size: 9pt;" if post_len >= 240 else "color: #f39c12; font-size: 9pt;"
            )
            box_layout.addWidget(length_hint)

            row = QHBoxLayout()
            btn_copy = QPushButton(f"Copy Post {idx}")
            btn_copy.clicked.connect(
                lambda _checked=False, text=part: self._copy_text(text, "Post copied")
            )
            row.addWidget(btn_copy)
            row.addStretch()
            box_layout.addLayout(row)

            self._x_thread_edits.append(post_edit)
            self.x_layout.addWidget(box)

        self.x_layout.addStretch()

    def _copy_full_thread(self):
        parts = [edit.toPlainText().strip() for edit in self._x_thread_edits if edit.toPlainText().strip()]
        full_text = "\n\n".join(parts)
        self._copy_text(full_text, "Thread copied")

    def _copy_text(self, text: str, ok_message: str):
        value = (text or "").strip()
        if not value:
            QMessageBox.warning(self, "Empty value", "There is nothing to copy.")
            return
        QApplication.clipboard().setText(value)
        self.status_label.setText(ok_message)
        self.status_label.setStyleSheet("color: #14a085; font-weight: bold;")
