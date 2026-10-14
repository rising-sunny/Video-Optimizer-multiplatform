"""Toma 3D: tablero de evidencias. Corcho, fotos con chinches e hilo rojo trenzado.

blender -b --factory-startup -P corkboard.py -- params.json   (mismos params que desk_photos)
La camara sigue el hilo desde una foto hasta la protagonista (images[0]).

Lo que lo hace creible (y por eso necesita calidad Normal o mas: en Borrador el hilo
fino sale serruchado): corcho con granos y relieve, chinches con sombreado suave,
capa brillante y aguja hundida, hilo de algodon con trenzado real en la silueta.
"""
import math
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bpy  # noqa: E402
from mathutils import Vector  # noqa: E402
from _scene_common import (  # noqa: E402
    camera_rig, flat, image_material, light, load_params, material, motion_keys,
    paper_material, photo_size, plane, render, set_inputs, setup_scene, smooth,
)

params = load_params()
IMAGES = [p for p in params['images'] if os.path.exists(p)]
FRAMES = int(params['frames'])
VERTICAL = int(params['height']) >= int(params['width'])
rng = random.Random(int(params.get('seed', 11)))
scene = setup_scene(params, world_color=(0.006, 0.005, 0.004), shadow_quality=True)


def cork(nt, b):
    """Granos (voronoi ~6 mm), variacion de tono grande y relieve."""
    n, link = nt.nodes, nt.links.new
    coord = n.new('ShaderNodeTexCoord')
    grains = n.new('ShaderNodeTexVoronoi')
    grains.inputs['Scale'].default_value = 430.0
    patches = n.new('ShaderNodeTexNoise')
    patches.inputs['Scale'].default_value = 5.0
    patches.inputs['Detail'].default_value = 6.0
    fuzz = n.new('ShaderNodeTexNoise')
    fuzz.inputs['Scale'].default_value = 900.0
    for tex in (grains, patches, fuzz):
        link(coord.outputs['Object'], tex.inputs['Vector'])
    tone = n.new('ShaderNodeRGBToBW')
    link(grains.outputs['Color'], tone.inputs['Color'])
    mix_a = n.new('ShaderNodeMath')
    mix_a.operation = 'MULTIPLY'
    mix_a.inputs[1].default_value = 0.65
    link(tone.outputs['Val'], mix_a.inputs[0])
    mix_b = n.new('ShaderNodeMath')
    mix_b.operation = 'MULTIPLY_ADD'
    mix_b.inputs[1].default_value = 0.35
    link(patches.outputs['Fac'], mix_b.inputs[0])
    link(mix_a.outputs['Value'], mix_b.inputs[2])
    ramp = n.new('ShaderNodeValToRGB')
    ramp.color_ramp.elements[0].color = (0.17, 0.09, 0.035, 1)
    ramp.color_ramp.elements[1].color = (0.50, 0.32, 0.16, 1)
    ramp.color_ramp.elements.new(0.5).color = (0.33, 0.19, 0.085, 1)
    link(mix_b.outputs['Value'], ramp.inputs['Fac'])
    link(ramp.outputs['Color'], b.inputs['Base Color'])
    height = n.new('ShaderNodeMath')
    height.operation = 'MULTIPLY_ADD'
    height.inputs[1].default_value = 0.3
    link(fuzz.outputs['Fac'], height.inputs[0])
    link(grains.outputs['Distance'], height.inputs[2])
    bump = n.new('ShaderNodeBump')
    bump.inputs['Strength'].default_value = 0.32
    bump.inputs['Distance'].default_value = 0.02
    link(height.outputs['Value'], bump.inputs['Height'])
    link(bump.outputs['Normal'], b.inputs['Normal'])
    b.inputs['Roughness'].default_value = 0.95


def glossy_plastic(color):
    def build(nt, b):
        b.inputs['Base Color'].default_value = color
        b.inputs['Roughness'].default_value = 0.2
        set_inputs(b, Coat_Weight=0.6, Coat_Roughness=0.04, Subsurface_Weight=0.12,
                   Subsurface_Radius=(0.08, 0.02, 0.02))
    return build


