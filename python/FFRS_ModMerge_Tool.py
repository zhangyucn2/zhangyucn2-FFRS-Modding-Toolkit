"""FFRS MOD 合并工具（多 MOD → 一个三件套）

为什么另起一个工具：`FFRS_VideoMod_Tool.py` 里的「MOD合并」只能合**一个**，原因是它
  ① 中途目录写死成 `merge_src/merge_legacy`（第二次合并覆盖第一次）
  ② 只对 `.utoc` 做 `to-legacy` 抽 IoStore 资产，**完全忽略 `.pak` 里的 NonUFS**
     （`.usm` 影片、`Game.locres` 文本都在 .pak 里）→ 视频/文本 MOD 合进去等于没合

本工具的做法（都不重 cook，字节原样搬运）：
  * `.pak`  → `repak unpack` 每个源 → 合并目录 → `repak pack`（基础 pak 的 mount/seed）
  * `.utoc` → `retoc unpack-raw` 每个源 → 合并 chunks + manifest → `retoc pack-raw`
  * 这样每个源里的 chunk 头/uasset 一个字节都不变，游戏一定认（见 docs/memory/ffrs-textmod-tool.md
    「to-zen 重 cook 会导致 chunk 头变化 → 容器被静默忽略」）

角色线索：从 pak 条目路径 + utoc chunk 路径里抽 ID（`MV_Skill440010`、`skl440010`、
`SEQ_Battle_440011`、`DT_BtlEv_440010`、`summon13100`、`unit0010`…），再用
`_text_cache/support/vision_skill.json` 把「LB 技能 → 幻兵」对上；文本 MOD（locres）
会解析出被改过的 key（`UnitName13100` 之类）一起算。**不同角色的 MOD 会弹确认框**，不静默合并。

也支持「依次合并」：本工具产出的三件套本身就是合法的源，可以继续跟下一个 MOD 合。

用法：python FFRS_ModMerge_Tool.py
"""
import json
import re
import shutil
import subprocess
import sys
import threading
from pathlib import Path

APP_DIR = (Path(sys.executable).resolve().parent if getattr(sys, "frozen", False)
           else Path(__file__).resolve().parent)
SETTINGS = APP_DIR / "ffrs_modmerge_settings.json"
try:
    import kit.settings as _KIT
    SETTINGS = _KIT.state_file("ffrs_modmerge_settings.json")
except Exception:
    pass
CACHE = APP_DIR / "_merge_cache"
try:
    import kit.settings as _K3
    CACHE = _K3.cache_root() / "merge"
except Exception:
    pass
OUT_DIR = APP_DIR / "Output"
# ★ 路径统一由 Toolkit 首页提供（禁止在 python/ 下自建 Output）
try:
    import kit.settings as _K
    OUT_DIR = _K.output_mods()
    if "_BASE_VIEW_P" not in globals():
        _BASE_VIEW_P = str(_K.get("base_view") or "")
except Exception:
    pass

MOUNT = "../../../"


MERGE_HELP_EN = """[Which function to use]
· Skills / visions / awakening / LB (DataTable changes) -> "Smart merge (skills/data)..."
· Video (.usm) / sprites / textures / audio / text (locres) -> "Merge" (original, chunk/pak copy)
· Both kinds: smart-merge skills first, then use "Merge" for non-skill mods only
              (or simply install the two packages side by side)

[Smart merge steps]
1. Select 2+ skill mods
2. Click "Scan new skills" -> lists new skill IDs
   · Mods built by this toolkit auto-fill "ID:anim:fx" (from fx_sources.json)
   · Unknown ones show as "229xxx:" and must be filled manually
3. Complete the mapping, then click "Start merge"
4. Output: Output/NEWMOD/<name>_P.{pak,utoc,ucas}

[Mapping format]
  newSkillID:animationSourceID:effectSourceID
  · "ID:anim" only -> effect uses the animation source
  · Missing mapping aborts with an error (no broken no-animation package)

[Why mapping is required]
New-skill visuals are brand-new chunks; the toolkit must regenerate the
sequence assets and pack them with to-zen.

[Notes]
· Never "Merge" skill mod + skill mod (same table overrides)
· "Merge" output has no ContainerHeader; replacements only.
  New sequence chunks must go through Smart merge (to-zen)
· TextMod only changes locres + subtitle timeline chunks; it is not treated as a skill mod
· Same path from two sources: the later one wins (logged)"""

MERGE_HELP = """【选哪个功能】
· 技能/幻兵/觉醒/终结技（改 DataTable 的）  → 「智能合并（技能/数据）…」
· 视频(.usm) / 精灵片 / 贴图 / 音频 / 文本(locres)
                                              → 「合并」（原功能，chunk/pak 原样搬运）
· 两类都有：先智能合并技能 → 得到技能包；
           再用「合并」把技能包排除，只合无技能 MOD
           （或直接同时安装两个包，效果相同）

【智能合并流程】
1. 勾选要合并的技能 MOD（≥2 个）
2. 点「扫描新技能」→ 自动列出新技能 ID
   · 本工具生成的 MOD 会自动带出「ID:动画源:特效源」（读 fx_sources.json）
   · 查不到记录的会显示成 "229xxx:"，需要手填
3. 补全映射后点「开始合并」
4. 产物：Output/NEWMOD/<名字>_P.{pak,utoc,ucas}

【映射怎么填】
  新技能ID:动画源ID:特效源ID
  · 只写 ID:动画源   → 特效用动画源自己的
  · 动画/特效源就是“借谁的演出”，如 229009:420070:220170
  · 缺失映射时工具会直接报错并中止（不会产出没动画的坏包）

【为什么缺映射不行】
新技能的演出是全新 chunk，必须由本工具重新生成序列资产并 to-zen 打包；
只搬表不加演出 → 进游戏没有动画/特效。

【注意】
· 不要用「合并」去合“技能 MOD + 技能 MOD”：同表会互相覆盖
· 「合并」产出的容器没有 ContainerHeader，只适合替换型内容；
  新增演出 chunk 必须走智能合并（to-zen）
· TextMod 只改 locres + 字幕时间轴，不会被当成技能 MOD；
  它会正常并进「合并」的 pak/替换 chunk
· 同一路径被两个源改过时，后者覆盖前者（日志会提示）"""




