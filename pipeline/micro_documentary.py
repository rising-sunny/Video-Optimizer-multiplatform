"""Packaging-first pilot workflow, sharing the existing media/assembly pipeline.

Generation stops at a reviewable manifest by default. Approved manifests are
reused verbatim when scripting; a resume never silently regenerates packaging.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import uuid
from pathlib import Path

from channel.channel_profiles import active_channel, load_profile

UNCERTAINTY = {"established_fact", "scholarly_interpretation", "plausible_hypothesis", "disputed_claim", "unknown"}

# Las clases de certeza viven en el array `claims`. El LLM las FILTRABA a la
# narracion hablada como "(established fact)" -- el TTS las leia en voz alta y
# ademas les metia 0.7s de pausa, lo que desfasaba los subtitulos proporcionales
# desde cada parentesis hasta el fin del segmento (2026-09-10, Gunnerside).
_CERTAINTY_LABEL_RE = re.compile(
    r"\s*[\(\[]\s*(?:established\s+fact|scholarly\s+interpretation|plausible\s+hypothesis|"
    r"disputed\s+claim|unknown|hecho\s+establecido|interpretaci[oó]n\s+acad[eé]mica|"
    r"hip[oó]tesis\s+plausible|afirmaci[oó]n\s+disputada)\s*[\)\]]",
    re.IGNORECASE,
)


def find_certainty_labels(text: str):
    """Etiquetas de certeza que se colaron en el texto hablado."""
    return [m.group(0).strip() for m in _CERTAINTY_LABEL_RE.finditer(str(text or ""))]


def strip_certainty_labels(text: str) -> str:
    """Saca las etiquetas y deja la puntuacion prolija.

    '...output (established fact).' -> '...output.'
    """
    limpio = _CERTAINTY_LABEL_RE.sub("", str(text or ""))
    limpio = re.sub(r"\s+([.,;:!?])", r"\1", limpio)   # sin espacio antes del signo
    return re.sub(r"\s{2,}", " ", limpio).strip()
METRICS = ["impressions", "ctr_percent", "views", "organic_views", "retention_10s_percent", "retention_30s_percent", "retention_60s_percent", "average_view_duration_seconds", "average_percentage_viewed", "watch_hours"]
FORBIDDEN = ("welcome back", "today we are going to explore", "throughout history", "in this video")


def resolve_image_provider(value):
    text = str(value or 'flux_dev').strip().lower()
    if text.startswith('manual'):
        return 'manual'
    if 'stability' in text:
        return 'stability_core' if 'core' in text else 'stability_ultra'
    if 'comfy' in text:
        return text if text in ('comfy_dev', 'comfy_schnell', 'comfy_sdxl') else ('comfy_schnell' if 'schnell' in text else 'comfy_dev')
    if 'recraft' in text:
        return 'recraft'
    if 'schnell' in text:
        return 'flux_schnell'
    return text if text in ('flux_dev', 'auto', 'google_ai') else 'flux_dev'


def missing_manual_visuals(storyboard, out):
    missing = []
    for index, segment in enumerate(storyboard.get('segments', []), 1):
        ready = False
        for key in ('video_path', 'image_path'):
            value = segment.get(key)
            if value and not (key == 'image_path' and segment.get('image_deleted')):
                path = Path(value)
                if not path.is_absolute():
                    path = Path(out) / path
                if path.is_file():
                    ready = True
                    break
        if not ready:
            missing.append(index)
    return missing


def write_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    temp.replace(path)


def runtime_plan(seconds=270, wpm=120):
    if not math.isfinite(seconds) or not 210 <= seconds <= 330:
        raise ValueError("Microdocumentary target must be between 210 and 330 seconds")
    if not math.isfinite(wpm) or not 60 <= wpm <= 240:
        raise ValueError("Effective narration WPM must be between 60 and 240")
    return {"target_runtime_seconds": seconds, "effective_wpm": wpm,
            "word_budget": round(seconds * wpm / 60), "min_seconds": 210, "max_seconds": 330}


def estimate(text, wpm=120):
    return len(text.split()) * 60 / wpm


def _json_generate(client, prompt):
    correction = ''
    for attempt in range(3):
        raw = client._generate(prompt + correction + "\nReturn ONLY one complete JSON object, no markdown. Escape quotes inside strings.",
                               max_tokens=8192, task_type="script_quality", json_mode=True)
        if not raw:
            break  # The client's provider/model fallback has already been exhausted.
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", str(raw).strip(), flags=re.IGNORECASE)
        try:
            data = json.loads(text)
            if not isinstance(data, dict):
                raise ValueError('Expected a JSON object')
            return data
        except (json.JSONDecodeError, ValueError) as exc:
            print(f'[Microdoc] JSON incompleto o inválido (intento {attempt + 1}/3): {exc}')
            correction = ('\nThe previous response was malformed or truncated. Regenerate the COMPLETE object from the original instructions. '
                          'Use concise visual prompts, keep the requested narration word budget, and close all strings and arrays. '
                          'Do not continue a partial JSON fragment.')
    raise RuntimeError('El modelo no pudo devolver un JSON completo después de los intentos de recuperación. '
                       'La propuesta guardada se conserva. Puedes volver a intentar crear el guion.')


def title_score(title):
    """Observable heuristics only; semantic truthfulness needs editorial review."""
    words = title.split()
    generic = any(p in title.lower() for p in ("explained", "history of", "uncovering", "secrets of", "everything you need"))
    readable = 1 <= len(title) <= 75 and 3 <= len(words) <= 14
    return {"heuristic_score": 50 * int(readable) + 50 * int(not generic),
            "scored_dimensions": ["readability", "non_generic"], "readability": readable,
            "non_generic": not generic,
            "clarity": "editorial_review", "curiosity": "editorial_review",
            "historical_specificity": "editorial_review", "tension": "editorial_review",
            "truthfulness": "source_review_required"}


def validate_packaging(data, wpm=120):
    errors = []
    titles = data.get("title_variants", [])
    thumbs = data.get("thumbnail_variants", [])
    if not isinstance(titles, list) or len(titles) < 3 or any(not isinstance(t, str) or not t.strip() for t in titles) or len(set(titles)) < 3:
        errors.append("At least three distinct titles are required")
    if not isinstance(thumbs, list) or len(thumbs) < 3:
        errors.append("At least three thumbnail concepts are required")
    else:
        for t in thumbs:
            if not isinstance(t, dict) or not t.get("prompt") or len(str(t.get("text", "")).split()) > 4:
                errors.append("Each thumbnail needs a prompt and at most four text words")
    if data.get("selected_title") not in titles:
        errors.append("Selected title must be one of the variants")
    if data.get("selected_thumbnail_concept") not in thumbs:
        errors.append("Selected thumbnail must be one of the variants")
    hook = str(data.get("hook", ""))
    if not 5 <= estimate(hook, wpm) <= 10:
        errors.append("Hook must take 5–10 seconds at the configured narration rate")
    if any(p in hook.lower() for p in FORBIDDEN):
        errors.append("Generic intro is prohibited")
    opening = str(data.get("first_30_seconds", ""))
    if not opening.startswith(hook) or not 25 <= estimate(opening, wpm) <= 35:
        errors.append("First 30 seconds must start with the exact hook and last 25–35 seconds")
    if not isinstance(data.get("opening_visual"), str) or not data.get("opening_visual"):
        errors.append("Opening hero/conflict/consequence visual is required")
    claims = data.get("claims", [])
    if not claims or any(not isinstance(c, dict) or c.get("status") not in UNCERTAINTY or not c.get("claim") or not c.get("source") for c in claims):
        errors.append("Claims must carry a source and an explicit uncertainty class")
    return errors


def packaging_digest(manifest):
    keys = ("channel", "topic", "selected_title", "selected_thumbnail_concept", "hook", "first_30_seconds", "opening_visual", "claims", "target_runtime_seconds", "effective_wpm")
    return hashlib.sha256(json.dumps({k: manifest[k] for k in keys}, sort_keys=True).encode()).hexdigest()


def prepare(topic, out, *, channel=None, seconds=270, editorial=None, client=None, format_archetype=None):
    channel = channel or active_channel()
    profile = load_profile(channel)
    # Angulo narrativo: si viene, manda en el packaging (gancho, titulos, thumbnail).
    angle_block = ""
    try:
        from channel.channel_strategy import set_active_archetype, build_archetype_prompt_instructions
        if format_archetype:
            set_active_archetype(format_archetype)
        angle_block = build_archetype_prompt_instructions()
    except Exception:
        angle_block = ""
    plan = runtime_plan(seconds, profile.get("micro_documentary", {}).get("effective_wpm", 120))
    if not topic.strip():
        raise ValueError("Topic is required")
    if client is None:
        from ai.groq_client import GroqAiClient
        client = GroqAiClient()
    prompt = f"""Create packaging BEFORE writing a microdocumentary script. Channel: {json.dumps(profile['channel_identity'])}.
