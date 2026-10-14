"""Toma 3D: fotos sobre una mesa, camara que baja hasta la protagonista.

Corre DENTRO de Blender (no importar desde la app):

    blender -b --factory-startup -P desk_photos.py -- params.json

params.json (lo arma `pipeline.blender_shots`):
    images          rutas; la primera es la protagonista (donde termina la camara)
    frames, fps     duracion de la toma
    width, height   tamano final del video (la escala la decide resolution_pct)
    resolution_pct  % de render (se reescala con FFmpeg despues)
    samples         muestras de EEVEE
    out_dir         carpeta de los PNG (f_0001.png, ...)
    seed            variacion de la disposicion

Escribe RENDER_TIME <segundos> al terminar, para que la app lo registre.
"""
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bpy  # noqa: E402
from _scene_common import (  # noqa: E402
    camera_rig, image_material, light, load_params, material, motion_keys, paper_material,
    photo_size, plane, render, setup_scene, wood,
)

params = load_params()
IMAGES = [p for p in params['images'] if os.path.exists(p)]
FRAMES = int(params['frames'])
VERTICAL = int(params['height']) >= int(params['width'])
rng = random.Random(int(params.get('seed', 7)))
scene = setup_scene(params, world_color=(0.012, 0.010, 0.009))

plane('Table', 10, 12, (0, 0, 0), 0, material('Wood', wood()))
paper = paper_material()

# La protagonista va en el origen y ARRIBA de la pila; las demas alrededor.
# La camara mira desde +Y hacia -Y, por eso las fotos van giradas 180 grados.
SLOTS = [(-0.95, 0.80), (0.90, 1.00), (-1.05, -0.55), (1.00, -0.45), (0.05, 1.70), (-0.15, -1.45)]
placements = [(IMAGES[0], 1.0, (0.0, 0.0), rng.uniform(-6, 6))] if IMAGES else []
for idx, path in enumerate(IMAGES[1:len(SLOTS) + 1]):
    sx, sy = SLOTS[idx]
    placements.append((path, rng.uniform(0.78, 0.95),
                       (sx + rng.uniform(-0.12, 0.12), sy + rng.uniform(-0.10, 0.10)),
                       rng.uniform(-14, 14)))

for order, (path, longest, (x, y), rot) in enumerate(reversed(placements)):
    img = bpy.data.images.load(path)
    w, h = photo_size(img, longest)
    z = 0.004 + order * 0.003
    border = 0.05 * max(w, h)
    plane(f'Border{order}', w + 2 * border, h + 2 * border, (x, y, z), rot + 180, paper)
    plane(f'Photo{order}', w, h, (x, y, z + 0.0012), rot + 180, image_material(f'Photo{order}', img))

light(scene, 'Key', 'AREA', 260, (1.0, 0.82, 0.62), (-2.0, 1.6, 2.6), (0.4, -0.3, 0.0), size=2.2)
light(scene, 'Fill', 'AREA', 40, (0.55, 0.65, 1.0), (2.5, -2.0, 3.0), (0.0, 0.0, 0.0), size=4.0)

# Arranca abierta, mirando las fotos de arriba, y baja hasta encuadrar a la protagonista.
end = ((0.05, 1.28, 1.50), (0.0, 0.02, 0.0)) if VERTICAL else ((0.05, 1.25, 1.45), (0.0, 0.02, 0.0))
push = ((1, (0.15, 2.95, 2.35), (0.05, 1.05, 0.0)), (FRAMES, end[0], end[1]))
camera_rig(scene, lens=40 if VERTICAL else 32, fstop=1.6,
           keys=motion_keys(params.get("motion", "push"), FRAMES, end[1], push))
render()
