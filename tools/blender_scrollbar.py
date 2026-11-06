"""Renders the scroll bar parts of the WoW-style windows (thumb, up/down buttons) with Blender, transparent background.

    "C:/Program Files/Blender Foundation/Blender 5.2/blender.exe" -b -P tools/blender_scrollbar.py

Output: wowclaude/art/sb_thumb.png (40x120, 3-slice: 20 px caps), sb_btn_up.png, sb_btn_down.png (40x40).
"""
import math
import os

import bmesh
import bpy
from mathutils import Vector

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "wowclaude", "art")


def reset():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    sc = bpy.context.scene
    sc.render.engine = "CYCLES"
    sc.cycles.samples = 96
    sc.cycles.device = "CPU"
    sc.render.film_transparent = True
    sc.view_settings.view_transform = "Standard"
    sc.render.image_settings.file_format = "PNG"
    sc.render.image_settings.color_mode = "RGBA"
    w = bpy.data.worlds.new("w")
    sc.world = w
    w.use_nodes = True
    bg = w.node_tree.nodes["Background"]
    bg.inputs[0].default_value = (0.05, 0.04, 0.03, 1)
    bg.inputs[1].default_value = 0.6


def material(name, color, metallic=0.85, rough=0.28):
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    b = m.node_tree.nodes["Principled BSDF"]
    b.inputs["Base Color"].default_value = color
    b.inputs["Metallic"].default_value = metallic
    b.inputs["Roughness"].default_value = rough
    return m


def softbox(loc, size, power, rot):
    d = bpy.data.lights.new("sb", "AREA")
    d.shape = "RECTANGLE"
    d.size, d.size_y = size
    d.energy = power
    d.use_shadow = False
    o = bpy.data.objects.new("sb", d)
    o.location = loc
    o.rotation_euler = rot
    bpy.context.scene.collection.objects.link(o)


def camera(w, h, scale):
    c = bpy.data.cameras.new("cam")
    c.type = "ORTHO"
    c.ortho_scale = scale
    o = bpy.data.objects.new("cam", c)
    o.location = (0, -10, 0)
    o.rotation_euler = (math.radians(90), 0, 0)
    bpy.context.scene.collection.objects.link(o)
    bpy.context.scene.camera = o
    bpy.context.scene.render.resolution_x = w
    bpy.context.scene.render.resolution_y = h
    bpy.context.scene.render.resolution_percentage = 100


def rrect(w, h, r, seg=10):
    pts = []
    for cx, cy, a0 in ((w / 2 - r, h / 2 - r, 0), (-w / 2 + r, h / 2 - r, 90), (-w / 2 + r, -h / 2 + r, 180), (w / 2 - r, -h / 2 + r, 270)):
        for i in range(seg + 1):
            a = math.radians(a0 + 90 * i / seg)
            pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))
    return pts


def dome(name, w, h, r, depth, mat, rings=7):
    """A pillow: rounded-rectangle outline lifted into a soft dome (several shrinking rings, smooth shaded)."""
    me = bpy.data.meshes.new(name)
    bm = bmesh.new()
    layers = []
    for i in range(rings + 1):
        t = i / rings
        inset = (1 - math.sqrt(max(0.0, 1 - (1 - t) ** 2))) * min(w, h) * 0.22  # circular shoulder profile
        z = depth * math.sqrt(max(0.0, 1 - (1 - t) ** 2))
        ww, hh = max(0.02, w - 2 * inset), max(0.02, h - 2 * inset)
        rr = max(0.01, min(r - inset * 0.6, ww / 2 - 0.005, hh / 2 - 0.005))
        layers.append([bm.verts.new((x, 0 + 0, 0)) if False else bm.verts.new((x, z, y)) for x, y in rrect(ww, hh, rr)])
    for a, b in zip(layers, layers[1:]):
        n = len(a)
        for k in range(n):
            bm.faces.new((a[k], a[(k + 1) % n], b[(k + 1) % n], b[k]))
    bm.faces.new(layers[-1][::-1])
    n = len(layers[0])
    base = [bm.verts.new((v.co.x, 0, v.co.z)) for v in layers[0]]
    for k in range(n):
        bm.faces.new((layers[0][k], base[k], base[(k + 1) % n], layers[0][(k + 1) % n]))
    bm.faces.new(base)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    bm.to_mesh(me)
    bm.free()
    o = bpy.data.objects.new(name, me)
    bpy.context.scene.collection.objects.link(o)
    o.data.materials.append(mat)
    for p in me.polygons:
        p.use_smooth = True
    # Blender's front view looks along +Y: the dome rises toward -Y (camera), so flip
    o.scale.y = -1
    return o


def triangle(up, size, mat, z=0.0):
    me = bpy.data.meshes.new("tri")
    bm = bmesh.new()
    s = size
    pts = [(-s, -s * 0.55), (s, -s * 0.55), (0, s * 0.65)] if up else [(-s, s * 0.55), (s, s * 0.55), (0, -s * 0.65)]
    top = [bm.verts.new((x, -0.16, y)) for x, y in pts]
    bot = [bm.verts.new((x, 0.0, y)) for x, y in pts]
    bm.faces.new(top)
    bm.faces.new(bot[::-1])
    for k in range(3):
        bm.faces.new((top[k], bot[k], bot[(k + 1) % 3], top[(k + 1) % 3]))
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    bm.to_mesh(me)
    bm.free()
    o = bpy.data.objects.new("tri", me)
    bpy.context.scene.collection.objects.link(o)
    o.data.materials.append(mat)
    bev = o.modifiers.new("b", "BEVEL")
    bev.width = 0.03
    bev.segments = 2
    return o


def lights():
    softbox((-3, -6, 4), (6, 3), 700, (math.radians(60), 0, math.radians(-30)))
    softbox((4, -5, -2), (4, 6), 260, (math.radians(70), 0, math.radians(40)))


def render(path):
    bpy.context.scene.render.filepath = path
    bpy.ops.render.render(write_still=True)


def thumb():
    reset()
    lights()
    camera(40, 120, 3.0)  # 40 x 120 px  =  1.0 x 3.0 units
    brass = material("brass", (0.62, 0.38, 0.12, 1), 0.9, 0.32)
    dome("thumb", 0.86, 2.86, 0.43, 0.22, brass)
    ridge = material("ridge", (0.16, 0.09, 0.03, 1), 0.6, 0.5)
    for dz in (-0.16, 0.0, 0.16):  # grip lines in the middle
        g = dome("g", 0.42, 0.045, 0.02, 0.03, ridge, rings=3)
        g.location = (0, -0.2, dz)
    render(os.path.join(OUT, "sb_thumb.png"))


def button(up):
    reset()
    lights()
    camera(40, 40, 1.0)
    body = material("btn", (0.30, 0.10, 0.06, 1), 0.7, 0.35)
    dome("btn", 0.9, 0.9, 0.2, 0.12, body, rings=6)
    tri = triangle(up, 0.2, material("gold", (1.0, 0.78, 0.1, 1), 1.0, 0.25))
    tri.location.y = -0.12
    render(os.path.join(OUT, "sb_btn_up.png" if up else "sb_btn_down.png"))


os.makedirs(OUT, exist_ok=True)
thumb()
button(True)
button(False)
print("scrollbar parts rendered to", OUT)
