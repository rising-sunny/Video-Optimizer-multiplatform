"""Piezas comunes de las plantillas 3D. Corre DENTRO de Blender (importa bpy).

Cada plantilla hace `sys.path.insert(0, carpeta_de_plantillas)` y
`from _scene_common import ...`. Compatible con Blender 4.x y 5.x.
"""
import json
import math
import os
import sys
import time
import warnings

import bpy

# Blender 4.x necesita `use_nodes = True`; 5.x siempre usa nodos y lo depreca.
warnings.simplefilter('ignore', DeprecationWarning)


def load_params():
    with open(sys.argv[sys.argv.index('--') + 1], encoding='utf-8') as fh:
        return json.load(fh)


def use_nodes(idblock):
    try:
        idblock.use_nodes = True
    except Exception:
        pass


def setup_scene(params, world_color=(0.01, 0.009, 0.008), shadow_quality=False):
    """Escena vacia con EEVEE, resolucion, cuadros y salida PNG segun `params`."""
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
    scene.frame_start, scene.frame_end = 1, int(params['frames'])
    scene.eevee.taa_render_samples = int(params.get('samples', 8))
    try:
        scene.eevee.shadow_resolution_scale = float(params.get('shadow_scale', 1.0))
    except Exception:
        pass
    if shadow_quality:
        # Sombras suaves sin punteado (objetos chicos y cercanos: chinches, hilos).
        for attr, value in (('shadow_ray_count', 3), ('shadow_step_count', 10)):
            try:
                setattr(scene.eevee, attr, value)
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
    use_nodes(world)
    world.node_tree.nodes['Background'].inputs[0].default_value = tuple(world_color) + (1,)
    return scene


def material(name, build):
    mat = bpy.data.materials.new(name)
    use_nodes(mat)
    build(mat.node_tree, mat.node_tree.nodes['Principled BSDF'])
    return mat


def set_inputs(bsdf, **values):
    """Entradas del Principled que cambian de nombre entre versiones: se ignoran si faltan."""
    for name, value in values.items():
        key = name.replace('_', ' ')
        if key in bsdf.inputs:
            bsdf.inputs[key].default_value = value


def flat(color, rough=0.6, metal=0.0):
    def build(nt, b):
        b.inputs['Base Color'].default_value = color
        b.inputs['Roughness'].default_value = rough
        b.inputs['Metallic'].default_value = metal
    return build


def noisy(c0, c1, scale, stretch=(1, 1, 1), rough=0.6):
    """Color con ruido procedural (madera si se estira en un eje, pared, etc.)."""
    def build(nt, b):
        coord = nt.nodes.new('ShaderNodeTexCoord')
        mapping = nt.nodes.new('ShaderNodeMapping')
        mapping.inputs['Scale'].default_value = stretch
        noise = nt.nodes.new('ShaderNodeTexNoise')
        noise.inputs['Scale'].default_value = scale
        noise.inputs['Detail'].default_value = 8.0
        ramp = nt.nodes.new('ShaderNodeValToRGB')
        ramp.color_ramp.elements[0].color = c0
        ramp.color_ramp.elements[1].color = c1
        nt.links.new(coord.outputs['Object'], mapping.inputs['Vector'])
        nt.links.new(mapping.outputs['Vector'], noise.inputs['Vector'])
        nt.links.new(noise.outputs['Fac'], ramp.inputs['Fac'])
        nt.links.new(ramp.outputs['Color'], b.inputs['Base Color'])
        b.inputs['Roughness'].default_value = rough
    return build


def wood(dark=False):
    c0, c1 = ((0.025, 0.013, 0.006, 1), (0.09, 0.048, 0.022, 1)) if dark else \
        ((0.030, 0.015, 0.007, 1), (0.105, 0.055, 0.026, 1))
    return noisy(c0, c1, 2.5, (1.0, 14.0, 1.0), 0.5)


def image_material(name, image, rough=0.32):
    def build(nt, b):
        tex = nt.nodes.new('ShaderNodeTexImage')
        tex.image = image
        nt.links.new(tex.outputs['Color'], b.inputs['Base Color'])
        b.inputs['Roughness'].default_value = rough
    return material(name, build)


def paper_material():
    def build(nt, b):
        b.inputs['Base Color'].default_value = (0.82, 0.79, 0.70, 1)
        b.inputs['Roughness'].default_value = 0.85
        coord = nt.nodes.new('ShaderNodeTexCoord')
        grain = nt.nodes.new('ShaderNodeTexNoise')
        grain.inputs['Scale'].default_value = 400.0
        bump = nt.nodes.new('ShaderNodeBump')
        bump.inputs['Strength'].default_value = 0.15
        nt.links.new(coord.outputs['Object'], grain.inputs['Vector'])
        nt.links.new(grain.outputs['Fac'], bump.inputs['Height'])
        nt.links.new(bump.outputs['Normal'], b.inputs['Normal'])
    return material('Paper', build)


