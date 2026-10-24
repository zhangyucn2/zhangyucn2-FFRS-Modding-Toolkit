"""FFRS 技能修改工具 v1.5

按用户实测的四分类组织（见 docs/memory/ffrs-skill-datamodel.md）：

  ① 原生技能（随等级掌握）  DT_UnitLevelParameter<Unit>.AddSkills  —— 99 级 × 3 槽
  ② 幻兵精通技能（可装配）  DT_VisionAwakening/SynchroMasteryData 的 ActiveSkill 池
  ③ 真·幻兵技能（幻兵自身）  Unit/LevelParameter/Vision/DT_UnitLevelParameter<Vision>.AddSkills
  ④ 召唤兽技能（AI 自动）   DT_BtlUnitAIParameter 的 fightSkillId / skillRandData1&2

写入链路（docs/memory/ffrs-skill-mod-pipeline.md，已实测）：
  UAssetGUI tojson → 改 JSON → fromjson → **只取新 uexp**（uasset 用原版）
  → `retoc get` 取原始 chunk → 用新 uexp 覆盖 chunk 尾部 → `pack-raw`
  → 再补一个同名的 `_P.pak`（没有 pak 游戏不挂载容器）

只做「改 int 字段/换技能 id」，**不增删数组元素**（长度不变才能保证 chunk 头不动）。
"""
import json
import os
import re
import shutil
import struct
import subprocess
import sys
import threading
import traceback
from pathlib import Path
from tkinter import messagebox

APP_DIR = (Path(sys.executable).resolve().parent if getattr(sys, "frozen", False)
           else Path(__file__).resolve().parent)
SETTINGS = APP_DIR / "ffrs_skillmod_settings.json"
try:
    import kit.settings as _KIT
    SETTINGS = _KIT.state_file("ffrs_skillmod_settings.json")
except Exception:
    pass
CACHE = APP_DIR / "_skill_cache"
try:
    import kit.settings as _K2
    CACHE = _K2.cache_root() / "skill"
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
BASE_SEED = 1451793619

UNIT_LEVEL_GROUP = {"Playable": "Playable", "Vision": "Vision", "summon": "summon"}


def run(cmd, timeout=1800):
    p = subprocess.run([str(c) for c in cmd], capture_output=True, timeout=timeout)
    return (p.returncode,
            (p.stdout or b"").decode("utf-8", "replace"),
            (p.stderr or b"").decode("utf-8", "replace"))


# ──────────────────────────── 基础视图 / 表缓存 ────────────────────────────
def base_view(paks: Path) -> Path:
    """只含基础三件套的目录（硬链接），避免抽到已装 MOD 的资产。"""
    paks = Path(paks)
    if not any(paks.glob("*_P.utoc")):
        return paks
    d = CACHE / "base_paks"
    d.mkdir(parents=True, exist_ok=True)
    for n in ("FFRS-Windows.pak", "FFRS-Windows.utoc", "FFRS-Windows.ucas",
              "global.utoc", "global.ucas"):
        src, dst = paks / n, d / n
        if src.exists() and not dst.exists():
            try:
                os.link(src, dst)
            except OSError:
                shutil.copy2(src, dst)
    return d


def _ffr_tools():
    """ffr-dt 与 usmap 的路径（优先首页设置，其次本目录 tools）。"""
    try:
        import kit.settings as _K
        dt = Path(_K.get("ffrdt") or "")
        mp = Path(_K.get("usmap") or "")
    except Exception:
        dt = Path(""); mp = Path("")
    if not dt.exists():
        dt = APP_DIR / "tools" / "ffr-dt" / "ffr-dt.exe"
    if not mp.exists():
        mp = APP_DIR / "tools" / "FFRS.usmap"
    return dt, mp


class Tables:
    """按需从基础容器抽出 DataTable 并转 JSON，缓存在 _skill_cache。"""

    def __init__(self, paks: Path, retoc: Path, uassetgui: Path, log):
        self.paks = Path(paks)
        self.retoc = Path(retoc)
        self.uag = Path(uassetgui)
        self.log = log
        self.view = base_view(self.paks)
        CACHE.mkdir(parents=True, exist_ok=True)
        (CACHE / "legacy").mkdir(exist_ok=True)
        (CACHE / "json").mkdir(exist_ok=True)
        self._cache = {}

    def json_path(self, table: str) -> Path:
        js = CACHE / "json" / f"{table}.json"
        if js.exists():
            return js
        leg = CACHE / "legacy"
        ua = next(leg.rglob(f"{table}.uasset"), None)
        if ua is None:
            self.log(f"抽取 {table} …")
            rc, out, err = run([self.retoc, "to-legacy", self.view, leg,
                                "-f", f"{table}.uasset", "--no-shaders"], timeout=1800)
            ua = next(leg.rglob(f"{table}.uasset"), None)
            if ua is None:
                raise RuntimeError(f"容器里找不到 {table}：{(err or out)[-200:]}")
        dt, mp = _ffr_tools()
        if dt.exists() and mp.exists():
            rc, out, err = run([dt, "tojson", ua, js, "--usmap", mp], timeout=1800)
        else:
            rc, out, err = run([self.uag, "tojson", ua, js, "VER_UE5_6", "FFRS"], timeout=900)
        if not js.exists():
            raise RuntimeError(f"{table} 转 JSON 失败：{(err or out)[-300:]}")
        return js

    def doc(self, table: str) -> dict:
        if table not in self._cache:
            self._cache[table] = json.loads(self.json_path(table).read_text(encoding="utf-8"))
        return self._cache[table]

    def rows(self, table: str) -> list:
        d = self.doc(table)
        return (d["Exports"][0].get("Table") or {}).get("Data") or []


# ──────────────────────────── JSON 读写小工具 ────────────────────────────
def props_of(row: dict) -> dict:
    return {p["Name"]: p for p in row["Value"]}


def get_path(props: list, path: list):
    """按 [名字 | 下标] 序列取值（props 是属性列表）"""
    node = props
    for step in path:
        if isinstance(step, int):
            node = node[step]
        else:
            node = props_of({"Value": node})[step]["Value"] if isinstance(node, list) else node[step]["Value"]
    return node


def walk(props: list, path: list):
    """返回 path 指向的**属性节点**（dict），方便读/写它的 Value。"""
    node = props
    for i, step in enumerate(path):
        last = (i == len(path) - 1)
        if isinstance(step, int):
            if not isinstance(node, list):
                raise TypeError(f"第 {i} 步 {step} 需要列表，实际 {type(node)}")
            if last:
                return node[step]
            node = node[step]
            node = node["Value"] if isinstance(node, dict) and "Value" in node else node
        else:
            if not isinstance(node, list):
                raise TypeError(f"第 {i} 步 {step} 需要属性列表")
            p = props_of({"Value": node})[step]
            if last:
                return p
            node = p["Value"]
    return node


def get_value(props: list, path: list):
    return walk(props, path)["Value"]


def set_value(props: list, path: list, value):
    walk(props, path)["Value"] = value


# ──────────────────────────── 设置 ────────────────────────────
def load_settings() -> dict:
    d = {"game_root": "", "repak": str(APP_DIR / "repak.exe"), "retoc": str(APP_DIR / "retoc.exe"),
         "uassetgui": str(APP_DIR.parent / "UAssetGUI" / "UAssetGUI.exe"),
         "out_dir": str(OUT_DIR), "unit": "", "mod_name": "SkillMod"}
    if SETTINGS.exists():
        try:
            d.update(json.loads(SETTINGS.read_text(encoding="utf-8")))
        except Exception:
            pass
    return d


def save_settings(d: dict):
    SETTINGS.write_text(json.dumps(d, indent=1, ensure_ascii=False), encoding="utf-8")


