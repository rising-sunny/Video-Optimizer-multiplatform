"""Toma 3D: periodico que entra girando, frena sobre la mesa y la camara se acerca al titular.

blender -b --factory-startup -P newspaper.py -- params.json   (mismos params que desk_photos)
images[0] = la portada ya armada (PNG de `pipeline.front_page`).
"""
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bpy  # noqa: E402
from _scene_common import (  # noqa: E402
    action_fcurves, camera_rig, image_material, light, load_params, material, render,
    setup_scene, wood,
)

params = load_params()
FRAMES = int(params['frames'])
VERTICAL = int(params['height']) >= int(params['width'])
scene = setup_scene(params, world_color=(0.004, 0.0035, 0.003))
scene.render.use_motion_blur = True          # el giro se ve como giro, no como saltos
scene.render.motion_blur_shutter = 0.6

bpy.ops.mesh.primitive_plane_add(size=14, location=(0, 0, 0))
bpy.context.object.data.materials.append(material('Desk', wood(dark=True)))

img = bpy.data.images.load(params['images'][0])
iw, ih = img.size
PW = 1.0
PH = PW * ih / max(iw, 1)
# Hoja plana: primitive_grid_add trae el UV invertido (portada boca abajo) y un
# SIMPLE_DEFORM 'BEND' para curvarla doblaba media hoja y la tapaba.
bpy.ops.mesh.primitive_plane_add(size=1, location=(0, 0, 0.02))
page = bpy.context.object
page.scale = (PW, PH, 1)
bpy.ops.object.transform_apply(scale=True)
page.data.materials.append(image_material('Page', img, rough=0.85))

# Giro clasico: entra chica girando tres vueltas, frena y queda casi derecha.
# La camara mira desde +Y: la hoja va girada 180 grados para leerse derecha.
land = max(2, int(FRAMES * 0.55))
page.rotation_euler = (0, 0, math.radians(180 + 3 * 360 + 40))
page.scale = (0.05, 0.05, 0.05)
page.location = (0, 0, 0.35)
for attr in ('rotation_euler', 'scale', 'location'):
    page.keyframe_insert(attr, frame=1)
page.rotation_euler = (0, 0, math.radians(180 - 3))
page.scale = (1, 1, 1)
page.location = (0, 0, 0.02)
for attr in ('rotation_euler', 'scale', 'location'):
    page.keyframe_insert(attr, frame=land)
for curve in action_fcurves(page):
    first = curve.keyframe_points[0]
    first.interpolation = 'EXPO'
    first.easing = 'EASE_OUT'

light(scene, 'Key', 'SPOT', 1400, (1.0, 0.86, 0.68), (-1.0, 1.4, 3.8), (0, 0, 0), size=0.6,
      spot=(math.radians(55), 0.8))
light(scene, 'Fill', 'AREA', 30, (0.6, 0.7, 1.0), (2.0, -2.0, 3.0), (0, 0, 0), size=3.0)

# Quieta mientras gira; despues se acerca al titular (arriba de la hoja = -Y).
headline_y = -PH * 0.22
wide = (0.0, 0.70, 3.55) if VERTICAL else (0.0, 0.55, 2.55)
camera_rig(scene, lens=40 if VERTICAL else 35, fstop=2.8, keys=(
    (1, wide, (0.0, 0.0, 0.0)),
    (land, wide, (0.0, 0.0, 0.0)),
    (FRAMES, (0.0, headline_y + 0.55, 1.75 if VERTICAL else 1.45), (0.0, headline_y, 0.0)),
))
render()
