"""造「全新 ID 的技能 + 完整动画/特效」——2026-10-20 游戏内验证通过的配方。

原理（详见 docs/memory/ffrs-new-skill-pipeline.md）：

    技能 ID
     ├── DT_SkillData 行           技能本体（数值/元素/效果槽）
     ├── DT_SkillAsset 行          ★演出引用：LevelSequence / soundSequence（FSoftObjectPath）
     └── 序列资产（路径约定）      Sequencer/Battle/{Skill|Magic}/<id>/<id+1>/SEQ_Battle_<id+1>_Master

必须三个一起做：加技能行 + 加演出引用行 + 克隆演出树。少了第二项 → 技能能放但没动画/特效。

写入必须走 `ffr-dt patch`（UAssetAPI 自己管 NameMap / SoftObjectPath 表）；
手工改 JSON 会崩（Bad name index / DummyFNameSerializationException）。

用法（CLI）：
    python skill_new.py --donor 220170 --new 229001 \
        --slot-table DT_VisionAwakeningMasteryData \
        --slot-row "ウォーリアオブライト覚醒度1の恩恵" \
        --slot-path "detailData[4].params[0]" --out zzz_NewSkill_P
"""
import argparse
import json
import pathlib
import shutil
import subprocess
import sys

APP_DIR = pathlib.Path(__file__).resolve().parent      # Toolkit/python
try:
    import kit.settings as _K
    _app_root = _K.TOOLKIT_DIR
except Exception:
    _K = None
    _app_root = APP_DIR.parent
REPO = APP_DIR.parent
RETOC = APP_DIR / "retoc.exe"
REPAK = APP_DIR / "repak.exe"
if _K is not None:
    _tools = pathlib.Path(_K.get("tools_dir") or (APP_DIR / ".." / "tools"))
    RETOC = _tools / "retoc.exe"
    REPAK = _tools / "repak.exe"
FFRDT = APP_DIR / "tools" / "ffr-dt" / "ffr-dt.exe"
USMAP = APP_DIR / "tools" / "FFRS.usmap"
if _K is not None:
    if _K.get("ffrdt"):
        FFRDT = pathlib.Path(_K.get("ffrdt"))
    if _K.get("usmap"):
        USMAP = pathlib.Path(_K.get("usmap"))
BASE_VIEW = APP_DIR / "_audio_cache" / "base_paks"
if _K is not None and _K.get("base_view"):
    BASE_VIEW = pathlib.Path(_K.get("base_view"))
OUT_DIR = APP_DIR / "Output"
if _K is not None:
    try:
        OUT_DIR = _K.output_mods()
    except Exception:
        pass
CACHE = APP_DIR / "_skill_cache"
if _K is not None:
    try:
        CACHE = _K.cache_root() / "skill"
    except Exception:
        pass
MOD_MOUNT = "../../../"


def _bv() -> pathlib.Path:
    """基础三件套视图：首页有值就用；留空则自动建到 save/_cache/base_paks（共享）。"""
    if _K is not None:
        try:
            v = str(_K.get("base_view") or "").strip()
            if v:
                return pathlib.Path(v)
            d, _size, _files = _K.build_base_cache()
            return d
        except Exception:
            pass
        try:
            paks = pathlib.Path(_K.get("game_root")) / "FFRS" / "Content" / "Paks"
            if (paks / "FFRS-Windows.utoc").exists():
                return paks
        except Exception:
            pass
    return BASE_VIEW


def run(cmd, timeout=3600):
    p = subprocess.run([str(c) for c in cmd], capture_output=True, timeout=timeout)
    return p.returncode, (p.stdout or b"").decode("utf-8", "replace") + (p.stderr or b"").decode("utf-8", "replace")


def check_tools():
    for name, p in (("retoc", RETOC), ("repak", REPAK), ("ffr-dt", FFRDT), ("usmap", USMAP),
                    ("base_paks", _bv())):
        if not pathlib.Path(p).exists():
            raise RuntimeError(f"缺少 {name}：{p}")


_INDEX = None