def run(cmd, timeout=1800):
    p = subprocess.run([str(c) for c in cmd], capture_output=True, timeout=timeout)
    out = (p.stdout or b"").decode("utf-8", "replace") + (p.stderr or b"").decode("utf-8", "replace")
    return p.returncode, out


# ──────────────────────────── 三件套识别 ────────────────────────────
def find_sets(path: Path) -> list:
    """从目录或文件里找出所有三件套（同前缀的 pak/utoc/ucas 归一组）。"""
    path = Path(path)
    files = []
    if path.is_file():
        files = [path]
        if path.suffix.lower() in (".pak", ".utoc", ".ucas"):
            stem = path.with_suffix("")
            for ext in (".pak", ".utoc", ".ucas"):
                q = stem.with_suffix(ext)
                if q.exists():
                    files.append(q)
    else:
        files = sorted(path.glob("*_P.*")) or sorted(path.glob("*.utoc"))
    groups = {}
    for f in files:
        if f.suffix.lower() in (".pak", ".utoc", ".ucas"):
            key = f.with_suffix("")
            groups.setdefault(str(key), {})[f.suffix.lower()] = f
    out = []
    for k, v in groups.items():
        if ".utoc" in v or ".pak" in v:
            out.append({"name": Path(k).name, "pak": v.get(".pak"), "utoc": v.get(".utoc"),
                        "ucas": v.get(".ucas")})
    return out


# ──────────────────────────── 角色线索 ────────────────────────────
SKILL_PATTERNS = [
    # ★ 顺序有讲究：长的先匹配，并且 SkillName 用后顾断言防止吃进 MasterSkillName1310000 的后半段
    (re.compile(r"MasterSkill(?:Name|Description)(\d{7})", re.I), "master"),
    (re.compile(r"MV_(?:Skill|Summon|Legend)?(\d{6})", re.I), "skill"),
    (re.compile(r"skl(\d{6})", re.I), "skill"),
    (re.compile(r"SEQ_Battle_(\d{6})", re.I), "phase"),
    (re.compile(r"DT_BtlEv_(\d{6})", re.I), "skill"),
    (re.compile(r"(?<![A-Za-z])SkillName(\d{6})", re.I), "skill"),
    (re.compile(r"(?:summon|unit|pc|npc)(\d{4,5})", re.I), "unit"),
    (re.compile(r"(?:UnitName|VisionName|UnitDescription|VisionDescription)(\d{3,5})", re.I), "unit"),
]


def load_vision_skill() -> dict:
    """{幻兵ID: LB技能ID}（工具跑过一次解析后就有；没有就返回空）"""
    p = CACHE.parent / "_text_cache" / "support" / "vision_skill.json"
    if p.exists():
        try:
            return {int(k): int(v) for k, v in json.loads(p.read_text(encoding="utf-8")).items()}
        except Exception:
            pass
    return {}


def clues_from_paths(paths, vision_skill: dict) -> dict:
    """从路径/文本 key 里抽角色线索 → {角色token: 证据集合}。

    ★ 归一：同一个 id 既可能以「单位13100」也可能以「幻兵13100」出现（召唤物/幻兵共用 id），
      只要该 id 在 vision_skill 的**键**里，就统一成「幻兵xxxx」，避免被当成两个角色。
    """
    inv = {v: k for k, v in vision_skill.items()}
    chars = {}

    def tok_of(kind, raw):
        num = int(raw)
        if kind == "master":
            num = num // 100 if num >= 100 and num % 100 == 0 else num
        if kind == "phase":
            sid = num - 1
        elif kind == "skill":
            sid = num
        else:
            sid = None
        if sid is not None and sid in inv:
            return f"幻兵{inv[sid]}"
        if num in vision_skill:          # num 本身就是幻兵 id
            return f"幻兵{num}"
        if kind in ("skill", "phase") and sid is not None:
            return f"技能{sid}"
        return f"单位{num}"

    for s in paths:
        for rx, kind in SKILL_PATTERNS:
            for m in rx.finditer(s):
                chars.setdefault(tok_of(kind, m.group(1)), set()).add(f"{kind}:{m.group(1)}")
    return chars


