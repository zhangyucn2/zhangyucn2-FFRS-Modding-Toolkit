"""把多个 MOD 的差异翻译成「技能工具的暂存项」，再调用工具自己的构建管线生成合并包。

这是 B 方案：写入全部由 ffr-dt（patch/clone）完成，避免裸拷贝资产被 to-zen 重 cook 弄坏。

用法：
  python merge_to_staging.py <输出名> <MOD1> <MOD2> [...]
"""
import json
import pathlib
import shutil
import subprocess
import sys

S = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(S / "python"))


from kit import settings as C
# flatten / run / tojson 直接内置在下面（从 merge_skill_mods_v2 拷来）

RETOC = pathlib.Path(C.get("tools_dir")) / "retoc.exe"
FFRDT = pathlib.Path(C.get("tools_dir")) / "ffr-dt" / "ffr-dt.exe"
USMAP = pathlib.Path(C.get("usmap"))
OUT = pathlib.Path(C.get("output_dir")) / "NEWMOD"
WORK = S / "python" / "save" / "_temp" / "smart_merge"




def run(cmd, t=3600):
    p = subprocess.run([str(c) for c in cmd], capture_output=True, timeout=t)
    return p.returncode, (p.stdout or b"").decode("utf-8", "replace") + (p.stderr or b"").decode("utf-8", "replace")


def tojson(ua: pathlib.Path, js: pathlib.Path):
    rc, o = run([FFRDT, "tojson", str(ua), str(js), "--usmap", str(USMAP)])
    if rc != 0 or not js.exists():
        raise RuntimeError(f"tojson 失败 {ua.name}: {o[-200:]}")
    return json.loads(js.read_text(encoding="utf-8"))


def _special_value(sub):
    def find_text(n):
        if isinstance(n, dict):
            if n.get("Name") in ("CultureInvariantString", "SourceString") and isinstance(n.get("Value"), str):
                return n["Value"]
            for v in n.values():
                r = find_text(v)
                if r is not None:
                    return r
        elif isinstance(n, list):
            for x in n:
                r = find_text(x)
                if r is not None:
                    return r
        return None
    def find_pkg(n):
        if isinstance(n, dict):
            ap = n.get("AssetPath")
            if isinstance(ap, dict) and ap.get("PackageName"):
                return ap["PackageName"]
            for v in n.values():
                r = find_pkg(v)
                if r is not None:
                    return r
        elif isinstance(n, list):
            for x in n:
                r = find_pkg(x)
                if r is not None:
                    return r
        return None
    t = find_text(sub)
    if t is not None:
        return t
    return find_pkg(sub)


def flatten(node, prefix=""):
    out = {}
    def walk(n, path):
        if isinstance(n, dict) and "Name" in n and "Value" in n:
            sub = n["Value"]
            npath = f"{path}.{n['Name']}" if path else str(n["Name"])
            if isinstance(n.get("CultureInvariantString"), str):
                out[npath] = n["CultureInvariantString"]; return
            _ap = n.get("AssetPath")
            if isinstance(_ap, dict) and _ap.get("PackageName"):
                out[npath] = _ap["PackageName"]; return
            sp = _special_value(sub)
            if sp is not None:
                out[npath] = sp; return
            if isinstance(sub, list):
                if sub and all(isinstance(x, dict) and "Name" in x and not str(x["Name"]).isdigit() for x in sub):
                    for it in sub: walk(it, npath)
                else:
                    for i, it in enumerate(sub):
                        tgt = it.get("Value") if isinstance(it, dict) and str(it.get("Name", "")).isdigit() else it
                        walk(tgt, f"{npath}[{i}]")
            elif isinstance(sub, dict):
                if "PackageName" in (sub.get("AssetPath") or {}):
                    out[npath] = sub["AssetPath"]["PackageName"]
                else:
                    walk(sub, npath)
            else:
                out[npath] = sub
            return
        if isinstance(n, dict):
            if "$type" in n and "Value" in n:
                walk(n["Value"], path); return
            if "PackageName" in (n.get("AssetPath") or {}):
                out[path] = n["AssetPath"]["PackageName"]; return
            for k, v in n.items(): walk(v, path)
            return
        if isinstance(n, list):
            if n and all(isinstance(x, dict) and "Name" in x and not str(x["Name"]).isdigit() for x in n):
                for it in n: walk(it, path)
            else:
                for i, it in enumerate(n):
                    tgt = it.get("Value") if isinstance(it, dict) and str(it.get("Name", "")).isdigit() else it
                    walk(tgt, f"{path}[{i}]")
            return
        out[path] = n
    walk(node, prefix)
    return out

