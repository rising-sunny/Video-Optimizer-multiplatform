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
    sfx_swoosh = apply_echo(AudioSegment.from_file(sfx_paths['swoosh']), delay_ms=250, repeats=1) - 10
    
    # 3. Inyectar inteligentemente según el guion
    print("Inyectando sonidos sincronizados con la narración...")
    for seg in storyboard_data.get('segments', []):
        t_start_ms = int(seg.get('timestamp_start', 0) * 1000)
        text = seg.get('text', '').lower()
        
        # Siempre swoosh en transiciones (inicio de segmento, no en el seg 0 para no tapar el inicio)
        if t_start_ms > 1000:
            master = master.overlay(sfx_swoosh, position=t_start_ms)

    # 4. Exportar y reensamblar
    mixed_audio_path = video_path.replace(".mp4", "_master_mixed.mp3")
    master.export(mixed_audio_path, format="mp3")
    print(f"Pista maestra exportada: {mixed_audio_path}")
    
    final_audio = AudioFileClip(mixed_audio_path)
    final_video = video.set_audio(final_audio)
    
    print("Escribiendo video final con mezcla avanzada...")
    final_video.write_videofile(output_path, codec="libx264", audio_codec="aac", logger=None)
    
    # Cleanup
    if os.path.exists(temp_audio_path): os.remove(temp_audio_path)
    if os.path.exists(mixed_audio_path): os.remove(mixed_audio_path)
    video.close()
    final_video.close()
    
    print(f"Video completado exitosamente: {output_path}")