def container_index() -> dict:
    """{文件basename: 相对路径(不含 FFRS/Content/)}；一次扫容器并缓存。"""
    global _INDEX
    if _INDEX is not None:
        return _INDEX
    cache = CACHE / "container_index.json"
    if cache.exists():
        try:
            _INDEX = json.loads(cache.read_text(encoding="utf-8"))
            if _INDEX and "DT_SkillData.uasset" in _INDEX:
                return _INDEX
            _INDEX = None          # 空/不完整的缓存 → 重建
        except Exception:
            pass
    utoc = _bv() / "FFRS-Windows.utoc"
    rc, o = run([RETOC, "list", utoc, "--path"])
    m = {}
    for line in o.splitlines():
        parts = line.split()
        if len(parts) < 4 or parts[2] != "ExportBundleData":
            continue
        path = parts[-1].replace("../../../FFRS/Content/", "")
        m.setdefault(path.rsplit("/", 1)[-1], path)
    CACHE.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(m, ensure_ascii=False), encoding="utf-8")
    _INDEX = m
    return m


def find_sequence(donor_id: int):
    """找源技能的演出目录：返回 (相对目录, 类别) 或 (None, None)。

    先按惯例找 `SEQ_Battle_<id+1>_Master`；找不到再在容器里搜
    `Sequencer/Battle/*/<id>/**/SEQ_Battle_*_Master`（有些技能是 +2 或别的编号）。
    只认 Master，Sound 单独存在不算有演出（没有动画/特效轨）。
    """
    idx = container_index()
    name = f"SEQ_Battle_{donor_id + 1}_Master.uasset"
    path = idx.get(name)
    if not path:
        pat = f"/{donor_id}/"
        cands = [(k, v) for k, v in idx.items()
                 if k.startswith("SEQ_Battle_") and k.endswith("_Master.uasset")
                 and pat in v]
        if cands:
            path = sorted(cands, key=lambda kv: kv[0])[0][1]
    if not path:
        return None, None
    rel_dir = path.rsplit("/", 1)[0]        # e.g. Sequencer/Battle/Skill/420160/420161
    cat = rel_dir.split("/")[2] if rel_dir.startswith("Sequencer/Battle/") else "Skill"
    return rel_dir, cat


def table_rel(table: str) -> str:
    """DT_xxx → FFRS/Content/... 的资产相对路径；带 / 的当作完整相对路径。"""
    t = table.rstrip("/")
    if t.endswith(".uasset"):
        t = t[:-7]
    if "/" in t:
        return t if t.startswith("FFRS/") else f"FFRS/Content/{t}"
    path = container_index().get(f"{t}.uasset")
    if path:
        return f"FFRS/Content/{path[:-7]}"
    return f"FFRS/Content/Datatable/{t}"


def created_ids_file() -> pathlib.Path:
    if _K is not None:
        try:
            return _K.state_file("created_skill_ids.json")
        except Exception:
            pass
    return CACHE / "created_skill_ids.json"


def load_created_ids() -> list:
    f = created_ids_file()
    try:
        return json.loads(f.read_text(encoding="utf-8")) if f.exists() else []
    except Exception:
        return []


def remember_id(new_id: int) -> None:
    ids = load_created_ids()
    if new_id not in ids:
        ids.append(new_id)
        CACHE.mkdir(parents=True, exist_ok=True)
        created_ids_file().write_text(json.dumps(ids), encoding="utf-8")


def next_free_id(start: int = 229001) -> int:
    """挑一个没被用过的技能 ID：DT_SkillData 里没有 + 本工具没生成过。"""
    created = load_created_ids()
    used = set(created)
    try:
        used |= set(rows_cache("DT_SkillData", CACHE / "newskill").keys())
    except Exception:
        pass
    # 依次往后排：从"已记录的最大 ID + 1"开始，而不是每次回到起点
    i = max([start] + [int(x) + 1 for x in created if int(x) >= start])
    while i in used:
        i += 1
    return i


def fx_sources_file() -> pathlib.Path:
    d = CACHE.parent
    d.mkdir(parents=True, exist_ok=True)
    return d / "fx_sources.json"


def load_fx_sources() -> dict:
    f = fx_sources_file()
    if not f.exists():
        return {}
    try:
        return {int(k): v for k, v in json.loads(f.read_text(encoding="utf-8")).items()}
    except Exception:
        return {}


def remember_fx_source(new_id: int, anim: int, fx: int | None = None) -> None:
    """记录"哪个新技能用了谁的动画/特效"，合并工具据此自动填映射。"""
    f = fx_sources_file()
    data = load_fx_sources()
    data[int(new_id)] = {"anim": int(anim), "fx": int(fx) if fx else int(anim)}
    f.write_text(json.dumps({str(k): v for k, v in data.items()}, ensure_ascii=False, indent=1),
                 encoding="utf-8")


