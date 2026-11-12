"""Generate the explicitly requested pair with the existing renderer and QA."""
import argparse
import contextlib
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sys
import time

from history_data import CHANNELS, PLATFORMS, atomic, read, timestamp
from generation_service import STATE, JOBS, valid_batch, safe_error

AUTOMATION = Path('/home/videoagent/video-automation')
SOURCE_HASHES = {'runner.py': '3746cb10296bdff378d1ab026be1102795052c6ab450187bd71c039bdf73d9e2', 'daily_core.py': '896a24a21c67966f3cb889c776b6a238a7b3be3eb2fd7719f4565d7c56d5907b', 'daily_remote.py': 'd0edd530d9929d516f3f2c96079daf4245cacbc144e3c39eebaa9eea5e196a51', 'editorial.py': 'f09de5bf5817611dbb802f02e65af7f4a733a4a2c5ce58039a905e0309b012ec', 'render_adapter.py': '3f88cff95be05f808796d1361b78fcc22c7a3b20b9f6d6ee8a8cb1b31c9d41bf', 'music_provider.py': '8f7cf5719f0494186ac27eea5bc81eb60077159c4346246a7c323bd01a53ce13', 'epidemic_mcp.py': 'd0e28e4bd91a0d10e8dab9f77c7c1fd10a2dc587ae6128c23400a814c7c2f699'}
DIRECTOR = '''
MANUAL CATARSIS DIRECTOR BRIEF: This is an on-demand GENERATION-ONLY request.
Create a 50-59 second English portrait short, no narration. Use the existing
Catarsis language: psychological tension, large brief text cards, isolated words,
archival imagery, deliberate hard cuts and a meaningful quiet break before an
ending that lingers. Text is an expressive visual element, not a paragraph of
subtitles. Alternate short cards and longer image holds while respecting every
readability/duration rule above. Supported card style="word" or "center" and
kinetic=true may be used. Use the current Catarsis style profile for transitions and sound design.
Keep contextual labels visible and the complete archival frame readable.
Do not use Evangelion footage, AI media, feature-film stills, invented dialogue,
or invented thoughts attributed to real people. Rhetorical cards must not add
unsupported factual claims. Use the current style profile for visual variety; clips remain optional.
If no clip qualifies, create an IMAGES-ONLY montage; do not block for that alone.
Every URL cited by a claim MUST ALSO appear literally in research, including
Commons file pages when used as evidence. All claims still need real support.
Keep complete source/asset/music credits. Preserve the photographer spelling from
the specific asset source; do not unify similar surnames across different records.
Search for licensed alternatives when
a proposed asset is unusable. Never relax evidence, licenses, QA or review.
Keep base descriptions/captions under 400 characters, without source URLs or
licensing boilerplate: the controller appends full factual sources and credits.
YouTube title <=100 UTF-16 units; description with full credits <=5000 UTF-8 bytes.
YouTube tags have an API ceiling of 500 units including commas and quotes
around spaced tags. For compatibility with the native publisher use at most
480 such units (local reserve), preferably a short list of relevant tags.
Use a short Facebook title <=100 units and description <=2200 units (our local
delivery profile). Instagram caption <=2200 units including all credits; use at
most 5 hashtags and 20 mentions (conservative local profile). No angle brackets
in YouTube title/description. Keep complete credits and revise promotional text
before rendering if necessary. These are separate from thumbnail image layout.
The controller assigns a unique manual marker. Never publish or schedule anything.
'''


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        while block := f.read(1024 * 1024):
            h.update(block)
    return h.hexdigest()


def preflight(root=AUTOMATION):
    for name, expected in SOURCE_HASHES.items():
        if sha(root / name) != expected:
            raise RuntimeError('generation_source_changed')
    ready = read(root / 'runtime/production/readiness.json')
    checks = ready.get('checks')
    if not isinstance(checks, dict) or not checks or not all(v is True for v in checks.values()):
        raise RuntimeError('generation_readiness_failed')
    hashes = ready.get('code_sha256')
    if not isinstance(hashes, dict) or not hashes:
        raise RuntimeError('generation_readiness_hashes_missing')
    for name, expected in hashes.items():
        path = (root / name).resolve()
        if not path.is_relative_to(root) or sha(path) != expected:
            raise RuntimeError('generation_readiness_source_changed')
    if not (root / 'runtime/production/PAUSED').exists():
        raise RuntimeError('daily_automation_pause_missing')
    for binary in ('ffmpeg', 'ffprobe', 'bwrap', 'codex'):
        if not shutil.which(binary):
            raise RuntimeError('generation_dependency_missing')


