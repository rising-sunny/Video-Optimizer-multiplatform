"""Client for generating images through a self-hosted ComfyUI instance.

The client intentionally matches the small provider interface used by the
existing image pipeline: generate_image(...) returns a local file path or None.
"""

from __future__ import annotations

import copy
import json
import os
import random
import time
import uuid
from pathlib import Path
from typing import Any, Optional

import requests

from infra.env_loader import load_project_env
from infra.vast_ai_instance_manager import get_default_vast_manager

PROJECT_DIR = Path(__file__).resolve().parent
load_project_env(PROJECT_DIR)

DEFAULT_BASE_URL = "http://127.0.0.1:8188"
DEFAULT_WORKFLOW_DIR = PROJECT_DIR / "comfyui_workflows"
DEFAULT_TIMEOUT_SECONDS = 300
DEFAULT_POLL_SECONDS = 1.5

PLACEHOLDER_VALUES = {
    "__PROMPT__": "prompt",
    "__NEGATIVE_PROMPT__": "negative_prompt",
    "__WIDTH__": "width",
    "__HEIGHT__": "height",
    "__SEED__": "seed",
    "__BATCH_SIZE__": "batch_size",
    "__FILENAME_PREFIX__": "filename_prefix",
    "__STYLE__": "style",
}


class ComfyUiImageClient:
    """Thin wrapper around the local ComfyUI HTTP API."""

    PRESET_ALIASES = {
        "comfy": "historical_vertical_schnell",
        "comfyui": "historical_vertical_schnell",
        "comfy_schnell": "historical_vertical_schnell",
        "comfy_dev": "historical_vertical_dev",
        "comfy_flux_dev": "historical_vertical_dev",
        "comfy_sdxl": "coloring_sdxl_lineart",
        "historical_vertical": "historical_vertical_schnell",
        "historical_vertical_dev": "historical_vertical_dev",
        "thumbnail": "thumbnail_16x9_schnell",
        "thumbnail_dev": "thumbnail_16x9_dev",
        "coloring": "coloring_sdxl_lineart",
    }

    def __init__(
        self,
        log_callback=None,
        base_url: Optional[str] = None,
        workflow_dir: Optional[str | Path] = None,
        timeout_seconds: Optional[int] = None,
        session: Optional[requests.Session] = None,
        vast_manager=None,
    ):
        self.log_callback = log_callback
        self._base_url_explicit = base_url is not None
        self.base_url = (base_url or os.getenv("COMFYUI_BASE_URL") or DEFAULT_BASE_URL).rstrip("/")
        self.workflow_dir = Path(
            workflow_dir
            or os.getenv("COMFYUI_WORKFLOW_DIR")
            or DEFAULT_WORKFLOW_DIR
        )
        self.timeout_seconds = int(
            timeout_seconds
            or os.getenv("COMFYUI_TIMEOUT_SECONDS")
            or DEFAULT_TIMEOUT_SECONDS
        )
        self.poll_seconds = float(os.getenv("COMFYUI_POLL_SECONDS") or DEFAULT_POLL_SECONDS)
        self.session = session or requests.Session()
        self.vast_manager = (
            vast_manager
            if vast_manager is not None
            else (None if self._base_url_explicit else get_default_vast_manager(log_callback=log_callback))
        )
        self.available = bool(self.base_url)
        self.last_error: Optional[str] = None

        if self.available:
            self._log(f"[ComfyUI] Client ready ({self.base_url})")
        else:
            self._log("[ComfyUI] COMFYUI_BASE_URL is not configured")

    def _log(self, message: str) -> None:
        if self.log_callback:
            try:
                self.log_callback(message)
                return
            except Exception:
                pass
        print(message)


    def generate_image(
        self,
        prompt: str,
        width: int = 1024,
        height: int = 1024,
        output_path: Optional[str] = None,
        negative_prompt: Optional[str] = None,
        style: Optional[str] = None,
        seed: Optional[int] = None,
        preset: Optional[str] = None,
        batch_size: int = 1,
    ) -> Optional[str]:
        self.last_error = None
        if not self.available:
            self.last_error = "ComfyUI no disponible: COMFYUI_BASE_URL vacio"
            return None

        prompt_text = str(prompt or "").strip()
        if not prompt_text:
            self.last_error = "prompt vacio"
            return None

        try:
            if self.vast_manager and getattr(self.vast_manager, "enabled", False):
                self.vast_manager.ensure_ready()

            resolved_preset = self._resolve_preset(preset, width, height, style)
            workflow, preset_config = self._load_workflow(resolved_preset)
            seed_value = int(seed if seed is not None else random.randint(1, 2**31 - 1))
            output_file = Path(output_path or self._default_output_path(resolved_preset, seed_value))
            filename_prefix = output_file.stem

            rendered_workflow = self._render_workflow(
                workflow,
                preset_config,
                values={
                    "prompt": prompt_text,
                    "negative_prompt": str(negative_prompt or "").strip(),
                    "width": int(width),
                    "height": int(height),
                    "seed": seed_value,
                    "batch_size": int(batch_size or 1),
                    "filename_prefix": filename_prefix,
                    "style": str(style or "").strip(),
                },
            )

            prompt_id = self._queue_prompt(rendered_workflow)
            image_ref = self._wait_for_first_image(prompt_id)
            image_bytes = self._download_image_ref(image_ref)

            output_file.parent.mkdir(parents=True, exist_ok=True)
            output_file.write_bytes(image_bytes)
            return str(output_file)
        except Exception as exc:
            self.last_error = str(exc)
            self._log(f"[ComfyUI] Error generando imagen: {exc}")
            return None

    def _resolve_preset(self, preset: Optional[str], width: int, height: int, style: Optional[str]) -> str:
        raw = str(preset or "").strip().lower()
        if raw:
            return self.PRESET_ALIASES.get(raw, raw)

        style_text = str(style or "").strip().lower()
        if "coloring" in style_text or "lineart" in style_text or "line art" in style_text:
            return "coloring_sdxl_lineart"
        if width > height:
            return "thumbnail_16x9_schnell"
        return "historical_vertical_schnell"

    def _load_presets(self) -> dict[str, Any]:
        path = self.workflow_dir / "presets.json"
        if not path.exists():
            return {}
        with open(path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
        if isinstance(payload, dict) and isinstance(payload.get("presets"), dict):
            return payload["presets"]
        return payload if isinstance(payload, dict) else {}

    def _load_workflow(self, preset: str) -> tuple[dict[str, Any], dict[str, Any]]:
        presets = self._load_presets()
        preset_config = presets.get(preset, {}) if isinstance(presets, dict) else {}
        workflow_name = (
            preset_config.get("workflow")
            if isinstance(preset_config, dict)
            else None
        ) or f"{preset}.json"
        workflow_path = self.workflow_dir / str(workflow_name)
        if not workflow_path.exists():
            raise FileNotFoundError(
                f"Workflow ComfyUI no encontrado para preset '{preset}': {workflow_path}. "
                "Exporta un workflow con 'Save/Export (API)' y registra el archivo en comfyui_workflows/presets.json."
            )
        with open(workflow_path, "r", encoding="utf-8") as handle:
            workflow = json.load(handle)
        if not isinstance(workflow, dict):
            raise RuntimeError(f"Workflow invalido: {workflow_path}")
        return workflow, preset_config if isinstance(preset_config, dict) else {}

    def _render_workflow(self, workflow: dict[str, Any], preset_config: dict[str, Any],
                         values: dict[str, Any]) -> dict[str, Any]:
        rendered = self._replace_placeholders(copy.deepcopy(workflow), values)
        field_map = preset_config.get("fields") or {}
        if isinstance(field_map, dict):
            for value_name, target in field_map.items():
                if value_name in values:
                    self._apply_target(rendered, target, values[value_name])
        self._apply_save_image_fallback(rendered, values.get("filename_prefix"))
        return rendered

    def _replace_placeholders(self, value: Any, values: dict[str, Any]) -> Any:
        if isinstance(value, dict):
            return {k: self._replace_placeholders(v, values) for k, v in value.items()}
        if isinstance(value, list):
            return [self._replace_placeholders(item, values) for item in value]
        if isinstance(value, str):
            if value in PLACEHOLDER_VALUES:
                return values.get(PLACEHOLDER_VALUES[value], value)
            result = value
            for placeholder, value_key in PLACEHOLDER_VALUES.items():
                if placeholder in result:
                    result = result.replace(placeholder, str(values.get(value_key, "")))
            return result
        return value

    def _apply_target(self, workflow: dict[str, Any], target: Any, value: Any) -> None:
        if isinstance(target, str):
            parts = [part for part in target.split(".") if part]
            if len(parts) >= 2:
                cursor = workflow
                for part in parts[:-1]:
                    cursor = cursor[part]
                cursor[parts[-1]] = value
            return

        if not isinstance(target, dict):
            return
        node_id = str(target.get("node") or "").strip()
        field = str(target.get("field") or target.get("input") or "").strip()
        path = target.get("path")
        if path:
            self._apply_target(workflow, ".".join([node_id, *path]) if node_id else ".".join(path), value)
            return
        if node_id and field and node_id in workflow:
            workflow[node_id].setdefault("inputs", {})[field] = value

    def _apply_save_image_fallback(self, workflow: dict[str, Any], filename_prefix: Any) -> None:
        if not filename_prefix:
            return
        for node in workflow.values():
            if not isinstance(node, dict):
                continue
            class_type = str(node.get("class_type") or "")
            if "SaveImage" in class_type:
                node.setdefault("inputs", {})["filename_prefix"] = str(filename_prefix)

    def _queue_prompt(self, workflow: dict[str, Any]) -> str:
        payload = {
            "prompt": workflow,
            "client_id": str(uuid.uuid4()),
        }
        response = self.session.post(
            f"{self.base_url}/prompt",
            json=payload,
            timeout=30,
        )
        response.raise_for_status()
        data = response.json() if response.content else {}
        prompt_id = str(data.get("prompt_id") or "").strip()
        if not prompt_id:
            raise RuntimeError(f"ComfyUI no devolvio prompt_id: {data}")
        return prompt_id

    def _wait_for_first_image(self, prompt_id: str) -> dict[str, Any]:
        deadline = time.time() + max(1, self.timeout_seconds)
        history_url = f"{self.base_url}/history/{prompt_id}"
        last_payload = None

        while time.time() < deadline:
            response = self.session.get(history_url, timeout=30)
            response.raise_for_status()
            payload = response.json() if response.content else {}
            last_payload = payload
            prompt_history = payload.get(prompt_id, payload) if isinstance(payload, dict) else {}
            outputs = prompt_history.get("outputs", {}) if isinstance(prompt_history, dict) else {}
            image_ref = self._extract_first_image_ref(outputs)
            if image_ref:
                return image_ref
            time.sleep(max(0.2, self.poll_seconds))

        raise TimeoutError(f"ComfyUI timeout esperando imagen para prompt_id={prompt_id}: {last_payload}")

    @staticmethod
    def _extract_first_image_ref(outputs: Any) -> Optional[dict[str, Any]]:
        if not isinstance(outputs, dict):
            return None
        for node_output in outputs.values():
            if not isinstance(node_output, dict):
                continue
            images = node_output.get("images")
            if isinstance(images, list) and images:
                first = images[0]
                if isinstance(first, dict) and first.get("filename"):
                    return first
        return None

    def _download_image_ref(self, image_ref: dict[str, Any]) -> bytes:
        response = self.session.get(
            f"{self.base_url}/view",
            params={
                "filename": image_ref.get("filename"),
                "subfolder": image_ref.get("subfolder", ""),
                "type": image_ref.get("type", "output"),
            },
            timeout=60,
        )
        response.raise_for_status()
        if not response.content:
            raise RuntimeError(f"ComfyUI devolvio imagen vacia: {image_ref}")
        return response.content

    def _default_output_path(self, preset: str, seed: int) -> str:
        filename = f"comfy_{preset}_{seed}.png"
        return str(PROJECT_DIR / "auto_videos" / "temp" / "comfyui_images" / filename)


__all__ = ["ComfyUiImageClient"]
