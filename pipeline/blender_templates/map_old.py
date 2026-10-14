"""Toma 3D: mapa antiguo extendido sobre una mesa de madera.

La imagen de la escena es el mapa; la camara lo sobrevuela (push/orbit/crane).
Para temas de geografia, imperios y rutas.
"""
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bpy  # noqa: E402
from _scene_common import (  # noqa: E402
    camera_rig, flat, image_material, light, load_params, material, motion_keys,
    noisy, plane, render, setup_scene, wood,
)

params = load_params()
MEDIA = params['images'][0]
FRAMES = int(params['frames'])
VERTICAL = int(params['height']) >= int(params['width'])
scene = setup_scene(params, world_color=(0.012, 0.010, 0.008))

# Mesa de madera oscura.
plane('Table', 14, 14, (0, 0, 0), 0, material('Wood', wood(dark=True)))

# Mapa: la imagen de la escena, envejecida (ligero tinte sepia y bordes).
img = bpy.data.images.load(MEDIA)
mw, mh = (5.6, 4.0) if VERTICAL else (6.4, 4.2)
plane('Map', mw, mh, (0, 0.012, 0), 0, image_material('MapMat', img, 0.42))

# Borde del mapa (marco fino de cuero/piel).
border = material('Leather', flat((0.16, 0.10, 0.05, 1), 0.55))
plane('MapBorder', mw + 0.18, mh + 0.18, (0, 0.008, 0), 0, border)

# Rosa de los vientos: un disco + lineas, en la esquina.
compass_mat = material('Compass', flat((0.82, 0.74, 0.55, 1), 0.35, 0.2))
bpy.ops.mesh.primitive_cylinder_add(radius=0.28, depth=0.006, location=(-mw / 2 + 0.5, mh / 2 - 0.5, 0.02),
                                    rotation=(0, 0, 0), vertices=32)
bpy.context.object.data.materials.append(compass_mat)
for ang in (0, 90, 45, 135):
    line = plane(f'Compass{ang}', 0.46, 0.02, (-mw / 2 + 0.5, mh / 2 - 0.5, 0.024), ang, compass_mat)

# Luz: una lampara calida arriba + un relleno frio.
light(scene, 'Key', 'AREA', 60, (1.0, 0.82, 0.58), (0, 2.0, 3.2), (0, 0.0, 0.0), size=3.0)
light(scene, 'Fill', 'AREA', 25, (0.55, 0.65, 1.0), (2.5, -1.5, 2.8), (0, 0.0, 0.0), size=3.0)

# Camara: sobrevuela el mapa.
center = (0, 0.02, 0)
push = ((1, (0, 4.6, 4.2), (0, 0.02, 0)), (FRAMES, (0, 1.7, 1.9), center))
camera_rig(scene, lens=40 if VERTICAL else 32, fstop=2.0,
           keys=motion_keys(params.get("motion", "push"), FRAMES, center, push))
render()