def native_history(payload):
    if payload.get('complete') is not True or len(payload.get('sources', {})) != 8 or any(s.get('status') != 'available' for s in payload['sources'].values()):
        raise RuntimeError('generation_history_incomplete')
    result = dict(checked_at=payload['finished_at'], complete=True, channels={})
    for channel in CHANNELS:
        result['channels'][channel] = {}
        for platform in PLATFORMS:
            result['channels'][channel][platform] = [dict(id=x['id'], title=x['title'],
                description=x['text'], caption=x['text'], published_at=x['published_at'],
                created_time=x['published_at'], timestamp=x['published_at'],
                privacy=x['visibility']) for x in payload['channels'][channel][platform]]
    return result


def recoverable(code):
    return code.startswith(('youtube_', 'facebook_', 'instagram_', 'platform_metadata_')) or code in {'unsupported_claim', 'two_real_images_required', 'too_many_assets',
        'invalid_asset_type', 'duration_outside_contract', 'invalid_scene', 'text_too_dense',
        'source_collection_and_provider_credit_required', 'contextual_material_unlabelled',
        'attribution_incomplete', 'asset_host_or_size_rejected', 'unsupported_asset_type',
        'asset_too_large', 'source_clip_too_short', 'sharealike_visual_with_subscription_music_requires_review',
        'promotional_text_contains_protected_material', 'promotional_text_requires_editorial_shortening',
        'full_credits_exceed_platform_limit', 'credits_would_be_truncated',
        'source_http_403', 'source_http_404', 'thumbnail_text_requires_editorial_shortening'} or code.startswith('unsupported_or_noncommercial_license_')


def diagnostic(folder, code):
    if code.startswith('codex_'):
        for path in folder.glob('*-events.jsonl'):
            if path.is_symlink() or not re.fullmatch(r'(?:editorial-plan(?:-repair-[12]|-adapt-[1-6](?:-format)?|-images-only|-resume-review)?|visual-review)-events\.jsonl', path.name):
                continue
            with path.open('rb') as f:
                f.seek(max(0, path.stat().st_size - 1048576))
                for line in f.read(1048576).decode('utf-8', errors='replace').splitlines():
                    try:
                        event = json.loads(line)
                    except ValueError:
                        continue
                    if not isinstance(event, dict):
                        continue
                    if event.get('type') not in ('error', 'turn.failed'):
                        continue
                    value = json.dumps(event).casefold()
                    if any(term in value for term in ('usage limit', 'quota exceeded', 'insufficient_quota')):
                        return 'ai_usage_limit'
                    if any(term in value for term in ('not logged in', 'authentication required', 'unauthorized')):
                        return 'ai_authentication_required'
    if code.startswith('epidemic_'):
        return 'music_provider_requires_attention'
    if code == 'visual_or_editorial_review_failed':
        return 'quality_review_rejected'
    return code


def public_metadata(value):
    fields = {'youtube': ('title', 'description', 'tags'),
              'facebook': ('title', 'description'), 'instagram': ('caption',)}
    return {platform: {key: value[platform][key] for key in keys} for platform, keys in fields.items()}