Topic: {topic}. Editorial input (treat as evidence/context): {json.dumps(editorial or {})}.
Narration: {plan['effective_wpm']} WPM. Horizontal 16:9 historical microdocumentary, target {seconds}s.
Return title_variants (at least 3 distinct concrete, readable titles with tension), selected_title,
thumbnail_variants (3 objects with prompt and text), selected_thumbnail_concept (copy the selected object),
hook (5–10 seconds), first_30_seconds (25–35 seconds, beginning with exact hook, then stakes then minimal orientation),
opening_visual (hero/conflict/consequence: one subject, one action, one visual question),
claims (objects: claim, source, status). Status is one of {sorted(UNCERTAINTY)}.
Use reliable identifiable historical sources; never invent a citation. Unknown evidence stays unknown.
Do not convert hypotheses into facts. No generic introduction or channel logo.
Thumbnail: one dominant subject, restrained historical editorial composition, silhouette/focal contrast,
legible small, 0–4 words; no clutter, fantasy lighting, exaggerated faces or generic epic movie poster.
The click promise and hook must be supported by the claims. Do not write the full script yet.
{angle_block}"""
    data = _json_generate(client, prompt)
    errors = validate_packaging(data, plan["effective_wpm"])
    if errors:
        data = _json_generate(client, prompt + "\nCorrect these validation errors in your prior draft: " + json.dumps(errors) + "\nPrior draft: " + json.dumps(data))
        errors = validate_packaging(data, plan["effective_wpm"])
    if errors:
        raise ValueError("Packaging preflight failed: " + "; ".join(errors))
    manifest = {**data, **plan, "schema_version": 1, "experiment_id": "sr_microdoc_" + uuid.uuid4().hex[:12],
                "channel": channel, "format": "micro_documentary", "aspect_ratio": "16:9", "topic": topic,
                "editorial": editorial or {}, "topic_source": (editorial or {}).get("trend_source"),
                "topic_signal": (editorial or {}).get("trend_signal"), "publish_date": None,
                "youtube_video_id": None, "metrics": dict.fromkeys(METRICS),
                "status": "awaiting_editorial_review", "approval": None,
                "title_scores": {t: title_score(t) for t in data['title_variants']},
                "preflight": {"structural_errors": [], "historical_accuracy": "human_source_review_required"}}
    write_json(Path(out) / "experiment.json", manifest)
    return manifest


def make_storyboard(manifest, client, *, diagnostics_dir=None):
    wpm = manifest["effective_wpm"]
    errors = validate_packaging(manifest, wpm)
    if errors:
        raise ValueError("Invalid approved packaging: " + "; ".join(errors))
    opening = ' '.join(manifest['first_30_seconds'].split())
    hook = ' '.join(manifest['hook'].split())
    opening_words = opening.split()
    remaining_opening = opening_words[len(hook.split()):]
    locked_segments = [{'text': hook, 'visual_prompt': manifest['opening_visual'], 'visual_class': 'conflict'}]
    for i in range(0, len(remaining_opening), 25):
        locked_segments.append({'text': ' '.join(remaining_opening[i:i + 25]),
            'visual_prompt': manifest['opening_visual'] + '. Show the stakes or consequence, one dominant subject, historical realism, horizontal 16:9, no text.',
            'visual_class': 'consequence'})
    plan = runtime_plan(manifest['target_runtime_seconds'], wpm)
    body_words = plan['word_budget'] - len(opening_words)
    prompt = f"""Write the REMAINDER of a compact historical microdocumentary in English.
