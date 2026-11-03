"""Toma 3D: TV de tubo en un cuarto oscuro que reproduce el video (o la foto) de la escena.

blender -b --factory-startup -P crt_tv.py -- params.json   (mismos params que desk_photos)
images[0] = el medio de la pantalla. Si es un video, `blender_shots` ya lo dejo en
el tramo con movimiento y al largo de la toma: aca se reproduce cuadro a cuadro.
La camara se acerca desde el cuarto hasta la pantalla.
"""
import math
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bpy  # noqa: E402
from _scene_common import (  # noqa: E402
    camera_rig, flat, light, load_params, material, motion_keys, noisy, orbit_keys, render, setup_scene,
    smooth,
)

params = load_params()
MEDIA = params['images'][0]
FRAMES = int(params['frames'])
rng = random.Random(int(params.get('seed', 5)))
scene = setup_scene(params, world_color=(0.003, 0.003, 0.004))


def box(name, size, loc, mat, bevel=0.0):
    bpy.ops.mesh.primitive_cube_add(size=1, location=loc)
    obj = bpy.context.object
    obj.name = name
    obj.scale = size
    obj.data.materials.append(mat)
    if bevel:
        bpy.ops.object.transform_apply(scale=True)
        mod = obj.modifiers.new('Bevel', 'BEVEL')
        mod.width, mod.segments = bevel, 3
        smooth(obj)
    return obj


def cylinder(name, radius, depth, loc, rot, mat):
    bpy.ops.mesh.primitive_cylinder_add(radius=radius, depth=depth, location=loc, vertices=32)
    obj = bpy.context.object
    obj.name = name
    obj.rotation_euler = tuple(math.radians(a) for a in rot)
    obj.data.materials.append(mat)
    smooth(obj)
    return obj


# Cuarto: piso, pared con empapelado, mueble.
bpy.ops.mesh.primitive_plane_add(size=12, location=(0, 0, 0))
bpy.context.object.data.materials.append(
    material('Floor', noisy((0.02, 0.012, 0.008, 1), (0.07, 0.04, 0.02, 1), 3, (1, 12, 1), 0.45)))
bpy.ops.mesh.primitive_plane_add(size=12, location=(0, 1.3, 3), rotation=(math.radians(90), 0, 0))
bpy.context.object.data.materials.append(
    material('Wall', noisy((0.06, 0.05, 0.035, 1), (0.11, 0.09, 0.06, 1), 40, (6, 1, 1), 0.85)))
furniture = material('Wood', noisy((0.05, 0.028, 0.014, 1), (0.13, 0.075, 0.035, 1), 3, (1, 10, 1), 0.4))
box('Cabinet', (1.6, 0.7, 0.72), (0, 0.55, 0.36), furniture, bevel=0.02)

# Televisor: caja con biseles, pantalla 4:3 a la izquierda, perillas a la derecha.
box('TV', (1.08, 0.78, 0.84), (0, 0.55, 1.14), material('Plastic', flat((0.16, 0.11, 0.07, 1), 0.35)), bevel=0.06)
SX, SZ, SW, SH = -0.1, 1.15, 0.70, 0.525
bpy.ops.mesh.primitive_plane_add(size=1, location=(SX, 0.155, SZ), rotation=(math.radians(90), 0, 0))
bpy.context.object.scale = (SW + 0.08, SH + 0.08, 1)
bpy.context.object.data.materials.append(material('Bezel', flat((0.01, 0.01, 0.01, 1), 0.3)))

img = bpy.data.images.load(MEDIA)
is_movie = img.source == 'MOVIE'