def unpack_mod(i, m, base_paks):
    d = WORK / f"mod{i}"
    (d / "src").mkdir(parents=True)
    (d / "leg").mkdir()
    for ext in (".utoc", ".ucas", ".pak"):
        src = OUT / f"{m}_P{ext}"
        if src.exists():
            shutil.copy2(src, d / "src" / f"{m}_P{ext}")
    for n in ("global.utoc", "global.ucas"):
        shutil.copy2(base_paks / n, d / "src" / n)
    rc, o = run([RETOC, "to-legacy", str(d / "src"), str(d / "leg"), "--no-shaders"])
    if rc != 0:
        raise SystemExit(f"{m} 解包失败: {o[-300:]}")
    print(f"解包 {m}: {len(list((d/'leg').rglob('*.uasset')))} 个资产")
    return d


def scan_new_skills(mods):
    """列出各 MOD 里 DT_SkillData 的新增技能 ID（相对基础表）。"""
    base_paks = pathlib.Path(C.build_base_cache()[0])
    tmp = WORK / "scan"
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir(parents=True)
    bd = tmp / "base"
    bd.mkdir()
    for n in ("FFRS-Windows.utoc", "FFRS-Windows.ucas", "FFRS-Windows.pak", "global.utoc", "global.ucas"):
        shutil.copy2(base_paks / n, bd / n)
    run([RETOC, "to-legacy", str(bd), str(tmp / "baseleg"), "-f", "DT_SkillData.uasset", "--no-shaders"])
    bua = next((x for x in (tmp / "baseleg").rglob("DT_SkillData.uasset")), None)
    base_names = {r["Name"] for r in tojson(bua, tmp / "base.json")["Exports"][0]["Table"]["Data"]}
    seen = []
    for i, m in enumerate(mods):
        d = tmp / f"m{i}"
        (d / "src").mkdir(parents=True)
        (d / "leg").mkdir()
        for ext in (".utoc", ".ucas", ".pak"):
            src = OUT / f"{m}_P{ext}"
            if src.exists():
                shutil.copy2(src, d / "src" / f"{m}_P{ext}")
        for n in ("global.utoc", "global.ucas"):
            shutil.copy2(base_paks / n, d / "src" / n)
        run([RETOC, "to-legacy", str(d / "src"), str(d / "leg"), "--no-shaders"])
        ua = next((x for x in (d / "leg").rglob("DT_SkillData.uasset")), None)
        if not ua:
            continue
        doc = tojson(ua, d / "s.json")
        for row in doc["Exports"][0]["Table"]["Data"]:
            if row["Name"] in base_names:
                continue
            sid = {q["Name"]: q["Value"] for q in row["Value"]}.get("ID")
            if sid and sid not in seen:
                seen.append(sid)
    print("NEW_SKILLS:" + ",".join(str(x) for x in seen))


