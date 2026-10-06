"""Toma 3D para Blender: fotos sobre una mesa, camara que baja hasta la protagonista.

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
import json
import math
import os
import random
import sys
import time
import warnings

import bpy

# Blender 4.x necesita `use_nodes = True`; 5.x siempre usa nodos y lo depreca.
warnings.simplefilter('ignore', DeprecationWarning)


def _use_nodes(idblock):
    try:
        idblock.use_nodes = True
    except Exception:
        pass


params = json.load(open(sys.argv[sys.argv.index('--') + 1], encoding='utf-8'))
IMAGES = [p for p in params['images'] if os.path.exists(p)]
FRAMES = int(params['frames'])
VERTICAL = int(params['height']) >= int(params['width'])
rng = random.Random(int(params.get('seed', 7)))

bpy.ops.wm.read_factory_settings(use_empty=True)
scene = bpy.context.scene
for engine in ('BLENDER_EEVEE', 'BLENDER_EEVEE_NEXT'):
    try:
        scene.render.engine = engine
        break
    except TypeError:
        continue
scene.render.resolution_x = int(params['width'])
scene.render.resolution_y = int(params['height'])
scene.render.resolution_percentage = int(params.get('resolution_pct', 75))
scene.render.fps = int(params.get('fps', 30))
scene.frame_start, scene.frame_end = 1, FRAMES
scene.eevee.taa_render_samples = int(params.get('samples', 10))
try:
    scene.eevee.shadow_resolution_scale = float(params.get('shadow_scale', 1.0))
except Exception:
    pass
scene.render.image_settings.file_format = 'PNG'
scene.render.filepath = os.path.join(params['out_dir'], 'f_')
try:
    scene.view_settings.view_transform = 'AgX'
    scene.view_settings.look = 'AgX - Medium High Contrast'
except Exception:
    pass

world = bpy.data.worlds.new('World')
scene.world = world
_use_nodes(world)
world.node_tree.nodes['Background'].inputs[0].default_value = (0.012, 0.010, 0.009, 1)


def material(name, build):
    mat = bpy.data.materials.new(name)
    _use_nodes(mat)
    build(mat.node_tree, mat.node_tree.nodes['Principled BSDF'])
    return mat


def wood(nt, bsdf):
    coord = nt.nodes.new('ShaderNodeTexCoord')
    mapping = nt.nodes.new('ShaderNodeMapping')
    mapping.inputs['Scale'].default_value = (1.0, 14.0, 1.0)
    noise = nt.nodes.new('ShaderNodeTexNoise')
    noise.inputs['Scale'].default_value = 2.5
    noise.inputs['Detail'].default_value = 10.0
    ramp = nt.nodes.new('ShaderNodeValToRGB')
    ramp.color_ramp.elements[0].color = (0.030, 0.015, 0.007, 1)
    ramp.color_ramp.elements[1].color = (0.105, 0.055, 0.026, 1)
    nt.links.new(coord.outputs['Object'], mapping.inputs['Vector'])
    nt.links.new(mapping.outputs['Vector'], noise.inputs['Vector'])
    nt.links.new(noise.outputs['Fac'], ramp.inputs['Fac'])
    nt.links.new(ramp.outputs['Color'], bsdf.inputs['Base Color'])
    bsdf.inputs['Roughness'].default_value = 0.5


def paper(nt, bsdf):
    bsdf.inputs['Base Color'].default_value = (0.80, 0.76, 0.66, 1)
    bsdf.inputs['Roughness'].default_value = 0.8


def plane(name, w, h, loc, rot_z, mat):
    bpy.ops.mesh.primitive_plane_add(size=1, location=loc)
    obj = bpy.context.object
    obj.name = name
    obj.scale = (w, h, 1)
    obj.rotation_euler.z = math.radians(rot_z)
    obj.data.materials.append(mat)
    return obj


plane('Table', 10, 12, (0, 0, 0), 0, material('Wood', wood))
paper_mat = material('Paper', paper)

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
    iw, ih = img.size
    if iw >= ih:
        w, h = longest, longest * ih / max(iw, 1)
    else:
        w, h = longest * iw / max(ih, 1), longest
    z = 0.004 + order * 0.003

    def photo_mat(nt, bsdf, img=img):
        tex = nt.nodes.new('ShaderNodeTexImage')
        tex.image = img
        nt.links.new(tex.outputs['Color'], bsdf.inputs['Base Color'])
        bsdf.inputs['Roughness'].default_value = 0.32

    border = 0.05 * max(w, h)
    plane(f'Border{order}', w + 2 * border, h + 2 * border, (x, y, z), rot + 180, paper_mat)
    plane(f'Photo{order}', w, h, (x, y, z + 0.0012), rot + 180, material(f'Photo{order}', photo_mat))


def light(name, energy, size, color, loc, rot):
    data = bpy.data.lights.new(name, 'AREA')
    data.energy, data.size, data.color = energy, size, color
    obj = bpy.data.objects.new(name, data)
    obj.location = loc
    obj.rotation_euler = tuple(math.radians(a) for a in rot)
    scene.collection.objects.link(obj)


light('Key', 260, 2.2, (1.0, 0.82, 0.62), (-2.0, 1.6, 2.6), (40, -35, 0))
light('Fill', 40, 4.0, (0.55, 0.65, 1.0), (2.5, -2.0, 3.0), (35, 30, 0))

target = bpy.data.objects.new('Target', None)
scene.collection.objects.link(target)
cam_data = bpy.data.cameras.new('Cam')
cam_data.lens = 40 if VERTICAL else 32
cam_data.dof.use_dof = True
cam_data.dof.aperture_fstop = 1.6
cam_data.dof.focus_object = target
cam = bpy.data.objects.new('Cam', cam_data)
scene.collection.objects.link(cam)
scene.camera = cam
track = cam.constraints.new('TRACK_TO')
track.target = target
track.track_axis, track.up_axis = 'TRACK_NEGATIVE_Z', 'UP_Y'

# Arranca abierta, mirando las fotos de arriba, y baja hasta encuadrar a la protagonista.
start_cam, start_tgt = (0.15, 2.95, 2.35), (0.05, 1.05, 0.0)
end_cam, end_tgt = ((0.05, 1.28, 1.50), (0.0, 0.02, 0.0)) if VERTICAL else ((0.05, 1.25, 1.45), (0.0, 0.02, 0.0))
for frame, cam_loc, tgt_loc in ((1, start_cam, start_tgt), (FRAMES, end_cam, end_tgt)):
    cam.location, target.location = cam_loc, tgt_loc
    cam.keyframe_insert('location', frame=frame)
    target.keyframe_insert('location', frame=frame)

t0 = time.time()
bpy.ops.render.render(animation=True)
print(f"RENDER_TIME {time.time() - t0:.1f}")