def plane(name, w, h, loc, rot_z_deg, mat):
    bpy.ops.mesh.primitive_plane_add(size=1, location=loc)
    obj = bpy.context.object
    obj.name = name
    obj.scale = (w, h, 1)
    obj.rotation_euler.z = math.radians(rot_z_deg)
    obj.data.materials.append(mat)
    return obj


def photo_size(image, longest):
    iw, ih = image.size
    if iw >= ih:
        return longest, longest * ih / max(iw, 1)
    return longest * iw / max(ih, 1), longest


def smooth(obj):
    for poly in obj.data.polygons:
        poly.use_smooth = True


def light(scene, name, kind, energy, color, loc, aim, size=1.0, spot=None):
    """Luz apuntada a `aim` (TRACK_TO): mas facil de leer que angulos sueltos."""
    data = bpy.data.lights.new(name, kind)
    data.energy, data.color = energy, color
    if kind == 'AREA':
        data.size = size
    else:
        data.shadow_soft_size = size
    if spot:
        data.spot_size, data.spot_blend = spot
    try:
        data.shadow_filter_radius = 2.5
    except Exception:
        pass
    obj = bpy.data.objects.new(name, data)
    obj.location = loc
    scene.collection.objects.link(obj)
    aim_obj = bpy.data.objects.new(name + 'Aim', None)
    aim_obj.location = aim
    scene.collection.objects.link(aim_obj)
    track = obj.constraints.new('TRACK_TO')
    track.target = aim_obj
    track.track_axis, track.up_axis = 'TRACK_NEGATIVE_Z', 'UP_Y'
    return data


def camera_rig(scene, lens=40, fstop=1.8, keys=()):
    """Camara con foco y TRACK_TO a un objetivo; `keys` = [(cuadro, pos_camara, pos_objetivo)]."""
    target = bpy.data.objects.new('Target', None)
    scene.collection.objects.link(target)
    cam_data = bpy.data.cameras.new('Cam')
    cam_data.lens = lens
    cam_data.dof.use_dof = True
    cam_data.dof.aperture_fstop = fstop
    cam_data.dof.focus_object = target
    cam = bpy.data.objects.new('Cam', cam_data)
    scene.collection.objects.link(cam)
    scene.camera = cam
    track = cam.constraints.new('TRACK_TO')
    track.target = target
    track.track_axis, track.up_axis = 'TRACK_NEGATIVE_Z', 'UP_Y'
    for frame, cam_loc, tgt_loc in keys:
        cam.location, target.location = cam_loc, tgt_loc
        cam.keyframe_insert('location', frame=frame)
        target.keyframe_insert('location', frame=frame)
    return cam, target


def action_fcurves(obj):
    """Curvas de animacion del objeto (Blender 4: action.fcurves; 5: capas/tiras)."""
    action = obj.animation_data.action if obj.animation_data else None
    if action is None:
        return []
    try:
        return list(action.fcurves)
    except AttributeError:
        curves = []
        for layer in action.layers:
            for strip in layer.strips:
                for bag in strip.channelbags:
                    curves += list(bag.fcurves)
        return curves


def orbit_keys(frames, center, radius=2.2, height=1.4, phases=0.5, start_angle=-0.6):
    """Camara que orbita alrededor de `center` (media vuelta por defecto), mirandolo siempre."""
    keys = []
    steps = 10
    for k in range(steps + 1):
        frame = 1 + round((frames - 1) * k / steps)
        t = k / steps
        ang = start_angle + 2 * math.pi * phases * t
        x = center[0] + radius * math.cos(ang)
        y = center[1] + radius * math.sin(ang)
        z = center[2] + height
        keys.append((frame, (x, y, z), center))
    keys[-1] = (frames, keys[-1][1], center)
    return keys


def crane_keys(frames, center, radius=1.9, height_start=0.9, height_end=2.2, start_angle=-0.5):
    """Camara que sube (crane) mientras se acerca un poco, mirando `center`."""
    keys = []
    steps = 10
    for k in range(steps + 1):
        frame = 1 + round((frames - 1) * k / steps)
        t = k / steps
        shrink = 1.0 - 0.35 * t
        x = center[0] + radius * math.cos(start_angle) * shrink
        y = center[1] + radius * math.sin(start_angle) * shrink
        z = center[2] + height_start + (height_end - height_start) * t
        keys.append((frame, (x, y, z), center))
    keys[-1] = (frames, keys[-1][1], center)
    return keys


def motion_keys(motion, frames, center, push_keys):
    """Las keys de camara para `motion`: 'push' (las de siempre), 'orbit' o 'crane'."""
    if motion == "orbit":
        return orbit_keys(frames, center)
    if motion == "crane":
        return crane_keys(frames, center)
    return push_keys


def render():
    t0 = time.time()
    bpy.ops.render.render(animation=True)
    print(f"RENDER_TIME {time.time() - t0:.1f}")