def main():
    if len(sys.argv) < 3:
        raise SystemExit("用法: python merge_to_staging.py <输出名> <MOD1> <MOD2> [...]")
    args = [a for a in sys.argv[1:]]
    scan = False
    hints = {}
    cleaned = []
    i = 0
    while i < len(args):
        if args[i] == "--scan":
            scan = True
            i += 1
        elif args[i] == "--skill" and i + 1 < len(args):
            parts = args[i + 1].split(":")
            hints[int(parts[0])] = (int(parts[1]), int(parts[2]) if len(parts) > 2 and parts[2] else None)
            i += 2
        else:
            cleaned.append(args[i])
            i += 1
    if scan:
        scan_new_skills(cleaned)
        return
    if not cleaned:
        raise SystemExit("没有给出输出名/MOD")
    stem = cleaned[0]
    mods = [m[:-2] if m.endswith("_P") else m for m in cleaned[1:]]
    try:
        import skill_new as _SN
        auto = _SN.load_fx_sources()
    except Exception:
        auto = {}
    print("重建演出的新技能(手动):", hints, "| 自动记录:", auto)

    shutil.rmtree(WORK, ignore_errors=True)
    base_paks = pathlib.Path(C.build_base_cache()[0])
    base_src = WORK / "base_src"
    base_src.mkdir(parents=True)
    for n in ("FFRS-Windows.utoc", "FFRS-Windows.ucas", "FFRS-Windows.pak", "global.utoc", "global.ucas"):
        shutil.copy2(base_paks / n, base_src / n)
    base_leg = WORK / "base_leg"
    base_leg.mkdir()

    mod_dirs = [unpack_mod(i, m, base_paks) for i, m in enumerate(mods)]

    tables = set()
    for d in mod_dirs:
        for ua in (d / "leg").rglob("*.uasset"):
            if "/Datatable/" in ua.as_posix():
                tables.add(ua.name)
    tables = sorted(tables)
    print("涉及 DataTable:", len(tables))

    # 基础表
    base_rows, table_rel = {}, {}
    for t in tables:
        run([RETOC, "to-legacy", str(base_src), str(base_leg), "-f", t, "--no-shaders"])
        ua = next((p for p in base_leg.rglob(t)), None)
        if not ua:
            continue
        table_rel[t] = ua.relative_to(base_leg).with_suffix("").as_posix()
        doc = tojson(ua, WORK / f"base_{t}.json")
        base_rows[t] = {r["Name"]: r for r in doc["Exports"][0]["Table"]["Data"]}

    pending_rows, pending_sets, pending_assets, pending_news = [], [], [], []
    rebuilt_ids = set()
    touched = {}

    for d in mod_dirs:
        for t in tables:
            ua = next((p for p in (d / "leg").rglob(t)), None)
            if not ua or t not in base_rows:
                continue
            doc = tojson(ua, d / f"{t}.json")
            for row in doc["Exports"][0]["Table"]["Data"]:
                name = row["Name"]
                props = flatten(row["Value"])
                row_id = props.get("ID")
                if (t.startswith("DT_SkillData") and row_id not in hints
                        and row_id in auto):
                    a = auto[row_id]
                    hints[row_id] = (int(a["anim"]), int(a["fx"]) if a.get("fx") else None)
                    print(f"  ★ 新技能 {row_id}：使用构建记录里的动画 {a['anim']} / 特效 {a.get('fx')}")
                if t.startswith("DT_SkillData") and row_id in hints:
                    donor, fx = hints[row_id]
                    fields = {k: v for k, v in props.items() if k not in ("ID", "Name", "Description")}
                    pending_news.append({"donor": donor, "new_id": int(row_id),
                                         "name": props.get("Name"), "desc": props.get("Description"),
                                         "fields": fields, "fx_donor": fx, "fallback": [], "slot": None})
                    rebuilt_ids.add(int(row_id))
                    print(f"  ★ {t}: 新技能 {row_id} 交给工具重建（动画 {donor}，特效 {fx}）")
                    continue
                if t.startswith("DT_SkillAsset") and row_id in hints:
                    print(f"  ★ {t}: 跳过 {name}（由工具重建 SkillAsset 行）")
                    continue
                if name not in base_rows[t]:
                    # 新增行：挑同表模板
                    donor = next(iter(base_rows[t]))
                    if t.startswith("DT_SkillData"):
                        want = props.get("skillAttrType"), props.get("TargetType")
                        for k, v in base_rows[t].items():
                            fp = flatten(v["Value"])
                            if (fp.get("skillAttrType"), fp.get("TargetType")) == want:
                                donor = k
                                break
                    pending_rows.append({"table": table_rel[t], "row": name,
                                         "cloneFrom": donor, "set": props})
                    print(f"  + {t}: 新增行 {name}（模板 {donor}）")
                else:
                    base_props = flatten(base_rows[t][name]["Value"])
                    diff = {k: v for k, v in props.items() if base_props.get(k) != v}
                    if diff:
                        prev = touched.setdefault(t, {}).get(name)
                        if prev:
                            print(f"  ! {t}: 行 {name} 被多个 MOD 改过（保留后者）")
                        touched[t][name] = True
                        pending_sets.append({"table": table_rel[t], "row": name, "set": diff})
                        print(f"  ~ {t}: 改行 {name}（{len(diff)} 字段）")
        # 非表资产
        for f in (d / "leg").rglob("*.uasset"):
            if "/Datatable/" in f.as_posix():
                continue
            rel = f.relative_to(d / "leg")
            if "FFRS" not in rel.parts:
                continue
            if any(f"/{sid}/" in "/" + rel.as_posix() for sid in rebuilt_ids):
                continue
            pending_assets.append({"leg_root": str(d / "leg"), "rel": rel.as_posix()[:-7]})

    missing = [r["row"] for r in pending_rows if r["table"].endswith("DT_SkillData")]
    if missing:
        raise SystemExit(
            "检测到新技能但没有给映射（否则演出不会生成）：\n"
            + "\n".join(f"  {m}" for m in missing[:10])
            + "\n请填写 新技能ID:动画源ID:特效源ID（可用「扫描新技能」按钮先列出 ID）")

    if not (pending_rows or pending_sets or pending_assets):
        raise SystemExit("没有可合并的差异")

    print(f"暂存：重建新技能 {len(pending_news)} / 新增行 {len(pending_rows)} / 改行 {len(pending_sets)} / 资产 {len(pending_assets)}")

    # 调工具构建
    import tkinter as tk
    from kit.host import Host
    import FFRS_SkillMod_Tool as SK

    root = tk.Tk()
    root.withdraw()
    app = SK.App(host=Host(root))
    app._paths()
    app.pending_new = pending_news
    app.pending_rows = pending_rows
    app.pending_sets = pending_sets
    app.pending_assets = []            # 资产走 raw chunk 合并（保字节）
    app.v_name.set(stem + "__tables")
    lines = []
    orig = app.log
    app.log = lambda m: (lines.append(str(m)), None)[1]
    app._build_job()
    print("---- 构建日志 ----")
    print("\n".join(lines[-18:]))
    root.destroy()

    # 合并成功后把映射写回记录，下次自动可用
    try:
        import skill_new as _SN2
        for sid, (anim, fx) in hints.items():
            _SN2.remember_fx_source(int(sid), int(anim), int(fx) if fx else None)
    except Exception:
        pass

    if pending_assets:
        merge_raw(stem, mods, pending_assets)
    else:
        # 资产都由工具构建，直接用 to-zen 的容器（带 ContainerHeader）
        for ext in (".pak", ".utoc", ".ucas"):
            src = OUT / f"{stem}__tables_P{ext}"
            dst = OUT / f"{stem}_P{ext}"
            if src.exists():
                if dst.exists():
                    dst.unlink()
                src.rename(dst)
        print("  资产由工具重建，直接使用 to-zen 容器（含 ContainerHeader）")

    for ext in (".pak", ".utoc", ".ucas"):
        f = OUT / f"{stem}{'_P' if not stem.endswith('_P') else ''}{ext}"
        if f.exists():
            print("  ", f.name, f"{f.stat().st_size:,} B")