@contextlib.contextmanager
def manual_editorial(editorial, folder, batch, channel, day, guard, recovery=None):
    invoke, write, fit = editorial.invoke, editorial.atomic, editorial.fit_promotional_text
    from deepseek_editor import Router
    from codex_budget import bind
    routed_invoke = Router(bind(invoke), folder, batch, getattr(editorial, 'Blocked', RuntimeError))
    from catarsis_style import VERSION
    style_file = folder / 'style-profile.json'
    use_style = style_file.exists()
    if use_style and read(style_file).get('version') != VERSION:
        raise RuntimeError('style_profile_binding_mismatch')
    marker = 'VO:manual:' + batch + ':' + channel
    old_marker = 'VO:' + day + ':' + channel
    import platform_rules as rules
    from editorial_recovery import Recovery
    recovery = recovery or Recovery(folder, guard)
    validator = getattr(editorial, 'validate_plan', None)
    def checked_plan(plan, *args, **kwargs):
        result = validator(plan, *args, **kwargs)
        import catarsis_style
        try:
            if use_style: catarsis_style.validate(plan)
        except RuntimeError as exc: raise editorial.Blocked(str(exc)) from None
        try: rules.validate_base_plan(plan)
        except rules.PlatformViolation as exc: raise editorial.Blocked(str(exc)) from None
        return result
    def call(directory, prompt, output, *args, **kwargs):
        recovery.guard()
        kwargs["timeout"] = min(kwargs.get("timeout",1200), recovery.timeout(review=Path(output).name=="visual-review.json"))
        if Path(output).name == "editorial-plan.json":
            (folder / "editor-recovery-brief.txt").write_text(prompt)
        if Path(output).stem.startswith('editorial-plan'):
            from catarsis_style import BRIEF
            prompt += DIRECTOR + (BRIEF if use_style else '')
        if Path(output).name == 'visual-review.json':
            if getattr(recovery, 'before_agent', None):
                qa = read(folder / 'qa.json')
                if (not isinstance(qa, dict) or qa.get('technical_checks_passed') is not True
                        or qa.get('sha256') != sha(folder / 'video.mp4')):
                    raise editorial.Blocked('qa_missing_failed_or_hash_mismatch')
            try: report = rules.preflight(folder, require_review=False)
            except rules.PlatformViolation as exc: raise editorial.Blocked(str(exc)) from None
            write(folder / 'platform-preflight.json', report)
            from catarsis_style import REVIEW_BRIEF, EVIDENCE
            prompt += rules.POLICY_BRIEF
            from review_guidance import brief
            prompt += brief()
            from review_consistency import BRIEF as VERDICT_BRIEF
            prompt += VERDICT_BRIEF
            if use_style:
                if not (folder / EVIDENCE).is_file():
                    raise editorial.Blocked('style_render_evidence_missing')
                prompt += REVIEW_BRIEF
                images = kwargs.get('images', [])
                if not isinstance(images, list): images = list(images)
                if folder / 'style-transitions.jpg' not in images: images.append(folder / 'style-transitions.jpg')
                kwargs['images'] = images
        if Path(output).name == 'visual-review.json':
            from review_cache import lookup
            cached=lookup(folder,kwargs.get('images',()))
            if cached is not None:
                guard()
                write(folder/'visual-review.json',cached)
                return cached
        import catarsis_fixes
        import editor_efficiency
        prompt, kwargs, context = editor_efficiency.prepare(folder, prompt, output, kwargs)
        context['event_before'] = editor_efficiency.event_signature(folder, output)
        before_agent = getattr(recovery, 'before_agent', None)
        after_agent = getattr(recovery, 'after_agent', None)
        if Path(output).stem.startswith('editorial-plan') and (folder/'job.json').is_file():
            from shorts_media import build as prepare_catalog
            prepare_catalog(folder,guard)
        frozen = before_agent(output) if before_agent else None
        started = time.monotonic()
        try:
            from shorts_handoff import controller_sources
            with controller_sources(folder) as source_writes:
                try:
                    if context['mode'] == 'local_copy':
                        # Native JSON/event validation still applies. The general
                        # full-plan handoff contract does not fit a one-field edit.
                        result = routed_invoke(directory, prompt, output, *args, **kwargs)
                    else:
                        result = catarsis_fixes.invoke(editorial, routed_invoke, directory, prompt, output, *args, **kwargs)
                finally:
                    if after_agent:
                        after_agent(output, source_writes.reconcile(frozen))
            result = editor_efficiency.finish(result, context)
            if context['mode'] == 'local_copy':
                write(Path(directory) / output, result)
        finally:
            editor_efficiency.measure(folder, output, context, time.monotonic()-started)
        if Path(output).name == 'visual-review.json':
            from review_consistency import normalize_verdict
            result=normalize_verdict(folder,result,sha(folder/'video.mp4'),write)
            try: rules.validate_review(result)
            except rules.PlatformViolation as exc: raise editorial.Blocked(str(exc)) from None
            if result.get('recommendation')=='block':
                raise editorial.Blocked('visual_or_editorial_review_failed')
            if before_agent:
                from autonomous_generation import VISUAL_CHECKS
                if (result.get('approved') is not True or set(result.get('checks', {})) != VISUAL_CHECKS
                        or any(result['checks'][key] is not True for key in VISUAL_CHECKS)):
                    raise editorial.Blocked('visual_or_editorial_review_failed')
            from review_cache import save
            save(folder,kwargs.get('images',()),result)
        guard()
        return result
    def promotional(text, suffix, limit):
        from catarsis_fixes import credit_suffix
        suffix = credit_suffix(folder, suffix)
        from catarsis_style import compact_suffix
        if use_style: suffix = compact_suffix(folder, suffix)
        from music_credit_changes import for_job
        suffix = for_job(folder, suffix, channel)
        if suffix.endswith(old_marker):
            suffix = suffix[:-len(old_marker)] + marker
        from caption_policy import compact_suffix as concise_suffix
        suffix = concise_suffix(folder,suffix)
        try: return recovery.fit(text, suffix, limit)
        except rules.PlatformViolation as exc: raise editorial.Blocked(str(exc)) from None
    def store(path, value):
        path = Path(path)
        if path.parent == folder and path.name == 'metadata.json':
            if value.get('marker') != old_marker or any(not value[n][k].endswith(marker)
                    for n, k in (('youtube', 'description'), ('facebook', 'description'), ('instagram', 'caption'))):
                raise RuntimeError('manual_metadata_marker_mismatch')
            value = dict(value, marker=marker)
            from caption_policy import for_job
            value = for_job(folder,value)
            try: rules.validate_metadata(value)
            except rules.PlatformViolation as exc: raise editorial.Blocked(str(exc)) from None
        return write(path, value)
    original_external = getattr(editorial, 'external', None)
    original_asset = getattr(editorial, '_acquire_asset', None)
    music_module = getattr(editorial, 'mp', None)
    original_catalogue = getattr(music_module, 'catalogue', None)
    def fetched(url, *args, **kwargs):
        try: return recovery.external(original_external, url, *args, **kwargs)
        except Exception as exc:
            if type(exc).__name__ in ('ReadTimeout','ConnectTimeout','ConnectionError','ChunkedEncodingError'):
                raise editorial.Blocked('source_transport_error') from None
            raise
    def acquired_asset(directory, plan, index, asset):
        from shorts_media import acquire
        def verified(d,p,i,a):return acquire(original_asset,Path(d),p,i,a,guard)
        return recovery.acquire_asset(verified, directory, plan, index, asset)
    def stable_catalogue(directory, selected_channel, topic):
        key=(str(Path(directory)),selected_channel,topic)
        if key not in recovery.catalogue_cache:
            recovery.catalogue_cache[key]=original_catalogue(directory,selected_channel,topic)
        else: music_module.rights(selected_channel)
        return recovery.catalogue_cache[key]
    original_thumbnails = getattr(editorial, 'thumbnails', None)
    prepare_media = getattr(editorial, 'prepare_media', None)
    daily = getattr(editorial, 'd', None)
    render_project = getattr(daily, 'render_project', None)
    def acquired(*args, **kwargs):
        plan, media, credits = prepare_media(*args, **kwargs)
        from catarsis_fixes import asset_credits
        credits = asset_credits(plan, credits)
        write(folder / 'asset-credits.json', credits)
        return plan, media, credits
    def rendered(*args, **kwargs):
        from catarsis_fixes import multiline_cards
        from catharsis import catharsis_editor
        from catarsis_style import renderer
        with multiline_cards(catharsis_editor), rules.encoder_profile(catharsis_editor), (renderer(catharsis_editor, folder) if use_style else contextlib.nullcontext()):
            return render_project(*args, **kwargs)
    editorial.invoke, editorial.atomic, editorial.fit_promotional_text = call, store, promotional
    if validator is not None: editorial.validate_plan = checked_plan
    if original_external is not None: editorial.external = fetched
    if original_asset is not None: editorial._acquire_asset = acquired_asset
    if original_catalogue is not None: music_module.catalogue = stable_catalogue
    if original_thumbnails is not None:
        from catarsis_fixes import thumbnails
        def fitted_thumbnail(*args, **kwargs):
            try: return thumbnails(*args, **kwargs)
            except RuntimeError as exc: raise editorial.Blocked(str(exc)) from None
        editorial.thumbnails = fitted_thumbnail
    if prepare_media is not None: editorial.prepare_media = acquired
    if render_project is not None: daily.render_project = rendered
    try:
        yield
    finally:
        editorial.invoke, editorial.atomic, editorial.fit_promotional_text = invoke, write, fit
        if validator is not None: editorial.validate_plan = validator
        if original_external is not None: editorial.external = original_external
        if original_asset is not None: editorial._acquire_asset = original_asset
        if original_catalogue is not None: music_module.catalogue = original_catalogue
        if original_thumbnails is not None: editorial.thumbnails = original_thumbnails
        if prepare_media is not None: editorial.prepare_media = prepare_media
        if render_project is not None: daily.render_project = render_project