Approved editorial package: {json.dumps(manifest)}.
Return an object with segments: an array of objects with text, visual_prompt, visual_class.
The approved first_30_seconds are already fixed and will be inserted by the application.
DO NOT repeat, rewrite or include the hook or first_30_seconds in your response. Continue immediately after them.
Then essential setup to 1:00; escalation to about 3:30; resolution/consequence; concise meaning/close.
Write about {body_words} spoken words in YOUR response. Together with the {len(opening_words)} fixed opening words,
the completed video should be near {manifest['target_runtime_seconds']} seconds at {wpm} WPM.
Each segment 10–35 words. No repeated paragraphs, no filler, no headings in narration, no CTA or generic intro.
Preserve the source-supported certainty levels of the claims THROUGH THE WORDING ("historians believe", "the evidence suggests"). NEVER write the status label itself into the narration: no "(established fact)", "(disputed claim)" or similar -- those live only in the claims array and would be read aloud by the narrator. Do not add unsupported dramatic facts.
Each visual is horizontal 16:9, historical editorial realism, no text or watermarks.
First 30s use the approved opening visual then conflict/consequence/scale/evidence; orientation comes after stakes.
Later visual_class can also be orientation. Deliver a complete ending; never pad to duration."""
    reason = ""
    attempts = []
    reasons = []
    for _ in range(3):
        data = _json_generate(client, prompt + reason)
        segments = data.get("segments", [])
        if not segments or any(not isinstance(s, dict) or not isinstance(s.get("text"), str) or not s.get("visual_prompt") for s in segments):
            reasons = ['La respuesta contiene segmentos vacíos o sin descripción visual.']
            reason = "\nPrevious response had invalid segments. Return nonempty text and visual_prompt for every segment."
            attempts.append({'errors': reasons, 'draft': data})
            continue
        # Accept a full-script response only when it contains the exact approved
        # opening; remove that copy before inserting the canonical opening.
        generated = ' '.join(' '.join(s['text'].split()) for s in segments)
        if generated.startswith(opening):
            skip = len(opening_words)
            body = []
            for segment in segments:
                words = segment['text'].split()
                if skip >= len(words):
                    skip -= len(words)
                    continue
                body.append({**segment, 'text': ' '.join(words[skip:])})
                skip = 0
            segments = body
        segments = [dict(s) for s in locked_segments] + segments
        # Si el modelo filtro etiquetas de certeza a la narracion, se sacan:
        # son metadata del array `claims`, no texto para leer en voz alta.
        etiquetas_filtradas = []
        for seg in segments:
            halladas = find_certainty_labels(seg.get("text", ""))
            if halladas:
                etiquetas_filtradas.extend(halladas)
                seg["text"] = strip_certainty_labels(seg["text"])
        if etiquetas_filtradas:
            print("[Microdoc] Etiquetas de certeza sacadas de la narracion: "
                  + ", ".join(sorted(set(etiquetas_filtradas))))
        full = " ".join(s["text"].strip() for s in segments)
        duration = estimate(full, wpm)
        reasons = []
        if not 210 <= duration <= 330 or abs(duration - manifest["target_runtime_seconds"]) > 25:
            reasons.append(f"Duración estimada: {duration:.1f}s ({len(full.split())} palabras); objetivo: {manifest['target_runtime_seconds']}s ({plan['word_budget']} palabras), tolerancia ±25s.")
        if len({s['text'].strip() for s in segments}) != len(segments):
            reasons.append("Hay segmentos de narración repetidos.")
        if any(p in full[:200].lower() for p in FORBIDDEN):
            reasons.append("La apertura contiene una introducción genérica prohibida.")
        attempts.append({'errors': reasons, 'word_count': len(full.split()), 'estimated_runtime_seconds': duration, 'draft': data})
        if not reasons:
            break
        print('[Microdoc] Revisión del guion: ' + '; '.join(reasons))
        reason = ("\nCorrections: " + '; '.join(reasons) + f"\nReturn ONLY the body, aiming for {body_words} words. "
                  f"Adjust spoken length by approximately {plan['word_budget'] - len(full.split()):+d} words. Preserve a complete ending."
                  + "\nPrevious response: " + json.dumps(data))
    else:
        if diagnostics_dir:
            write_json(Path(diagnostics_dir) / 'script_preflight.json', {'passed': False, 'attempts': attempts})
        message = 'El guion no superó la revisión después de tres intentos. ' + '; '.join(reasons)
        if diagnostics_dir:
            message += ' La propuesta sigue guardada; el detalle está en script_preflight.json.'
        raise ValueError(message)
    if diagnostics_dir:
        write_json(Path(diagnostics_dir) / 'script_preflight.json', {'passed': True, 'attempts': attempts})
    cursor = 0.0
    for i, segment in enumerate(segments, 1):
        length = estimate(segment['text'], wpm)
        segment.update(segment_id=i, narration_text=segment['text'], assigned_filename=f"seg_{i:03d}",
                       chapter="Story", start=cursor, start_time=cursor, end=cursor + length,
                       end_time=cursor + length, duration=length, sfx_tag="none", overlay_tag="none")
        if cursor < 30:
            segment['visual_prompt'] = (manifest['opening_visual'] + ". " if i == 1 else "One dominant subject, conflict or consequence. ") + segment['visual_prompt']
        cursor += length
    return {"topic": manifest['topic'], "channel_profile": manifest['channel'], "format_strategy": "micro_documentary",
            "storyboard_format": "long_form_16_9", "platform": "youtube_long", "video_format": "16:9",
            "aspect_ratio": "16:9", "language": "en", "category": "history", "script": full,
            "segments": segments, "target_duration_min": manifest['target_runtime_seconds'] / 60,
            "status": "storyboard_ready", "experiment_id": manifest['experiment_id']}


def build(topic, out, *, channel=None, seconds=270, editorial=None, approve=False, assemble=False, client=None, image_provider=None, format_archetype=None):
    out = Path(out).resolve()
    path = out / "experiment.json"
    channel = channel or active_channel()
    if path.exists():
        manifest = json.loads(path.read_text(encoding="utf-8"))
        if manifest['topic'] != topic or manifest['channel'] != channel:
            raise ValueError("Existing pilot belongs to a different topic/channel; choose a new output directory")
    else:
        existing_project_path = out / 'project.json'
        existing_project = json.loads(existing_project_path.read_text(encoding='utf-8')) if existing_project_path.exists() else {}
        existing_config = existing_project.get('config', {})
        matching_empty_draft = (existing_config.get('topic') == topic and existing_config.get('channel_profile') == channel
                                and not (existing_project.get('storyboard') or {}).get('segments'))
        if (out / 'storyboard.json').exists() or (existing_project_path.exists() and not matching_empty_draft):
            raise ValueError('This folder already contains another project; choose an empty pilot folder')
        manifest = prepare(topic, out, channel=channel, seconds=seconds, editorial=editorial, client=client, format_archetype=format_archetype)
        # Approval must refer to packaging the user has already seen.
        return {"status": "awaiting_editorial_review", "output_dir": str(out), "manifest": manifest}
    if not approve:
        return {"status": "awaiting_editorial_review", "output_dir": str(out), "manifest": manifest}
    if client is None:
        from ai.groq_client import GroqAiClient
        client = GroqAiClient()
    digest = packaging_digest(manifest)
    errors = validate_packaging(manifest, manifest['effective_wpm'])
    runtime_plan(manifest['target_runtime_seconds'], manifest['effective_wpm'])
    if errors:
        raise ValueError('; '.join(errors))
    sb_path = out / 'storyboard.json'
    project_path = out / 'project.json'
    project = json.loads(project_path.read_text(encoding='utf-8')) if project_path.exists() else {}
    image_provider = resolve_image_provider(image_provider or project.get('config', {}).get('image_provider'))
    if sb_path.exists() and (manifest.get('approval') or {}).get('packaging_sha256') == digest:
        sb = project.get('storyboard') or json.loads(sb_path.read_text(encoding='utf-8'))
        script = ' '.join(s['text'] for s in sb['segments'])
        if sb.get('experiment_id') != manifest['experiment_id'] or not ' '.join(script.split()).startswith(' '.join(manifest['first_30_seconds'].split())):
            raise ValueError('Saved storyboard no longer matches the approved pilot opening')
        if not 210 <= estimate(script, manifest['effective_wpm']) <= 330:
            raise ValueError('Edited script is outside the pilot runtime guardrails')
        sb['script'] = script
    else:
        sb = make_storyboard(manifest, client, diagnostics_dir=out)
    manifest['approval'] = {"packaging_sha256": digest, "source_review": "operator_approved"}
    sb['_project_path'] = str(out)
    manifest.update(script_word_count=len(sb['script'].split()), estimated_runtime_seconds=estimate(sb['script'], manifest['effective_wpm']), status="storyboard_ready")
    write_json(path, manifest)
    write_json(out / "storyboard.json", sb)
    metadata = {"title": manifest['selected_title'], "description": sb['script'], "tags": [topic],
                "topic": topic, "script_excerpt": sb['script'][:4000], "is_short": False, "channel_profile": channel}
    write_json(out / "youtube_metadata.json", metadata)
    write_json(out / "metadata.json", metadata)
    project.setdefault('config', {}).update({"topic": topic, "channel_profile": channel, "format_strategy": "micro_documentary", "platform_key": "youtube", "video_format": "16:9", "duration": round(manifest['target_runtime_seconds']), "language": "en"})
    project['storyboard'] = sb
    project['config']['image_provider'] = {
        'manual': 'Manual (Gratuito)', 'flux_dev': 'FAL - Flux dev (calidad)',
        'flux_schnell': 'FAL - Flux schnell (rapido)', 'recraft': 'Recraft AI',
        'comfy_dev': 'ComfyUI - FLUX Dev (alta calidad)', 'comfy_schnell': 'ComfyUI - FLUX Schnell',
        'stability_core': 'Stability AI - Core (~$0.003)', 'stability_ultra': 'Stability AI - Ultra (~$0.008)',
    }.get(image_provider, image_provider)
    project.setdefault('progress', {}).update(storyboard_done=True)
    write_json(project_path, project)
    video = None
    if assemble:
        if image_provider == 'manual':
            missing = missing_manual_visuals(sb, out)
            if missing:
                raise ValueError('Modo manual: faltan imágenes o videos en los segmentos ' + ', '.join(map(str, missing)) + '. Usa Cargar en Studio para agregarlos; no se generarán imágenes automáticamente.')
        from infra.project_media_paths import prepare_existing_media, resolve_project_media
        if image_provider == 'manual':
            prepare_existing_media(sb, out)
        config = project.get('config') or {}
        if config.get('selected_music_path'):
            music = resolve_project_media(config['selected_music_path'], out)
            if not music:
                raise ValueError('No se encuentra la música seleccionada; revisa su archivo antes de ensamblar.')
            sb['_manual_bgm_path'] = music
        else:
            sb.pop('_manual_bgm_path', None)
            sb.pop('music_data', None)
        from pipeline.long_form_builder import _run_tts
        from pipeline.daily_short_pipeline import generate_images_for_draft, assemble_video, save_storyboard
        profile = load_profile(channel)
        cfg = profile.get('tts', {})
        audio = _run_tts(sb, out, {"voice": cfg.get('default_voice', 'en-US-GuyNeural'), "voice_rate": cfg.get('rate', '+5%')}, [{"title": "Story"}])
        if not audio:
            raise RuntimeError("Real narration is required before microdocumentary assembly")
        actual = sb['segments'][-1]['end']
        manifest['actual_narration_seconds'] = actual
        write_json(path, manifest)
        save_storyboard(out, sb)
        if not 210 <= actual <= 330:
            raise ValueError(f"Actual narration {actual:.1f}s is outside 210–330s; revise before rendering")
        if image_provider != 'manual':
            sb, _ = generate_images_for_draft(out, sb, image_provider=image_provider, visual_style=profile.get('visual_style', 'Photorealism'), platform='youtube_long')
        save_storyboard(out, sb)
        from studio.pilot_render_settings import pilot_render_settings
        settings = pilot_render_settings(config, profile, out)
        video = assemble_video(
            sb, out, image_provider='manual' if image_provider == 'manual' else 'auto',
            video_provider='none', pregenerate_images=False, strict_existing_visuals=True,
            platform='youtube_long', subtitle_style=settings['subtitle_style'],
            visual_style=profile.get('visual_style', 'Photorealism'),
            transition_type=settings['transition_type'], transition_duration=settings['transition_duration'],
            assembly_options=settings)

        if not video:
            raise RuntimeError("Microdocumentary assembly did not produce a video")
        manifest.update(status="assembled", video_path=str(video))
        import subprocess
        probe = subprocess.run(['ffprobe', '-v', 'error', '-show_entries', 'format=duration:stream=width,height', '-of', 'json', str(video)], capture_output=True, text=True, check=True)
        media = json.loads(probe.stdout)
        actual_video = float(media['format']['duration'])
        visual = next(s for s in media['streams'] if s.get('width'))
        if not 210 <= actual_video <= 330 or abs(visual['width'] / visual['height'] - 16 / 9) > 0.02:
            manifest['status'] = 'render_preflight_failed'
            write_json(path, manifest)
            raise ValueError('Rendered video failed runtime or 16:9 validation')
        manifest['actual_video_seconds'] = actual_video
        write_json(path, manifest)
        project_path = out / 'project.json'
        project = json.loads(project_path.read_text(encoding='utf-8'))
        project.update(storyboard=sb, video_path=str(video), generated_video_data={'video_path': str(video), 'audio_path': sb.get('audio_path'), 'segments': sb['segments'], 'topic': topic, 'duration': actual_video})
        project.setdefault('progress', {}).update(storyboard_done=True, images_generated=True, video_assembled=True)
        write_json(project_path, project)
    return {"status": manifest['status'], "output_dir": str(out), "storyboard_path": str(out / 'storyboard.json'), "project_path": str(out / 'project.json'), "video_path": str(video) if video else None, "manifest": manifest}
