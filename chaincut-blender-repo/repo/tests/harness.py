"""Arnes de test headless para add-ons Blender.
Uso: blender --background --python harness.py -- --addon <carpeta_addon> [--tests tests.py] [--out result.json]
Exit 0 = todo verde; 1 = algun assert falla; 2 = error de arnes.
Un tests.py opcional define run(bpy, mod, check) y llama check(nombre, condicion, detalle='').
"""
import sys, os, ast, json, time, importlib, importlib.util, traceback

def parse():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else sys.argv[1:]
    a = {"addon": None, "tests": None, "out": None}
    i = 0
    while i < len(argv):
        k = argv[i].lstrip("-")
        if k in a and i + 1 < len(argv):
            a[k] = argv[i + 1]; i += 2
        else:
            i += 1
    return a

NET_MODS = {"socket", "urllib", "urllib2", "http", "requests", "httpx", "aiohttp", "ftplib", "smtplib", "websocket", "websockets", "openai", "anthropic"}

def scan_network(addon_dir):
    hits = []
    for root, _, files in os.walk(addon_dir):
        for f in files:
            if not f.endswith(".py"):
                continue
            p = os.path.join(root, f)
            tree = ast.parse(open(p, encoding="utf-8").read(), p)
            for n in ast.walk(tree):
                names = []
                if isinstance(n, ast.Import):
                    names = [x.name for x in n.names]
                elif isinstance(n, ast.ImportFrom) and n.module:
                    names = [n.module]
                for nm in names:
                    if nm.split(".")[0] in NET_MODS:
                        hits.append(f"{os.path.relpath(p, addon_dir)}:{n.lineno} import {nm}")
    return hits

def main():
    import bpy
    args = parse()
    res = {"blender": bpy.app.version_string, "addon": args["addon"], "checks": [], "ts": time.strftime("%Y-%m-%dT%H:%M:%S")}
    def check(name, cond, detail=""):
        res["checks"].append({"name": name, "ok": bool(cond), "detail": str(detail)})
        return bool(cond)
    try:
        d = os.path.abspath(args["addon"]); name = os.path.basename(d.rstrip("/"))
        sys.path.insert(0, os.path.dirname(d))
        mod = importlib.import_module(name)
        bi = getattr(mod, "bl_info", None)
        check("bl_info presente", isinstance(bi, dict))
        for k in ("name", "author", "version", "blender", "category"):
            check(f"bl_info.{k}", bi and k in bi)
        if bi:
            need = tuple(bi.get("blender", (99, 0, 0)))
            check("bl_info.blender <= version actual", need <= bpy.app.version, f"{need} vs {bpy.app.version}")
        check("LICENSE presente", os.path.exists(os.path.join(d, "LICENSE")))
        net = scan_network(d)
        check("sin imports de red/IA", not net, net)
        mod.register()
        check("register ok", True)
        if args["tests"]:
            spec = importlib.util.spec_from_file_location("addon_tests", args["tests"])
            t = importlib.util.module_from_spec(spec); spec.loader.exec_module(t)
            t.run(bpy, mod, check)
        mod.unregister()
        check("unregister ok", True)
        mod.register(); mod.unregister()
        check("re-registro limpio", True)
    except Exception:
        check("excepcion", False, traceback.format_exc())
        res["fatal"] = True
    res["ok"] = all(c["ok"] for c in res["checks"]) and bool(res["checks"])
    out = json.dumps(res, indent=1, ensure_ascii=False)
    if args["out"]:
        open(args["out"], "w", encoding="utf-8").write(out)
    print("HARNESS_JSON_BEGIN\n" + out + "\nHARNESS_JSON_END")
    sys.stdout.flush()
    sys.exit(0 if res["ok"] else 1)

if __name__ == "__main__":
    main()
