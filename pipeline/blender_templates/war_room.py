"""Toma 3D: sala de guerra.

Mesa oscura, la imagen como "mapa de operaciones" y alfileres de colores
clavados alrededor. Luz dramatica. Para batallas, guerras y conspiraciones.
"""
import math
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bpy  # noqa: E402
from _scene_common import (  # noqa: E402
    camera_rig, flat, image_material, light, load_params, material, motion_keys,
    noisy, plane, render, setup_scene, smooth, wood,
)

params = load_params()
MEDIA = params['images'][0]
FRAMES = int(params['frames'])
VERTICAL = int(params['height']) >= int(params['width'])
rng = random.Random(int(params.get('seed', 5)))
scene = setup_scene(params, world_color=(0.004, 0.004, 0.006))

# Mesa oscura con vetas.
plane('Table', 14, 14, (0, 0, 0), 0, material('Wood', wood(dark=True)))

# Mapa/plano de operaciones: la imagen de la escena.
img = bpy.data.images.load(MEDIA)
mw, mh = (5.4, 3.8) if VERTICAL else (6.2, 4.0)
plane('Map', mw, mh, (0, 0.012, 0), 0, image_material('MapMat', img, 0.35))

# Alfileres de colores clavados en los bordes del mapa.
pin_colors = ((0.85, 0.12, 0.12, 1), (0.12, 0.12, 0.85, 1), (0.85, 0.75, 0.12, 1))
pin_mat = [material(f'Pin{i}', flat(c, 0.25, 0.4)) for i, c in enumerate(pin_colors)]
positions = [
    (-mw / 2 + 0.55, mh / 2 - 0.45), (mw / 2 - 0.5, mh / 2 - 0.4),
    (0.0, -mh / 2 + 0.5), (mw / 2 - 0.6, -mh / 2 + 0.45), (-mw / 2 + 0.5, -mh / 2 + 0.4),
]
for k, (x, y) in enumerate(positions):
    mat = pin_mat[k % len(pin_mat)]
    bpy.ops.mesh.primitive_uv_sphere_add(radius=0.07, location=(x, y, 0.05))
    head = bpy.context.object
    head.data.materials.append(mat)
    smooth(head)
    bpy.ops.mesh.primitive_cylinder_add(radius=0.012, depth=0.06, location=(x, y, 0.02), vertices=12)
    bpy.context.object.data.materials.append(mat)

# Lampara de trabajo (luz calida y dura) + un relleno tenue.
light(scene, 'Lamp', 'SPOT', 220, (1.0, 0.86, 0.6), (0, 2.6, 3.0), (0, 0.0, 0.0), size=0.3, spot=(0.9, 0.3))
light(scene, 'Rim', 'AREA', 15, (0.6, 0.7, 1.0), (-2.0, -1.5, 2.5), (0, 0.0, 0.0), size=2.0)

# Camara.
center = (0, 0.02, 0)
push = ((1, (0.3, 4.4, 3.6), (0, 0.02, 0)), (FRAMES, (0, 1.5, 1.7), center))
camera_rig(scene, lens=38 if VERTICAL else 30, fstop=1.8,
           keys=motion_keys(params.get("motion", "push"), FRAMES, center, push))
render()