def rows_cache(table: str, work: pathlib.Path) -> dict:
    """{ID: 行名}；用 ffr-dt tojson 现算一次并缓存。"""
    cache = CACHE / f"rows_{table}.json"
    if cache.exists():
        try:
            return {int(k): v for k, v in json.loads(cache.read_text(encoding="utf-8")).items()}
        except Exception:
            pass
    legacy = work / "legacy"
    legacy.mkdir(parents=True, exist_ok=True)
    run([RETOC, "to-legacy", _bv(), legacy, "-f", f"{table}.uasset", "--no-shaders"])
    ua = next(legacy.rglob(f"{table}.uasset"), None)
    if ua is None:
        raise RuntimeError(f"容器里找不到 {table}")
    js = work / f"{table}.json"
    rc, o = run([FFRDT, "tojson", ua, js, "--usmap", USMAP])
    d = json.loads(js.read_text(encoding="utf-8"))
    out = {}
    for r in d["Exports"][0]["Table"]["Data"]:
        for q in r["Value"]:
            if q["Name"] == "ID" and isinstance(q["Value"], int):
                out[q["Value"]] = r["Name"]
                break
    CACHE.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps({str(k): v for k, v in out.items()}, ensure_ascii=False), encoding="utf-8")
    js.unlink(missing_ok=True)
    return out


def skill_asset_template(work: pathlib.Path, prefer_id: int | None = None) -> str:
    """挑一个「有演出引用」的 DT_SkillAsset 行当模板（优先带 LevelSequence 的第一行）。"""
    legacy = work / "legacy"
    legacy.mkdir(parents=True, exist_ok=True)
    run([RETOC, "to-legacy", _bv(), legacy, "-f", "DT_SkillAsset.uasset", "--no-shaders"])
    ua = next(legacy.rglob("DT_SkillAsset.uasset"), None)
    if ua is None:
        raise RuntimeError("容器里找不到 DT_SkillAsset")
    js = work / "DT_SkillAsset.json"
    run([FFRDT, "tojson", ua, js, "--usmap", USMAP])
    d = json.loads(js.read_text(encoding="utf-8"))
    rows = d["Exports"][0]["Table"]["Data"]
    if prefer_id is not None:
        for r in rows:
            pr = {q["Name"]: q["Value"] for q in r["Value"]}
            if pr.get("ID") == prefer_id and pr.get("LevelSequence"):
                return r["Name"]
    for r in rows:
        pr = {q["Name"]: q["Value"] for q in r["Value"]}
        if pr.get("LevelSequence"):
            return r["Name"]
    raise RuntimeError("DT_SkillAsset 里没有带 LevelSequence 的行")


SEQ_KINDS = ("Master", "Cut_001", "Effect_001", "Sound_001")


