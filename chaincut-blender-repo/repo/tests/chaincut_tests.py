import re, math

def _clean(bpy):
    if bpy.context.object and bpy.context.object.mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')
    for o in list(bpy.data.objects):
        bpy.data.objects.remove(o, do_unlink=True)
    for d in list(bpy.data.armatures) + list(bpy.data.meshes):
        (bpy.data.armatures if d.rna_type.identifier == 'Armature' else bpy.data.meshes).remove(d)

def _build(bpy):
    _clean(bpy)
    arm = bpy.data.armatures.new("Arm"); ao = bpy.data.objects.new("Arm", arm)
    bpy.context.scene.collection.objects.link(ao)
    bpy.context.view_layer.objects.active = ao
    bpy.ops.object.mode_set(mode='EDIT')
    eb = arm.edit_bones
    def mk(name, h, t, parent=None, conn=False):
        b = eb.new(name); b.head = h; b.tail = t
        if parent: b.parent = eb[parent]; b.use_connect = conn
        return b
    mk("A", (0, 0, 0), (0, 0, 1)); mk("B", (0, 0, 1), (0, 0, 2), "A", True)
    mk("C", (0, 0, 2), (0, 0, 3), "B", True); mk("D", (0.3, 0, 0.5), (0.3, 0, 0.9), "A", False)
    bpy.ops.object.mode_set(mode='OBJECT')
    verts = [(0.1, 0, i * 0.1) for i in range(31)]
    me = bpy.data.meshes.new("Mesh"); me.from_pydata(verts, [], []); mo = bpy.data.objects.new("Mesh", me)
    bpy.context.scene.collection.objects.link(mo)
    mo.parent = ao
    md = mo.modifiers.new("Armature", 'ARMATURE'); md.object = ao
    gA, gB, gC = (mo.vertex_groups.new(name=n) for n in "ABC")
    for i, v in enumerate(verts):
        z = v[2]
        if z <= 1.5: gA.add([i], max(0.15, 1.0 - z / 1.8), 'REPLACE')
        if 0.5 <= z <= 2.5: gB.add([i], 0.2 + 0.1 * (i % 5), 'REPLACE')
        if z >= 2.0: gC.add([i], 0.5, 'REPLACE')
    return ao, mo

def _weights(mo):
    return {(v.index, mo.vertex_groups[g.group].name): g.weight for v in mo.data.vertices for g in v.groups}