def clues_from_locres(pak: Path, repak: Path, work: Path, base_locres: dict, log) -> dict:
    """文本 MOD：解出 pak 里的 Game.locres，和基础 locres 比对，找出被改过的 key。"""
    try:
        sys.path.insert(0, str(APP_DIR))
        import FFRS_TextMod_Tool as TT     # 复用 locres 解析
    except Exception as e:
        log(f"    （跳过 locres 分析：{e}）")
        return {}
    d = work / "locres_probe"
    shutil.rmtree(d, ignore_errors=True)
    d.mkdir(parents=True, exist_ok=True)
    rc, out = run([repak, "unpack", pak, "-o", d, "-f", "-i", "FFRS/Content/Localization/Game"], timeout=600)
    langs = list(d.rglob("Game.locres"))
    if not langs:
        return {}
    changed_keys = set()
    # ★ 必须遍历**所有语言**：文本 MOD 往往只改 zh-Hans，只取第一个（en）会永远没线索
    for lp in langs:
        lang = lp.parent.name
        base = base_locres.get(lang)
        if base is None:
            continue
        try:
            mod = TT.Locres(lp)
        except Exception as e:
            log(f"    （locres 解析失败：{e}）")
            continue
        for nk in mod.index:
            if base.text(*nk) != mod.text(*nk):
                changed_keys.add(nk[1])
    chars = clues_from_paths(changed_keys, load_vision_skill())
    if changed_keys and not chars:
        chars["未知（文本 key 无 ID）"] = set(list(changed_keys)[:3])
    chars["_n"] = {len(changed_keys)}
    return chars


# ──────────────────────────── Game.locres 智能合并 ────────────────────────────
def _locres_edits(loc, base_loc) -> dict:
    """相对于基础 locres 的改动 {key: text}。"""
    out = {}
    for nk in loc.index:
        v = loc.text(*nk)
        if base_loc.text(*nk) != v:
            out[nk] = v
    return out


def merge_locres(dst: Path, src: Path, base_loc, log) -> bool:
    """把 src 的改动并进 dst（同一 key 以 src 为准），返回是否成功。

    为什么需要：文本 MOD 的 pak 里装的是**完整 Game.locres**（只含自己那几条改动），
    两个角色的文本 MOD 同路径 → 直接覆盖会把前一个角色的改动丢掉。
    """
    if base_loc is None:
        return False
    try:
        sys.path.insert(0, str(APP_DIR))
        import FFRS_TextMod_Tool as TT
        cur, inc = TT.Locres(dst), TT.Locres(src)
    except Exception as e:
        log(f"    （locres 合并不可用：{e}）")
        return False
    a = _locres_edits(cur, base_loc)
    b = _locres_edits(inc, base_loc)
    if not b:
        log(f"    {dst.name}: 后加入的源没有改动，保留现有的 {len(a)} 条")
        return True
    merged = dict(a)
    merged.update(b)          # 同一 key 以后加入的为准
    base_loc.save_with_edits(dst, merged)
    TT.Locres.verify(dst, merged, base_loc)
    log(f"    {dst.name}: 文本合并 {len(a)} + {len(b)} 条 → 共 {len(merged)} 条"
        f"（{dst.parent.name}，回读校验通过）")
    return True


# ──────────────────────────── 合并 ────────────────────────────
def analyze(sources, repak, retoc, base_locres, log):
    """为每个源收集：pak 条目、chunk 列表、角色线索。"""
    CACHE.mkdir(parents=True, exist_ok=True)
    for i, src in enumerate(sources):
        w = CACHE / f"ana_{i}"
        shutil.rmtree(w, ignore_errors=True)
        w.mkdir(parents=True)
        entries, chunks, paths = [], {}, []
        if src["pak"]:
            d = w / "pak"
            rc, out = run([repak, "unpack", src["pak"], "-o", d, "-f"], timeout=1800)
            for f in d.rglob("*"):
                if f.is_file():
                    rel = f.relative_to(d).as_posix()
                    entries.append(rel)
                    paths.append(rel)
        if src["utoc"]:
            d = w / "raw"
            rc, out = run([retoc, "unpack-raw", src["utoc"], d], timeout=1800)
            man = d / "manifest.json"
            if man.exists():
                meta = json.loads(man.read_text(encoding="utf-8"))
                for cid, p in (meta.get("chunk_paths") or {}).items():
                    chunks[cid] = p
                    paths.append(str(p))
        clues = clues_from_paths(paths, load_vision_skill())
        n_tex = 0
        if src["pak"]:
            for tok, ev in clues_from_locres(src["pak"], repak, w, base_locres, log).items():
                if tok == "_n":
                    n_tex = max(ev)
                    continue
                clues.setdefault(tok, set()).update(ev)
        src["n_tex"] = n_tex
        src.update({"entries": entries, "chunks": chunks, "clues": clues, "paths": paths})
        log(f"  {src['name']}：pak {len(entries)} 条 / chunk {len(chunks)} 个 / "
            f"文本改动 {n_tex} 处 / 角色线索 " + ("、".join(sorted(clues)) or "无"))
    return sources