def plan_new_skill(donor_id: int, new_id: int, name: str | None = None,
                   desc: str | None = None, fallback_seq_ids: list | None = None,
                   log=print, legacy: pathlib.Path | None = None) -> dict:
    """只**规划**一个新技能（不执行 patch）：返回 {tables:[...], clones:[...], legacy:Path}。

    供「暂存多个新技能 → 生成时一次打包」使用；legacy 传进来可复用同一份抽取目录。
    """
    check_tools()
    legacy = pathlib.Path(legacy) if legacy else (CACHE / "plan" / "legacy")
    legacy.mkdir(parents=True, exist_ok=True)

    seq_src, rel_dir, cat = None, None, None
    d, c = find_sequence(donor_id)
    if d:
        seq_src, rel_dir, cat = donor_id, d, c
    elif fallback_seq_ids:
        # 源技能没有可复制的演出（只有 Sound / 完全没有 Master）：
        # 不再静默改用槽位原技能 —— 那样会产出"动画没换"的坏包。
        raise RuntimeError(
            f"源技能 {donor_id} 没有可复制的演出（容器里找不到 SEQ_Battle_*_Master）。"
            "请换一个源技能（例如同系里带完整演出的技能）。")
    seq_files = [f"SEQ_Battle_{seq_src + 1}_{k}.uasset" for k in SEQ_KINDS] if seq_src else []
    for f in ["DT_SkillData", "DT_SkillAsset"] + seq_files:
        if next(legacy.rglob(f), None):
            continue
        run([RETOC, "to-legacy", _bv(), legacy, "-f", f, "--no-shaders"])
    have_seq = [f for f in seq_files if next(legacy.rglob(f), None)]

    work = CACHE / "plan"
    work.mkdir(parents=True, exist_ok=True)
    sk_rows = rows_cache("DT_SkillData", work)
    donor_row = sk_rows.get(donor_id)
    if not donor_row:
        raise RuntimeError(f"DT_SkillData 里找不到源技能 {donor_id}")
    tmpl_row = skill_asset_template(work, prefer_id=donor_id)

    seq_dir = f"Sequencer/Battle/{cat or 'Skill'}/{new_id}/{new_id + 1}"
    level_seq = f"/Game/{seq_dir}/SEQ_Battle_{new_id + 1}_Master"
    sound_seq = f"/Game/{seq_dir}/Track/SEQ_Battle_{new_id + 1}_Sound_001"

    tables, clones = [], []
    _set = {"ID": new_id}
    if name:
        _set["Name"] = name
    if desc:
        _set["Description"] = desc
    tables.append({"asset": "FFRS/Content/Datatable/Skill/DT_SkillData",
                   "add": [{"row": f"NS_{new_id}", "cloneFrom": donor_row, "set": _set}]})
    if seq_src:
        tables.append({"asset": "FFRS/Content/Datatable/Asset/Skill/DT_SkillAsset",
                       "add": [{"row": f"NSA_{new_id}", "cloneFrom": tmpl_row,
                                "set": {"ID": new_id, "LevelSequence": level_seq,
                                        "soundSequence": sound_seq}}]})
    old_prefix = rel_dir or ""
    for f in have_seq:
        kind = f.replace(f"SEQ_Battle_{seq_src + 1}_", "").replace(".uasset", "")
        track = "" if kind == "Master" else "Track/"
        clones.append({
            "from": f"FFRS/Content/{old_prefix}/{track}{f[:-7]}",
            "to": f"FFRS/Content/{seq_dir}/{track}SEQ_Battle_{new_id + 1}_{kind}",
            "rename": [[old_prefix, seq_dir],
                       [f"SEQ_Battle_{seq_src + 1}", f"SEQ_Battle_{new_id + 1}"]]})
    if not seq_src:
        log(f"⚠ 技能 {donor_id} 与槽位原技能都没有演出资产：新技能将没有动画/特效")
    return {"tables": tables, "clones": clones, "legacy": legacy,
            "have_seq": len(have_seq), "donor_row": donor_row, "seq_dir": seq_dir}