def run(bpy, mod, check):
    bad = []
    for n in (2, 3, 5, 8):
        for s in (0.0, 0.5, 1.0):
            tag = f"N={n} s={s}"
            ao, mo = _build(bpy)
            before = _weights(mo)
            bpy.context.view_layer.objects.active = ao
            bpy.ops.object.mode_set(mode='EDIT')
            for b in ao.data.edit_bones:
                b.select = b.select_head = b.select_tail = b.name in ("A", "B")
            n_before = len(ao.data.edit_bones)
            r = bpy.ops.chaincut.split(segments=n, smoothness=s)
            bpy.ops.object.mode_set(mode='OBJECT')
            bones = ao.data.bones
            if r != {'FINISHED'}: bad.append(f"{tag}: op {r}")
            if len(bones) != n_before + (n - 1) * 2: bad.append(f"{tag}: bones {len(bones)}")
            if any(re.search(r"\.\d{3}$", b.name) for b in bones): bad.append(f"{tag}: sufijo .001")
            if len({b.name for b in bones}) != len(bones): bad.append(f"{tag}: nombres duplicados")
            after = _weights(mo)
            for v in mo.data.vertices:
                for orig, segs in (("A", ["A"] + [f"A_{i}" for i in range(2, n + 1)]), ("B", ["B"] + [f"B_{i}" for i in range(2, n + 1)])):
                    w0 = before.get((v.index, orig), 0.0)
                    w1 = sum(after.get((v.index, g), 0.0) for g in segs)
                    if abs(w0 - w1) > 1e-4: bad.append(f"{tag}: v{v.index} {orig} {w0:.4f}->{w1:.4f}")
                if abs(before.get((v.index, "C"), 0.0) - after.get((v.index, "C"), 0.0)) > 1e-6:
                    bad.append(f"{tag}: C cambiado v{v.index}")
            # jerarquia
            for base in ("A", "B"):
                chain = [base] + [f"{base}_{i}" for i in range(2, n + 1)]
                for i in range(1, n):
                    p = bones.get(chain[i])
                    if p is None or p.parent is None or p.parent.name != chain[i - 1] or not p.use_connect:
                        bad.append(f"{tag}: cadena {base} rota en {i}")
                L = sum(bones[c].length for c in chain if c in bones)
                if abs(L - 1.0) > 1e-4: bad.append(f"{tag}: longitud {base} {L:.4f}")
            if bones["B"].parent.name != f"A_{n}": bad.append(f"{tag}: B no cuelga del ultimo A")
            if bones["C"].parent.name != f"B_{n}": bad.append(f"{tag}: C no cuelga del ultimo B")
            want = min(int(0.5 * n + 1e-6), n - 1); wn = "A" if want == 0 else f"A_{want + 1}"
            if bones["D"].parent.name != wn: bad.append(f"{tag}: D cuelga de {bones['D'].parent.name}, esperado {wn}")
    check("aceptacion headless 12 escenarios (N,suavidad)", not bad, bad[:8])
    # sin malla: no falla
    ao, mo = _build(bpy); mo.parent = None; mo.modifiers.clear()
    bpy.context.view_layer.objects.active = ao; bpy.ops.object.mode_set(mode='EDIT')
    for b in ao.data.edit_bones: b.select = b.name == "A"
    r = bpy.ops.chaincut.split(segments=2, smoothness=0.5); bpy.ops.object.mode_set(mode='OBJECT')
    check("sin malla: divide huesos sin tocar pesos", r == {'FINISHED'} and len(ao.data.bones) == 5)
    # 2 mallas + malla ajena + armadura movida
    ao, mo = _build(bpy)
    ao.location = (2.0, 1.0, 0.1)
    me2 = bpy.data.meshes.new("Mesh2")
    me2.from_pydata([(0.0, 0.0, i * 0.15) for i in range(21)], [], [])
    mo2 = bpy.data.objects.new("Mesh2", me2); bpy.context.scene.collection.objects.link(mo2)
    mo2.location = (2.2, 1.1, 0.4)
    md = mo2.modifiers.new("Armature", 'ARMATURE'); md.object = ao
    gA2 = mo2.vertex_groups.new(name="A")
    for i in range(21):
        gA2.add([i], 0.4 + 0.02 * i, 'REPLACE')
    me3 = bpy.data.meshes.new("Ajena")
    me3.from_pydata([(0, 0, 0.2), (0, 0, 0.8)], [], [])
    mo3 = bpy.data.objects.new("Ajena", me3); bpy.context.scene.collection.objects.link(mo3)
    g3 = mo3.vertex_groups.new(name="A"); g3.add([0, 1], 0.7, 'REPLACE')
    bpy.context.view_layer.update()
    b1, b2, b3 = _weights(mo), _weights(mo2), _weights(mo3)
    bpy.context.view_layer.objects.active = ao; bpy.ops.object.mode_set(mode='EDIT')
    for b in ao.data.edit_bones: b.select = b.select_head = b.select_tail = b.name in ("A", "B")
    bpy.ops.chaincut.split(segments=2, smoothness=0.0); bpy.ops.object.mode_set(mode='OBJECT')
    a1, a2, a3 = _weights(mo), _weights(mo2), _weights(mo3)
    bad2 = []
    for lab, b0, a0, m in (("mesh1", b1, a1, mo), ("mesh2", b2, a2, mo2)):
        for v in m.data.vertices:
            for orig, seg in (("A", "A_2"), ("B", "B_2")):
                w0 = b0.get((v.index, orig), 0.0)
                w1 = a0.get((v.index, orig), 0.0) + a0.get((v.index, seg), 0.0)
                if abs(w0 - w1) > 1e-4: bad2.append(f"{lab} v{v.index} {orig} suma {w0:.3f}->{w1:.3f}")
    check("2 mallas: suma de pesos preservada en cada malla (armadura movida)", not bad2, bad2[:6])
    own = []
    for v in mo2.data.vertices:
        zw = v.co.z + (mo2.location.z - ao.location.z)
        hi = a2.get((v.index, "A_2"), 0.0); lo = a2.get((v.index, "A"), 0.0)
        if zw < 0.5 - 1e-6 and hi > 1e-6: own.append(f"v{v.index} z={zw:.2f} peso en A_2")
        if zw > 0.5 + 1e-6 and lo > 1e-6: own.append(f"v{v.index} z={zw:.2f} peso en A")
    check("2 mallas: segmento correcto por posicion mundial (suavidad 0)", not own, own[:6])
    check("malla ajena (sin armadura) intacta", a3 == b3, "")
    _clean(bpy)
    ao, mo = _build(bpy)
    # poll fuera de modo edicion
    check("poll falso fuera de Edit Armature", not bpy.ops.chaincut.split.poll())
    _clean(bpy)