def merge(sources, out_name, repak, retoc, paks_dir, log, base_locres=None) -> list:
    stage = CACHE / "merge_pak"
    rawd = CACHE / "merge_raw"
    shutil.rmtree(stage, ignore_errors=True)
    shutil.rmtree(rawd, ignore_errors=True)
    stage.mkdir(parents=True)
    (rawd / "chunks").mkdir(parents=True)

    seen_pak, seen_chunk, chunk_paths = {}, {}, {}
    conflicts = []
    for i, src in enumerate(sources):
        w = CACHE / f"ana_{i}"
        d = w / "pak"
        if d.exists():
            for f in d.rglob("*"):
                if not f.is_file():
                    continue
                rel = f.relative_to(d)
                dst = stage / rel
                dst.parent.mkdir(parents=True, exist_ok=True)
                if rel.as_posix() in seen_pak:
                    is_locres = rel.name == "Game.locres" and dst.exists()
                    base_loc = (base_locres or {}).get(rel.parent.name)
                    if is_locres and base_loc is not None:
                        if merge_locres(dst, f, base_loc, log):
                            seen_pak[rel.as_posix()] = seen_pak[rel.as_posix()] + "+" + src["name"]
                            continue
                    conflicts.append(f"pak 路径重复：{rel.as_posix()}（{seen_pak[rel.as_posix()]} → {src['name']}，以后者为准）")
                seen_pak[rel.as_posix()] = src["name"]
                shutil.copy2(f, dst)
        d = w / "raw" / "chunks"
        if d.exists():
            for f in d.iterdir():
                if not f.is_file():
                    continue
                if f.name.endswith("00000006"):
                    continue                      # ContainerHeader：pack-raw 自己会生成，别抄
                if not f.name.endswith("00000001"):
                    continue                      # 只搬 ExportBundleData
                if f.name in seen_chunk:
                    conflicts.append(f"同一资产被两个 MOD 改过：chunk {f.name[:8]}…"
                                     f"（{seen_chunk[f.name]} → {src['name']}，以后者为准）")
                seen_chunk[f.name] = src["name"]
                pth = (src.get("chunks") or {}).get(f.name) or ""
                if pth:
                    chunk_paths[f.name] = pth
                shutil.copy2(f, rawd / "chunks" / f.name)

    for c in conflicts:
        log("  ⚠ " + c)
    # 每个源贡献了多少 chunk（防"源被静默跳过"）
    per = {}
    for cid, who in seen_chunk.items():
        per[who] = per.get(who, 0) + 1
    for src in sources:
        n_src = len(src.get("chunks") or {})
        got = per.get(src["name"], 0)
        log(f"  {src['name']}：源有 {n_src} 个 chunk，并进 {got} 个")
        if n_src and got == 0:
            log(f"  ⚠ {src['name']} 一个 chunk 都没并进来（检查它是否真的被加进列表）")
    log(f"  合计：{len(seen_pak)} 个 pak 条目 + {len(seen_chunk)} 个 chunk")
    if not seen_pak and not seen_chunk:
        raise RuntimeError("两个源都是空的，没东西可合")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    pak_out = OUT_DIR / f"{out_name}_P.pak"
    utoc_out = OUT_DIR / f"{out_name}_P.utoc"
    ucas_out = OUT_DIR / f"{out_name}_P.ucas"
    for f in (pak_out, utoc_out, ucas_out):
        if f.exists():
            f.unlink()

    # pak
    if seen_pak:
        seed = 1451793619
        rc, out = run([repak, "info", Path(paks_dir) / "FFRS-Windows.pak"], timeout=120)
        m = re.search(r"path hash seed:\s*(?:Some\()?\s*(0x)?([0-9A-Fa-f]+)", out)
        if m:
            seed = int(m.group(2), 16) if (m.group(1) or re.search(r"[A-Fa-f]", m.group(2))) else int(m.group(2))
        log(f"  repak pack（{len(seen_pak)} 条目，seed={seed}）…")
        rc, out = run([repak, "pack", "-m", MOUNT, "--version", "V11", "-p", str(seed), stage, pak_out])
        if not pak_out.exists():
            raise RuntimeError("repak pack 失败：" + out[-300:])
    else:
        log("  （所有源都没有 pak 内容，跳过 .pak）")

    # utoc / ucas
    if seen_chunk:
        (rawd / "manifest.json").write_text(json.dumps({
            "chunk_paths": chunk_paths, "version": "ReplaceIoChunkHashWithIoHash",
            "mount_point": MOUNT}, indent=2), encoding="utf-8")
        log(f"  retoc pack-raw（{len(seen_chunk)} 个 chunk）…")
        rc, out = run([retoc, "pack-raw", rawd, utoc_out])
        if not utoc_out.exists():
            raise RuntimeError("pack-raw 失败：" + out[-300:])
    else:
        log("  （所有源都没有 IoStore 资产，跳过 .utoc/.ucas）")
    # 合并后自检：文本改动条数、有没有序列（时间轴）资产
    if pak_out.exists() and base_locres:
        try:
            d = CACHE / "verify_locres"
            shutil.rmtree(d, ignore_errors=True); d.mkdir(parents=True)
            run([repak, "unpack", pak_out, "-o", d, "-f"], timeout=900)
            sys.path.insert(0, str(APP_DIR))
            import FFRS_TextMod_Tool as TT
            n_all = 0
            for lp in d.rglob("Game.locres"):
                lang = lp.parent.name
                bl = (base_locres or {}).get(lang)
                if bl is None:
                    continue
                L = TT.Locres(lp)
                n_all += sum(1 for k in L.index if bl.text(*k) != L.text(*k))
            log(f"  ✅ 合并后文本改动 {n_all} 处")
            if n_all == 0:
                log("  ⚠ 合并后 locres 没有任何改动 —— 说明你加的源里没有带文本的 MOD")
        except Exception as e:
            log(f"  （文本自检跳过：{e}）")
    if seen_chunk:
        seq = [c for c, pth in chunk_paths.items() if "SEQ_Battle" in str(pth)]
        if seq:
            log(f"  ✅ 含战斗序列资产 {len(seq)} 个（时间轴能生效）")
        else:
            log("  ⚠ 合并后没有任何 SEQ_Battle_* 序列资产 —— 字幕时间轴不会生效")
    return [x for x in (pak_out, utoc_out, ucas_out) if x.exists()]