def merge_raw(stem: str, mods, pending_assets):
    """表用工具容器，非表资产用源 MOD 的 raw chunk（字节不改）。"""
    tables_stem = stem + "__tables"
    tables_utoc = OUT / f"{tables_stem}_P.utoc"
    if not tables_utoc.exists():
        raise SystemExit("表容器没生成出来")
    work = WORK / "raw"
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True)

    def unpack(utoc, tag):
        d = work / tag
        d.parent.mkdir(parents=True, exist_ok=True)
        rc, o = run([RETOC, "unpack-raw", str(utoc), str(d)])
        if rc != 0:
            raise SystemExit(f"unpack-raw 失败 {tag}: {o[-300:]}")
        man = json.loads((d / "manifest.json").read_text(encoding="utf-8"))
        return d, man.get("chunk_paths", {})

    chunks = {}   # cid -> (物理文件, 逻辑路径)
    order = [f"{m}_P.utoc" for m in mods] + [f"{tables_stem}_P.utoc"]
    for i, name in enumerate(order):
        d, paths = unpack(OUT / name, f"src{i}")
        for cid, logical in paths.items():
            src = d / "chunks" / cid
            if src.exists():
                chunks[cid] = (src, logical)
        print(f"  raw 合并 {name}: 累计 {len(chunks)} 个 chunk")

    outd = work / "out"
    (outd / "chunks").mkdir(parents=True)
    outm = {}
    for cid, (src, logical) in chunks.items():
        shutil.copy2(src, outd / "chunks" / cid)
        outm[cid] = logical
    (outd / "manifest.json").write_text(json.dumps({
        "chunk_paths": outm,
        "version": "ReplaceIoChunkHashWithIoHash",
        "mount_point": "../../../"}, indent=2), encoding="utf-8")
    final = OUT / f"{stem}_P.utoc"
    for ext in (".utoc", ".ucas"):
        (OUT / f"{stem}_P{ext}").unlink(missing_ok=True)
    rc, o = run([RETOC, "pack-raw", str(outd), str(final)])
    if rc != 0:
        raise SystemExit("pack-raw 失败: " + o[-300:])
    # pak：沿用表容器的空 pak
    pak_t = OUT / f"{tables_stem}_P.pak"
    if pak_t.exists():
        shutil.copy2(pak_t, OUT / f"{stem}_P.pak")
    for f in [OUT / f"{tables_stem}_P{p}" for p in (".utoc", ".ucas", ".pak")]:
        f.unlink(missing_ok=True)
    print(f"  raw 合并完成：{len(chunks)} chunk")
    return len(chunks)


if __name__ == "__main__":
    main()
