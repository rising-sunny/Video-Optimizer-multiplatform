import os
from pydub import AudioSegment
from moviepy.editor import VideoFileClip, AudioFileClip

def apply_echo(audio, delay_ms=400, decay=0.4, repeats=2):
    """Aplica eco simple usando PyDub"""
    echo = audio
    for i in range(1, repeats + 1):
        delayed = audio - (10 * i / decay)
        silence = AudioSegment.silent(duration=delay_ms * i)
        echo = echo.overlay(silence + delayed)
    return echo

def apply_distortion(audio, gain_db=12):
    """Aplica overdrive (clipping natural)"""
    return audio + gain_db

def apply_advanced_sfx_to_video(video_path, storyboard_data, sfx_paths, output_path):
    print("Iniciando mezcla avanzada de audio con PyDub...")
    
    # 1. Extraer audio original (Voz + BGM ya mezclados por el motor)
    video = VideoFileClip(video_path)
    temp_audio_path = video_path.replace(".mp4", "_temp_audio.wav")
    video.audio.write_audiofile(temp_audio_path, logger=None)
    
    # Cargar en PyDub
    master = AudioSegment.from_file(temp_audio_path)
    
    # 2. Cargar y procesar SFX (con los efectos que pidió el usuario)
    print("Aplicando efectos digitales a las pistas (Eco, Distorsion)...")
    sfx_raw = AudioSegment.from_file(sfx_paths['swoosh'])
    # Extract the 300ms peak window to match the Film Burn visual transition
    target_duration_ms = 300
    max_rms = 0
    peak_idx = 0
    chunk_size = 10
    for i in range(0, len(sfx_raw) - chunk_size, chunk_size):
        rms = sfx_raw[i:i+chunk_size].rms
        if rms > max_rms:
            max_rms = rms
            peak_idx = i
            
    start_idx = max(0, peak_idx - target_duration_ms // 2)
    end_idx = start_idx + target_duration_ms
    if end_idx > len(sfx_raw):
        end_idx = len(sfx_raw)
        start_idx = max(0, end_idx - target_duration_ms)
        
    sfx_swoosh = sfx_raw[start_idx:end_idx]
    sfx_swoosh = apply_echo(sfx_swoosh, delay_ms=100, repeats=1) - 4
    
    # 3. Inyectar inteligentemente según el guion
    print("Inyectando sonidos sincronizados con la narración...")
    
    # Manejar ambos formatos (directamente array o anidado en 'storyboard')
    segments = storyboard_data.get('storyboard', {}).get('segments', []) if 'storyboard' in storyboard_data else storyboard_data.get('segments', [])
    current_acc_ms = 0
    for seg in segments:
        t_start_ms = int(seg.get('start', seg.get('timestamp_start', -1)) * 1000)
        if t_start_ms < 0:
            t_start_ms = current_acc_ms
            current_acc_ms += int(seg.get('duration', 4.0) * 1000)
        
        # Siempre swoosh en transiciones (inicio de segmento, no en el seg 0 para no tapar el inicio)
        if t_start_ms > 1000:
            # La transicion visual ocurre exactamente en los 300ms ANTES del inicio de este clip
            transition_start_ms = max(0, t_start_ms - 300)
            master = master.overlay(sfx_swoosh, position=transition_start_ms)

    # 4. Exportar y reensamblar
    mixed_audio_path = video_path.replace(".mp4", "_master_mixed.mp3")
    master.export(mixed_audio_path, format="mp3")
    print(f"Pista maestra exportada: {mixed_audio_path}")
    
    print("Escribiendo video final con mezcla avanzada (via FFmpeg)...")
    video.close()
    import subprocess
    cmd = [
        "ffmpeg", "-y", "-i", video_path, "-i", mixed_audio_path,
        "-c:v", "copy", "-c:a", "aac", "-map", "0:v:0", "-map", "1:a:0",
        output_path
    ]
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    
    # Cleanup
    if os.path.exists(temp_audio_path): os.remove(temp_audio_path)
    if os.path.exists(mixed_audio_path): os.remove(mixed_audio_path)
    
    print(f"Video completado exitosamente: {output_path}")
