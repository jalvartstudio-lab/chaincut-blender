bl_info = {
    "name": "ChainCut - Bone Chain Slicer",
    "author": "Jalvart Studio",
    "version": (0, 1, 0),
    "blender": (5, 2, 0),
    "location": "View3D > Sidebar > ChainCut (Armature Edit Mode)",
    "description": "Split selected bones into N segments and redistribute vertex-group weights on every mesh that uses the armature. Local-only.",
    "category": "Rigging",
}

import bpy
from mathutils import Vector

COPY_PROPS = ("use_deform", "envelope_distance", "envelope_weight", "use_envelope_multiply",
              "bbone_segments", "inherit_scale", "use_inherit_rotation", "use_local_location",
              "use_relative_parent")


def _smoothstep(x):
    x = 0.0 if x < 0.0 else (1.0 if x > 1.0 else x)
    return x * x * (3.0 - 2.0 * x)


def segment_weights(p, n, smooth):
    """Partition of unity over n segments for the parameter p in [0, 1].
    Sum of the returned list is exactly 1 (telescoping)."""
    s = [1.0]
    width = smooth / n
    for k in range(1, n):
        pk = k / n
        if width <= 1e-9:
            s.append(1.0 if p >= pk else 0.0)
        else:
            s.append(_smoothstep(0.5 + (p - pk) / width))
    s.append(0.0)
    return [s[i] - s[i + 1] for i in range(n)]


def meshes_for(arm_ob, scene):
    """All meshes that use the armature: Armature modifier pointing to it, or parented to it."""
    out = []
    for ob in scene.objects:
        if ob.type != 'MESH':
            continue
        if ob.parent == arm_ob or any(m.type == 'ARMATURE' and m.object == arm_ob for m in ob.modifiers):
            out.append(ob)
    return out


def _unique_name(taken, base, k):
    i = k + 1
    while True:
        nm = f"{base}_{i}"
        if nm not in taken:
            return nm
        i += 1


class CHAINCUT_OT_split(bpy.types.Operator):
    bl_idname = "chaincut.split"
    bl_label = "Split Bones and Weights"
    bl_description = "Split the selected bones into N segments and redistribute the weights of every mesh that uses the armature"
    bl_options = {'REGISTER', 'UNDO'}

    segments: bpy.props.IntProperty(name="Segments", default=2, min=2, max=8)
    smoothness: bpy.props.FloatProperty(name="Smoothness", default=0.5, min=0.0, max=1.0)

    @classmethod
    def poll(cls, context):
        ob = context.object
        return ob is not None and ob.type == 'ARMATURE' and context.mode == 'EDIT_ARMATURE'

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self)

    def execute(self, context):
        arm_ob = context.object
        eb = arm_ob.data.edit_bones
        names = [b.name for b in eb if b.select]
        if not names:
            self.report({'ERROR'}, "Select at least one bone")
            return {'CANCELLED'}
        n = self.segments
        info = {nm: (eb[nm].head.copy(), eb[nm].tail.copy()) for nm in names}
        mapping = {}
        for nm in names:
            b = eb[nm]
            h, t = info[nm]
            vec = t - h
            L = vec.length
            if L < 1e-9:
                continue
            axis = vec / L
            kids = []
            for c in b.children:
                kids.append((c.name, c.head.copy(), c.tail.copy(), c.use_connect))
            snap = {p: getattr(b, p) for p in COPY_PROPS if hasattr(b, p)}
            roll, hr, tr = b.roll, b.head_radius, b.tail_radius
            cols = [c for c in b.collections] if hasattr(b, "collections") else []
            taken = {x.name for x in eb}
            seg_names = [nm]
            b.tail = h + vec / n
            b.tail_radius = hr + (tr - hr) / n
            prev_name = nm
            for k in range(1, n):
                new_name = _unique_name(taken, nm, k)
                taken.add(new_name)
                nb = eb.new(new_name)
                nb.head = h + vec * (k / n)
                nb.tail = h + vec * ((k + 1) / n)
                nb.roll = roll
                nb.head_radius = hr + (tr - hr) * (k / n)
                nb.tail_radius = hr + (tr - hr) * ((k + 1) / n)
                for p, v in snap.items():
                    try:
                        setattr(nb, p, v)
                    except Exception:
                        pass
                nb.parent = eb[prev_name]
                nb.use_connect = True
                for c in cols:
                    try:
                        c.assign(nb)
                    except Exception:
                        pass
                seg_names.append(new_name)
                prev_name = new_name
            for cn, ch, ct, conn in kids:
                c = eb[cn]
                p = max(0.0, min(1.0, (ch - h).dot(axis) / L))
                idx = n - 1 if conn else min(int(p * n + 1e-6), n - 1)
                c.parent = eb[seg_names[idx]]
                c.use_connect = conn
                if not conn:
                    c.head, c.tail = ch, ct
            mapping[nm] = seg_names
        meshes = meshes_for(arm_ob, context.scene)
        moved = 0
        for mesh_ob in meshes:
            moved += self._redistribute(arm_ob, mesh_ob, info, mapping, n, self.smoothness)
        if not meshes:
            self.report({'WARNING'}, "No mesh uses this armature: bones split, weights untouched")
        self.report({'INFO'}, f"Split {len(mapping)} bone(s); {len(meshes)} mesh(es); {moved} weight(s) redistributed")
        return {'FINISHED'}

    @staticmethod
    def _redistribute(arm_ob, mesh_ob, info, mapping, n, smooth):
        inv = arm_ob.matrix_world.inverted()
        mw = mesh_ob.matrix_world
        vgs = mesh_ob.vertex_groups
        moved = 0
        for nm, segs in mapping.items():
            g0 = vgs.get(nm)
            if g0 is None:
                continue
            h, t = info[nm]
            vec = t - h
            l2 = vec.length_squared
            gs = [g0]
            for sn in segs[1:]:
                gs.append(vgs.get(sn) or vgs.new(name=sn))
            for v in mesh_ob.data.vertices:
                w = None
                for ge in v.groups:
                    if ge.group == g0.index:
                        w = ge.weight
                        break
                if w is None:
                    continue
                co = inv @ (mw @ v.co)
                p = max(0.0, min(1.0, (co - h).dot(vec) / l2))
                u = segment_weights(p, n, smooth)
                for i, g in enumerate(gs):
                    val = w * u[i]
                    if val > 1e-6:
                        g.add([v.index], val, 'REPLACE')
                        moved += 1
                    elif i == 0:
                        g0.remove([v.index])
        return moved


class CHAINCUT_PT_panel(bpy.types.Panel):
    bl_idname = "CHAINCUT_PT_panel"
    bl_label = "ChainCut"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "ChainCut"

    @classmethod
    def poll(cls, context):
        return context.mode == 'EDIT_ARMATURE'

    def draw(self, context):
        self.layout.operator(CHAINCUT_OT_split.bl_idname)


classes = (CHAINCUT_OT_split, CHAINCUT_PT_panel)


def register():
    for c in classes:
        bpy.utils.register_class(c)


def unregister():
    for c in reversed(classes):
        bpy.utils.unregister_class(c)