def make_new_skill(donor_id: int, new_id: int, slot_sets: list, out_name: str,
                   effect_swap: dict | None = None, log=print,
                   fallback_seq_ids: list | None = None,
                   name: str | None = None, desc: str | None = None) -> list:
    """donor_id: 源技能；new_id: 新技能 ID；slot_sets: [{'table','row','set':{path:val}}]
    effect_swap: {技能ID: 新演出路径} 用于"换演出"（改 DT_SkillAsset 软路径）"""
    check_tools()
    work = CACHE / "newskill"
    shutil.rmtree(work, ignore_errors=True)
    (work / "legacy").mkdir(parents=True)
    legacy = work / "legacy"
    out_root = work / "out"
    out_root.mkdir()

    # 1) 抽需要的表 + 源的演出树
    tables = {"DT_SkillData", "DT_SkillAsset"}
    for s in slot_sets:
        tables.add(s["table"].rsplit("/", 1)[-1])
    # 演出来源：优先源技能；没有就退回槽位原技能；再没有就"无演出"生成
    seq_src, rel_dir, cat = None, None, None
    for cand in [donor_id] + list(fallback_seq_ids or []):
        d, c = find_sequence(cand)
        if d:
            seq_src, rel_dir, cat = cand, d, c
            if cand != donor_id:
                log(f"源技能 {donor_id} 没有演出资产，改用槽位原技能 {cand} 的演出")
            break
    if not seq_src:
        log(f"⚠ 技能 {donor_id} 与槽位原技能都没有演出资产：将生成『无演出』的新技能"
            f"（能放、能造成伤害，但没有动画/特效）")
    seq_files = [f"SEQ_Battle_{seq_src + 1}_{k}.uasset" for k in SEQ_KINDS] if seq_src else []
    for f in sorted(tables) + seq_files:
        rc, o = run([RETOC, "to-legacy", _bv(), legacy, "-f", f, "--no-shaders"])
    have_seq = [f for f in seq_files if next(legacy.rglob(f), None)]
    log(f"演出资产：{len(have_seq)}/4（{', '.join(k.split('_')[-1].replace('.uasset','') for k in have_seq) or '源技能没有演出'}）")

    # 2) 行名
    sk_rows = rows_cache("DT_SkillData", work)
    donor_row = sk_rows.get(donor_id)
    if not donor_row:
        raise RuntimeError(f"DT_SkillData 里找不到源技能 {donor_id}")
    tmpl_row = skill_asset_template(work, prefer_id=donor_id)

    # 3) 演出路径（新 ID 的序列）
    seq_dir = f"Sequencer/Battle/{cat or 'Skill'}/{new_id}/{new_id + 1}"
    level_seq = f"/Game/{seq_dir}/SEQ_Battle_{new_id + 1}_Master"
    sound_seq = f"/Game/{seq_dir}/Track/SEQ_Battle_{new_id + 1}_Sound_001"

    job = {"legacyRoot": str(legacy), "outRoot": str(out_root), "tables": [], "clones": []}
    _set = {"ID": new_id}
    if name:
        _set["Name"] = name                  # ★ 字面量 FText（游戏内已验证可显示）
    if desc:
        _set["Description"] = desc
    job["tables"].append({"asset": "FFRS/Content/Datatable/Skill/DT_SkillData",
                          "add": [{"row": f"NS_{new_id}", "cloneFrom": donor_row,
                                   "set": _set}]})
    if seq_src:
        job["tables"].append({"asset": "FFRS/Content/Datatable/Asset/Skill/DT_SkillAsset",
                              "add": [{"row": f"NSA_{new_id}", "cloneFrom": tmpl_row,
                                       "set": {"ID": new_id, "LevelSequence": level_seq,
                                               "soundSequence": sound_seq}}]})
    for s in slot_sets:
        job["tables"].append({"asset": table_rel(s["table"]),
                              "set": [{"row": s["row"], "set": s["set"]}]})
    if effect_swap:
        sets = [{"row": rows_skillasset_row_for(work, sid), "set": {"LevelSequence": p}}
                for sid, p in effect_swap.items()]
        job["tables"].append({"asset": "FFRS/Content/Datatable/Asset/Skill/DT_SkillAsset",
                              "set": sets})
    # 克隆整棵演出树到新 ID 路径
    old_prefix = rel_dir or ""
    for f in have_seq:
        kind = f.replace(f"SEQ_Battle_{seq_src + 1}_", "").replace(".uasset", "")
        track = "" if kind == "Master" else "Track/"
        job["clones"].append({
            "from": f"FFRS/Content/{old_prefix}/{track}{f.replace('.uasset','')}",
            "to": f"FFRS/Content/{seq_dir}/{track}SEQ_Battle_{new_id + 1}_{kind}",
            "rename": [[old_prefix, seq_dir],
                       [f"SEQ_Battle_{seq_src + 1}", f"SEQ_Battle_{new_id + 1}"]]})

    jobp = work / "job.json"
    jobp.write_text(json.dumps(job, ensure_ascii=False, indent=1), encoding="utf-8")
    log("ffr-dt patch …")
    rc, o = run([FFRDT, "patch", jobp, "--usmap", USMAP])
    if rc != 0:
        raise RuntimeError("patch 失败：" + o[-500:])
    for line in o.strip().splitlines():
        if line.strip().startswith(("+", "~", "*", "=")):
            log("   " + line.strip())

    # 4) 打包三件套
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    if not out_name.endswith("_P"):
        out_name = out_name + "_P"        # 合并工具只认 *_P.{pak,utoc,ucas}
    utoc = OUT_DIR / f"{out_name}.utoc"
    for e in (".pak", ".utoc", ".ucas"):
        (OUT_DIR / f"{out_name}{e}").unlink(missing_ok=True)
    log("retoc to-zen …")
    rc, o = run([RETOC, "to-zen", "--version", "UE5_6", out_root, utoc])
    if rc != 0 or not utoc.exists():
        raise RuntimeError("to-zen 失败：" + o[-400:])
    stage = work / "pakstage"
    stage.mkdir(exist_ok=True)
    rc, o = run([REPAK, "pack", "-m", MOD_MOUNT, "--version", "V11", "-p", "1451793619",
                 stage, OUT_DIR / f"{out_name}.pak"], timeout=600)
    files = [OUT_DIR / f"{out_name}{e}" for e in (".pak", ".utoc", ".ucas")]
    for f in files:
        if not f.exists():
            raise RuntimeError(f"缺 {f.name}")
    try:
        remember_id(new_id)
    except Exception:
        pass
    log("完成：" + "、".join(f"{f.name}（{f.stat().st_size:,} B）" for f in files))
    return files


