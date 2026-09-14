"""FFmpeg region effects, with coordinates relative to the displayed video."""
import json
import math
import subprocess
from pathlib import Path
from uuid import uuid4


def video_size(path):
    result = subprocess.run(
        ['ffprobe', '-v', 'error', '-select_streams', 'v:0', '-show_streams',
         '-of', 'json', str(path)], capture_output=True, check=True, timeout=20)
    stream = json.loads(result.stdout)['streams'][0]
    width, height = int(stream['width']), int(stream['height'])
    rotation = float(stream.get('tags', {}).get('rotate', 0))
    for side in stream.get('side_data_list', []):
        rotation = float(side.get('rotation', rotation))
    if round(rotation) % 180 == 90:
        width, height = height, width
    return width, height


def region_pixels(edit, width, height):
    rect = edit['rect']
    if len(rect) != 4 or not all(math.isfinite(float(v)) for v in rect):
        raise ValueError('Zona inválida.')
    x, y, w, h = map(float, rect)
    if min(x, y) < 0 or min(w, h) <= 0 or x + w > 1.000001 or y + h > 1.000001:
        raise ValueError('La zona debe quedar dentro del video.')
    left, top = int(x * width), int(y * height)
    right, bottom = min(width, math.ceil((x + w) * width)), min(height, math.ceil((y + h) * height))
    if right - left < 4 or bottom - top < 4:
        raise ValueError('Selecciona una zona de al menos 4 × 4 píxeles.')
    return left, top, right - left, bottom - top


def effect_graph(edit, width, height):
    x, y, w, h = region_pixels(edit, width, height)
    mode = edit['mode']
    if mode == 'cover':
        return f'[0:v:0]drawbox=x={x}:y={y}:w={w}:h={h}:color=black:t=fill[vout]'
    if mode == 'blur':
        radius = max(1, min(20, (min(w, h) - 1) // 2))
        return (f'[0:v:0]split[base][patch];[patch]crop={w}:{h}:{x}:{y}:exact=1,'
                f'boxblur=luma_radius={radius}:luma_power=3:chroma_radius=0[blur];'
                f'[base][blur]overlay={x}:{y}[vout]')
    if mode == 'remove':
        if x < 1 or y < 1 or x + w >= width or y + h >= height:
            raise ValueError('Para quitar la marca deja un margen alrededor de la zona; '
                             'si toca el borde, usa cubrir o difuminar.')
        return f'[0:v:0]delogo=x={x}:y={y}:w={w}:h={h}[vout]'
    raise ValueError('Efecto desconocido.')


def preview_frame(path, seconds=0, edit=None):
    args = ['ffmpeg', '-hide_banner', '-loglevel', 'error', '-ss', str(max(0, seconds)), '-i', str(path)]
    if edit:
        graph = effect_graph(edit, *video_size(path)).replace('[vout]', '[effect]')
        args += ['-filter_complex', graph + ';[effect]scale=960:-2[vout]', '-map', '[vout]']
    else:
        args += ['-vf', 'scale=960:-2']
    result = subprocess.run(args + ['-frames:v', '1', '-an', '-f', 'image2pipe', '-vcodec', 'png', 'pipe:1'],
                            capture_output=True, timeout=30)
    if result.returncode or not result.stdout:
        raise RuntimeError(result.stderr.decode('utf-8', 'replace')[-1500:] or 'No se pudo leer el fotograma.')
    return result.stdout


def export_command(source, edit):
    source = Path(source)
    output = source.with_name(source.stem + '_edited_' + uuid4().hex[:10] + '.mp4')
    args = ['-hide_banner', '-loglevel', 'error', '-nostdin', '-n', '-i', str(source),
            '-filter_complex', effect_graph(edit, *video_size(source)), '-map', '[vout]',
            '-map', '0:a?', '-map_metadata', '0', '-c:v', 'libx264', '-preset', 'fast',
            '-crf', '18', '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-movflags', '+faststart', str(output)]
    return args, output
