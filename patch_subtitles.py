with open('daily_short_pipeline.py', 'r', encoding='utf-8') as f:
    text = f.read()

patch = '''    if not generator:
        from auto_video_generator_v2 import AutoVideoGenerator
        generator = AutoVideoGenerator(parent_window=None)

    # RE-PARCHEAR SUBTÍTULOS AQUÍ:
    effective_subtitle = subtitle_style or CHANNEL_CONFIG.get("subtitle_style", "capcut")
    try:
        from dynamic_subtitle_wrapper import patch_subtitle_generation
        patch_subtitle_generation(generator, style_name=effective_subtitle)
    except Exception as e:
        log(f"No se pudieron re-configurar subtítulos dinámicos: {e}", "WARN")'''

text = text.replace('''    if not generator:
        from auto_video_generator_v2 import AutoVideoGenerator
        generator = AutoVideoGenerator(parent_window=None)''', patch)

with open('daily_short_pipeline.py', 'w', encoding='utf-8') as f:
    f.write(text)

print('Added subtitle re-patch')
