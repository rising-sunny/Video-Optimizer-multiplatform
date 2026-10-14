"""Toma 3D: linea de tiempo.

Una linea horizontal con marcas de fechas; la imagen de la escena es una
"tarjeta" colgada en la linea. Para temas con fechas, eras y procesos.
"""
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bpy  # noqa: E402
from _scene_common import (  # noqa: E402
    camera_rig, flat, image_material, light, load_params, material, motion_keys,
    noisy, plane, render, setup_scene, smooth,
)

params = load_params()
MEDIA = params['images'][0]
FRAMES = int(params['frames'])
VERTICAL = int(params['height']) >= int(params['width'])
scene = setup_scene(params, world_color=(0.008, 0.008, 0.011))

# Pared de fondo.
bpy.ops.mesh.primitive_plane_add(size=14, location=(0, 0, -1.5), rotation=(math.radians(90), 0, 0))
bpy.context.object.data.materials.append(
    material('Wall', noisy((0.03, 0.03, 0.05, 1), (0.07, 0.07, 0.10, 1), 40, (6, 1, 1), 0.85)))

# La linea de tiempo (una tira metalica/acuarela horizontal).
line = material('Line', flat((0.62, 0.55, 0.40, 1), 0.4, 0.5))
plane('Timeline', 8.0, 0.03, (0, 0.35, 0.0), 0, line)

# Marcas de fechas: puntos + tics a lo largo de la linea.
tick = material('Tick', flat((0.75, 0.68, 0.5, 1), 0.4, 0.3))
for k in range(-3, 4):
    x = k * 1.1
    bpy.ops.mesh.primitive_uv_sphere_add(radius=0.045, location=(x, 0.35, 0.02))
    obj = bpy.context.object
    obj.data.materials.append(tick)
    smooth(obj)
    plane(f'Tick{k}', 0.012, 0.14, (x, 0.35, 0.0), 0, tick)

# La imagen: una tarjeta colgada sobre la linea.
img = bpy.data.images.load(MEDIA)
cw, ch = (2.6, 1.9) if VERTICAL else (3.0, 2.0)
card = plane('Card', cw, ch, (0, 0.35 + ch / 2 + 0.08, 0.015), 0, image_material('CardMat', img, 0.3))
frame = material('Frame', flat((0.16, 0.13, 0.09, 1), 0.5))
plane('CardFrame', cw + 0.12, ch + 0.12, (0, 0.35 + ch / 2 + 0.08, 0.008), 0, frame)

# Luz.
light(scene, 'Key', 'AREA', 55, (0.85, 0.85, 1.0), (0, 1.2, 2.6), (0, 0.35, 0.0), size=2.5)
light(scene, 'Fill', 'AREA', 18, (0.8, 0.6, 0.4), (-2.2, 0.5, 1.8), (0, 0.35, 0.0), size=2.0)

# Camara: recorre la linea y se queda en la tarjeta.
center = (0, 0.35 + ch / 2 + 0.05, 0.015)
push = ((1, (-3.2, 0.35, 2.8), (0, 0.35, 0.0)), (FRAMES, (0, 0.35 + ch / 2 + 0.05, 1.5), center))
camera_rig(scene, lens=40 if VERTICAL else 34, fstop=2.0,
           keys=motion_keys(params.get("motion", "push"), FRAMES, center, push))
render()