def build(editorial, folder, channel, day, topic, batch, guard, *, recovery=None, prepare=None):
    from workflow_native import implementation
    editorial = implementation(editorial)
    from autonomous_generation import Supervisor, build as supervised_build
    recovery = recovery or Supervisor(folder, guard)
    with manual_editorial(editorial, folder, batch, channel, day, guard, recovery=recovery):
        return supervised_build(editorial, folder, channel, day, topic, recovery, recoverable, prepare=prepare)


def perform(batch):
    folder = STATE / batch
    request = read(folder / 'request.json')
    from catarsis_selection import task_channels
    selected = task_channels(request, CHANNELS)
    if request.get('batch_id') != batch or request.get('publication_allowed') is not False:
        raise RuntimeError('invalid_generation_task')
    # A durable claim also protects direct CLI execution against replay.
    with (folder / 'claimed').open('x') as claim:
        claim.write(timestamp())
        claim.flush()
        os.fsync(claim.fileno())
    def guard():
        if (folder / 'STOP').exists():
            raise RuntimeError('generation_cancelled')
    guard()
    preflight()
    # Freeze request, native/connector sources and daily controls for the full
    # supervised execution. Automatic correction never alters these controls.
    from publication_service import controls
    control_pins = controls()
    request_pin = sha(folder / 'request.json')
    module_names = ('workflow_common.py','workflow_jobs.py','workflow_native.py','workflow_recovery.py','workflow_service.py','catarsis_selection.py','generation_service.py','shorts_handoff.py','shorts_handoff_resume.py','documentary_sources.py','generation_worker.py', 'autonomous_generation.py', 'editorial_recovery.py',
        'catarsis_fixes.py', 'platform_rules.py', 'music_credit_changes.py', 'credit_repair.py', 'catarsis_style.py', 'editor_efficiency.py', 'claude_editor.py', 'codex_budget.py', 'caption_policy.py', 'review_guidance.py', 'review_consistency.py', 'review_cache.py', 'deepseek_runtime.py', 'deepseek_editor.py', 'deepseek_review.py', 'documentary_media.py','shorts_media.py','shorts_resume.py','shorts_context_resume.py','shorts_curated_resume.py','curated_short_plans.py')
    module_pins = {name: sha(Path(__file__).with_name(name)) for name in module_names}
    def guard():
        if (folder / 'STOP').exists():
            raise RuntimeError('generation_cancelled')
        if sha(folder / 'request.json') != request_pin:
            raise RuntimeError('autonomy_request_changed')
        if controls() != control_pins:
            raise RuntimeError('autonomy_controls_changed')
        if any(sha(Path(__file__).with_name(name)) != value for name, value in module_pins.items()):
            raise RuntimeError('autonomy_source_changed')
        preflight()
    guard()
    sys.path.insert(0, str(AUTOMATION))
    import daily_core as core
    import daily_remote as remote
    import editorial
    import music_provider
    from helpers import daily
    if CHANNELS[1] in selected:
        if not music_provider.configured(CHANNELS[1]):
            raise RuntimeError('epidemic_configuration_required_for_revelations')
        music_provider.rights(CHANNELS[1])
    status = read(folder / 'status.json')
    status.update(state='running', updated_at=timestamp())
    atomic(folder / 'status.json', status)
    with daily.locked():
        from history_worker import collect
        history = collect(remote)
        core.atomic(AUTOMATION / 'runtime/production/history.json', native_history(history))
        for channel in selected:
            guard()
            job = JOBS / batch / channel
            job.mkdir(parents=True, exist_ok=False)
            core.atomic(job / 'job.json', dict(date=request['date'], channel=channel,
                topic=request['topics'][channel], scope='production', manual_batch=batch,
                generation_only=True, publication_allowed=False))
            from catarsis_style import VERSION
            core.atomic(job / 'style-profile.json', dict(version=VERSION))
            status['channels'][channel] = dict(state='preparing', error_code=None)
            status['updated_at'] = timestamp()
            atomic(folder / 'status.json', status)
            try:
                build(editorial, job, channel, request['date'], request['topics'][channel], batch, guard)
                approved = core.approval(job, channel, request['date'])
                if approved.get('scope') != 'production':
                    raise RuntimeError('manual_quality_scope_mismatch')
                files = {}
                for kind, name in (('video', 'video.mp4'), ('thumbnail', 'thumbnail.jpg')):
                    path = job / name
                    info = path.stat()
                    files[kind] = dict(size=info.st_size, mtime_ns=info.st_mtime_ns,
                                       ctime_ns=info.st_ctime_ns, sha256=sha(path))
                status['channels'][channel] = dict(state='ready', error_code=None, files=files,
                    metadata=public_metadata(core.load(job / 'metadata.json')),
                    approval_sha256=sha(job / 'approval.json'))
            except Exception as exc:
                code = safe_error(exc)
                core.atomic(job / 'blocked.json', dict(at=timestamp(), phase='manual_generation', reason=code))
                try:
                    detail = diagnostic(job, code)
                except (OSError, ValueError, TypeError, AttributeError):
                    detail = code
                status['channels'][channel] = dict(state='blocked', error_code=code, diagnostic=detail)
            status['updated_at'] = timestamp()
            atomic(folder / 'status.json', status)
    ready = sum(x.get('state') == 'ready' for x in status['channels'].values())
    status.update(state='ready' if ready == len(selected) else 'partial' if ready else 'blocked', updated_at=timestamp())
    atomic(folder / 'status.json', status)


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser()
    parser.add_argument('--batch', required=True)
    parser.add_argument('--repair-known-batch', action='store_true')
    parser.add_argument('--repair-thumbnail-batch', action='store_true')
    parser.add_argument('--repair-editor-batch', action='store_true')
    parser.add_argument('--repair-pendleton-credits', action='store_true')
    parser.add_argument('--repair-claude-service', action='store_true')
    parser.add_argument('--repair-claude-continuation', action='store_true')
    parser.add_argument('--clean-captions', action='store_true')
    parser.add_argument('--correct-review', action='store_true')
    parser.add_argument('--resolve-review', action='store_true')
    parser.add_argument('--resolve-saved-reviews',action='store_true')
    parser.add_argument('--prepare-saved-pair',action='store_true')
    parser.add_argument('--review-saved-pair',action='store_true')
    parser.add_argument('--resume-curated-pair',action='store_true')
    parser.add_argument('--resume-catalog-context',action='store_true')
    parser.add_argument('--resume-verified-media',action='store_true')
    parser.add_argument('--resume-saved-handoffs',action='store_true')
    parser.add_argument('--finish-saved-pair', action='store_true')
    args = parser.parse_args()
    batch = args.batch
    if not valid_batch(batch):
        raise SystemExit(2)
    # No API credentials, signed audio URLs or raw agent logs reach the journal.
    with open(os.devnull, 'w') as sink, contextlib.redirect_stdout(sink), contextlib.redirect_stderr(sink):
        try:
            if args.finish_saved_pair:
                from shorts_finish import perform as repair
                repair(batch)
            elif args.resume_saved_handoffs:
                from shorts_handoff_resume import perform as repair
                repair(batch)
            elif args.resolve_saved_reviews:
                from shorts_review_resolution import perform as repair
                repair(batch)
            elif args.prepare_saved_pair or args.review_saved_pair:
                from shorts_saved_resume import perform as repair
                repair(batch,review=args.review_saved_pair)
            elif args.resume_curated_pair:
                from shorts_curated_resume import perform as repair
                repair(batch)
            elif args.resume_catalog_context:
                from shorts_context_resume import perform as repair
                repair(batch)
            elif args.resume_verified_media:
                from shorts_resume import perform as repair
                repair(batch)
            elif args.resolve_review:
                from review_resolution import perform as repair
                repair(batch)
            elif args.correct_review:
                from review_correction import perform as repair
                repair(batch)
            elif args.clean_captions:
                from caption_cleanup import perform as repair
                repair(batch)
            elif args.repair_claude_continuation:
                from claude_continuation import perform as repair
                repair(batch)
            elif args.repair_claude_service:
                from claude_service_repair import perform as repair
                repair(batch)
            elif args.repair_pendleton_credits:
                from credit_repair import perform as repair
                repair(batch)
            elif args.repair_editor_batch:
                from adaptive_repair import perform as repair
                repair(args.batch)
            elif args.repair_thumbnail_batch:
                from thumbnail_repair import perform as repair
                repair(batch)
            elif args.repair_known_batch:
                from repair_controller import perform as repair
                repair(batch)
            else:
                perform(batch)
        except Exception as exc:
            path = STATE / batch / 'status.json'
            value = read(path)
            value.update(state='blocked', error_code=safe_error(exc), updated_at=timestamp())
            atomic(path, value)


if __name__ == '__main__':
    main()