def cotton(nt, b):
    """Algodon: rojo profundo, brillo de tela suave y pelusa fina en el relieve."""
    b.inputs['Base Color'].default_value = (0.52, 0.006, 0.008, 1)
    b.inputs['Roughness'].default_value = 0.72
    set_inputs(b, Sheen_Weight=0.25, Sheen_Roughness=0.4, Sheen_Tint=(1.0, 0.35, 0.35, 1),
               Subsurface_Weight=0.15, Subsurface_Radius=(0.05, 0.01, 0.01))
    coord = nt.nodes.new('ShaderNodeTexCoord')
    fuzz = nt.nodes.new('ShaderNodeTexNoise')
    fuzz.inputs['Scale'].default_value = 2500.0
    bump = nt.nodes.new('ShaderNodeBump')
    bump.inputs['Strength'].default_value = 0.4
    nt.links.new(coord.outputs['Object'], fuzz.inputs['Vector'])
    nt.links.new(fuzz.outputs['Fac'], bump.inputs['Height'])
    nt.links.new(bump.outputs['Normal'], b.inputs['Normal'])


def box(name, size, loc, mat):
    bpy.ops.mesh.primitive_cube_add(size=1, location=loc)
    obj = bpy.context.object
    obj.name = name
    obj.scale = size
    obj.data.materials.append(mat)
    return obj


# Tablero en el plano XY (la camara lo mira desde arriba, como a una pared de frente).
BW, BH = 4.2, 5.4
box('Cork', (BW, BH, 0.04), (0, 0, -0.02), material('Cork', cork))
frame_wood = material('Frame', flat((0.09, 0.05, 0.025, 1), 0.5))
for name, size, loc in (('FrameT', (BW + 0.3, 0.15, 0.1), (0, BH / 2 + 0.07, 0)),
                        ('FrameB', (BW + 0.3, 0.15, 0.1), (0, -BH / 2 - 0.07, 0)),
                        ('FrameL', (0.15, BH, 0.1), (-BW / 2 - 0.07, 0, 0)),
                        ('FrameR', (0.15, BH, 0.1), (BW / 2 + 0.07, 0, 0))):
    box(name, size, loc, frame_wood)

paper = paper_material()
pin_mats = [material('PinRed', glossy_plastic((0.42, 0.012, 0.012, 1))),
            material('PinYellow', glossy_plastic((0.70, 0.48, 0.03, 1)))]
steel = material('Steel', flat((0.75, 0.75, 0.76, 1), 0.12, 1.0))


def pushpin(px, py, z, mat):
    """Chinche de mapa: cabeza, cuello conico y aguja casi toda dentro del corcho.

    Devuelve el punto del cuello, donde se enrolla el hilo.
    """
    base = bpy.data.objects.new('PinBase', None)
    base.location = (px, py, z)
    scene.collection.objects.link(base)
    parts = []
    bpy.ops.mesh.primitive_cylinder_add(radius=0.0045, depth=0.05, location=(0, 0, -0.017), vertices=24)
    parts.append((bpy.context.object, steel))
    bpy.ops.mesh.primitive_cone_add(radius1=0.010, radius2=0.019, depth=0.026, location=(0, 0, 0.019), vertices=32)
    parts.append((bpy.context.object, mat))
    bpy.ops.mesh.primitive_uv_sphere_add(radius=0.04, location=(0, 0, 0.062), segments=48, ring_count=24)
    bpy.context.object.scale = (1, 1, 0.86)
    parts.append((bpy.context.object, mat))
    for obj, m in parts:
        obj.data.materials.append(m)
        smooth(obj)
        obj.parent = base
    base.rotation_euler = (math.radians(rng.uniform(-6, 6)), math.radians(rng.uniform(-6, 6)), 0)
    bpy.context.view_layer.update()
    return base.matrix_world @ Vector((0, 0, 0.02))


# La camara mira desde +Y: en el cuadro, "arriba" es -Y y "abajo" es +Y.
SLOTS = [(0.0, -0.35), (-1.25, 1.55), (1.25, 1.75), (-1.35, -0.85), (1.35, -1.05), (0.1, 1.05), (-0.2, -2.05)]
pins = []
for idx, path in enumerate(IMAGES[:len(SLOTS)]):
    img = bpy.data.images.load(path)
    w, h = photo_size(img, 1.25 if idx == 0 else rng.uniform(0.85, 1.0))
    x, y = SLOTS[idx]
    if idx:
        x += rng.uniform(-0.1, 0.1)
        y += rng.uniform(-0.08, 0.08)
    rot = rng.uniform(-7, 7) + 180
    z = 0.006 + idx * 0.002
    border = 0.045 * max(w, h)
    plane(f'Border{idx}', w + 2 * border, h + 2 * border, (x, y, z), rot, paper)
    photo = plane(f'Photo{idx}', w, h, (x, y, z + 0.0012), rot, image_material(f'Photo{idx}', img, 0.3))
    off = Vector((0, (h / 2 + border * 0.2) - 0.06, 0))       # arriba al centro de la foto
    off.rotate(photo.rotation_euler)
    pins.append(pushpin(x + off.x, y + off.y, z + 0.002, pin_mats[idx % 2]))