def screen(nt, b):
    """Imagen emisiva + lineas de barrido + vineta del tubo + un poco de reflejo de vidrio."""
    nodes, link = nt.nodes, nt.links.new
    tex = nodes.new('ShaderNodeTexImage')
    tex.image = img
    if is_movie:
        tex.image_user.frame_duration = img.frame_duration
        tex.image_user.use_cyclic = True
        tex.image_user.use_auto_refresh = True
    coord = nodes.new('ShaderNodeTexCoord')
    wave = nodes.new('ShaderNodeTexWave')
    wave.wave_type = 'BANDS'
    wave.bands_direction = 'Y'
    wave.inputs['Scale'].default_value = 90.0
    scan = nodes.new('ShaderNodeMapRange')
    scan.inputs['To Min'].default_value = 0.55
    scan.inputs['To Max'].default_value = 1.0
    link(coord.outputs['UV'], wave.inputs['Vector'])
    link(wave.outputs['Fac'], scan.inputs['Value'])
    grad = nodes.new('ShaderNodeTexGradient')
    grad.gradient_type = 'SPHERICAL'
    centre = nodes.new('ShaderNodeMapping')
    centre.inputs['Location'].default_value = (-0.5, -0.5, 0)
    centre.inputs['Scale'].default_value = (1.35, 1.35, 1)
    link(coord.outputs['UV'], centre.inputs['Vector'])
    link(centre.outputs['Vector'], grad.inputs['Vector'])
    vig = nodes.new('ShaderNodeMapRange')
    vig.inputs['From Max'].default_value = 0.6
    vig.inputs['To Min'].default_value = 0.25
    link(grad.outputs['Fac'], vig.inputs['Value'])
    tint = nodes.new('ShaderNodeHueSaturation')
    tint.inputs['Saturation'].default_value = 0.75
    link(tex.outputs['Color'], tint.inputs['Color'])
    shade = nodes.new('ShaderNodeMath')
    shade.operation = 'MULTIPLY'
    link(scan.outputs['Result'], shade.inputs[0])
    link(vig.outputs['Result'], shade.inputs[1])
    mix = nodes.new('ShaderNodeMixRGB')
    mix.blend_type = 'MULTIPLY'
    mix.inputs['Fac'].default_value = 1.0
    link(tint.outputs['Color'], mix.inputs['Color1'])
    link(shade.outputs['Value'], mix.inputs['Color2'])
    emit = nodes.new('ShaderNodeEmission')
    emit.inputs['Strength'].default_value = 1.5
    link(mix.outputs['Color'], emit.inputs['Color'])
    b.inputs['Base Color'].default_value = (0, 0, 0, 1)
    b.inputs['Roughness'].default_value = 0.12
    add = nodes.new('ShaderNodeAddShader')
    link(emit.outputs['Emission'], add.inputs[0])
    link(b.outputs['BSDF'], add.inputs[1])
    link(add.outputs['Shader'], nodes['Material Output'].inputs['Surface'])


bpy.ops.mesh.primitive_grid_add(x_subdivisions=24, y_subdivisions=18, size=1, location=(SX, 0.14, SZ),
                                rotation=(math.radians(90), 0, 0))
scr = bpy.context.object
scr.scale = (SW, SH, 1)
scr.data.materials.append(material('Screen', screen))
cast = scr.modifiers.new('Bulge', 'CAST')    # la panza del tubo
cast.factor, cast.use_z = 0.25, False

metal = material('Knob', flat((0.55, 0.5, 0.42, 1), 0.3, 1.0))
for kz in (1.30, 1.10, 0.92):
    cylinder(f'Knob{kz}', 0.045, 0.05, (0.38, 0.14, kz), (90, 0, 0), metal)
bpy.ops.mesh.primitive_plane_add(size=1, location=(0.38, 0.155, 0.72), rotation=(math.radians(90), 0, 0))
bpy.context.object.scale = (0.18, 0.16, 1)
bpy.context.object.data.materials.append(
    material('Grill', noisy((0.02, 0.02, 0.02, 1), (0.08, 0.07, 0.06, 1), 200, (1, 1, 1), 0.6)))
chrome = material('Chrome', flat((0.8, 0.8, 0.8, 1), 0.15, 1.0))
for ang in (-28, 28):
    cylinder(f'Antenna{ang}', 0.008, 0.9, (ang * 0.006, 0.6, 1.95), (0, ang, 0), chrome)

# La luz de la pantalla bana el cuarto y titila como una TV de verdad.
glow = light(scene, 'ScreenGlow', 'AREA', 45, (0.70, 0.82, 1.0), (SX, 0.05, SZ), (SX, -3.0, 1.0), size=0.75)
for frame in range(1, FRAMES + 1, 3):
    glow.energy = rng.uniform(30, 52)
    glow.keyframe_insert('energy', frame=frame)
light(scene, 'Lamp', 'POINT', 35, (1.0, 0.62, 0.30), (2.2, -0.6, 1.7), (0, 0, 0), size=0.2)
light(scene, 'Rim', 'AREA', 20, (1.0, 0.75, 0.5), (-1.8, 1.0, 2.6), (0, 0.5, 1.1), size=1.0)

center = (SX, 0.14, SZ)
push = ((1, (0.75, -3.4, 1.45), (0.0, 0.5, 1.0)), (FRAMES, (SX, -0.95, SZ + 0.02), center))
# La orbita por defecto de _scene_common (media vuelta, radio 2.2) saca la camara del cuarto por detras de la
# pared (y=1.3) desde ~37 % de la toma y el resto sale NEGRO (visto el 2026-11-02 en la VPS, con Blender 4.5 y 5.1).
# Aca orbita solo por el frente: de la izquierda a la derecha del televisor, siempre dentro del cuarto.
motion = params.get("motion", "push")
keys = (orbit_keys(FRAMES, center, radius=2.2, phases=0.32, start_angle=-2.4) if motion == "orbit"
        else motion_keys(motion, FRAMES, center, push))
camera_rig(scene, lens=35, fstop=2.2, keys=keys)
render()
