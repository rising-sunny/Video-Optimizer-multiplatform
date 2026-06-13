"""TTS voices and subtitle styles reference endpoints."""

from fastapi import APIRouter, Depends, Header
from typing import Optional

from app.dependencies import get_current_user_optional

router = APIRouter()


@router.get("/voices")
async def list_voices(user=Depends(get_current_user_optional)):
    """Return available Edge-TTS voices + ElevenLabs if user has BYOK key."""
    voices = {}

    # 1. Edge-TTS voices (async-native, works in FastAPI)
    try:
        import edge_tts
        edge_voices = await edge_tts.list_voices()
        for v in edge_voices:
            voice_id = v.get("ShortName", "")
            if not voice_id:
                continue
            lang = v.get("Locale", "")
            gender = v.get("Gender", "")
            friendly = v.get("FriendlyName", voice_id)
            # Only include common languages
            if any(lang.startswith(p) for p in ["es-", "en-", "pt-", "fr-", "de-", "it-", "ja-", "ko-", "zh-"]):
                voices[voice_id] = {
                    "id": voice_id,
                    "name": friendly,
                    "language": lang,
                    "gender": gender,
                    "provider": "edge-tts",
                }
    except Exception as e:
        print(f"Edge-TTS voices error: {e}")

    # 2. ElevenLabs voices (only if user has their own BYOK key)
    if user and getattr(user, "elevenlabs_api_key", None):
        try:
            import requests
            resp = requests.get(
                "https://api.elevenlabs.io/v1/voices",
                headers={"xi-api-key": user.elevenlabs_api_key},
                timeout=10,
            )
            if resp.status_code == 200:
                for v in resp.json().get("voices", []):
                    vid = v.get("voice_id", "")
                    name = v.get("name", vid)
                    voices[f"el_{vid}"] = {
                        "id": vid,
                        "name": f"{name} (ElevenLabs)",
                        "language": "multi",
                        "gender": "",
                        "provider": "elevenlabs",
                    }
            elif resp.status_code == 401:
                print("ElevenLabs BYOK key invalid")
        except Exception as e:
            print(f"ElevenLabs voices error: {e}")

    return {"voices": voices}


@router.get("/subtitle-styles")
async def list_subtitle_styles():
    """Return available dynamic subtitle style presets."""
    try:
        from core.dynamic_subtitles_generator import SubtitleStyle

        styles = {}
        for key, style in SubtitleStyle.STYLES.items():
            styles[key] = {
                "name": style.get("name", key),
                "karaoke": style.get("karaoke", False),
                "animation": style.get("animation", "none"),
                "font_size": style.get("font_size", 50),
            }
        return {"styles": styles}
    except Exception as e:
        try:
            from core.video_config import VideoConfig
            return {"styles": VideoConfig.SUBTITLE_STYLES}
        except Exception:
            return {"styles": {}, "error": str(e)}