# ──────────────────────────── 界面 ────────────────────────────
def load_settings():
    d = {"game_root": "", "repak": str(APP_DIR / "repak.exe"), "retoc": str(APP_DIR / "retoc.exe"),
         "out_name": "MergedMod"}
    if SETTINGS.exists():
        try:
            d.update(json.loads(SETTINGS.read_text(encoding="utf-8")))
        except Exception:
            pass
    return d


class App:
    def __init__(self, host=None):
        self._host = host
        import tkinter as tk
        from tkinter import ttk
        self.tk, self.ttk = tk, ttk
        self.st = load_settings()
        self.sources = {}
        self._sid = 0
        self._build()

    def _build(self):
        tk, ttk = self.tk, self.ttk
        self.root = getattr(self, "_host", None) or tk.Tk()
        self.root.title("FFRS MOD 合并工具 v1.0（多 MOD → 一个三件套）")
        self.root.geometry("1080x680")

        top = ttk.LabelFrame(self.root, text="① 环境")
        top.pack(fill="x", padx=8, pady=6)
        ttk.Label(top, text="游戏目录").grid(row=0, column=0, sticky="w", padx=4)
        self.v_root = tk.StringVar(value=self.st["game_root"])
        ttk.Entry(top, textvariable=self.v_root, width=60).grid(row=0, column=1, sticky="we", padx=4)
        ttk.Button(top, text="指定…", command=self.pick_root).grid(row=0, column=2, padx=4)
        ttk.Label(top, text="repak").grid(row=1, column=0, sticky="w", padx=4)
        self.v_repak = tk.StringVar(value=self.st["repak"])
        ttk.Entry(top, textvariable=self.v_repak, width=40).grid(row=1, column=1, sticky="we", padx=4)
        ttk.Label(top, text="retoc").grid(row=1, column=2, sticky="e", padx=4)
        self.v_retoc = tk.StringVar(value=self.st["retoc"])
        ttk.Entry(top, textvariable=self.v_retoc, width=40).grid(row=1, column=3, sticky="we", padx=4)
        top.columnconfigure(1, weight=1)
        top.columnconfigure(3, weight=1)

        mid = ttk.LabelFrame(self.root, text="② 待合并的 MOD（可加多个；也支持依次合并：把上次的产物再当源加进来）")
        mid.pack(fill="both", expand=True, padx=8, pady=4)
        self.tree = ttk.Treeview(mid, columns=("pak", "chunk", "clue"), show="tree headings", height=10)
        _en = False
        try:
            import kit.settings as _KS
            _en = str(_KS.get("ui_lang") or "zh") == "en"
        except Exception:
            pass
        self.tree.heading("#0", text="Source / location" if _en else "源 / 位置")
        self.tree.heading("pak", text="pak entries" if _en else "pak 条目")
        self.tree.heading("chunk", text="chunk")
        self.tree.heading("clue", text="Character clue" if _en else "角色线索")
        self.tree.column("#0", width=430)
        self.tree.column("pak", width=80, anchor="center")
        self.tree.column("chunk", width=70, anchor="center")
        self.tree.column("clue", width=380)
        self.tree.pack(side="left", fill="both", expand=True)
        sb = ttk.Scrollbar(mid, orient="vertical", command=self.tree.yview)
        sb.pack(side="right", fill="y")
        self.tree.configure(yscrollcommand=sb.set)

        helpf = ttk.LabelFrame(self.root, text="使用说明（哪种 MOD 用哪个合并 / 智能合并流程）")
        helpf.pack(fill="x", padx=8, pady=(2, 0))
        help_t = tk.Text(helpf, height=10, wrap="word", font=("Microsoft YaHei UI", 9))
        help_sb = ttk.Scrollbar(helpf, orient="vertical", command=help_t.yview)
        help_t.configure(yscrollcommand=help_sb.set)
        help_sb.pack(side="right", fill="y")
        help_t.pack(side="left", fill="both", expand=True)
        try:
            import kit.settings as _KS
            _txt = MERGE_HELP_EN if str(_KS.get("ui_lang") or "zh") == "en" else MERGE_HELP
        except Exception:
            _txt = MERGE_HELP
        help_t.insert("1.0", _txt)
        help_t.configure(state="disabled")

        bar = ttk.Frame(self.root)
        bar.pack(fill="x", padx=8, pady=2)
        ttk.Button(bar, text="添加 MOD…", command=self.add_dir).pack(side="left", padx=3)
        ttk.Button(bar, text="刷新 Output", command=self.refresh_output).pack(side="left", padx=3)
        ttk.Button(bar, text="移除选中", command=self.remove_sel).pack(side="left", padx=3)
        ttk.Button(bar, text="分析", command=self.on_analyze).pack(side="left", padx=12)
        ttk.Label(bar, text="输出名").pack(side="left", padx=(16, 2))
        self.v_name = tk.StringVar(value=self.st["out_name"])
        ttk.Entry(bar, textvariable=self.v_name, width=22).pack(side="left")
        ttk.Button(bar, text="合并", command=self.on_merge).pack(side="left", padx=8)
        ttk.Button(bar, text="智能合并（技能/数据）…", command=self.on_smart_merge).pack(side="left", padx=8)

        # ★ 环境统一由首页提供
        try:
            import kit.settings as _K
            _tools = _K.get("tools_dir")
            self.v_root.set(str(_K.get("game_root")))
            self.v_repak.set(str(_tools + "/repak.exe"))
            self.v_retoc.set(str(_tools + "/retoc.exe"))
        except Exception:
            pass
        try:
            top.pack_forget()
        except Exception:
            pass
        logf = ttk.LabelFrame(self.root, text="③ 日志")
        logf.pack(fill="both", expand=False, padx=8, pady=6)
        self.log_t = tk.Text(logf, height=14, wrap="word")
        self.log_t.pack(side="left", fill="both", expand=True)
        sb2 = ttk.Scrollbar(logf, orient="vertical", command=self.log_t.yview)
        sb2.pack(side="right", fill="y")
        self.log_t.configure(yscrollcommand=sb2.set)
        self.log("提示：合并前会自动分析每个源，若角色线索不一致会弹确认框（仍可强制合并）。")
        self.root.after(300, self.refresh_output)

    def log(self, msg):
        try:
            import kit.i18n as _I
            msg = _I.tr_log(msg)
        except Exception:
            pass
        def _do():
            self.log_t.insert("end", str(msg) + "\n")
            self.log_t.see("end")
        try:
            self.root.after(0, _do)
        except Exception:
            print(msg)

    def refresh_output(self):
        """从工具集的 Output/NEWMOD 里刷新已有的 MOD 三件套。"""
        try:
            import kit.settings as _K
            d = _K.output_mods()
        except Exception:
            d = pathlib.Path(self.st.get("add_dir") or ".")
        try:
            sets = find_sets(d)
        except Exception as e:
            self.log(f"刷新失败：{e}")
            return
        if not sets:
            self.log(f"刷新：{d} 里还没有 MOD 三件套")
            return
        self._add(sets)
        self.log(f"刷新：{d} 里发现 {len(sets)} 个 MOD")

    def pick_root(self):
        from tkinter import filedialog
        d = filedialog.askdirectory(title="选游戏根目录")
        if d:
            self.v_root.set(d)

    def _add(self, sets):
        added = 0
        for s in sets:
            if any(x["name"] == s["name"] and x.get("utoc") == s.get("utoc")
                   for x in self.sources.values()):
                continue
            self._sid += 1
            self.sources[self._sid] = s
            self.tree.insert("", "end", text=s["name"], values=("?", "?", "（未分析）"),
                             tags=(str(self._sid),))
            added += 1
        self.log(f"已加入 {added} 个源，共 {len(self.sources)} 个")

    def add_dir(self):
        from tkinter import filedialog
        d = filedialog.askdirectory(title="选 MOD 所在目录（自动找 *_P.三件套）")
        if d:
            sets = find_sets(Path(d))
            if not sets:
                self.log("这个目录里没找到 *_P.pak / *_P.utoc")
                return
            self._add(sets)

    def remove_sel(self):
        sel = list(self.tree.selection())
        if not sel:
            self.log("先选中要移除的源")
            return
        for it in sel:
            tags = self.tree.item(it, "tags")
            if tags:
                self.sources.pop(int(tags[0]), None)
            self.tree.delete(it)
        self.log(f"已移除 {len(sel)} 个，剩余 {len(self.sources)} 个源")

    def _paths(self):
        root = Path(self.v_root.get().strip())
        paks = root / "FFRS" / "Content" / "Paks"
        if not paks.exists():
            paks = root / "Content" / "Paks"
        if not paks.exists():
            raise RuntimeError("游戏目录下找不到 FFRS/Content/Paks")
        repak, retoc = Path(self.v_repak.get()), Path(self.v_retoc.get())
        if not repak.exists():
            raise RuntimeError("repak.exe 路径不对")
        if not retoc.exists():
            raise RuntimeError("retoc.exe 路径不对")
        return paks, repak, retoc

    def _base_locres(self, paks, repak):
        try:
            sys.path.insert(0, str(APP_DIR))
            import FFRS_TextMod_Tool as TT
            loc = TT.extract_locres(paks, repak, lambda *_a: None)
            return {lang: TT.Locres(p) for lang, p in loc.items()}
        except Exception:
            return {}

    def on_analyze(self):
        if not self.sources:
            self.log("先添加 MOD")
            return
        threading.Thread(target=self._analyze_job, daemon=True).start()

    def _analyze_job(self):
        try:
            paks, repak, retoc = self._paths()
            base = self._base_locres(paks, repak)
            self.log("分析中 …")
            analyze(list(self.sources.values()), repak, retoc, base, self.log)
            self.root.after(0, self._refresh)
        except Exception as e:
            self.log("分析失败：" + str(e))

    def _refresh(self):
        for it in self.tree.get_children():
            tags = self.tree.item(it, "tags")
            if not tags:
                continue
            s = self.sources.get(int(tags[0]))
            if s is None:
                self.tree.delete(it)
                continue
            self.tree.item(it, values=(len(s.get("entries") or []), len(s.get("chunks") or {}),
                                        "、".join(sorted(s.get("clues") or {})) or "无"))

    def on_smart_merge(self):
        """技能/数据 MOD 智能合并：行级合并表 + 重建演出 + to-zen（实验功能）。"""
        import subprocess, sys
        top = self.tk.Toplevel(self.root)
        top.title("智能合并（技能/数据）")
        top.geometry("720x560")
        self.ttk.Label(top, text="选择要合并的 MOD（Output/NEWMOD 或输入目录里的 *​_P.utoc）").pack(anchor="w", padx=8, pady=(8, 2))
        stems = sorted({p.name[:-7] for p in OUT_DIR.glob("*_P.utoc")} |
                       {p.name[:-7] for p in Path(self.st.get("in_dir") or ".").glob("*_P.utoc")}) if OUT_DIR.exists() else []
        lb = self.tk.Listbox(top, selectmode="extended", height=12)
        for sname in stems:
            lb.insert("end", sname)
        lb.pack(fill="both", expand=True, padx=8)
        self.ttk.Label(top, text="新技能映射（每行：新技能ID:动画源ID:特效源ID；没有可留空）").pack(anchor="w", padx=8, pady=(8, 2))
        mp = self.tk.Text(top, height=5, wrap="word")
        mp.pack(fill="x", padx=8)
        def scan():
            sel = [lb.get(i) for i in lb.curselection()]
            if not sel:
                self.log("先选 MOD")
                return
            self.log("扫描新技能：" + " + ".join(sel))
            args = [sys.executable, str(APP_DIR / "merge_smart.py"), "--scan"] + sel

            def work():
                try:
                    r = subprocess.run(args, cwd=str(APP_DIR.parent), capture_output=True, timeout=3600)
                    out = (r.stdout or b"").decode("utf-8", "replace")
                    ids = []
                    for line in out.splitlines():
                        if line.startswith("NEW_SKILLS:"):
                            ids = [x for x in line.split(":", 1)[1].split(",") if x]
                    if ids:
                        rec = {}
                        try:
                            import kit.settings as _K2
                            _f = _K2.cache_root() / "fx_sources.json"
                            if _f.exists():
                                rec = json.loads(_f.read_text(encoding="utf-8"))
                        except Exception:
                            rec = {}
                        lines = []
                        for i in ids:
                            r = rec.get(str(i)) or {}
                            if r.get("anim"):
                                lines.append(f"{i}:{r['anim']}:{r.get('fx') or r['anim']}")
                            else:
                                lines.append(f"{i}:")
                        txt = "\n".join(lines)
                        self.root.after(0, lambda: (mp.delete("1.0", "end"), mp.insert("1.0", txt)))
                        miss = sum(1 for ln in lines if ln.endswith(":"))
                        self.root.after(0, lambda: self.log(
                            f"发现新技能 {len(ids)} 个，已填入映射框"
                            + ("（其中 %d 个没有构建记录，需手填动画/特效源）" % miss if miss else "（全部来自构建记录）")))
                    else:
                        self.root.after(0, lambda: self.log("没发现新技能行"))
                except Exception as e:
                    self.root.after(0, lambda: self.log(f"扫描失败：{e}"))
            threading.Thread(target=work, daemon=True).start()

        self.ttk.Label(top, text="输出名（自动加 _P）").pack(anchor="w", padx=8, pady=(8, 2))
        nv = self.tk.StringVar(value="SmartMerged")
        self.ttk.Entry(top, textvariable=nv, width=30).pack(anchor="w", padx=8)

        def do():
            sel = [lb.get(i) for i in lb.curselection()]
            if len(sel) < 2:
                self.log("至少选两个 MOD")
                return
            name = nv.get().strip() or "SmartMerged"
            args = [sys.executable, str(APP_DIR / "merge_smart.py"), name] + sel
            bad = []
            for line in mp.get("1.0", "end").splitlines():
                line = line.strip()
                if not line:
                    continue
                parts = line.replace("：", ":").replace("，", ",").replace(",", ":").split(":")
                a = parts[0].strip() if parts else ""
                b = parts[1].strip() if len(parts) > 1 else ""
                c = parts[2].strip() if len(parts) > 2 else ""
                if a and b:
                    args += ["--skill", f"{a}:{b}:{c}"]
                else:
                    bad.append(line)
            if bad:
                self.log("映射不完整（需要 新技能ID:动画源ID[:特效源ID]）：" + "、".join(bad))
                return
            top.destroy()
            self.log("智能合并开始：" + " + ".join(sel))
            self.log("  命令：" + " ".join(args[2:]))

            def work():
                try:
                    import os
                    env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUTF8="1")
                    r = subprocess.run(args, cwd=str(APP_DIR.parent), capture_output=True,
                                       timeout=7200, env=env)
                    out = (r.stdout or b"").decode("utf-8", "replace")
                    err = (r.stderr or b"").decode("utf-8", "replace")
                    self.root.after(0, lambda: [self.log(x) for x in out.strip().splitlines()[-40:]])
                    if r.returncode != 0:
                        self.root.after(0, lambda: self.log("智能合并失败：" + err[-500:]))
                    else:
                        self.root.after(0, lambda: self.log("智能合并完成 → " + str(OUT_DIR)))
                except Exception as e:
                    self.root.after(0, lambda: self.log(f"智能合并异常：{e}"))
            threading.Thread(target=work, daemon=True).start()

        bar = self.ttk.Frame(top)
        bar.pack(fill="x", padx=8, pady=8)
        self.ttk.Button(bar, text="扫描新技能", command=scan).pack(side="left", padx=4)
        self.ttk.Button(bar, text="开始合并", command=do).pack(side="right", padx=4)
        self.ttk.Button(bar, text="取消", command=top.destroy).pack(side="right", padx=4)

    def on_merge(self):
        if len(self.sources) < 2:
            self.log("至少需要两个源（依次合并的话，把上次产物当第二个源）")
            return
        threading.Thread(target=self._merge_job, daemon=True).start()

    def _merge_job(self):
        try:
            paks, repak, retoc = self._paths()
            base = self._base_locres(paks, repak)
            # 技能/数据 MOD 检测：优先智能合并，或跳过
            skill_srcs = []
            for _s in self.sources.values():
                if not _s.get("utoc"):
                    continue
                _rc, _out = run([retoc, "list", _s["utoc"], "--path"], timeout=600)
                if "DT_SkillData" in _out or "DT_SkillAsset" in _out or "/Datatable/Skill/" in _out:
                    skill_srcs.append(_s)
            if skill_srcs:
                names = "、".join(s2["name"] for s2 in skill_srcs)
                msg = (f"检测到 {len(skill_srcs)} 个包含技能/数据的 MOD：\n  {names}\n\n"
                       "「是」= 先把它们智能合并成一个技能包，再和其他 MOD 合并\n"
                       "「否」= 跳过这些技能 MOD，只合并其他 MOD")
                if self._ask(msg, title="检测到技能 MOD"):
                    import subprocess as _sp, sys as _sys, time as _time, os as _os
                    outname = "SmartSkills_" + _time.strftime("%m%d_%H%M%S")
                    args2 = [_sys.executable, str(APP_DIR / "merge_smart.py"), outname] + [s2["name"] for s2 in skill_srcs]
                    self.log("先智能合并技能：" + " + ".join(s2["name"] for s2 in skill_srcs))
                    env = dict(_os.environ, PYTHONIOENCODING="utf-8", PYTHONUTF8="1")
                    r2 = _sp.run(args2, cwd=str(APP_DIR.parent), capture_output=True, timeout=7200, env=env)
                    o2 = (r2.stdout or b"").decode("utf-8", "replace")
                    e2 = (r2.stderr or b"").decode("utf-8", "replace")
                    for line in o2.strip().splitlines()[-25:]:
                        self.log("  " + line)
                    if r2.returncode != 0:
                        self.log("智能合并失败：" + e2[-400:])
                        return
                    for k, s2 in list(self.sources.items()):
                        if s2 in skill_srcs:
                            del self.sources[k]
                    try:
                        sets2 = [x for x in find_sets(OUT_DIR)
                                 if x["name"] == outname or x["name"] == outname + "_P"
                                 or outname in x["name"]]
                        if sets2:
                            self._add(sets2)
                            self.log(f"已把智能合并产物加入源：{sets2[0]['name']}")
                        else:
                            self.log(f"⚠ 找不到智能合并产物 {outname}_P（检查 {OUT_DIR}）")
                    except Exception as e3:
                        self.log(f"加入智能合并产物失败：{e3}")
                    self.root.after(0, self._refresh)
                else:
                    for k, s2 in list(self.sources.items()):
                        if s2 in skill_srcs:
                            del self.sources[k]
                    self.log(f"已跳过 {len(skill_srcs)} 个技能 MOD，只合并其他")
                    if len(self.sources) < 2:
                        self.log("跳过技能 MOD 后不足两个源，合并取消")
                        return
            if not any(s.get("entries") is not None for s in self.sources.values()):
                analyze(list(self.sources.values()), repak, retoc, base, self.log)
                self.root.after(0, self._refresh)
            # 角色一致性检查
            charsets = []
            for s in self.sources.values():
                cs = {c for c in (s.get("clues") or {}) if c.startswith("幻兵") or c.startswith("单位")}
                if cs:
                    charsets.append((s["name"], cs))
            allchars = set().union(*[c for _n, c in charsets]) if charsets else set()
            if len(allchars) > 1:
                msg = ("这几个 MOD 的角色线索不一致：\n\n"
                       + "\n".join(f"  {n}：{'、'.join(sorted(c))}" for n, c in charsets)
                       + "\n\n确定要继续合并吗？（仍可合并，只是可能把不同角色的东西放进同一套）")
                self.log("⚠ 角色线索不一致：" + "；".join(f"{n}={sorted(c)}" for n, c in charsets))
                ans = self._ask(msg)
                if not ans:
                    self.log("已取消合并")
                    return
            name = (self.v_name.get() or "MergedMod").strip()
            files = merge(list(self.sources.values()), name, repak, retoc, paks, self.log, base_locres=base)
            self.log("完成：" + "、".join(f"{f.name}（{f.stat().st_size:,} B）" for f in files))
            self.log(f"→ {OUT_DIR}")
            self._save_cfg()
        except Exception as e:
            self.log("合并失败：" + str(e))

    def _ask(self, msg, title="角色线索不一致"):
        box = {}
        def ask():
            from tkinter import messagebox
            box["r"] = messagebox.askyesno(title, msg)
        self.root.after(0, ask)
        import time
        for _ in range(600):
            if "r" in box:
                break
            time.sleep(0.1)
        return box.get("r", False)

    def _save_cfg(self):
        self.st.update({"game_root": self.v_root.get(), "repak": self.v_repak.get(),
                        "retoc": self.v_retoc.get(), "out_name": self.v_name.get()})
        SETTINGS.write_text(json.dumps(self.st, indent=1, ensure_ascii=False), encoding="utf-8")

    def run(self):
        self.root.protocol("WM_DELETE_WINDOW", lambda: (self._save_cfg(), self.root.destroy()))
        self.root.mainloop()


if __name__ == "__main__":
    App().run()