def rows_skillasset_row_for(work: pathlib.Path, skill_id: int) -> str:
    """给 effect_swap 用：DT_SkillAsset 里某个技能 ID 对应的行名。"""
    legacy = work / "legacy"
    run([RETOC, "to-legacy", _bv(), legacy, "-f", "DT_SkillAsset.uasset", "--no-shaders"])
    ua = next(legacy.rglob("DT_SkillAsset.uasset"), None)
    js = work / "DT_SkillAsset.json"
    run([FFRDT, "tojson", ua, js, "--usmap", USMAP])
    d = json.loads(js.read_text(encoding="utf-8"))
    for r in d["Exports"][0]["Table"]["Data"]:
        pr = {q["Name"]: q["Value"] for q in r["Value"]}
        if pr.get("ID") == skill_id:
            return r["Name"]
    raise RuntimeError(f"DT_SkillAsset 里没有技能 {skill_id} 的行")


def path_to_str(path) -> str:
    """["detailData", 4, "params", 0] → "detailData[4].params[0]" """
    out = ""
    for step in path:
        if isinstance(step, int):
            out += f"[{step}]"
        else:
            out += ("." if out else "") + str(step)
    return out


def row_names(table: str, work: pathlib.Path) -> list:
    """按行序返回该表的行名（ffr-dt tojson 一次并缓存）。"""
    cache = CACHE / f"rownames_{table}.json"
    if cache.exists():
        try:
            return json.loads(cache.read_text(encoding="utf-8"))
        except Exception:
            pass
    legacy = work / "legacy"
    legacy.mkdir(parents=True, exist_ok=True)
    run([RETOC, "to-legacy", _bv(), legacy, "-f", f"{table}.uasset", "--no-shaders"])
    ua = next(legacy.rglob(f"{table}.uasset"), None)
    if ua is None:
        raise RuntimeError(f"容器里找不到 {table}")
    js = work / f"{table}.json"
    run([FFRDT, "tojson", ua, js, "--usmap", USMAP])
    d = json.loads(js.read_text(encoding="utf-8"))
    names = [r["Name"] for r in d["Exports"][0]["Table"]["Data"]]
    CACHE.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(names, ensure_ascii=False), encoding="utf-8")
    js.unlink(missing_ok=True)
    return names