# ──────────────────────────── 界面 ────────────────────────────
class App:
    SHOW_NEW_ID = True       # ★ 新 ID（生成新技能）：已用 skill_new + ffr-dt patch 打通（含动画/特效）

    def __init__(self, host=None):
        self._host = host
        import tkinter as tk
        from tkinter import ttk
        self.tk, self.ttk = tk, ttk
        self.settings = load_settings()
        self.tables = None
        self.edits = {}        # {(table, tuple(path_with_row)): 新值}
        self.skill_names = {}  # {skill_id: 名称（简中优先，缺则英文）}
        self.unit_names = {}   # {单位名: ID}
        self.passive_names = {}
        self.master_names = {}
        self.skill_row = {}    # {skill_id: DT_SkillData 行号}
        self.effect_names = {} # {effect_id: 效果行名}
        self.hit_row = {}      # {skill_id: DT_BtlHitEffectData 行号}
        self.cur_slot = None   # 当前技能来自哪个槽
        self.pending_new = []  # 暂存的新技能（生成时一起打包）
        self.pending_fx = []   # 暂存的「分轨替换」：{skill, anim, fx}
        self.pending_rows = []   # 通用新增行：{table, row, cloneFrom, set}
        self.pending_sets = []   # 通用改值：{table, row, set:{path:val}}
        self.pending_assets = [] # 通用资产克隆：{leg_root, rel}
        self.last_query = ""
        self.rowmeta = {"native": [], "vision": [], "truevision": [], "summon": []}
        self.busy = False
        self._build()

    # ---- UI ----
    def _build(self):
        tk, ttk = self.tk, self.ttk
        self.root = getattr(self, "_host", None) or tk.Tk()
        self.root.title("FFRS 技能修改工具 v1.5")
        self.root.geometry("1150x760")

        top = ttk.LabelFrame(self.root, text="① 路径设置")
        top.pack(fill="x", padx=8, pady=6)
        ttk.Label(top, text="游戏目录").grid(row=0, column=0, sticky="w", padx=4, pady=2)
        self.v_root = tk.StringVar(value=self.settings["game_root"])
        ttk.Entry(top, textvariable=self.v_root, width=70).grid(row=0, column=1, columnspan=3, sticky="we", padx=4)
        ttk.Button(top, text="指定…", command=self.pick_root).grid(row=0, column=4, padx=4)
        ttk.Label(top, text="导出路径").grid(row=1, column=0, sticky="w", padx=4, pady=2)
        self.v_out = tk.StringVar(value=self.settings["out_dir"])
        ttk.Entry(top, textvariable=self.v_out, width=70).grid(row=1, column=1, columnspan=3, sticky="we", padx=4)
        ttk.Button(top, text="指定…", command=self.pick_out).grid(row=1, column=4, padx=4)
        ttk.Label(top, text="UAssetGUI").grid(row=2, column=0, sticky="w", padx=4, pady=2)
        self.v_uag = tk.StringVar(value=self.settings["uassetgui"])
        ttk.Entry(top, textvariable=self.v_uag, width=70).grid(row=2, column=1, columnspan=3, sticky="we", padx=4)
        ttk.Button(top, text="指定…", command=self.pick_uag).grid(row=2, column=4, padx=4)
        ttk.Label(top, text="repak / retoc").grid(row=3, column=0, sticky="w", padx=4, pady=2)
        self.v_repak = tk.StringVar(value=self.settings["repak"])
        self.v_retoc = tk.StringVar(value=self.settings["retoc"])
        ttk.Entry(top, textvariable=self.v_repak, width=34).grid(row=3, column=1, sticky="we", padx=4)
        ttk.Entry(top, textvariable=self.v_retoc, width=34).grid(row=3, column=2, columnspan=2, sticky="we", padx=4)
        top.columnconfigure(3, weight=1)

        sel = ttk.LabelFrame(self.root, text="② 单位 / 幻兵（名称或 ID）")
        sel.pack(fill="x", padx=8, pady=2)
        self.v_unit = tk.StringVar(value=self.settings.get("unit", ""))
        ttk.Entry(sel, textvariable=self.v_unit, width=30).pack(side="left", padx=4, pady=4)
        self.btn_load = ttk.Button(sel, text="读取", command=self.on_load)
        self.btn_load.pack(side="left", padx=4)
        self._lang = self._ui_lang()
        self.v_info = tk.StringVar(value=(
            "(enter unit name/ID, e.g. Rain, 1001, vision 13100, esper 300010)"
            if getattr(self, "_lang", "zh") == "en" else
            "（填角色名/ID，如 雷因、Rain、1001、幻兵 13100 或 召唤兽 300010）"))
        ttk.Label(sel, textvariable=self.v_info).pack(side="left", padx=8)

        nb = ttk.Notebook(self.root)
        nb.pack(fill="both", expand=True, padx=8, pady=4)
        self.nb = nb
        self.trees = {}
        for key, title, cols in (
                ("native", "① 原生技能（主角 · 按等级学会）", ("level", "s1", "s2", "s3", "names")),
                ("vision", "② 幻兵精通（装配池 · 8 槽）", ("row", "idx", "type", "skill", "name")),
                ("truevision", "③ 真·幻兵（幻兵自身技能）", ("level", "s1", "s2", "s3", "names")),
                ("summon", "④ 召唤兽（AI 自动释放）", ("field", "idx", "skill", "name")),
                ("values", "⑤ 技能修改", ("field", "value", "type"))):
            fr = ttk.Frame(nb)
            nb.add(fr, text=self._tr(title))
            t = ttk.Treeview(fr, columns=cols, show="headings", height=16)
            for c in cols:
                t.heading(c, text=c)
                t.column(c, width=110 if c not in ("names", "name") else 260,
                         anchor="w" if c in ("names", "name") else "center")
            t.pack(side="left", fill="both", expand=True)
            sb = ttk.Scrollbar(fr, orient="vertical", command=t.yview)
            sb.pack(side="right", fill="y")
            t.configure(yscrollcommand=sb.set)
            t.bind("<Double-1>", lambda e, k=key: self.on_edit(k, e))
            self.trees[key] = t
            if key == "values":
                bar = self.ttk.Frame(fr)
                self._values_bar = bar
                bar.pack(side="bottom", fill="x", padx=4, pady=4)
                self.ttk.Label(bar, text="技能（ID 或中/英文名）").pack(side="left")
                self.v_skillq = tk.StringVar()
                self.ttk.Entry(bar, textvariable=self.v_skillq, width=34).pack(side="left", padx=4)
                self.ttk.Button(bar, text="读取技能", command=self.on_load_skill).pack(side="left", padx=4)
                self.ttk.Button(bar, text="替换技能…", command=self.on_replace_skill).pack(side="left", padx=4)
                self.ttk.Button(bar, text="效果槽详情…", command=self.on_effect_details).pack(side="left", padx=4)
                self.ttk.Button(bar, text="替换特效…", command=self.on_replace_effect).pack(side="left", padx=4)
                self.ttk.Button(bar, text="清 ID 记录", command=self.on_clear_id_record).pack(side="left", padx=4)
                self.ttk.Button(bar, text="分轨替换…", command=self.on_split_fx).pack(side="left", padx=4)
                self.v_skillinfo = tk.StringVar(value="")
                self.ttk.Label(bar, textvariable=self.v_skillinfo).pack(side="left", padx=8)
                # ── 右侧使用说明（测试期放这里，方便随时看）──
                self._build_help_panel(fr)

        bar = ttk.Frame(self.root)
        bar.pack(fill="x", padx=8, pady=2)
        ttk.Button(bar, text="编辑选中…", command=lambda: self.on_edit(self._cur_tab())).pack(side="left", padx=4)
        ttk.Button(bar, text="撤销该条", command=lambda: self.on_undo(self._cur_tab())).pack(side="left", padx=4)
        ttk.Label(bar, text="MOD 名").pack(side="left", padx=(16, 2))
        self.v_name = tk.StringVar(value=self.settings.get("mod_name", "SkillMod"))
        ttk.Entry(bar, textvariable=self.v_name, width=20).pack(side="left")
        ttk.Button(bar, text="生成 MOD", command=self.on_build).pack(side="left", padx=8)
        ttk.Button(bar, text="安装到游戏", command=self.on_install).pack(side="left", padx=4)
        ttk.Button(bar, text="还原", command=self.on_restore).pack(side="left", padx=4)
        self.v_count = tk.StringVar(value="未修改")
        ttk.Label(bar, textvariable=self.v_count).pack(side="left", padx=10)

        # ★ 路径/工具统一由首页提供
        try:
            import kit.settings as _K
            _tools = _K.get("tools_dir")
            self.v_root.set(str(_K.get("game_root")))
            self.v_out.set(str(_K.output_mods()))
            self.v_uag.set(str(_K.get("uassetgui")))
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
        self.log_t = tk.Text(logf, height=12, wrap="word")
        self.log_t.pack(side="left", fill="both", expand=True)
        sb2 = ttk.Scrollbar(logf, orient="vertical", command=self.log_t.yview)
        sb2.pack(side="right", fill="y")
        self.log_t.configure(yscrollcommand=sb2.set)
        self.log("提示：双击单元格可直接改技能 ID；技能名来自 ST_SkillName（四语里取简体/日文）")

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

    def _cur_tab(self):
        try:
            return ("native", "vision", "truevision", "summon")[self.nb.index(self.nb.select())]
        except Exception:
            return "native"

    def pick_root(self):
        from tkinter import filedialog
        d = filedialog.askdirectory(title="选游戏根目录")
        if d:
            self.v_root.set(d)

    def pick_out(self):
        from tkinter import filedialog
        d = filedialog.askdirectory(title="选导出路径")
        if d:
            self.v_out.set(d)

    def pick_uag(self):
        from tkinter import filedialog
        f = filedialog.askopenfilename(title="选 UAssetGUI.exe", filetypes=[("exe", "*.exe")])
        if f:
            self.v_uag.set(f)

    # ---- 路径 ----
    def _paths(self):
        root = Path(self.v_root.get().strip())
        paks = root / "FFRS" / "Content" / "Paks"
        if not paks.exists():
            paks = root / "Content" / "Paks"
        if not paks.exists():
            raise RuntimeError("游戏目录下找不到 FFRS/Content/Paks")
        for nm, v in (("repak", self.v_repak), ("retoc", self.v_retoc), ("UAssetGUI", self.v_uag)):
            if not Path(v.get()).exists():
                raise RuntimeError(f"{nm} 路径不对：{v.get()}")
        if self.tables is None:
            self.tables = Tables(paks, Path(self.v_retoc.get()), Path(self.v_uag.get()), self.log)
        return paks, Path(self.v_repak.get()), Path(self.v_retoc.get())

    # ---- 技能名 ----
    def _ensure_names(self):
        if self.skill_names:
            return
        try:
            sys.path.insert(0, str(APP_DIR))
            import FFRS_TextMod_Tool as TT
            paks, repak, _r = self._paths()
            loc = TT.extract_locres(paks, repak, lambda *_a: None)
            self.unit_names = {}
            self.passive_names = {}
            self.master_names = {}
            for lang in ("zh-Hans", "en", "zh-Hant", "ja"):
                if lang not in loc:
                    continue
                L = TT.Locres(loc[lang])
                for (ns, key), e in L.index.items():
                    txt = L.strings[e["idx"]][0]
                    if not txt:
                        continue
                    m = re.search(r"(\d+)$", key)
                    if not m:
                        continue
                    if ns == "ST_SkillName":
                        self.skill_names.setdefault(int(m.group(1)), txt)
                    elif ns == "ST_PassiveSkillName":
                        self.passive_names.setdefault(int(m.group(1)), txt)
                    elif ns == "ST_MasterSkillName":
                        self.master_names.setdefault(int(m.group(1)), txt)
                    elif ns in ("ST_UnitName", "ST_VisionName"):
                        self.unit_names.setdefault(txt.strip(), int(m.group(1)))
            self.log(f"技能名 {len(self.skill_names)} 条 / 单位名 {len(self.unit_names)} 条")
        except Exception as e:
            self.log(f"（名表读取失败，不影响按 ID 改：{e}）")

    def _val(self, table, row, path, cur):
        """列表里显示时优先用已暂存的值"""
        return self.edits.get((table, row, tuple(path)), cur)

    def _unit_category(self, q: str) -> str:
        r = self._resolve_unit_row(q)
        if r is None:
            return ""
        return props_of(r).get("Category", {}).get("Value") or ""

    def _empty_hint(self, tab, msg="该角色无此类别技能"):
        t = self.trees[tab]
        t.delete(*t.get_children())
        self.rowmeta[tab] = []
        if len(t["columns"]) >= 2:
            vals = [""] * len(t["columns"])
            vals[0] = msg
        else:
            vals = (msg,)
        t.insert("", "end", values=vals)
        self.log(f"{tab}：{msg}")

    def _skill_label(self, sid, kind=None):
        if not isinstance(sid, int) or sid <= 0:
            return ""
        if kind == "PassiveSkill":
            return self.passive_names.get(sid, "")
        if kind == "MasterSkill":
            return self.master_names.get(sid, "")
        return self.sname(sid)

    def _resolve_unit_row(self, q: str):
        """角色名/ID → DT_UnitParameter 的行"""
        rows = self.tables.rows("DT_UnitParameter")
        q = (q or "").strip()
        if not q:
            return None
        if q.isdigit():
            for r in rows:
                if props_of(r).get("ID", {}).get("Value") == int(q):
                    return r
        uid = self.unit_names.get(q)
        if uid is None:
            for nm, i in self.unit_names.items():
                if nm and (nm in q or q in nm):
                    uid = i
                    break
        if uid is not None:
            for r in rows:
                if props_of(r).get("ID", {}).get("Value") == uid:
                    return r
        for r in rows:
            if r["Name"] == q:
                return r
        return None

    def _level_table_for(self, q: str):
        """角色 → DT_UnitLevelParameter<X>（走 LevelParamId → List 表的 DataTable 引用）"""
        row = self._resolve_unit_row(q)
        if row is None:
            return None
        pr = props_of(row)
        lp = pr.get("LevelParamId", {}).get("Value")
        if lp is None:
            return None
        try:
            doc = self.tables.doc("DT_UnitLevelParameterList")
            lst = (doc["Exports"][0].get("Table") or {}).get("Data") or []
            imports = doc.get("Imports") or []
            for r in lst:
                lpr = props_of(r)
                if lpr.get("ID", {}).get("Value") != lp:
                    continue
                dt = lpr.get("DataTable", {}).get("Value")
                if isinstance(dt, int):
                    idx = (-dt - 1) if dt < 0 else dt
                    if 0 <= idx < len(imports):
                        nm = imports[idx].get("ObjectName")
                        if nm:
                            return nm
            return None
        except Exception as e:
            self.log(f"等级表映射失败：{e}")
            return None

    def sname(self, sid) -> str:
        try:
            sid = int(sid)
        except Exception:
            return ""
        if sid < 0:
            return "（空槽）"
        return self.skill_names.get(sid, "")

    # ---- 读取 ----
    def on_load(self):
        if self.busy:
            return
        self.busy = True
        self.btn_load.configure(state="disabled")
        threading.Thread(target=self._load_job, daemon=True).start()

    def _load_job(self):
        try:
            self._paths()
            self._ensure_names()
            q = self.v_unit.get().strip()
            self.last_query = q
            cat = self._unit_category(q)
            if cat == "Vision":
                self._empty_hint("native", "该角色无此类别技能（主角专属：随等级学会）")
            else:
                self._load_level_into("native", q)
            self._load_mastery("vision", q)
            self._load_mastery("truevision", q)
            self._load_summon(q)
            self._save_cfg()
        except Exception as e:
            self.log("读取失败：" + str(e))
            self.log(traceback.format_exc(limit=3))
        finally:
            self.busy = False
            self.root.after(0, lambda: self.btn_load.configure(state="normal"))

    def _load_native(self, q):
        t = self.trees["native"]
        t.delete(*t.get_children())
        self.rowmeta["native"] = []
        table = self._level_table_for(q)
        if not table:
            self.log("找不到对应的等级表")
            return
        try:
            rows = self.tables.rows(table)
        except Exception as e:
            self.log(f"等级表 {table} 读取失败：{e}")
            return
        n_slot = 0
        for i, r in enumerate(rows):
            pr = props_of(r)
            lv = pr.get("Level", {}).get("Value")
            sk = pr.get("AddSkills", {}).get("Value") or []
            vals = [x["Value"] for x in sk]
            n_slot = max(n_slot, len(vals))
            vals += [-1] * (3 - len(vals))
            names = " / ".join(self.sname(v) or "" for v in vals if v and v > 0)
            t.insert("", "end", values=(lv, vals[0], vals[1], vals[2], names))
            self.rowmeta["native"].append({"table": table, "row": i, "label": f"Lv{lv}",
                                           "paths": [["AddSkills", 0], ["AddSkills", 1],
                                                     ["AddSkills", 2]] if len(sk) >= 3 else
                                                    [["AddSkills", k] for k in range(len(sk))]})
        self.log(f"① {table}：{len(rows)} 级 × {n_slot} 槽（技能名 {len(self.skill_names)} 条可查）")

    def _load_level_into(self, tab, q):
        """① 原生技能：主角等级表（Playable 组）99~100 级 × 3 槽"""
        t = self.trees[tab]
        t.delete(*t.get_children())
        self.rowmeta[tab] = []
        table = self._level_table_for(q)
        if not table:
            self._empty_hint(tab, "找不到该角色的等级表（可填 名称 / ID）")
            return
        try:
            rows = self.tables.rows(table)
        except Exception as e:
            self._empty_hint(tab, f"等级表读取失败：{e}")
            return
        n = 0
        for i, r in enumerate(rows):
            pr = props_of(r)
            lv = pr.get("Level", {}).get("Value")
            sk = (pr.get("AddSkills") or {}).get("Value") or []
            vals = [self._val(table, i, ["AddSkills", k], x["Value"]) for k, x in enumerate(sk)][:3]
            vals += [-1] * (3 - len(vals))
            names = " / ".join(self.sname(v) for v in vals if isinstance(v, int) and v > 0)
            t.insert("", "end", values=(lv, vals[0], vals[1], vals[2], names))
            self.rowmeta[tab].append({"table": table, "row": i, "label": f"Lv{lv}",
                                      "paths": [["AddSkills", k] for k in range(len(sk))],
                                      "skill": next((v for v in vals if isinstance(v, int) and v > 0), None)})
            n += 1
        if n == 0:
            self._empty_hint(tab, "该角色无此类别技能")
            return
        has_any = any(isinstance(v, int) and v > 0
                      for m in self.rowmeta[tab] for v in
                      [x["Value"] for x in (props_of(rows[m["row"]]).get("AddSkills") or {}).get("Value") or []])
        if not has_any:
            self._empty_hint(tab, "该角色无此类别技能（等级表里全是空槽）")
            return
        self.log(f"① {table}：{n} 级")

    MASTERY_TABLES = {
        "vision": ("DT_VisionSynchroMasteryData", "② 幻兵精通（装配池）"),
        "truevision": ("DT_VisionAwakeningMasteryData", "③ 真·幻兵（觉醒技能）"),
    }

    def _load_mastery(self, tab, q):
        """② = 同调（精通奖励，主角可装配）；③ = 觉醒（幻兵自身技能，含被动）"""
        table, title = self.MASTERY_TABLES[tab]
        t = self.trees[tab]
        t.delete(*t.get_children())
        self.rowmeta[tab] = []
        cat = self._unit_category(q)
        if cat and cat != "Vision":
            self._empty_hint(tab, "该角色无此类别技能（幻兵专属）")
            return
        vid = self._unit_id(q)
        if vid is None:
            self.log(f"{title}：请填幻兵 ID 或名称")
            return
        try:
            rows = self.tables.rows(table)
        except Exception as e:
            self.log(f"{table} 读取失败：{e}")
            return
        n = 0
        for i, r in enumerate(rows):
            pr = props_of(r)
            if pr.get("ID", {}).get("Value") != vid:
                continue
            lv = pr.get("Level", {}).get("Value")
            for j, dd in enumerate((pr.get("detailData") or {}).get("Value") or []):
                dp = props_of(dd)
                ptype = dp.get("parameterType", {}).get("Value") or "None"
                if ptype == "None":
                    continue
                ps = (dp.get("params") or {}).get("Value") or []
                vals = [x["Value"] for x in ps] or [-1]
                sid = self._val(table, i, ["detailData", j, "params", 0], vals[0])
                if ptype == "BaseParameter":
                    bname = {"1": "生命值", "2": "魔力", "3": "攻击", "4": "防御",
                             "5": "力量", "6": "体力", "7": "智力", "8": "精神",
                             "9": "敏捷", "10": "命中", "11": "AP"}.get(str(sid), f"参数{sid}")
                    extra = f" +{vals[1]}" if len(vals) > 1 else ""
                    label = f"{bname}{extra}（永续）"
                    self.rowmeta[tab].append({"table": table, "row": i,
                                              "path": ["detailData", j, "params", 1]
                                              if len(vals) > 1 else None, "label": label})
                    t.insert("", "end", values=(f"{lv}", j, ptype, sid, label))
                else:
                    label = self._skill_label(sid, ptype)
                    self.rowmeta[tab].append({"table": table, "row": i,
                                              "path": ["detailData", j, "params", 0],
                                              "label": f"{ptype} {sid}", "skill": sid,
                                              "kind": ptype})
                    t.insert("", "end", values=(f"{lv}", j, ptype, sid, label))
                n += 1
        if tab == "truevision":
            # 补一条：该幻兵的大招（LB）= DT_VisionItemData.finishBlowSkill
            try:
                for vr in self.tables.rows("DT_VisionItemData"):
                    vpr = props_of(vr)
                    if vpr.get("ID", {}).get("Value") != vid:
                        continue
                    lb = vpr.get("finishBlowSkill", {}).get("Value")
                    if isinstance(lb, int) and lb > 0:
                        t.insert("", "end", values=("LB", "-", "FinishBlow", lb, self.sname(lb)))
                        self.rowmeta[tab].append({"table": "DT_VisionItemData", "row": None,
                                                  "path": ["finishBlowSkill"],
                                                  "label": f"LB {lb}", "skill": lb,
                                                  "kind": "FinishBlow"})
                        n += 1
                    break
            except Exception as e:
                self.log(f"LB 技能读取失败：{e}")
        if n == 0:
            self._empty_hint(tab, "该幻兵无此类条目（表里全是空槽）")
            return
        self.log(f"{title}：{n} 条（幻兵 {vid}，{table}）")

    def _unit_id(self, q):
        r = self._resolve_unit_row(q)
        if r is not None:
            return props_of(r).get("ID", {}).get("Value")
        if (q or "").strip().isdigit():
            return int(q)
        return None

    def _load_vision(self, q):
        self._load_mastery("vision", q)

    def _load_truevision(self, q):
        self._load_mastery("truevision", q)

    def _load_summon(self, q):
        t = self.trees["summon"]
        t.delete(*t.get_children())
        self.rowmeta["summon"] = []
        try:
            rows = self.tables.rows("DT_BtlUnitAIParameter")
        except Exception as e:
            self.log(f"④ AI 表读取失败：{e}")
            return
        qs = (q or "").strip()
        cat = self._unit_category(q)
        if cat and cat not in ("Beast", "Enemy"):
            if not qs.isdigit() or not qs.startswith("300"):
                self._empty_hint("summon", "该角色无此类别技能（召唤兽专属）")
                return
        target = None
        # 1) 按单位 ID / 行名
        for i, r in enumerate(rows):
            pr = props_of(r)
            uid = pr.get("ID", {}).get("Value")
            if qs and (str(uid) == qs or r["Name"] == qs):
                target = (i, r, pr)
                break
        # 2) 按单位名（走 locres 单位名表）
        if target is None and qs in getattr(self, "unit_names", {}):
            uid = self.unit_names[qs]
            for i, r in enumerate(rows):
                if props_of(r).get("ID", {}).get("Value") == uid:
                    target = (i, r, props_of(r))
                    break
        # 3) 按技能 ID（300xxx）反查：哪个单位的技能池里有它
        if target is None and qs.isdigit():
            sid = int(qs)
            for i, r in enumerate(rows):
                pr = props_of(r)
                hit = pr.get("fightSkillId", {}).get("Value") == sid
                if not hit:
                    for arr in ("skillRandData1", "skillRandData2"):
                        for item in (pr.get(arr) or {}).get("Value") or []:
                            ip = props_of(item)
                            if any(ip.get(k, {}).get("Value") == sid for k in ("SkillId", "skillId", "SkillID")):
                                hit = True
                                break
                        if hit:
                            break
                if hit:
                    target = (i, r, pr)
                    self.log(f"④ 按技能 {sid} 反查到单位：{r['Name']}")
                    break
        if target is None:
            self.log("④ 找不到这个单位的 AI 技能池（可填单位 ID/名称，或 300xxx 技能 ID）")
            return
        i, r, pr = target
        for fld in ("fightSkillId", "chaseSkillId", "silenceFightId"):
            if fld in pr:
                v = pr[fld]["Value"]
                t.insert("", "end", values=(fld, "", v, self.sname(v)))
                self.rowmeta["summon"].append({"table": "DT_BtlUnitAIParameter", "row": i,
                                               "path": [fld], "label": fld, "skill": v})
        for arr in ("skillRandData1", "skillRandData2"):
            lst = (pr.get(arr) or {}).get("Value") or []
            for k, item in enumerate(lst):
                ip = props_of(item)
                sid = None
                for key in ("SkillId", "skillId", "SkillID"):
                    if key in ip:
                        sid = ip[key]["Value"]
                        break
                t.insert("", "end", values=(arr, k, sid, self.sname(sid) if sid else ""))
                if sid is not None:
                    key = "SkillId" if "SkillId" in ip else ("skillId" if "skillId" in ip else "SkillID")
                    self.rowmeta["summon"].append({"table": "DT_BtlUnitAIParameter", "row": i,
                                                   "path": [arr, k, key],
                                                   "label": f"{arr}[{k}]", "skill": sid})
        self.log(f"④ {r['Name']}（ID {pr.get('ID', {}).get('Value')}）技能池已载入")

    # 简单直译用的关键词（日文 → 中文）
    JP2ZH = [("物理防御", "物防"), ("魔法防御", "魔防"), ("防御力", "防御"), ("精神", "精神"),
             ("麻痺", "麻痹"), ("毒", "中毒"), ("沈黙", "沉默"), ("暗闇", "黑暗"),
             ("スロウ", "减速"), ("ヘイスト", "加速"), ("リジェネ", "再生"), ("弱体", "弱化"),
             ("攻撃", "攻击"), ("ダメージ", "伤害"), ("回復", "回复"), ("減少", "下降"),
             ("上昇", "上升"), ("ダウン", "下降"), ("無効", "无效"), ("反射", "反射"),
             ("吸収", "吸收"), ("状態", "状态"), ("必中", "必中"), ("カウンター", "反击"),
             ("パッシブ", "被动"), ("アクティブ", "主动"), ("全体", "全体"), ("単体", "单体"),
             ("魔法", "魔法"), ("剣", "剑"), ("技", "技"), ("強化", "强化")]
    EFFECT_NOTE = {1167: "减物防30%（实测可用）", 1169: "减魔防30%（实测可用）",
                   1033: "麻痹（实测可用）", 1349: "减防（仅敌方技能用，实测无效）",
                   1350: "减精神（仅敌方技能用，实测无效）"}

    def _effect_meta(self):
        """{effect_id: (中文直译, 使用者类别)}，扫描 DT_SkillData 统计。"""
        if getattr(self, "_eff_meta", None) is not None:
            return self._eff_meta
        def cat_of(sid: int) -> str:
            n = sid // 100000
            return {1: "主角", 2: "幻兵", 3: "召唤兽", 4: "幻兵", 5: "敌人"}.get(n, "其他")
        users = {}
        try:
            for r in self.tables.rows("DT_SkillData"):
                pr = props_of(r)
                sid = pr.get("ID", {}).get("Value") or 0
                for it in (pr.get("effectBundleList", {}).get("Value") or []):
                    e = {q["Name"]: q["Value"] for q in it["Value"]}.get("effectId", -1)
                    if e and e != -1:
                        users.setdefault(int(e), set()).add(cat_of(sid))
        except Exception:
            pass
        meta = {}
        for eid, cats in users.items():
            nm = self.effect_names.get(eid, "")
            zh = nm
            for jp, cn in self.JP2ZH:
                zh = zh.replace(jp, cn)
            zh = zh.replace("\u3000", " ").strip()
            note = self.EFFECT_NOTE.get(eid)
            label = f"{note}" if note else zh
            meta[eid] = (label, "/".join(sorted(cats)))
        for eid, note in self.EFFECT_NOTE.items():
            if eid not in meta:
                meta[eid] = (note, "")
        self._eff_meta = meta
        return meta

    def _pick_effect(self, old, on_pick):
        """1006 个效果 → 搜索式选择器；on_pick(effect_id) 负责写入"""
        top = self.tk.Toplevel(self.root)
        top.title(f"选效果（当前 {old}）")
        top.geometry("760x480")
        self.ttk.Label(top, text="搜索（ID 或名称，如 麻痹 / 增益 / 伤害 / 属性）").pack(anchor="w", padx=8, pady=(8, 2))
        qv = self.tk.StringVar()
        e = self.ttk.Entry(top, textvariable=qv, width=44)
        e.pack(anchor="w", padx=8)
        lb = self.tk.Listbox(top, height=18)
        lb.pack(fill="both", expand=True, padx=8, pady=6)
        meta = self._effect_meta()
        items = [(i, n, meta.get(i, ("", ""))) for i, n in sorted(self.effect_names.items())]
        self.ttk.Label(top, text="格式：ID 日文名 ｜ 中文直译 ｜ 使用者类别（可搜中文）",
                       foreground="#666").pack(anchor="w", padx=8)

        shown = []

        def refill(*_a):
            q = qv.get().strip()
            lb.delete(0, "end")
            shown.clear()
            for eid, nm, (zh, cats) in items:
                line = f"{eid}\t{nm}  ｜ {zh} ｜ {cats}"
                if not q or q in str(eid) or q in nm or (zh and q in zh) or (cats and q in cats):
                    shown.append(eid)
                    lb.insert("end", line)
        qv.trace_add("write", refill)
        refill()

        def choose(_e=None):
            sel = lb.curselection()
            if not sel:
                return
            eid = shown[sel[0]]
            top.destroy()
            on_pick(eid)

        bar = self.ttk.Frame(top)
        bar.pack(fill="x", padx=8, pady=(0, 8))
        self.ttk.Button(bar, text="确定", command=choose).pack(side="right", padx=4)
        self.ttk.Button(bar, text="取消", command=top.destroy).pack(side="right", padx=4)
        lb.bind("<Double-Button-1>", choose)
        e.focus_set()

    def _pick_skill(self, on_pick, plain: bool = False, block: bool = False):
        """1160 个技能 → 搜索式选择器。

        plain=True 时只选技能（用于"替换特效/新技能特效来源"），
        不显示新 ID 输入框，也不会回调到 _make_new_skill（避免无限递归）。
        """
        plain_new = self.SHOW_NEW_ID and not plain
        top = self.tk.Toplevel(self.root)
        top.title("选源技能（只借用它的特效/演出）" if plain else "选要替换成的技能")
        top.geometry("800x500")
        self.ttk.Label(top, text=("搜索源技能（技能 ID / 中文名 / 英文名）" if plain else "搜索（技能 ID / 中文名 / 英文名）")).pack(anchor="w", padx=8, pady=(8, 2))
        qv = self.tk.StringVar()
        e = self.ttk.Entry(top, textvariable=qv, width=46)
        e.pack(anchor="w", padx=8)
        lb = self.tk.Listbox(top, height=20)
        lb.pack(fill="both", expand=True, padx=8, pady=6)
        items = sorted(self.skill_names.items())

        def refill(*_a):
            q = qv.get().strip()
            lb.delete(0, "end")
            for sid, nm in items:
                if not q or q in str(sid) or q in nm:
                    lb.insert("end", "%d\t%s" % (sid, nm))
        qv.trace_add("write", refill)
        refill()

        def choose(_e=None):
            sel = lb.curselection()
            if not sel:
                return
            sid = int(lb.get(sel[0]).split("\t")[0])
            new_id = nv.get().strip() if plain_new else ""
            if new_id and not check():
                self.log("新 ID 不合法或已存在")
                return
            top.destroy()
            if new_id:
                self._make_new_skill(sid, int(new_id))
                return
            on_pick(sid)

        nbar = self.ttk.Frame(top)
        if plain_new:
            nbar.pack(fill="x", padx=8)
        if not plain_new:
            self.ttk.Label(nbar, text="（新 ID 功能已暂时隐藏）").pack(side="left")
        self.ttk.Label(nbar, text="新 ID（留空 = 直接替换；填了 = 生成新技能）").pack(side="left")
        self.ttk.Label(nbar, text="　→ 填了新 ID 后会再问你「新技能名称 / 描述」（可留空）",
                       foreground="#0a6").pack(side="left")
        nv = self.tk.StringVar()
        ne = self.ttk.Entry(nbar, textvariable=nv, width=14)
        ne.pack(side="left", padx=4)
        hint = self.ttk.Label(nbar, text="", foreground="#b33")
        hint.pack(side="left", padx=6)

        def _used_ids():
            used = set(self.skill_row) | set(self.skill_names)
            for p_ in (getattr(self, "pending_new", []) or []):
                try:
                    used.add(int(p_["new_id"]))
                except Exception:
                    pass
            try:
                import skill_new as _SN
                used |= set(_SN.load_created_ids())
            except Exception:
                pass
            return used

        def check(*_a):
            t = nv.get().strip()
            if not t:
                hint.config(text="", foreground="#b33")
                return True
            if not t.isdigit():
                hint.config(text="只能填数字", foreground="#b33")
                return False
            v = int(t)
            if v < 1 or v > 9_999_999:
                hint.config(text="ID 超出可接受范围（1 ~ 9999999）", foreground="#b33")
                return False
            if v in _used_ids():
                hint.config(text="此 ID 已存在（含已生成/已暂存）", foreground="#b33")
                return False
            hint.config(text="ID 可用", foreground="#080")
            return True
        nv.trace_add("write", check)

        def gen_id():
            try:
                import skill_new as _SN
                v = _SN.next_free_id()
            except Exception:
                used = _used_ids()
                v = 229001
                while v in used:
                    v += 1
            nv.set(str(v))
        if plain_new:
            try:
                import skill_new as _SN2
                _next = _SN2.next_free_id()
            except Exception:
                _next = 229001
            self.ttk.Button(nbar, text="生成新 ID", command=gen_id).pack(side="left", padx=4)
            self.ttk.Label(nbar, text=f"下一个：{_next}", foreground="#080").pack(side="left", padx=2)
        if plain_new:
            self.ttk.Button(nbar, text="（行复制待实现）", state="disabled").pack(side="left", padx=8)

        bar = self.ttk.Frame(top)
        bar.pack(fill="x", padx=8, pady=(0, 8))
        self.ttk.Button(bar, text="确定替换", command=choose).pack(side="right", padx=4)
        self.ttk.Button(bar, text="取消", command=top.destroy).pack(side="right", padx=4)
        lb.bind("<Double-Button-1>", choose)
        e.focus_set()
        if block:
            self.root.wait_window(top)

    NUM_FIELDS = [("Cost", "MP 消耗"), ("equipCost", "装配点"), ("magnification", "威力"),
                  ("breakDamageValue", "破防值"), ("accuracy", "命中"), ("criticalHitRate", "暴击率"),
                  ("hitCount", "Hit 数")]
    ENUM_FIELDS = [("element", "元素属性"), ("DamageType", "伤害类型"), ("TargetType", "目标类型"),
                   ("skillAttrType", "技能属性"), ("skillEffectType", "效果类型")]

    def _enum_choices(self, field: str) -> list:
        ch = self.ENUM_CHOICES.get(field)
        if ch:
            return [str(x) for x in ch]
        # skillEffectType 之类：从整表里收集出现过的字符串值
        try:
            vals = {}
            for r in self.tables.rows("DT_SkillData"):
                v = props_of(r).get(field, {}).get("Value")
                if isinstance(v, str) and v:
                    vals[v] = vals.get(v, 0) + 1
            return [k for k, _n in sorted(vals.items(), key=lambda kv: -kv[1])][:20]
        except Exception:
            return []

    def _donor_row_props(self, donor: int) -> dict:
        try:
            for r in self.tables.rows("DT_SkillData"):
                pr = props_of(r)
                if pr.get("ID", {}).get("Value") == donor:
                    return pr
        except Exception:
            pass
        return {}

    def _donor_slots(self, donor: int) -> list:
        """源技能的 8 个效果槽完整结构（effectId + TargetType/targetRelation/timing）。"""
        pr = self._donor_row_props(donor)
        out = []
        for it in (pr.get("effectBundleList", {}).get("Value") or []):
            try:
                d = {q["Name"]: q["Value"] for q in it["Value"]}
            except Exception:
                d = {}
            out.append({"effectId": d.get("effectId", -1),
                        "TargetType": d.get("TargetType"),
                        "targetRelation": d.get("targetRelation"),
                        "activeSkillAddTiming": d.get("activeSkillAddTiming")})
        while len(out) < 8:
            out.append({"effectId": -1, "TargetType": None, "targetRelation": None,
                        "activeSkillAddTiming": None})
        return out[:8]

    def _donor_effects(self, donor: int) -> list:
        pr = self._donor_row_props(donor)
        out = []
        for it in (pr.get("effectBundleList", {}).get("Value") or []):
            try:
                d = {q["Name"]: q["Value"] for q in it["Value"]}
                out.append(d.get("effectId", -1))
            except Exception:
                out.append(-1)
        while len(out) < 8:
            out.append(-1)
        return out[:8]

    def _edit_new_skill_fields(self, donor: int, new_id: int, name, desc):
        """新技能字段编辑：数值 + 枚举下拉 + 8 个效果槽（搜索选择器）。取消 = 不改数值直接暂存。"""
        pr = self._donor_row_props(donor)
        cur = {k: pr.get(k, {}).get("Value") for k in
               [f[0] for f in self.NUM_FIELDS] + [f[0] for f in self.ENUM_FIELDS]}
        eff = self._donor_effects(donor)
        top = self.tk.Toplevel(self.root)
        top.title(f"新技能 {new_id} 的数值 / 属性 / 效果（源 {donor}）")
        top.geometry("760x820")
        self.ttk.Label(top, text=f"名称：{name or '（沿用源技能）'}", anchor="w").grid(
            row=0, column=0, columnspan=4, sticky="we", padx=8, pady=(8, 2))
        self.ttk.Label(top, text="改完点「确定」；点「取消」= 不改数值，直接暂存名称/描述",
                       anchor="w", foreground="#666").grid(row=1, column=0, columnspan=4, sticky="we", padx=8)

        vars_, enum_vars = {}, {}
        r = 2
        # 数值
        for key, label in self.NUM_FIELDS:
            self.ttk.Label(top, text=label, width=10, anchor="w").grid(row=r, column=0, sticky="w", padx=8, pady=2)
            v = self.tk.StringVar(value="" if cur.get(key) is None else str(cur[key]))
            vars_[key] = (v, cur.get(key))
            self.ttk.Entry(top, textvariable=v, width=24).grid(row=r, column=1, sticky="we", padx=4)
            r += 1
        # 枚举下拉
        for key, label in self.ENUM_FIELDS:
            self.ttk.Label(top, text=label, width=10, anchor="w").grid(row=r, column=0, sticky="w", padx=8, pady=2)
            choices = self._enum_choices(key)
            cb = self.ttk.Combobox(top, state="readonly", width=30, values=choices)
            curval = cur.get(key)
            if curval is not None:
                cb.set(str(curval))
            enum_vars[key] = (cb, curval)
            cb.grid(row=r, column=1, sticky="we", padx=4)
            r += 1
        # 效果槽 8 个
        self.ttk.Label(top, text="效果槽（effectBundleList）", anchor="w",
                       font=("Segoe UI", 10, "bold")).grid(row=r, column=0, columnspan=5, sticky="w", padx=8, pady=(8, 2))
        r += 1
        self.ttk.Label(top, text="  槽 / 效果 / TargetType / 关系 / 时机", anchor="w",
                       foreground="#666").grid(row=r, column=0, columnspan=5, sticky="w", padx=8)
        r += 1
        slots0 = self._donor_slots(donor)
        slot_enums = {f: self._slot_enum_values(f) for f in self.SLOT_ENUM_FIELDS}
        eff_vars = {}
        for i in range(8):
            d0 = slots0[i]
            self.ttk.Label(top, text=f"槽{i}", width=4, anchor="w").grid(row=r, column=0, sticky="w", padx=8)
            eid = d0["effectId"]
            lv = self.tk.StringVar(value=f"{eid}  {self.effect_names.get(eid, '')}".strip())
            holder = {"eid": eid, "var": lv}
            self.ttk.Entry(top, textvariable=lv, width=20, state="readonly").grid(row=r, column=1, sticky="we", padx=4)

            def make_pick(_h=holder):
                def pick():
                    def cb(new_id, _h=_h):
                        _h["eid"] = new_id
                        _h["var"].set(f"{new_id}  {self.effect_names.get(new_id, '')}".strip())
                    self._pick_effect(_h["eid"], cb)
                return pick

            self.ttk.Button(top, text="选…", command=make_pick()).grid(row=r, column=2, padx=2)
            combos = {}
            for c, f in enumerate(self.SLOT_ENUM_FIELDS, start=3):
                cb = self.ttk.Combobox(top, state="readonly", width=18, values=slot_enums[f])
                if d0.get(f):
                    cb.set(str(d0[f]))
                cb.grid(row=r, column=c, sticky="we", padx=2)
                combos[f] = (cb, d0.get(f))
            eff_vars[i] = {"h": holder, "combos": combos, "old": d0}
            r += 1
        for _c in (1, 2, 3, 4, 5):
            top.columnconfigure(_c, weight=1, minsize=110)

        result = {"ok": False, "fields": {}}

        def ok():
            out = {}
            for key, (v, old) in vars_.items():
                txt = v.get().strip()
                if not txt:
                    continue
                try:
                    val = float(txt)
                    if isinstance(old, int) or (old is None and val.is_integer()):
                        val = int(val)
                except Exception:
                    continue
                if old is None or str(val) != str(old):
                    out[key] = val
            if isinstance(out.get("hitCount"), int):
                for i, val in enumerate(self._hit_ratios(out["hitCount"])):
                    out[f"hitDamageRatioList[{i}]"] = val
            for key, (cb, old) in enum_vars.items():
                val = cb.get().strip()
                if val and str(val) != str(old):
                    out[key] = val
            if isinstance(out.get("element"), str):
                _icon = {"Fire": "Fire", "Water": "Water", "Wind": "Wind", "Ice": "Ice",
                         "Thunder": "Thunder", "Dark": "Dark", "Light": "Light", "Earth": "Earth",
                         "Heal": "Heal"}.get(out["element"])
                if _icon:
                    out["SkillIcon.TagName"] = f"UI.Skill.Action.Icon.{_icon}"
            for i, rec in eff_vars.items():
                if int(rec["h"]["eid"]) != int(rec["old"]["effectId"]):
                    out[f"effectBundleList[{i}].effectId"] = int(rec["h"]["eid"])
                for f, (cb, oldv) in rec["combos"].items():
                    nv = cb.get().strip()
                    if nv and str(nv) != str(oldv or ""):
                        out[f"effectBundleList[{i}].{f}"] = nv
            result["fields"] = out
            result["ok"] = True
            top.destroy()

        bar = self.ttk.Frame(top); bar.grid(row=r, column=0, columnspan=4, pady=10)
        self.ttk.Button(bar, text="确定", command=ok).pack(side="left", padx=6)
        self.ttk.Button(bar, text="取消（不改进数值）", command=top.destroy).pack(side="left")
        self.root.wait_window(top)
        if not result["ok"]:
            self.log("未改数值（只暂存名称/描述）")
            return {}
        return result["fields"]

    SLOT_ENUM_FIELDS = ["TargetType", "targetRelation", "activeSkillAddTiming"]

    def _slot_enum_values(self, field: str) -> list:
        try:
            cnt = {}
            for r in self.tables.rows("DT_SkillData"):
                for it in (props_of(r).get("effectBundleList", {}).get("Value") or []):
                    try:
                        d = {q["Name"]: q["Value"] for q in it["Value"]}
                        v = d.get(field)
                        if isinstance(v, str) and v:
                            cnt[v] = cnt.get(v, 0) + 1
                    except Exception:
                        continue
            return [k for k, _n in sorted(cnt.items(), key=lambda kv: -kv[1])]
        except Exception:
            return []

    def _skill_row_by_id(self, sid: int):
        try:
            rows = self.tables.rows("DT_SkillData")
            for i, r in enumerate(rows):
                if props_of(r).get("ID", {}).get("Value") == sid:
                    return i, r
        except Exception:
            pass
        return None, None

    def _asset_row_of(self, sid: int):
        """DT_SkillAsset 里按 ID 找 (行号, props)。"""
        try:
            rows = self.tables.rows("DT_SkillAsset")
            for i, r in enumerate(rows):
                pr = props_of(r)
                if pr.get("ID", {}).get("Value") == sid:
                    return i, pr
        except Exception:
            pass
        return None, None

    @staticmethod
    def _soft_path_str(v) -> str:
        """FSoftObjectPath 结构 → /Game/... 字符串。"""
        if isinstance(v, str):
            return v
        if isinstance(v, dict):
            ap = v.get("AssetPath") or {}
            if isinstance(ap, dict):
                pkg = ap.get("PackageName")
                if pkg:
                    return str(pkg)
            if v.get("AssetPathName"):
                return str(v["AssetPathName"])
        return ""

    def _sequence_paths_of(self, sid: int) -> tuple:
        """返回 (LevelSequence, soundSequence) 的 /Game 路径；资产行没有就按目录推导。"""
        _i, pr = self._asset_row_of(sid)
        ls = ss = ""
        if pr is not None:
            ls = self._soft_path_str(pr.get("LevelSequence", {}).get("Value"))
            ss = self._soft_path_str(pr.get("soundSequence", {}).get("Value"))
        if not ls:
            try:
                import skill_new as SN
                rel, _cat = SN.find_sequence(int(sid))
            except Exception:
                rel = None
            if rel:
                ls = f"/Game/{rel}/SEQ_Battle_{int(sid) + 1}_Master"
                ss = f"/Game/{rel}/Track/SEQ_Battle_{int(sid) + 1}_Sound_001"
        return ls, ss

    def on_replace_effect(self):
        """把当前技能的特效（演出）换成另一个技能的 —— 只改 DT_SkillAsset 的软路径，不动技能 ID。"""
        sid = getattr(self, "cur_sid", None)
        if not sid:
            q = (self.v_skillq.get() or "").strip()
            if q.isdigit():
                sid = int(q)
            elif q:
                sid = next((i for n, i in self.skill_names.items() if n == q), None)
        if not sid:
            self.log("先双击/读取一个技能，再点「替换特效…」")
            return
        sid = int(sid)
        my_i, my_pr = self._asset_row_of(sid)
        if my_pr is None:
            self.log(f"DT_SkillAsset 里没有技能 {sid} 的演出行（这个技能本身没有演出）")
            return
        cur_ls = self._soft_path_str(my_pr.get("LevelSequence", {}).get("Value"))
        cur_ss = self._soft_path_str(my_pr.get("soundSequence", {}).get("Value"))
        self.log(f"当前技能 {sid} 的演出：{cur_ls or '（空）'}")

        def picked(donor_id):
            donor_id = int(donor_id)
            d_ls, d_ss = self._sequence_paths_of(donor_id)
            if not d_ls:
                self.log(f"技能 {donor_id} 找不到演出（DT_SkillAsset 无行，也没扫到 SEQ 资产）")
                return
            self.edits[("DT_SkillAsset", my_i, ("LevelSequence",))] = d_ls
            if d_ss:
                self.edits[("DT_SkillAsset", my_i, ("soundSequence",))] = d_ss
            self.log(f"已暂存：用技能 {donor_id} 的演出替换当前技能 {sid} 的演出"
                     f"（{d_ls.rsplit('/', 1)[-1]}）")
            if hasattr(self, "_update_count"):
                try:
                    self._update_count()
                except Exception:
                    pass

        self._pick_skill(picked, plain=True)

    HELP_TEXT = """【总流程】所有改动都是「先暂存，最后生成一次」。
多个幻兵 / 多套技能请在同一个会话里做完再生成；
不要分几次生成再合并（同表会互相覆盖）。

【1】直接改（不换技能）
· ①②③④ 里双击要改的槽位 → 进入 ⑤
· ⑤ 下方表格双击字段改值；枚举字段会出下拉
· 改 hitCount 会自动分配伤害比例
· 改 element 会自动换技能图标
· 效果槽用「效果槽详情…」改（见 6）

【2】替换技能（同一个槽换别的技能）
· 双击槽位进入 ⑤ → 替换技能…
· 选源技能；「新 ID」留空 = 直接替换

【3】新技能（全新 ID）
· 替换技能… → 填新 ID（或点「生成新 ID」）
· 依次填：名称 → 描述 → 数值/属性/效果槽
· 再问「要用其它技能的特效吗？」
    否 = 用源技能演出（会克隆一份）
    是 = 再选一个技能，只换它的**特效**（动画仍用源技能）
· 生成时一起打包（含技能行/演出引用/演出资产）

【4】替换特效（整组演出，不动技能 ID）
· 选中技能 → 替换特效…
· 选源技能 → 该技能的 Master/Cut/Effect/Sound 全换成源的
· 伤害、名字、效果都不变，只有演出变

【5】分轨替换（动画用 A，特效用 D）／也能在「替换技能」里顺手做
· 选中技能 → 分轨替换…
· 先选「动画来源」，再选「特效来源」
· 结果：动作/时长来自 A，粒子特效用 D
· 例：飞石剑用疾风的动作 + 坚石剑的特效
· 「替换技能…」选完之后也会问「要不要配其它特效」（动画保持该技能自己的）

【6】效果槽详情
· 选中技能 → 效果槽详情…
· 8 个槽可改：效果 ID、TargetType、targetRelation、触发时机
· 挂减益请照抄真实用例：
   TargetType=SkillTarget、targetRelation=Friendlies、AfterDamageCalculation
· 可用减益：1167 减物防 / 1169 减魔防 / 1033 麻痹
· 效果搜索框支持中文（如 搜「减防」「麻痹」）

【7】暂存与生成
· 所有改动显示在状态里（已改 N 处）
· 点「生成 MOD」一次打包成一个三件套
· 日志会列出：普通改动、待打包的新技能、分轨

【8】新 ID 与「来源记录」（合并工具要用）
· 生成成功后记录到 config/created_skill_ids.json
· 「生成新 ID」按最大已用 ID+1 递增；手填会校验（非数字/超范围/已存在）
· 「清 ID 记录」可手动清空（回到 229001 起）
· ★ 每次生成还会写 save/_cache/fx_sources.json：
    {新技能ID: {anim: 动画源ID, fx: 特效源ID}}
  合并工具会读它来自动填「新技能ID:动画源:特效源」，
  所以：用本工具做出来的技能 MOD，合并时不用手填映射；
  换机器/清缓存后才会需要补填一次（合并成功会自动回写）

【9】已知限制（DEMO）
· TargetType 改成 Random 不一定生效
· LB（终结技）的效果槽可能只认其它 LB 的效果
· 有的技能段数由演出帧驱动，改 hitCount 不一定加段
· 改完需重启游戏才生效"""

    HELP_TEXT_EN = """[Workflow] Everything is STAGED first, then one Build.
Do all visions/skills for one mod in the same session, then build once.
Do NOT build several skill mods and merge them with the plain Merge tool.

[1] Direct edit (same skill)
· Double-click a slot in 1-4 to open it in 5
· Double-click a field in the 5 table; enums show a dropdown
· Changing hitCount auto-distributes hitDamageRatioList
· Changing element auto-updates SkillIcon
· Use "Effect slots..." to edit effects (see 6)

[2] Replace skill (same slot, another skill)
· Open the slot in 5 -> Replace skill... -> pick source
· Leave "New ID" empty = plain replacement

[3] New skill (brand-new ID)
· Replace skill... -> enter New ID (or "Gen new ID")
· Name -> Description -> numbers/attributes/effect slots
· Then: use another skill's visuals?
    No  = clone the source skill's visuals
    Yes = pick one skill and use its visuals (not cloned)
· Build packages skill row + visual refs + sequence assets

[4] Replace visuals (whole set, keep skill ID)
· Select skill -> Replace visuals... -> pick source
· Master/Cut/Effect/Sound all become the source's

[5] Split anim/FX (animation from A, effect from D)
· Select skill -> Split anim/FX... -> pick animation source, then effect source
· Also offered right after Replace skill...

[6] Effect slots
· Select skill -> Effect slots...
· 8 slots: effect ID, TargetType, targetRelation, timing
· Debuffs: copy real usage (SkillTarget / Friendlies / AfterDamageCalculation)
· Working ones: 1167 DEF-down, 1169 MDEF-down, 1033 Paralysis
· Search supports Chinese (e.g. 减防 / 麻痹)

[7] Stage & Build
· Status shows staged count; Build packs one triple
· Log lists plain edits, pending new skills, splits

[8] New IDs and source records (used by the Merge tool)
· Successful builds record config/created_skill_ids.json
· "Gen new ID" = max used + 1; typed IDs are validated
· "Clear ID records" resets to 229001
· Every build also writes save/_cache/fx_sources.json:
    {new_skill_id: {anim: animation_source_id, fx: effect_source_id}}
  The Merge tool reads it to auto-fill "new:anim:fx" mappings,
  so skill mods built here need no manual mapping.

[9] Known limits (DEMO)
· TargetType Random may not work
· LB effect slots may only accept other LB effects
· Some hit counts are driven by sequence events
· Restart the game after installing
"""

    def _ui_lang(self):
        try:
            import kit.settings as _K
            return str(_K.get("ui_lang") or "zh")
        except Exception:
            return "zh"

    def _tr(self, s):
        try:
            import kit.settings as _K
            if str(_K.get("ui_lang") or "zh") == "en":
                import kit.i18n as _I
                return _I.DICT.get(s, s)
        except Exception:
            pass
        return s

    def _help_text(self):
        try:
            import kit.settings as _K
            if str(_K.get("ui_lang") or "zh") == "en":
                return self.HELP_TEXT_EN
        except Exception:
            pass
        return self.HELP_TEXT

    def _build_help_panel(self, parent):
        """⑤ 页使用说明：放在技能表格右侧空白区；按钮行保持整行宽度。"""
        tree = self.trees["values"]
        bar = getattr(self, "_values_bar", None)
        box = self.ttk.LabelFrame(parent, text="使用说明")
        txt = self.tk.Text(box, wrap="word", font=("Microsoft YaHei UI", 9))
        sb = self.ttk.Scrollbar(box, orient="vertical", command=txt.yview)
        txt.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        txt.pack(side="left", fill="both", expand=True)
        txt.insert("1.0", self._help_text())
        txt.configure(state="disabled")
        # 重新按 顺序放置：按钮行（底）→ 说明（右）→ 表格（左）
        for w in (tree, bar, box):
            if w is not None:
                w.pack_forget()
        if bar is not None:
            bar.pack(side="bottom", fill="x", padx=4, pady=4)
        box.pack(side="right", fill="both", expand=True, padx=(6, 4), pady=(4, 0))
        tree.pack(side="left", fill="both", expand=True)
        # 让表格优先拿到自己的宽度：说明区不抢
        box.pack_configure(expand=True)

    def on_split_fx(self):
        """动画 / 特效拆分：动画用 A、特效用 D，生成时克隆到当前技能名下。"""
        sid = getattr(self, "cur_sid", None)
        if not sid:
            q = (self.v_skillq.get() or "").strip()
            if q.isdigit():
                sid = int(q)
            elif q:
                sid = next((i for n, i in self.skill_names.items() if n == q), None)
        if not sid:
            self.log("先双击/读取一个技能，再点「分轨替换…」")
            return
        sid = int(sid)
        anim, fxs = [], []
        self._pick_skill(lambda d: anim.append(int(d)), plain=True, block=True)
        if not anim:
            self.log("已取消（没选动画来源）")
            return
        self._pick_skill(lambda d: fxs.append(int(d)), plain=True, block=True)
        if not fxs:
            self.log("已取消（没选特效来源）")
            return
        A, D = anim[0], fxs[0]
        self.pending_fx.append({"skill": sid, "anim": A, "fx": D})
        self.log(f"已暂存分轨：技能 {sid} 用 {A} 的动画 + {D} 的特效（生成时克隆演出）")
        if hasattr(self, "_update_count"):
            try:
                self._update_count()
            except Exception:
                pass

    def on_clear_id_record(self):
        """手动清空「已生成的新技能 ID」记录（生成过但不想再占用号码时用）。"""
        try:
            import skill_new as SN
            f = SN.created_ids_file()
            ids = SN.load_created_ids()
            if not f.exists() or not ids:
                self.log("ID 记录本来就是空的")
                return
            if not messagebox.askyesno("清 ID 记录",
                                       f"当前记录了 {len(ids)} 个 ID：{ids[:20]}\n\n清空后「生成新 ID」会从 229001 重新开始。继续？",
                                       parent=self.root):
                return
            f.unlink(missing_ok=True)
            self.log(f"已清空 ID 记录（原 {len(ids)} 个），下一个：「生成新 ID」会从 229001 开始")
        except Exception as e:
            self.log(f"清 ID 记录失败：{e}")

    def on_effect_details(self):
        sid = getattr(self, "cur_sid", None)
        if not sid:
            q = (self.v_skillq.get() or "").strip()
            if q:
                if q.isdigit():
                    sid = int(q)
                else:
                    sid = next((i for n, i in self.skill_names.items() if n == q), None)
                if sid:
                    self.cur_sid = int(sid)
            if not sid:
                self.log("先双击一个技能（或在上方填技能 ID/名称后点「读取技能」），再点「效果槽详情…」")
                return
        idx, row = self._skill_row_by_id(int(sid))
        if row is None:
            self.log(f"DT_SkillData 里找不到技能 {sid}")
            return
        slots = props_of(row).get("effectBundleList", {}).get("Value") or []
        vals = {f: self._slot_enum_values(f) for f in self.SLOT_ENUM_FIELDS}
        self.log(f"效果槽枚举：TargetType {len(vals['TargetType'])} / relation {len(vals['targetRelation'])} / timing {len(vals['activeSkillAddTiming'])}")

        top = self.tk.Toplevel(self.root)
        top.title(f"技能 {sid} 的效果槽")
        top.geometry("1000x560")
        heads = ["槽", "效果", "TargetType", "targetRelation", "触发时机"]
        for c, h in enumerate(heads):
            self.ttk.Label(top, text=h, font=("Segoe UI", 9, "bold")).grid(row=0, column=c, sticky="w", padx=6, pady=4)
        rows_ui = []
        for i in range(8):
            d = {}
            if i < len(slots):
                try:
                    d = {q["Name"]: q["Value"] for q in slots[i]["Value"]}
                except Exception:
                    d = {}
            eid0 = d.get("effectId", -1)
            self.ttk.Label(top, text=f"{i}", width=3).grid(row=i + 1, column=0, padx=6)
            ev = self.tk.StringVar(value=f"{eid0}  {self.effect_names.get(eid0, '')}".strip())
            self.ttk.Entry(top, textvariable=ev, width=24, state="readonly").grid(row=i + 1, column=1, sticky="we", padx=4)
            holder = {"eid": eid0, "var": ev}

            def make_pick(_h=holder):
                def pick():
                    def cb(new_id, _h=_h):
                        _h["eid"] = new_id
                        _h["var"].set(f"{new_id}  {self.effect_names.get(new_id, '')}".strip())
                    self._pick_effect(_h["eid"], cb)
                return pick

            self.ttk.Button(top, text="选…", command=make_pick()).grid(row=i + 1, column=1, sticky="e")
            combos = {}
            for c, f in enumerate(self.SLOT_ENUM_FIELDS, start=2):
                cb = self.ttk.Combobox(top, state="readonly", width=20, values=vals[f])
                if d.get(f):
                    cb.set(str(d[f]))
                cb.grid(row=i + 1, column=c, sticky="we", padx=4)
                combos[f] = (cb, d.get(f))
            rows_ui.append({"i": i, "h": holder, "combos": combos, "old_eid": eid0})
        for c in (1, 2, 3, 4):
            top.columnconfigure(c, weight=1)

        def ok():
            n = 0
            for it in rows_ui:
                i = it["i"]
                if int(it["h"]["eid"]) != int(it["old_eid"]):
                    self.edits[("DT_SkillData", idx, ("effectBundleList", i, "effectId"))] = int(it["h"]["eid"])
                    n += 1
                for f, (cb, old) in it["combos"].items():
                    nv = cb.get().strip()
                    if nv and str(nv) != str(old or ""):
                        self.edits[("DT_SkillData", idx, ("effectBundleList", i, f))] = nv
                        n += 1
            top.destroy()
            self.log(f"效果槽详情：已暂存 {n} 处改动（技能 {sid}）")
            if hasattr(self, "_update_count"):
                try:
                    self._update_count()
                except Exception:
                    pass

        bar = self.ttk.Frame(top); bar.grid(row=10, column=0, columnspan=5, pady=10)
        self.ttk.Button(bar, text="确定", command=ok).pack(side="left", padx=6)
        self.ttk.Button(bar, text="取消", command=top.destroy).pack(side="left")

    def _make_new_skill(self, donor: int, new_id: int):
        """造全新 ID 的技能：skill_new（ffr-dt patch：加技能行 + 加演出引用行 + clone 演出树）"""
        import skill_new as SN
        cs = self.cur_slot
        if not cs or cs.get("row") is None or not cs.get("path"):
            self.log("新技能需要知道『装进哪个槽』：请到 ①②③④ 里**双击那个槽位**进入 ⑤"
                     "（只用「读取技能」看不出槽位），再点「替换技能…」并填新 ID")
            return
        slot_tbl = cs["table"]
        slot_idx = cs["row"]
        slot_path = ".".join(str(x) if not isinstance(x, int) else f"[{x}]" for x in cs["path"])
        slot_path = slot_path.replace(".[", "[")
        self.log(f"生成新技能：{donor} → {new_id}（槽位 {slot_tbl} 第 {slot_idx} 行 {slot_path}）")

        # ★ 新 ID 技能可以写「字面量」名称/描述（游戏内已验证会显示），留空则沿用源技能
        from tkinter import simpledialog
        src_name = self.sname(donor) or ""
        name = simpledialog.askstring(
            "新技能名称",
            f"给新技能 {new_id} 起个名字（留空 = 沿用源技能名「{src_name}」）：",
            parent=self.root)
        if name is None:
            self.log("已取消")
            return
        desc = simpledialog.askstring(
            "新技能描述",
            "描述（留空 = 沿用源技能描述）：", parent=self.root)
        if desc is None:
            self.log("已取消")
            return
        name = (name or "").strip() or None
        desc = (desc or "").strip() or None
        if name or desc:
            self.log(f"名称/描述将写为字面量：{name or '（沿用源）'}｜{desc or '（沿用源）'}")

        # ★ 先确认源技能有完整演出（没有 Master 就没法复制动画/特效）
        try:
            _d, _ = SN.find_sequence(int(donor))
        except Exception as e:
            messagebox.showerror("检查源技能演出失败",
                                 f"{type(e).__name__}: {e}", parent=self.root)
            return
        if not _d:
            messagebox.showerror("源技能没有演出",
                                 f"技能 {donor} 在游戏数据里找不到演出（SEQ_Battle_*_Master），\n"
                                 "只能复制数值，动画/特效无法复制。\n\n请换一个带完整演出的源技能。",
                                 parent=self.root)
            return

        # ★ 打开「字段编辑」：新技能可以继续改数值/元素等，最后一起打包
        fields = self._edit_new_skill_fields(donor, new_id, name, desc)
        if fields is None:
            fields = {}

        fx = []
        if messagebox.askyesno("新技能特效",
                               f"新技能 {new_id} 要配其它技能的「特效」吗？\n\n"
                               "动画保持源技能 " + str(donor) + " 的；选「是」只换粒子特效",
                               parent=self.root):
            self._pick_skill(lambda d: fx.append(int(d)), plain=True, block=True)
        fx_donor = fx[0] if fx else None

        try:
            orig_val = int((self.cur_slot or {}).get("orig"))
        except Exception:
            orig_val = None

        # ★ 只暂存，生成时随其它改动一起打包
        self.pending_new.append({
            "donor": donor, "new_id": new_id, "name": name, "desc": desc,
            "fields": fields, "fx_donor": fx_donor,
            "fallback": [orig_val] if orig_val else [],
            "slot": {"table": slot_tbl, "row": slot_idx, "path": list(cs["path"])},
        })
        if fields:
            self.log("  数值/属性改动：" + "，".join(f"{k}={v}" for k, v in list(fields.items())[:8]))
        self.log(f"已暂存新技能 {new_id}（源 {donor}"
                 + (f"，名称「{name}」" if name else "")
                 + (f"，描述「{desc}」" if desc else "")
                 + "）→ 点「生成 MOD」时一起打包")
        if hasattr(self, "_update_count"):
            try:
                self._update_count()
            except Exception:
                pass

    def on_replace_skill(self):
        """把当前技能在它所在的槽里替换成另一个技能，然后刷新界面"""
        cs = self.cur_slot
        if not cs or cs.get("row") is None or not cs.get("path"):
            self.log("请先从 ①②③④ 里双击一个技能进入 ⑤，再点「替换技能…」")
            return

        def _do(new_id):
            self.edits[(cs["table"], cs["row"], tuple(cs["path"]))] = new_id
            self._update_count()
            self.log(f"已暂存：{cs['label']} 替换为 {new_id}（{self.sname(new_id)}）")
            self.log("  ↳ 可继续在 ⑤ 表格双击改字段（数值/效果/图标都会一起打包）")
            self.cur_slot = {"table": cs["table"], "row": cs["row"],
                             "path": cs["path"], "tab": cs["tab"], "label": cs["label"],
                             "orig": new_id}
            self._open_skill(new_id)
            # ★ 可选：顺手给这个技能做「动画/特效分轨」
            try:
                if messagebox.askyesno("替换特效",
                                       f"要给技能 {new_id}（{self.sname(new_id)}）配其它「特效」吗？\n\n"
                                       "动画保持它自己的；选「是」只换粒子特效", parent=self.root):
                    d = []
                    self._pick_skill(lambda x: d.append(int(x)), plain=True, block=True)
                    if d:
                        self.pending_fx.append({"skill": int(new_id), "anim": int(new_id), "fx": d[0]})
                        self.log(f"已暂存特效替换：技能 {new_id} 保持自己动画，特效用 {d[0]}")
            except Exception as e:
                self.log(f"分轨设置失败：{e}")
            self._refresh_source(cs["tab"])
        self._pick_skill(_do)

    def _refresh_source(self, tab):
        q = self.last_query
        try:
            if tab == "native":
                self._load_level_into("native", q)
            elif tab in ("vision", "truevision"):
                self._load_mastery(tab, q)
            elif tab == "summon":
                self._load_summon(q)
        except Exception as e:
            self.log(f"刷新列表失败：{e}")

    def _open_table_row(self, table, sid):
        """在 ⑤ 里显示 PassiveSkill / MasterSkill 这类非 SkillData 的行的字段"""
        try:
            rows = self.tables.rows(table)
        except Exception as e:
            self.log(f"{table} 读取失败：{e}")
            return
        idx = None
        for i, r in enumerate(rows):
            pr = props_of(r)
            if pr.get("ID", {}).get("Value") == sid:
                idx = i
                break
        if idx is None:
            self.log(f"{table} 里找不到 ID {sid}")
            return
        self.nb.select(4)
        t = self.trees["values"]
        t.delete(*t.get_children())
        self.rowmeta["values"] = []
        r = rows[idx]
        self.v_skillinfo.set(f"{table}｜ID {sid}｜{r['Name']}")
        shown = 0
        for pr in r["Value"]:
            name = pr["Name"]
            val = pr["Value"]
            typ = str(pr.get("$type", "")).split(".")[-1].split(",")[0]
            if not isinstance(val, (int, float, str, bool)):
                continue
            t.insert("", "end", values=(name, val, typ))
            self.rowmeta["values"].append({"table": table, "row": idx, "path": [name],
                                           "label": f"{r['Name']} · {name}"})
            shown += 1
        self.log(f"⑤ 已载入 {table} ID {sid}：{shown} 个可改字段")

    def _open_skill(self, sid, kind=None):
        """双击 1-4 页的技能 → 切到 ⑤ 并读取"""
        try:
            if kind == "PassiveSkill":
                self._open_table_row("DT_PassiveSkillData", sid)
                return
            if kind == "MasterSkill":
                self._open_table_row("DT_MasterSkillData", sid)
                return
            self.nb.select(4)
            self.cur_sid = int(sid)
            self.v_skillq.set(str(sid))
            self.on_load_skill()
        except Exception as e:
            self.log(f"跳转失败：{e}")

    ENUM_CHOICES = {
        "element": ["None", "Fire", "Water", "Wind", "Ice", "Thunder", "Dark", "Light", "Earth"],
        "TargetType": ["Single", "Group", "Self", "Random", "All", "SingleAndGroup"],
        "DamageType": ["Physic", "Magic", "None"],
        "damageCalcType": ["None", "Physic", "Magic", "Fixed", "TargetMaxHPRatio",
                           "TargetCurHPRatio", "MPAbsorb", "InvokerCurrentHP", "Level3Flare",
                           "ThrowMoney", "EscapeNum", "GoodLuck", "SameLevel", "DefeatUnitNum"],
        "skillAttrType": ["Ability", "Magic", "MagicSword", "Item", "Fight", "FinishBlow",
                          "Throw", "LimitBurst", "Summon", "ChaseAttack", "Mechabo", "Escape",
                          "ThrowMoney", "Mimic"],
        "parameterType": ["HitPoint", "MagicPoint", "BreakPoint"],
        "statusCondition": ["None", "Poison", "Sleep", "Silence", "Paralyze", "Confuse",
                            "Charm", "Berserk", "Stone", "Death"],
    }

    SKILL_FIELDS = [("Cost", "MP 消耗"), ("equipCost", "装配点"), ("magnification", "威力"),
                    ("breakDamageValue", "破防值"), ("accuracy", "命中"), ("criticalHitRate", "暴击率"),
                    ("hitCount", "Hit 数"), ("skillIdAfterModeChange", "变化后技能"),
                    ("element", "元素属性"), ("skillAttrType", "技能属性分类"),
                    ("DamageType", "伤害类型（物理/法术）"), ("damageCalcType", "伤害计算式"),
                    ("TargetType", "目标类型"),
                    ("playSequencerId", "演出/特效 ID（playSequencerId）"),
                    ("sequencerIdWhenTargetFriendlies", "友方目标演出 ID")]

    def on_load_elements(self):
        """⑤ 显示单位的 ElementResistanceList（8 项，界面 Element 那排图标）"""
        q = self.v_skillq.get().strip() or self.v_unit.get().strip()
        if not q:
            self.log("先填单位名/ID")
            return
        row = self._resolve_unit_row(q)
        if row is None:
            self.log(f"找不到单位：{q}")
            return
        rows = self.tables.rows("DT_UnitParameter")
        idx = rows.index(row)
        pr = props_of(row)
        erl = (pr.get("ElementResistanceList") or {}).get("Value") or []
        if not erl:
            self.log("这个单位没有 ElementResistanceList")
            return
        self.nb.select(4)
        t = self.trees["values"]
        t.delete(*t.get_children())
        self.rowmeta["values"] = []
        self.v_skillinfo.set(f"单位 {pr.get('ID', {}).get('Value')}｜{row['Name']}｜属性图标 {len(erl)} 项")
        for i, item in enumerate(erl):
            try:
                val = item[0]["Value"]
            except Exception:
                val = "?"
            t.insert("", "end", values=(f"属性图标{i + 1}（ElementResistanceList）", val, ""))
            self.rowmeta["values"].append({"table": "DT_UnitParameter", "row": idx,
                                           "path": ["ElementResistanceList", i, 0],
                                           "label": f"{row['Name']} · 属性图标{i + 1}"})
        self.log(f"⑤ 已载入 {row['Name']} 的 {len(erl)} 个属性图标（下拉选元素即可改，图标会跟着变）")

    def on_load_skill(self):
        """⑤ 技能数值：按 ID / 中英文名定位 DT_SkillData 行"""
        q = self.v_skillq.get().strip()
        if not q:
            self.log("⑤ 先填技能 ID 或名字")
            return
        try:
            rows = self.tables.rows("DT_SkillData")
        except Exception as e:
            self.log(f"DT_SkillData 读取失败：{e}")
            return
        if not self.skill_row:
            for i, r in enumerate(rows):
                try:
                    self.skill_row[props_of(r)["ID"]["Value"]] = i
                except Exception:
                    pass
        sid = None
        if q.isdigit():
            sid = int(q)
        else:
            nm2id = {v.strip(): k for k, v in self.skill_names.items() if v}
            sid = nm2id.get(q)
            if sid is None:
                for nm, k in nm2id.items():
                    if nm and (nm in q or q in nm):
                        sid = k
                        break
        if sid not in self.skill_row:
            self.log(f"⑤ 找不到技能：{q}")
            return
        i = self.skill_row[sid]
        r = rows[i]
        t = self.trees["values"]
        t.delete(*t.get_children())
        self.rowmeta["values"] = []
        pr = props_of(r)
        self.v_skillinfo.set(f"ID {sid}｜{self.sname(sid)}｜{r['Name']}")
        for fld, label in self.SKILL_FIELDS:
            if fld not in pr:
                continue
            v = pr[fld]["Value"]
            t.insert("", "end", values=(f"{label}（{fld}）", v, pr[fld].get("$type", "").split(".")[-1].split(",")[0]))
            self.rowmeta["values"].append({"table": "DT_SkillData", "row": i, "path": [fld],
                                           "label": f"{self.sname(sid) or sid} · {label}"})
        # 效果槽（8 个）：effectId = -1 是空槽
        if not self.effect_names:
            try:
                for er in self.tables.rows("DT_SkillEffectData"):
                    epr = props_of(er)
                    eid = epr.get("ID", {}).get("Value")
                    if isinstance(eid, int):
                        self.effect_names[eid] = er["Name"]
                self.log(f"效果名就绪：{len(self.effect_names)} 条")
            except Exception as e:
                self.log(f"效果表读取失败：{e}")
        # 命中特效（DT_BtlHitEffectData，按技能 ID 成行）
        HIT_FIELDS = [("NormalEffectID", "普通命中特效"), ("CriticalEffectID", "暴击特效"),
                      ("WeaknessEffectID", "弱点特效"), ("MissEffectID", "未命中特效"),
                      ("AdditionalEffectID", "追加特效"), ("DeathEffectID", "死亡特效")]
        if not self.hit_row:
            try:
                for hi, hr in enumerate(self.tables.rows("DT_BtlHitEffectData")):
                    hp = props_of(hr)
                    hid = hp.get("ID", {}).get("Value")
                    if isinstance(hid, int):
                        self.hit_row[hid] = hi
                self.log(f"命中特效表就绪：{len(self.hit_row)} 个对象 ID")
            except Exception as e:
                self.log(f"命中特效表读取失败：{e}")
        hi = self.hit_row.get(sid)
        if hi is not None:
            hrow = self.tables.rows("DT_BtlHitEffectData")[hi]
            hp = props_of(hrow)
            for fld, label in HIT_FIELDS:
                if fld not in hp:
                    continue
                hv = hp[fld]["Value"]
                t.insert("", "end", values=(f"命中·{label}（{fld}）", hv, ""))
                self.rowmeta["values"].append({"table": "DT_BtlHitEffectData", "row": hi,
                                               "path": [fld], "label": f"{sid} · {label}"})
        else:
            t.insert("", "end", values=("命中特效", "该技能没有命中特效行", ""))
        eb = (props_of(r).get("effectBundleList") or {}).get("Value") or []
        for k, slot in enumerate(eb):
            sp = props_of(slot)
            eid = (sp.get("effectId") or {}).get("Value", -1)
            tag = self.effect_names.get(eid, "") if isinstance(eid, int) and eid > 0 else "（空槽）"
            t.insert("", "end", values=(f"效果槽{k + 1}（effectId）", eid, tag))
            self.rowmeta["values"].append({"table": "DT_SkillData", "row": i,
                                           "path": ["effectBundleList", k, "effectId"],
                                           "label": f"{self.sname(sid) or sid} · 效果槽{k + 1}"})
        self.log(f"⑤ 已载入 {sid}（{self.sname(sid)}）：{len(self.rowmeta['values'])} 个可改字段"
                 f"（含效果槽 {len(eb)} 个）")

    # ---- 编辑 ----
    @staticmethod
    def _hit_ratios(n: int) -> list:
        """hitCount=n 时的 31 项伤害分配（前 n 项均分，其余 0）。"""
        n = max(1, min(31, int(n)))
        base = round(1.0 / n, 4)
        vals = [base] * (n - 1)
        vals.append(round(1.0 - sum(vals), 4))
        return [float(round(x, 6)) for x in vals] + [0.0] * (31 - n)

    def _stage_hit_ratios(self, table, row, n):
        for i, val in enumerate(self._hit_ratios(n)):
            self.edits[(table, row, ("hitDamageRatioList", i))] = val

    def on_edit(self, tab, event=None):
        t = self.trees[tab]
        item = t.identify_row(event.y) if event is not None else (t.selection() or [None])[0]
        if not item:
            self.log("先选一行")
            return
        pos = t.index(item)
        metas = self.rowmeta.get(tab) or []
        if pos >= len(metas):
            self.log("这一行不可编辑")
            return
        meta = metas[pos]
        path = meta.get("path")
        if tab == "native":
            col = 1
            if event is not None:
                col = int(t.identify_column(event.x)[1:]) - 1     # 0=Level
            if not (1 <= col <= 3):
                self.log("双击「槽1/槽2/槽3」那一列才能改")
                return
            paths = meta.get("paths") or []
            if col - 1 >= len(paths):
                self.log("这个槽不存在")
                return
            path = paths[col - 1]
        sid = meta.get("skill")
        if sid and isinstance(sid, int) and sid > 0 and (event is not None):
            self.cur_slot = {"table": meta.get("table"), "row": meta.get("row"),
                             "path": path or meta.get("path"), "tab": tab,
                             "label": meta.get("label"), "orig": sid}
            self._open_skill(sid, meta.get("kind"))
            return
        if not path:
            self.log("这一行不可编辑")
            return
        rows = self.tables.rows(meta["table"])
        old = get_value(rows[meta["row"]]["Value"], path)
        if path and path[0] == "effectBundleList":
            def _cb(eid, _m=meta, _p=list(path), _o=old):
                self.edits[(_m["table"], _m["row"], tuple(_p))] = eid
                self._update_count()
                self.log(f"已暂存：{_m['label']} {_o} → {eid}（{self.effect_names.get(eid, '')}）")
            self._pick_effect(old, _cb)
            return
        win = self.tk.Toplevel(self.root)
        win.title(f"{meta['label']} = {old}")
        win.geometry("460x160")
        self.ttk.Label(win, text=f"{meta['label']}   当前 = {old}（{self.sname(old)}）").pack(pady=8)
        v = self.tk.StringVar(value=str(old))
        is_effect = bool(path) and path[0] == "effectBundleList"
        choices = self.ENUM_CHOICES.get(path[0]) if path else None
        if path and path[0] == "ElementResistanceList":
            choices = ["eElement::" + x for x in
                       ("None", "Fire", "Water", "Wind", "Ice", "Thunder", "Dark", "Light", "Earth")]
        if is_effect:
            self._pick_effect(win, old)
            win.destroy()
            return
        if choices:
            e = self.ttk.Combobox(win, textvariable=v, values=choices, state="readonly", width=24)
            e.pack()
            e.focus_set()
            self.ttk.Label(win, text="下拉选择（枚举字段）").pack(pady=2)
        else:
            e = self.ttk.Entry(win, textvariable=v, width=18)
            e.pack()
            e.focus_set()
            self.ttk.Label(win, text="填数值 / 技能 ID（-1 = 空槽）；回车确定").pack(pady=2)

        def ok(_e=None):
            raw = v.get().strip()
            try:
                nv = int(raw)
            except Exception:
                nv = raw                      # 枚举字段直接存字符串
            if isinstance(nv, str) and not nv:
                self.log("不能为空")
                return
            self.edits[(meta["table"], meta["row"], tuple(path))] = nv
            if tuple(path) == ("element",) and isinstance(nv, str):
                _icon = {"Fire": "Fire", "Water": "Water", "Wind": "Wind", "Ice": "Ice",
                         "Thunder": "Thunder", "Dark": "Dark", "Light": "Light", "Earth": "Earth",
                         "Heal": "Heal"}.get(nv)
                if _icon:
                    self.edits[(meta["table"], meta["row"], ("SkillIcon", "TagName"))] = \
                        f"UI.Skill.Action.Icon.{_icon}"
                    self.log(f"  已同步图标：UI.Skill.Action.Icon.{_icon}")
            if tuple(path) == ("hitCount",) and isinstance(nv, int):
                self._stage_hit_ratios(meta["table"], meta["row"], nv)
                self.log(f"  已同步伤害分配：{self._hit_ratios(nv)[:nv]}")
            self._update_count()
            self.log(f"已暂存：{meta['label']} {old} → {nv}（{self.sname(nv)}）")
            win.destroy()
        e.bind("<Return>", ok)
        self.ttk.Button(win, text="确定", command=ok).pack(pady=8)

    def on_undo(self, tab):
        self.log("（v0.1：撤销请重新读取或改回原值）")

    def _update_count(self):
        self.v_count.set(f"已改 {len(self.edits)} 处" if self.edits else "未修改")

    # ---- 生成 ----
    def on_build(self):
        if (not self.edits and not getattr(self, "pending_new", []) and not getattr(self, "pending_fx", [])
                and not getattr(self, "pending_rows", []) and not getattr(self, "pending_sets", [])
                and not getattr(self, "pending_assets", [])):
            self.log("没有任何修改（也没暂存新技能 / 分轨替换）")
            return
        self._save_cfg()
        threading.Thread(target=self._build_job, daemon=True).start()

    def _build_job(self):
        """一次性打包：普通改值 + 暂存的新技能（含演出克隆）+ 文字改动。"""
        try:
            paks, repak, retoc = self._paths()
            name = (self.v_name.get() or "SkillMod").strip()
            out = Path(self.v_out.get().strip() or OUT_DIR)
            out.mkdir(parents=True, exist_ok=True)
            work = CACHE / "build"
            shutil.rmtree(work, ignore_errors=True)
            legacy = work / "legacy"
            legacy.mkdir(parents=True)
            sys.path.insert(0, str(APP_DIR))
            import skill_new as SN

            def pstr(p):
                t = ""
                for step in p:
                    t += f"[{step}]" if isinstance(step, int) else (("." if t else "") + str(step))
                return t

            ops = {}

            def put_set(asset, row_name, d):
                e = ops.setdefault(asset, {"add": [], "set": []})
                e["set"].append({"row": row_name, "set": d})

            # ① 普通改值
            by_table = {}
            for (table, row, path), val in self.edits.items():
                by_table.setdefault(table, []).append((row, list(path), val))
            n_plain = 0
            for table, items in by_table.items():
                rows = self.tables.rows(table)
                for row, path, val in items:
                    put_set(SN.table_rel(table), rows[row]["Name"], {pstr(path): val})
                    n_plain += 1
            if n_plain:
                self.log(f"普通改动：{n_plain} 处 / {len(by_table)} 张表")

            # ①b 通用新增行 / 改值（合并工具用）
            for _r in (getattr(self, "pending_rows", []) or []):
                asset = SN.table_rel(_r["table"])
                e = ops.setdefault(asset, {"add": [], "set": []})
                e["add"].append({"row": _r["row"], "cloneFrom": _r.get("cloneFrom"), "set": _r.get("set") or {}})
                self.log(f"  新增行：{_r['table'].rsplit('/',1)[-1]} / {_r['row']}")
            for _s in (getattr(self, "pending_sets", []) or []):
                asset = SN.table_rel(_s["table"])
                e = ops.setdefault(asset, {"add": [], "set": []})
                e["set"].append({"row": _s["row"], "set": _s.get("set") or {}})
                self.log(f"  改值：{_s['table'].rsplit('/',1)[-1]} / {_s['row']}（{len(_s.get('set') or {})} 个字段）")

            # ② 新技能（暂存里可能有多个）
            clones = []
            pend = getattr(self, "pending_new", []) or []
            if pend:
                def _slot_desc(p_):
                    sl = p_.get("slot")
                    if not sl:
                        return "槽位由其它改动负责"
                    return f"槽 {sl['table'].rsplit('/',1)[-1]} 行 {sl['row']}"
                self.log("待打包的新技能：" + "、".join(
                    f"{p_['new_id']}（源 {p_['donor']}，{_slot_desc(p_)}）" for p_ in pend))
            for p_ in pend:
                pl = SN.plan_new_skill(p_["donor"], p_["new_id"], name=p_.get("name"), desc=p_.get("desc"),
                                       fallback_seq_ids=p_.get("fallback") or [], log=self.log,
                                       legacy=legacy)
                fx_d = p_.get("fx_donor")
                if fx_d:
                    try:
                        SN.run_fx_split(int(p_["new_id"]), int(p_["donor"]), int(fx_d),
                                        work / "out", work / "fx", self.log,
                                        s_rel=pl.get("seq_dir"))
                        self.log(f"新技能 {p_['new_id']}：动画保留 {p_['donor']}，特效用 {fx_d}")
                        pl["clones"] = []      # 已由分轨写好，避免 patch 再克隆一遍把特效覆盖回源技能
                    except Exception as e:
                        raise RuntimeError(f"新技能 {p_['new_id']} 特效替换失败：{e}")
                for op in pl["tables"]:
                    if op["asset"].endswith("DT_SkillData") and p_.get("fields"):
                        for ad in op.get("add") or []:
                            ad.setdefault("set", {}).update(p_["fields"])
                    e = ops.setdefault(op["asset"], {"add": [], "set": []})
                    e["add"] += op.get("add") or []
                    e["set"] += op.get("set") or []
                clones += pl["clones"]
                slot = p_.get("slot")
                if slot:
                    rows = self.tables.rows(slot["table"])
                    put_set(SN.table_rel(slot["table"]), rows[slot["row"]]["Name"],
                            {pstr(slot["path"]): p_["new_id"]})
                self.log(f"新技能 {p_['new_id']}：演出 {pl['have_seq']}/4，并入本次打包")

            if not ops:
                raise RuntimeError("没有可生成的改动")

            job = {"legacyRoot": str(legacy), "outRoot": str(work / "out"),
                   "tables": [], "clones": clones}
            (work / "out").mkdir(parents=True, exist_ok=True)
            for asset, op in ops.items():
                entry = {"asset": asset}
                if op["add"]:
                    entry["add"] = op["add"]
                if op["set"]:
                    entry["set"] = op["set"]
                job["tables"].append(entry)

            # ★ patch 前：把 ops 里出现的所有表抽到 legacy（ffr-dt 只认识 legacyRoot 下的资产）
            need = set()
            for asset in ops:
                need.add(asset.rsplit("/", 1)[-1])
            for p_ in pend:
                if p_.get("slot"):
                    need.add(p_["slot"]["table"].rsplit("/", 1)[-1])
            for t in sorted(need):
                f = f"{t}.uasset"
                if next(legacy.rglob(f), None):
                    continue
                self.log(f"  抽取 {t} …")
                run([retoc, "to-legacy", SN._bv(), legacy, "-f", f, "--no-shaders"], timeout=1800)

            jobp = work / "job.json"
            jobp.write_text(json.dumps(job, ensure_ascii=False, indent=1), encoding="utf-8")
            dt, mp = SN.FFRDT, SN.USMAP
            self.log(f"ffr-dt patch（{len(job['tables'])} 张表 / {len(clones)} 个克隆）…")
            rc, o, _e = run([dt, "patch", jobp, "--usmap", mp], timeout=3600)
            if rc != 0:
                raise RuntimeError("patch 失败：" + (o[-500:] or _e[-500:]))
            for line in o.strip().splitlines():
                if line.strip().startswith(("+", "~", "*", "=")):
                    self.log("   " + line.strip())

            # ②a 通用资产克隆（合并进来的演出/贴图等；走 ffr-dt 归一化）
            for _a in (getattr(self, "pending_assets", []) or []):
                leg_root = Path(_a["leg_root"])
                rel = _a["rel"]
                if not (leg_root / rel).with_suffix(".uasset").exists():
                    self.log(f"  ⚠ 资产源不存在：{leg_root / rel}")
                    continue
                job2 = {"legacyRoot": str(leg_root), "outRoot": str(work / "out"),
                        "tables": [], "clones": [{"from": rel, "to": rel, "rename": []}]}
                jp2 = work / "assets.json"
                jp2.write_text(json.dumps(job2, ensure_ascii=False), encoding="utf-8")
                rc, o, _e = run([dt, "patch", jp2, "--usmap", mp], timeout=1800)
                if rc != 0:
                    self.log(f"  ⚠ 资产克隆失败 {rel}: {o[-200:]}")

            # ②b 分轨替换（动画/特效拆分）
            fx_pend = getattr(self, "pending_fx", []) or []
            for p_ in fx_pend:
                try:
                    wrote = SN.run_fx_split(int(p_["skill"]), int(p_["anim"]), int(p_["fx"]),
                                            work / "out", work / "fx", self.log)
                    self.log(f"  分轨：写入 {len(wrote)} 个演出资产")
                except Exception as e:
                    self.log(f"⚠ 分轨失败（技能 {p_['skill']}）：{e}")

            # ③ 打包 utoc/ucas
            stem = name if name.endswith("_P") else name + "_P"
            utoc, ucas, pak = out / f"{stem}.utoc", out / f"{stem}.ucas", out / f"{stem}.pak"
            for f in (utoc, ucas, pak):
                f.unlink(missing_ok=True)
            self.log("retoc to-zen …")
            rc, o, _e = run([retoc, "to-zen", "--version", "UE5_6", work / "out", utoc], timeout=3600)
            if rc != 0 or not utoc.exists():
                raise RuntimeError("to-zen 失败：" + o[-300:])

            # ④ pak：有文字改动就把 locres 打进去，否则空 pak
            stage = work / "_pak_stage"
            stage.mkdir(parents=True, exist_ok=True)
            wrote_text = 0
            if getattr(self, "text_edits", None):
                try:
                    import FFRS_TextMod_Tool as TT
                    if not getattr(self, "locres_by_lang", None):
                        self._ensure_names()
                    for lang, L in (self.locres_by_lang or {}).items():
                        per = {nk: d[lang] for nk, d in self.text_edits.items()
                               if d.get(lang) is not None and d[lang] != (L.text(*nk) or "")}
                        if not per:
                            continue
                        outp = stage / TT.LOCRES_REL / lang / "Game.locres"
                        L.save_with_edits(outp, per)
                        wrote_text += len(per)
                        self.log(f"  {lang}: 文字改动 {len(per)} 条（回读校验通过）")
                except Exception as e:
                    self.log(f"⚠ locres 打包失败，退化为空 pak：{e}")
                    wrote_text = 0
            seed = BASE_SEED
            if wrote_text:
                try:
                    import FFRS_TextMod_Tool as TT
                    seed = TT.pak_seed(repak, Path(paks) / "FFRS-Windows.pak", self.log)
                except Exception:
                    pass
            rc, o, e = run([repak, "pack", "-m", MOUNT, "--version", "V11",
                            "-p", str(seed), stage, pak], timeout=900)
            if not pak.exists():
                raise RuntimeError(f"_P.pak 生成失败：{(e or o)[-200:]}")
            for p_ in pend:                      # ★ 记录动画/特效来源（合并工具要用）
                try:
                    SN.remember_fx_source(int(p_["new_id"]), int(p_["donor"]),
                                          int(p_["fx_donor"]) if p_.get("fx_donor") else None)
                except Exception:
                    pass
            for p_ in (getattr(self, "pending_fx", []) or []):
                try:
                    SN.remember_fx_source(int(p_["skill"]), int(p_["anim"]), int(p_["fx"]))
                except Exception:
                    pass
            for p_ in pend:                      # ★ 记录用过的 ID，供下次自动排号
                try:
                    SN.remember_id(int(p_["new_id"]))
                except Exception:
                    pass
            for f in (pak, utoc, ucas):
                if f.exists():
                    self.log(f"  {f.name} {f.stat().st_size:,} B")
            self.log(f"生成完成 → {out}（普通改动 {n_plain} 处 / 新技能 {len(pend)} 个）")
        except Exception as e:
            self.log("生成失败：" + str(e))
            self.log(traceback.format_exc(limit=3))

    def _chunk_map(self, paks, retoc) -> dict:
        cache = CACHE / "chunks.json"
        if cache.exists():
            try:
                m = json.loads(cache.read_text(encoding="utf-8"))
                if m:
                    return m
            except Exception:
                pass
        base = Path(paks) / "FFRS-Windows.utoc"
        work = CACHE / "_man"
        shutil.rmtree(work, ignore_errors=True)
        work.mkdir(parents=True, exist_ok=True)
        cwd = os.getcwd()
        try:
            os.chdir(work)
            rc, o, e = run([retoc, "manifest", str(base)], timeout=1800)
        finally:
            os.chdir(cwd)
        pj = work / "pakstore.json"
        if not pj.exists():
            raise RuntimeError(f"取容器 manifest 失败：{(e or o)[-200:]}")
        d = json.loads(pj.read_text(encoding="utf-8"))
        m = {}
        for ent in (d.get("oplog") or {}).get("entries") or []:
            ps = ent.get("packagestoreentry") or {}
            pd = (ent.get("packagedata") or [{}])
            name = str(ps.get("packagename") or "")
            base_name = name.rsplit("/", 1)[-1]
            if not base_name or not pd or not pd[0].get("id"):
                continue
            m.setdefault(base_name, {"id": pd[0]["id"], "path": pd[0].get("filename")})
        cache.write_text(json.dumps(m, ensure_ascii=False), encoding="utf-8")
        self.log(f"容器 manifest 就绪：{len(m)} 张表")
        return m

    def _chunk_of(self, table, paks, retoc):
        m = self._chunk_map(paks, retoc)
        hit = m.get(table)
        if not hit:
            raise RuntimeError(f"容器 manifest 里找不到 {table}")
        return hit["id"], hit["path"]

    # ---- 安装 / 还原 ----
    def on_install(self):
        try:
            paks, _r, _rt = self._paths()
            name = (self.v_name.get() or "SkillMod").strip()
            files = [Path(self.v_out.get()) / f"{name}_P{s}" for s in (".pak", ".utoc", ".ucas")]
            miss = [f.name for f in files if not f.exists()]
            if miss:
                self.log("还没生成：" + "、".join(miss))
                return
            for f in files:
                shutil.copy2(f, Path(paks) / f.name)
                self.log(f"已安装 {f.name}")
            (APP_DIR / "ffrs_skillmod_state.json").write_text(
                json.dumps({"installed": [f.name for f in files]}), encoding="utf-8")
        except Exception as e:
            self.log("安装失败：" + str(e))

    def on_restore(self):
        st = APP_DIR / "ffrs_skillmod_state.json"
        if not st.exists():
            self.log("没有安装记录")
            return
        try:
            paks, _r, _rt = self._paths()
            rec = json.loads(st.read_text(encoding="utf-8"))
            for n in rec.get("installed", []):
                p = Path(paks) / n
                if p.exists():
                    p.unlink()
                    self.log(f"已删除 {n}")
            st.unlink()
        except Exception as e:
            self.log("还原失败：" + str(e))

    def _save_cfg(self):
        self.settings.update({"game_root": self.v_root.get(), "out_dir": self.v_out.get(),
                              "uassetgui": self.v_uag.get(), "repak": self.v_repak.get(),
                              "retoc": self.v_retoc.get(), "unit": self.v_unit.get(),
                              "mod_name": self.v_name.get()})
        save_settings(self.settings)

    def run(self):
        self.root.protocol("WM_DELETE_WINDOW", lambda: (self._save_cfg(), self.root.destroy()))
        self.root.mainloop()


if __name__ == "__main__":
    App().run()