note = material('Note', flat((0.92, 0.80, 0.32, 1), 0.8))
for nx, ny, r in ((1.55, 0.35, 8), (-1.6, 0.35, -6), (0.95, -2.2, 4)):
    plane('Note', 0.42, 0.42, (nx, ny, 0.004), r, note)

# Hilo: perfil de tres hebras que gira a lo largo (el trenzado se ve en la silueta).
thread = material('Thread', cotton)
profile_data = bpy.data.curves.new('ThreadProfile', 'CURVE')
profile_data.dimensions = '2D'
ply = profile_data.splines.new('POLY')
ply.points.add(35)
for k, point in enumerate(ply.points):
    ang = 2 * math.pi * k / 36
    r = 0.0066 * (1 + 0.13 * math.cos(3 * ang))
    point.co = (r * math.cos(ang), r * math.sin(ang), 0, 1)
ply.use_cyclic_u = True
profile = bpy.data.objects.new('ThreadProfile', profile_data)
scene.collection.objects.link(profile)
profile.hide_render = True

# Las fotos de abajo no se atan a la protagonista (el hilo le cruzaria la cara):
# se atan a la foto lateral mas cercana.
links = []
if pins:
    above = [j for j in range(1, len(pins)) if pins[j].y <= pins[0].y + 0.15]
    for k in range(1, len(pins)):
        if k in above:
            links.append((0, k))
        else:
            side = min((j for j in above if j != k), key=lambda j: (pins[j] - pins[k]).length, default=None)
            if side is not None:
                links.append((side, k))
    links += [(a, b) for a, b in ((1, 5), (2, 5)) if b < len(pins)]
for a, b in links:
    curve = bpy.data.curves.new(f'Thread{a}_{b}', 'CURVE')
    curve.dimensions = '3D'
    curve.bevel_mode = 'OBJECT'
    curve.bevel_object = profile
    curve.resolution_u = 48
    curve.twist_mode = 'MINIMUM'
    spline = curve.splines.new('BEZIER')
    spline.bezier_points.add(2)
    span = (pins[b] - pins[a]).length
    middle = (pins[a] + pins[b]) / 2 + Vector((0, 0.012 * span, 0.01))   # leve comba
    turns = span / 0.06                                                  # una vuelta cada ~6 cm
    for point, co, tilt in zip(spline.bezier_points, (pins[a], middle, pins[b]),
                               (0.0, math.pi * turns, 2 * math.pi * turns)):
        point.co = co
        point.tilt = tilt
        point.handle_left_type = point.handle_right_type = 'AUTO'
    spline.tilt_interpolation = 'LINEAR'
    spline.use_smooth = True
    obj = bpy.data.objects.new(f'Thread{a}_{b}', curve)
    obj.data.materials.append(thread)
    scene.collection.objects.link(obj)

# Lampara calida sobre el centro: la protagonista queda en la zona mas iluminada.
light(scene, 'Lamp', 'SPOT', 1250, (1.0, 0.80, 0.56), (-1.3, 1.9, 4.6), (0.0, -0.2, 0.0), size=0.8,
      spot=(math.radians(62), 0.75))
light(scene, 'Fill', 'AREA', 40, (0.55, 0.65, 1.0), (2.5, -2.5, 3.5), (0.0, 0.0, 0.0), size=4.0)

start = pins[2] if len(pins) > 2 else (pins[-1] if pins else Vector((0, 0, 0)))
hero = SLOTS[0]
center = (hero[0], hero[1] - 0.05, 0.0)
push = ((1, (start.x + 0.2, start.y + 0.9, 1.25), (start.x, start.y - 0.25, 0.0)),
        (FRAMES, (hero[0] + 0.05, hero[1] + 1.35, 2.05), center))
camera_rig(scene, lens=42 if VERTICAL else 34, fstop=2.0,
           keys=motion_keys(params.get("motion", "push"), FRAMES, center, push))
render()
