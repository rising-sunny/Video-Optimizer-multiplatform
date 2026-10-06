"""Use the saved Studio selections when rendering a pilot."""
from infra.project_media_paths import resolve_project_media


def pilot_render_settings(config, profile, root):
    from pipeline.dynamic_subtitle_wrapper import normalize_subtitle_style
    settings = {
        'add_subtitles': config.get('subtitles_enabled', True),
        'subtitle_style': normalize_subtitle_style(config.get('subtitle_style') or profile.get('subtitle_style', 'hormozi')),
        'add_overlays': config.get('overlays_enabled', True),
        'apply_cinematic': config.get('cinematic_enabled', False),
        'cinematic_preset': str(config.get('cinematic_preset') or 'auto').lower(),
        'cinematic_intensity': str(config.get('cinematic_intensity') or 'auto').lower(),
        'dynamism': str(config.get('dynamism') or 'off').lower(),
        'blender_shots': bool(config.get('blender_shots', False)),
        'blender_quality': str(config.get('blender_quality') or 'normal').lower(),
        'transition_type': config.get('transition_type') or profile.get('transition_type', 'Fade Smooth'),
        'transition_duration': config.get('transition_duration', profile.get('transition_duration', 0.3)),
        'enable_transition_sfx': config.get('transition_sfx_enabled', True),
        'transition_sfx_path': config.get('transition_sfx_path'),
        'manual_bgm_metadata': config.get('selected_music_metadata'),
    }
    selected = config.get('selected_music_paths') or ([config['selected_music_path']] if config.get('selected_music_path') else [])
    paths = []
    for value in selected:
        path = resolve_project_media(value, root)
        if not path:
            raise ValueError(f'No se encuentra la pista seleccionada: {value}')
        paths.append(path)
    if paths:
        settings['manual_bgm_paths'] = paths
        settings['manual_bgm_path'] = paths[0]
    return settings