def run_fx_split(sid: int, anim_id: int, fx_id: int, out_root: pathlib.Path,
                 work: pathlib.Path, log=print, s_rel: str | None = None) -> list:
    """把「动画来自 anim、特效来自 fx」的演出克隆到技能 sid 的演出路径下（写进 out_root）。

    返回写出的相对路径列表。做法：
      1) 克隆 anim 的 4 个演出资产 → sid 目录（改名）
      2) 删掉克隆出的 sid_Effect_001
      3) 用 fx 的 Effect_001 替换它
    """
    import shutil as _sh
    out_root = pathlib.Path(out_root)
    work = pathlib.Path(work)
    if not s_rel:
        s_rel, _s_cat = find_sequence(sid)
    a_rel, a_cat = find_sequence(anim_id)
    d_rel, d_cat = find_sequence(fx_id)
    if not (s_rel and a_rel):
        raise RuntimeError(f"演出目录缺失: skill={s_rel} anim={a_rel}")
    if not d_rel:
        raise RuntimeError(f"特效来源 {fx_id} 没有演出目录")
    leg = work / f"leg_{sid}"
    out1 = work / f"out1_{sid}"
    out2 = work / f"out2_{sid}"
    for d in (leg, out1, out2):
        _sh.rmtree(d, ignore_errors=True)
        d.mkdir(parents=True)
    names = [f"SEQ_Battle_{anim_id + 1}_{k}.uasset" for k in SEQ_KINDS]
    names.append(f"SEQ_Battle_{fx_id + 1}_Effect_001.uasset")
    for n in names:
        if not next(leg.rglob(n), None):
            run([RETOC, "to-legacy", _bv(), leg, "-f", n, "--no-shaders"])
    have = [k for k in SEQ_KINDS if next(leg.rglob(f"SEQ_Battle_{anim_id + 1}_{k}.uasset"), None)]
    log(f"  分轨：动画 {anim_id}（{len(have)}/4）+ 特效 {fx_id} → 技能 {sid}")

    def rel(dir_, kind, ident, track=True):
        tr = "" if kind == "Master" else "Track/"
        return f"FFRS/Content/{dir_}/{tr}SEQ_Battle_{ident}_{kind}"

    job1 = {"legacyRoot": str(leg), "outRoot": str(out1), "tables": [], "clones": [
        {"from": rel(a_rel, k, anim_id + 1), "to": rel(s_rel, k, sid + 1),
         "rename": [[a_rel, s_rel], [f"SEQ_Battle_{anim_id + 1}", f"SEQ_Battle_{sid + 1}"]]}
        for k in have]}
    jp = work / f"job1_{sid}.json"
    jp.write_text(json.dumps(job1, ensure_ascii=False, indent=1), encoding="utf-8")
    rc, o = run([FFRDT, "patch", jp, "--usmap", USMAP])
    if rc != 0:
        raise RuntimeError("分轨克隆失败：" + o[-400:])

    # 删掉 S 的 Effect，放入 D 的 Effect 作为克隆源
    for ext in (".uasset", ".uexp"):
        (out1 / (rel(s_rel, "Effect_001", sid + 1) + ext)).unlink(missing_ok=True)
    d_eff = next(leg.rglob(f"SEQ_Battle_{fx_id + 1}_Effect_001.uasset"))
    dst = leg / rel(d_rel, "Effect_001", fx_id + 1).replace("FFRS/Content/", "")
    dst.parent.mkdir(parents=True, exist_ok=True)
    _sh.copy2(d_eff, dst)
    if d_eff.with_suffix(".uexp").exists():
        _sh.copy2(d_eff.with_suffix(".uexp"), dst.with_suffix(".uexp"))

    for p_ in out1.rglob("*"):
        if p_.is_file():
            r = p_.relative_to(out1)
            (out2 / r).parent.mkdir(parents=True, exist_ok=True)
            _sh.copy2(p_, out2 / r)
    job2 = {"legacyRoot": str(leg), "outRoot": str(out2), "tables": [], "clones": [{
        "from": rel(d_rel, "Effect_001", fx_id + 1), "to": rel(s_rel, "Effect_001", sid + 1),
        "rename": [[d_rel, s_rel], [f"SEQ_Battle_{fx_id + 1}", f"SEQ_Battle_{sid + 1}"]]}]}
    jp2 = work / f"job2_{sid}.json"
    jp2.write_text(json.dumps(job2, ensure_ascii=False, indent=1), encoding="utf-8")
    rc, o = run([FFRDT, "patch", jp2, "--usmap", USMAP])
    if rc != 0:
        raise RuntimeError("分轨特效替换失败：" + o[-400:])

    written = []
    for p_ in out2.rglob("*"):
        if p_.is_file():
            r = p_.relative_to(out2)
            (out_root / r).parent.mkdir(parents=True, exist_ok=True)
            _sh.copy2(p_, out_root / r)
            written.append(str(r).replace("\\", "/"))
    return written


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--donor", type=int, required=True, help="源技能 ID（如 220170 疾风）")
    ap.add_argument("--new", type=int, required=True, help="新技能 ID（如 229001）")
    ap.add_argument("--slot-table", default="", help="槽位表名，如 DT_VisionAwakeningMasteryData")
    ap.add_argument("--slot-row", default="", help="槽位表行名")
    ap.add_argument("--slot-path", default="", help="槽位字段路径，如 detailData[4].params[0]")
    ap.add_argument("--out", default="zzz_NewSkill_P", help="输出三件套前缀")
    a = ap.parse_args()
    slots = []
    if a.slot_table and a.slot_row and a.slot_path:
        slots.append({"table": a.slot_table, "row": a.slot_row, "set": {a.slot_path: a.new}})
    make_new_skill(a.donor, a.new, slots, a.out)


if __name__ == "__main__":
    main()
