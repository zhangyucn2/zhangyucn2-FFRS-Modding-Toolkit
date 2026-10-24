"""FFRS 文本修改工具（Text Mod Tool）

给 FINAL FANTASY RESONANCE DEMO 做「角色相关文本」的四语替换：
    简体中文（zh-Hans）/ 繁体中文（zh-Hant）/ 日文（ja）/ 英文（en）

数据来源（全部实测，见 docs/memory/ffrs-text-locres-and-13100.md）：
  * 四语正文 → `.pak` 里的 `FFRS/Content/Localization/Game/<lang>/Game.locres`
    （用 repak.exe 抽出来；Datatable 里的 StringTable 只有日文一份，中文不在那儿）
  * 角色 → LB 技能 → 字幕：
      - 幻兵（vision）与 LB 技能的对应在 `Datatable/Item/Vision/DT_VisionItemData.uexp`
        （实测 26 个幻兵各恰好 1 条技能 id，例：13100 → 440010）
      - `Datatable/Event/Text/BattleSequencerEvent/DT_BtlEv_<技能id>.uexp` 里直接写着
        字幕 key（例：440010 → BtlLegendCGMV_001/002/072）
    → 这两张表在 IoStore 里，用 retoc.exe to-legacy 抽（基础容器视图，不受已装 MOD 影响）

修改只落在内存里；点「生成 MOD」才会把改过的 Game.locres 打进
`<名字>_P.{pak,utoc,ucas}` 三件套（还原 = 删掉这三个文件）。

用法：
    python FFRS_TextMod_Tool.py              # 开界面
    python FFRS_TextMod_Tool.py --selftest 光之战士   # 不开界面，打印分类结果（调试用）
"""
from __future__ import annotations

import json
import os
import re
import difflib
import shutil
import struct
import subprocess
import sys
import threading
import traceback
from datetime import datetime
from pathlib import Path

import textmod_seq as SEQ      # 字幕时间轴：raw chunk 里的关键帧 + 句柄表
import textmod_voice as VOICE  # 幻兵祠堂语音：文本行 ↔ 音库条目

APP_DIR = (Path(sys.executable).resolve().parent if getattr(sys, "frozen", False)
           else Path(__file__).resolve().parent)
SETTINGS = APP_DIR / "ffrs_textmod_settings.json"
try:
    import kit.settings as _KIT
    SETTINGS = _KIT.state_file("ffrs_textmod_settings.json")
    VIDEO_SETTINGS = _KIT.state_file("ffrs_videomod_settings.json")
except Exception:
    pass
STATE = APP_DIR / "ffrs_textmod_state.json"        # 装了哪些补丁（供还原）
STASH = APP_DIR / "ffrs_textmod_stash.json"
try:
    import kit.settings as _K2
    STASH = _K2.state_file("ffrs_textmod_stash.json")
    STASH_BAK = _K2.state_file("ffrs_textmod_stash.bak.json")
    STATE = _K2.state_file("ffrs_textmod_state.json")
except Exception:
    pass        # ★ 按角色持久化的暂存（文本 + 时间轴）
STASH_BAK = APP_DIR / "ffrs_textmod_stash.bak.json"  # 每次保存前自动备份上一版
CACHE = APP_DIR / "_text_cache"
try:
    import kit.settings as _KC
    CACHE = _KC.cache_root() / "text"
    CACHE.mkdir(parents=True, exist_ok=True)
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

def _find_uassetgui():
    """按顺序找 UAssetGUI：首页设置 → tools 目录 → 仓库常见位置。"""
    cands = []
    try:
        import kit.settings as _KU
        if _KU.get("uassetgui"):
            cands.append(Path(_KU.get("uassetgui")))
        if _KU.get("tools_dir"):
            cands.append(Path(_KU.get("tools_dir")) / "UAssetGUI" / "UAssetGUI.exe")
    except Exception:
        pass
    cands += [
        APP_DIR.parent / "tools" / "UAssetGUI" / "UAssetGUI.exe",
        APP_DIR.parent / "UAssetGUI" / "UAssetGUI.exe",
    ]
    for c in cands:
        try:
            if c and Path(c).is_file():
                return Path(c)
        except Exception:
            continue
    return cands[0] if cands else Path("UAssetGUI.exe")

AUDIO_INDEX = APP_DIR / "ffrs_audio_index.json"
STORY_VOICE = APP_DIR / "ffrs_voice_story.json"
HERO_SPEAKERS = {1001: "レイン", 1002: "ラスウェル", 1003: "フィーナ", 1004: "リド",
                 1005: "ニコル", 1006: "魔人フィーナ", 1007: "ジェイク", 1008: "サクラ"}
VOICE_PREVIEW = CACHE / "voice_preview"
try:
    VIDEO_SETTINGS = _KC.state_file("ffrs_videomod_settings.json")
except Exception:
    pass
VIDEO_SETTINGS = APP_DIR / "ffrs_videomod_settings.json"
try:
    import kit.settings as _KVS
    VIDEO_SETTINGS = _KVS.state_file("ffrs_videomod_settings.json")
except Exception:
    pass

LANGS = ["zh-Hans", "zh-Hant", "ja", "en"]
LANG_LABEL = {"zh-Hans": "简体中文", "zh-Hant": "繁體中文", "ja": "日文", "en": "英文"}
LOCRES_REL = "FFRS/Content/Localization/Game"
MOUNT = "../../../"

# 分类（顺序即界面顺序）。第三列 = 该分类下「按 key 精确猜」的规则说明，仅用于日志。
CAT_NAME = "① 名称"
CAT_DESC = "② 描述"
CAT_MASTER = "③ 大师技能"
CAT_SKILL = "④ 技能"
CAT_SUB = "⑤ 字幕"
CAT_STORY = "⑥ 剧情台词"
CAT_OTHER = "⑦ 其他"


# ──────────────────────────── 文件读写小工具 ────────────────────────────
def run(cmd, timeout=1800, cwd=None):
    """跑外部命令，返回 (rc, stdout+stderr)。Windows 下不弹窗。"""
    flags = 0
    if os.name == "nt":
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        p = subprocess.run([str(c) for c in cmd], capture_output=True, timeout=timeout,
                           cwd=str(cwd) if cwd else None, creationflags=flags)
        out = (p.stdout or b"").decode("utf-8", "replace") + (p.stderr or b"").decode("utf-8", "replace")
        return p.returncode, out
    except Exception as e:
        return -1, repr(e)


def fstring(b, o):
    """UE FString：int32 n；n>0 → ANSI n 字节（含结尾 0）；n<0 → UTF-16，-n*2 字节（含结尾 0）。"""
    n = struct.unpack_from("<i", b, o)[0]
    o += 4
    if n == 0:
        return "", o
    if n > 0:
        return b[o:o + n - 1].decode("utf-8", "replace"), o + n
    m = -n
    return b[o:o + m * 2 - 2].decode("utf-16-le", "replace"), o + m * 2


def enc_fstring(s: str) -> bytes:
    """写 FString：含中文一律用 UTF-16（-n，n = 字符数 + 1）。"""
    if s.isascii():
        raw = s.encode("utf-8") + b"\x00"
        return struct.pack("<i", len(raw)) + raw
    raw = s.encode("utf-16-le") + b"\x00\x00"
    return struct.pack("<i", -(len(raw) // 2)) + raw


# ──────────────────────────── Game.locres ────────────────────────────
class Locres:
    """本作 locres 的头部不是 4 字节对齐的（str_off 在 0x11、条目总数在 0x19），
    所以字段偏移靠「条目数与头一致 + 条目区末端贴着字符串表」穷举确认，不写死单个魔数。"""

    def __init__(self, path: Path):
        self.path = Path(path)
        self.raw = self.path.read_bytes()
        assert struct.unpack_from("<I", self.raw, 0)[0] == 0x7574140E, f"不是 locres：{path}"
        self._locate()
        self._parse()

    # ---- 布局定位 ----
    def _candidate(self, str_off_at, total_at, start):
        b = self.raw
        str_off = struct.unpack_from("<i", b, str_off_at)[0]
        total = struct.unpack_from("<I", b, total_at)[0]
        if not (0 < str_off < len(b)) or not (0 < total < 5_000_000):
            return None
        o, got = start, 0
        try:
            while got < total:
                ns, o = fstring(b, o)
                n, _x = struct.unpack_from("<II", b, o)
                o += 8
                if not (0 < n < 200_000) or not ns.startswith("ST_"):
                    return None
                for _ in range(n):
                    _k, o = fstring(b, o)
                    o += 12
                got += n
                if o > str_off + 8:
                    return None
        except Exception:
            return None
        if got != total or abs(o - str_off) > 8:
            return None
        return str_off, total, start

    def _locate(self):
        for str_off_at in range(0x08, 0x1C):
            for total_at in range(0x10, 0x26):
                for start in range(0x1C, 0x34):
                    r = self._candidate(str_off_at, total_at, start)
                    if r:
                        self.str_off, self.total, self.entry_start = r
                        return
        raise RuntimeError(f"解析不了 locres 头部：{self.path.name}")

    def _parse(self):
        b = self.raw
        self.entries = []          # dict(ns, key, idx, idx_off)
        self.index = {}            # (ns,key) -> entry
        o = self.entry_start
        while len(self.entries) < self.total:
            ns, o = fstring(b, o)
            n, _x = struct.unpack_from("<II", b, o)
            o += 8
            for _ in range(n):
                k, o = fstring(b, o)
                _h, idx, _h2 = struct.unpack_from("<III", b, o)
                e = {"ns": ns, "key": k, "idx": idx, "idx_off": o + 4}
                self.entries.append(e)
                self.index[(ns, k)] = e
                o += 12
        o = self.str_off
        cnt = struct.unpack_from("<I", b, o)[0]
        o += 4
        self.strings = []          # [text, extra_u32]
        for _ in range(cnt):
            s, o = fstring(b, o)
            extra = struct.unpack_from("<I", b, o)[0]
            o += 4
            self.strings.append([s, extra])

    # ---- 查询 ----
    def text(self, ns, key):
        e = self.index.get((ns, key))
        if not e or not (0 <= e["idx"] < len(self.strings)):
            return None
        return self.strings[e["idx"]][0]

    def refs(self):
        """每条字符串被多少条目引用 —— 共享的字符串改一个会污染别人，得复制一份。"""
        n = [0] * len(self.strings)
        for e in self.entries:
            if 0 <= e["idx"] < len(n):
                n[e["idx"]] += 1
        return n

    # ---- 写回（只改文本；条目区长度不变 ⇒ str_off 不变 ⇒ 头部原样保留）----
    def save_with_edits(self, out_path: Path, edits: dict):
        """edits: {(ns,key): text}"""
        b = bytearray(self.raw)
        refs = self.refs()
        strings = [list(s) for s in self.strings]
        for (ns, key), new_text in edits.items():
            e = self.index.get((ns, key))
            if not e:
                continue
            idx = e["idx"]
            if strings[idx][0] == new_text:
                continue
            if refs[idx] > 1:
                strings.append([new_text, 1])          # 共享串 → 追加一份，改指向
                idx = len(strings) - 1
                struct.pack_into("<I", b, e["idx_off"], idx)
            else:
                strings[idx][0] = new_text
        tail = bytearray()
        tail += struct.pack("<I", len(strings))
        for s, extra in strings:
            tail += enc_fstring(s)
            tail += struct.pack("<I", extra)
        out = bytes(b[:self.str_off]) + bytes(tail)
        Path(out_path).parent.mkdir(parents=True, exist_ok=True)
        Path(out_path).write_bytes(out)
        return out

    @staticmethod
    def verify(out_path: Path, edits: dict, origin: "Locres"):
        """回读校验：改过的 key 读回必须是新文本；没改的必须与原来一致。"""
        chk = Locres(out_path)
        for (ns, key), want in edits.items():
            got = chk.text(ns, key)
            if got != want:
                raise RuntimeError(f"回读校验失败：{ns}/{key} 期望 {want!r} 实得 {got!r}")
        if len(chk.entries) != len(origin.entries):
            raise RuntimeError("回读校验失败：条目数变了")
        return True


def base_view(paks_dir: Path) -> Path:
    """返回一个**只含基础三件套**的目录，供 retoc 抽表用（不受已装 MOD 影响）。

    Paks 里装着 `_P` 补丁时，`retoc to-legacy <Paks 目录>` 会优先读补丁容器，
    抽出来的是「被 MOD 改过」的资产。这里用**硬链接**把基础三件套 + global 链到
    缓存目录（同盘秒建、不占空间）；没装补丁就直接用 Paks 目录本身。
    """
    paks_dir = Path(paks_dir)
    if not any(paks_dir.glob("*_P.utoc")):
        return paks_dir
    d = CACHE / "base_paks"
    d.mkdir(parents=True, exist_ok=True)
    for n in ("FFRS-Windows.pak", "FFRS-Windows.utoc", "FFRS-Windows.ucas",
              "global.utoc", "global.ucas"):
        src, dst = paks_dir / n, d / n
        if not src.exists() or dst.exists():
            continue
        try:
            os.link(src, dst)
        except OSError:
            try:
                shutil.copy2(src, dst)      # 跨盘时退回复制
            except Exception:
                return paks_dir
    return d


# ──────────────────────────── 文本库 ────────────────────────────
class TextDB:
    def __init__(self, locres_by_lang: dict, log=None):
        self.log = log or (lambda *_a, **_k: None)
        self.by_lang = locres_by_lang                # lang -> Locres
        self.texts = {}                              # (ns,key) -> {lang: text}
        for lang, loc in locres_by_lang.items():
            for (ns, key), e in loc.index.items():
                if 0 <= e["idx"] < len(loc.strings):
                    self.texts.setdefault((ns, key), {})[lang] = loc.strings[e["idx"]][0]
        self.ns = {}
        for ns, key in self.texts:
            self.ns.setdefault(ns, []).append(key)

    def get(self, ns, key):
        return self.texts.get((ns, key))

    def has(self, ns, key):
        return (ns, key) in self.texts

    def val(self, ns, key, prefer="zh-Hans"):
        d = self.texts.get((ns, key))
        if not d:
            return ""
        return d.get(prefer) or next(iter(d.values()))

    def mentions(self, needle):
        """四语任意一处包含 needle 的 (ns,key)。"""
        out = []
        for nk, d in self.texts.items():
            if any(needle and needle in v for v in d.values()):
                out.append(nk)
        return out

    def find_character(self, query):
        """角色名 / ID / 资产名 → [(id, 命中来源, 命中方式)]。

        支持的输入（实测）：
          * 纯 ID：`13100`、`0010`（自动去前导零）
          * 带资产前缀：`summon13100`、`unit0010`、`pc0010`、`npc0100`、`monster001`
            —— 前缀只是资产命名，去掉后按 ID 走
          * 四语任意一种角色名（完全匹配）
          * 完全匹配不到时退一步：包含匹配 → difflib 近似匹配（给候选，不硬猜）
        """
        q = (query or "").strip()
        if not q:
            return []
        name_ns = ("ST_UnitName", "ST_VisionName", "ST_CharaName", "ST_UI_Unit")
        by_ns = {ns: [(k, v) for (n, k), v in self.texts.items() if n == ns] for ns in name_ns}

        # ① 去掉资产前缀（summon/unit/pc/npc/monster/field_unit/chara…）
        tok = re.sub(r"^(?:summon|unit|pc|npc|monster|mob|enemy|boss|field[_]?unit|chara|vision|"
                     r"ch02|ch01|ch)[_\-]?", "", q, flags=re.I).strip()
        hits = []

        # ② 纯数字（或去前缀后是数字）→ 按 ID
        #     ★ 前导零要保留：`unit0010`/`0010` 是**资产名**（Chara/unit/unit0010），
        #       不是数据表 ID。直接去零会错误命中 `UnitName10`（曼陀罗）。
        #       所以：优先用原样数字做 key 尾号匹配；只有输入本来就没前导零时，才允许去零匹配。
        if tok.isdigit():
            raw = tok
            bare = tok.lstrip("0") or "0"
            forms = {raw} if raw == bare else {raw}
            if raw == bare:
                forms = {bare}
            for ns in name_ns:
                for key, _d in by_ns[ns]:
                    for m in re.finditer(r"(\d{2,})", key):
                        if m.group(1) in forms:
                            hits.append((int(bare), f"{ns}/{key}", "ID"))
                            break
            if hits:
                return self._dedup(hits)

        # ③ 完全匹配（四语，忽略大小写/首尾空格）
        for ns in name_ns:
            for key, d in by_ns[ns]:
                for lang, v in d.items():
                    if q.lower() == (v or "").strip().lower():
                        m = re.search(r"(\d{2,})", key)
                        if m:
                            hits.append((int(m.group(1)), f"{ns}/{key}", f"名称/{lang}"))
        if hits:
            return self._dedup(hits)

        # ④ 包含匹配（名字里含查询串）
        for ns in name_ns:
            for key, d in by_ns[ns]:
                for lang, v in d.items():
                    if q.lower() in (v or "").lower():
                        m = re.search(r"(\d{2,})", key)
                        if m:
                            hits.append((int(m.group(1)), f"{ns}/{key}", f"包含/{lang}"))
        if hits:
            return self._dedup(hits)[:12]

        # ⑤ 近似匹配（打错字也能救回来，例如「雷恩」→「雷因」）
        cands = []
        for ns in name_ns:
            for key, d in by_ns[ns]:
                best = max((difflib.SequenceMatcher(None, q.lower(), (v or "").strip().lower()).ratio()
                            for v in d.values()), default=0.0)
                if best >= 0.5:
                    m = re.search(r"(\d{2,})", key)
                    if m:
                        cands.append((best, int(m.group(1)), f"{ns}/{key}", self.val(ns, key)))
        cands.sort(key=lambda x: -x[0])
        return [(cid, src, f"近似 {r:.0%}（{txt}）") for r, cid, src, txt in cands[:8]]

    @staticmethod
    def _dedup(hits):
        seen, out = set(), []
        for uid, k, how in hits:
            if uid in seen:
                continue
            seen.add(uid)
            out.append((uid, k, how))
        return out


# ──────────────────────────── 从 pak 抽 locres ────────────────────────────
def extract_locres(paks_dir: Path, repak: Path, log) -> dict:
    """抽四语 Game.locres 到缓存目录，返回 {lang: Path}。"""
    dst = CACHE / "locres"
    want = {lang: dst / lang / "Game.locres" for lang in LANGS}
    if all(p.exists() and p.stat().st_size > 1000 for p in want.values()):
        log("locres 已在缓存里，跳过抽取")
        return want
    pak = Path(paks_dir) / "FFRS-Windows.pak"
    if not pak.exists():
        raise RuntimeError(f"找不到 {pak}")
    shutil.rmtree(dst, ignore_errors=True)
    dst.mkdir(parents=True, exist_ok=True)
    log(f"从 {pak.name} 抽 Localization/Game …")
    rc, out = run([repak, "unpack", pak, "-o", dst, "-i", LOCRES_REL, "-f"], timeout=600)
    if rc != 0:
        raise RuntimeError(f"repak unpack 失败：{out[-400:]}")
    got = {}
    for lang in LANGS:
        p = dst / LOCRES_REL.replace("/", os.sep) / lang / "Game.locres"
        if not p.exists():
            p = next((q for q in dst.rglob(f"{lang}/Game.locres")), None)
        if p is None:
            raise RuntimeError(f"没抽到 {lang}/Game.locres")
        got[lang] = p
    log("locres 抽取完成：" + "、".join(f"{l}={got[l].stat().st_size // 1024}KB" for l in LANGS))
    return got


# ──────────────────────────── 角色 → 技能 → 字幕 ────────────────────────────
class Support:
    """视觉（幻兵）→ LB 技能；技能 → 战斗 CG 字幕 key；技能 → 字幕行名（BtlEv_…）。"""

    def __init__(self, vision_skill=None, skill_cgmv=None, notes=None, row_names=None):
        self.vision_skill = vision_skill or {}
        self.skill_cgmv = skill_cgmv or {}
        self.notes = notes or []
        self.row_names = row_names or {}

    def sub_label(self, skill, i, cgmv_key):
        """字幕条目在界面上的名字：行名 → key。"""
        rows = self.row_names.get(skill) or []
        rn = rows[i] if i < len(rows) else ""
        return f"{rn}｜{cgmv_key}" if rn else cgmv_key


def extract_support(paks_dir: Path, retoc: Path, base_view: Path, skill_ids: set, log) -> Support:
    dst = CACHE / "support"
    vision_p = dst / "DT_VisionItemData.uexp"
    cgmv_map_p = dst / "skill_cgmv.json"
    vision_map_p = dst / "vision_skill.json"
    rows_map_p = dst / "skill_rows.json"
    if vision_map_p.exists() and cgmv_map_p.exists():
        log("技能/字幕映射已在缓存里，跳过 retoc")
        vs = {int(k): v for k, v in json.loads(vision_map_p.read_text(encoding="utf-8")).items()}
        sc = {int(k): v for k, v in json.loads(cgmv_map_p.read_text(encoding="utf-8")).items()}
        sr = ({int(k): v for k, v in json.loads(rows_map_p.read_text(encoding="utf-8")).items()}
              if rows_map_p.exists() else {})
        if not sr:      # 旧缓存没有行名：直接从已抽出来的 .uasset 补一遍（不用再跑 retoc）
            for ua in dst.glob("DT_BtlEv_*.uasset"):
                sid = ua.stem.replace("DT_BtlEv_", "")
                rows = [r.decode() for r in dict.fromkeys(re.findall(rb"BtlEv_\d+_\d+_\d+", ua.read_bytes()))]
                if rows:
                    sr[int(sid)] = rows
            if sr:
                rows_map_p.write_text(json.dumps({str(k): v for k, v in sr.items()}, indent=1), encoding="utf-8")
        return Support(vs, sc, row_names=sr)
    dst.mkdir(parents=True, exist_ok=True)
    utoc = Path(paks_dir) / "FFRS-Windows.utoc"
    log("列容器目录索引，找 DT_VisionItemData / DT_BtlEv_* …")
    rc, out = run([retoc, "list", utoc, "--path"], timeout=600)
    if rc != 0:
        raise RuntimeError(f"retoc list 失败：{out[-300:]}")
    paths = out.splitlines()
    names, btlev = set(), set()
    for line in paths:
        for tok in re.findall(r"[\w/]+\.uasset", line):
            stem = tok.rsplit("/", 1)[-1]
            if stem == "DT_VisionItemData.uasset":
                names.add(stem)
            elif re.match(r"DT_BtlEv_\w+\.uasset$", stem):
                btlev.add(stem)
    notes = [f"容器里：DT_VisionItemData={'有' if names else '无'}，DT_BtlEv_*={len(btlev)} 个"]
    todo = sorted(names) + sorted(btlev)
    log(f"要抽 {len(todo)} 个支持表")
    for i, name in enumerate(todo):
        ua = dst / name
        if ua.exists() and (dst / name.replace(".uasset", ".uexp")).exists():
            continue
        tmp = dst / "_tmp"
        shutil.rmtree(tmp, ignore_errors=True)
        tmp.mkdir(parents=True, exist_ok=True)
        rc, out = run([retoc, "to-legacy", base_view, tmp, "-f", name, "--no-shaders"], timeout=600)
        if rc != 0:
            notes.append(f"抽 {name} 失败")
            continue
        src = next((p for p in tmp.rglob(name)), None)
        if not src:
            notes.append(f"{name} 不在容器里")
            continue
        shutil.copy2(src, ua)
        ux = src.with_suffix(".uexp")
        if ux.exists():
            shutil.copy2(ux, dst / ux.name)
        shutil.rmtree(tmp, ignore_errors=True)
        log(f"  [{i + 1}/{len(todo)}] {name}")

    vision_skill = {}
    if vision_p.exists():
        b = vision_p.read_bytes()
        anchors = [(m.start(), int(m.group(1))) for m in re.finditer(rb"VisionName(\d+)", b)]
        cand = []
        for off in range(0, len(b) - 4):
            v = struct.unpack_from("<I", b, off)[0]
            if v in skill_ids:
                cand.append((off, v))
        for off, v in cand:
            if not anchors:
                break
            a = min(anchors, key=lambda x: abs(x[0] - off))
            if abs(a[0] - off) < 200:
                vision_skill.setdefault(a[1], v)
        notes.append(f"幻兵→LB技能：{len(vision_skill)} 条")
    else:
        notes.append("没有 DT_VisionItemData，④技能/⑤字幕 只能靠文本提及")

    skill_cgmv = {}
    skill_rows = {}
    for f in sorted(dst.glob("DT_BtlEv_*.uexp")):
        m = re.match(r"DT_BtlEv_(\w+)\.uexp$", f.name)
        if not m:
            continue
        sid = m.group(1)
        keys = [k.decode() for k in dict.fromkeys(re.findall(rb"BtlLegendCGMV_\d+", f.read_bytes()))]
        if keys:
            skill_cgmv[sid] = keys
        # 行名（BtlEv_<技能>_<阶段>_00N）在 .uasset 的 NameMap 里；与文本 key 一一对应（实测）
        ua = dst / f.name.replace(".uexp", ".uasset")
        if ua.exists():
            rows = [r.decode() for r in dict.fromkeys(re.findall(rb"BtlEv_\d+_\d+_\d+", ua.read_bytes()))]
            if rows:
                skill_rows[sid] = rows
    notes.append(f"技能→字幕：{len(skill_cgmv)} 个技能有表；带行名的 {len(skill_rows)} 个")

    vision_map_p.write_text(json.dumps({str(k): v for k, v in vision_skill.items()}, indent=1), encoding="utf-8")
    cgmv_map_p.write_text(json.dumps(skill_cgmv, indent=1), encoding="utf-8")
    rows_map_p.write_text(json.dumps(skill_rows, indent=1), encoding="utf-8")
    for n in notes:
        log("  " + n)
    return Support(vision_skill, {int(k): v for k, v in skill_cgmv.items()},
                   notes, row_names={int(k): v for k, v in skill_rows.items()})


# ──────────────────────────── 分类收集 ────────────────────────────
NAME_NS = ("ST_UnitName", "ST_VisionName", "ST_CharaName", "ST_UI_Unit")
SKILL_NS = ("ST_SkillName", "ST_SkillDescription", "ST_PassiveSkillName",
            "ST_PassiveSkillDescription", "ST_CommandSkillName", "ST_CommandSkillDescription",
            "ST_MasterSkillName", "ST_MasterSkillDescription", "ST_SkillFilterName")
SUB_NS = ("ST_BtlLegendCGMV",)
OTHER_NS_EXCLUDE = NAME_NS + SKILL_NS + SUB_NS + ("ST_UnitDescription", "ST_VisionDescription")


def legend_index_map(db, vision_ids) -> dict:
    """幻兵 ID → 祠堂剧本编号（ST_LegendEV_XX 的 XX）。

    游戏里没有现成字段（DT_VisionItemData 只有技能/名字/描述），但每套祠堂剧本都在讲该幻兵，
    所以用「哪套剧本里提到这个幻兵名最多」来定归属。实测 16 套与 16 个幻兵完美一一对应
    （01=13100 ウォーリアオブライト、06=13108 ティナ、07=13110 クラウド …）。
    """
    def best_name(vid):
        d = (db.get("ST_VisionName", f"VisionName{vid}")
             or db.get("ST_UnitName", f"UnitName{vid}") or {})
        for lang in LANGS:
            v = d.get(lang) or ""
            if len(v) >= 3:
                return v
        return ""

    out = {}
    for vid in vision_ids:
        nm = best_name(vid)
        if not nm:
            continue
        best_idx, best_n = None, 0
        for idx in range(1, 17):
            ns = f"ST_LegendEV_{idx:02d}"
            keys = db.ns.get(ns)
            if not keys:
                continue
            n = 0
            for k in keys:
                d = db.get(ns, k) or {}
                if any(nm in (d.get(lang) or "") for lang in LANGS):
                    n += 1
            if n > best_n:
                best_idx, best_n = idx, n
        if best_idx:
            out[vid] = best_idx
            db.log(f"  {vid} → 祠堂剧本 LegendEV_{best_idx:02d}（命中 {best_n} 行）")
    return out


def collect(db: TextDB, ids, aliases, support: Support, log):
    """返回 [(分类, [(label, ns, key)])]，顺序固定，空分类也保留（界面上显示为空）。"""
    cats = {c: [] for c in (CAT_NAME, CAT_DESC, CAT_MASTER, CAT_SKILL, CAT_SUB, CAT_STORY, CAT_OTHER)}
    seen = {c: set() for c in cats}

    def add(cat, ns, key, label=None):
        if not db.has(ns, key) or (ns, key) in seen[cat]:
            return
        seen[cat].add((ns, key))
        txt = db.val(ns, key)
        snippet = (txt or "").replace("\r", " ").replace("\n", " ")[:24]
        if label and label.endswith("｜"):
            label = f"{label}{snippet}"
        cats[cat].append((label or f"{key}｜{snippet}", ns, key))

    for uid in ids:
        # ① 名称 / ② 描述 / ③ 大师技能：key 里带 id，精确命中
        for ns in NAME_NS:
            for k in db.ns.get(ns, []):
                m = re.search(r"(\d{3,})$", k)
                if m and int(m.group(1)) == uid:
                    add(CAT_NAME, ns, k)
        for ns, base in (("ST_UnitDescription", "UnitDescription"),
                         ("ST_VisionDescription", "VisionDescription")):
            add(CAT_DESC, ns, f"{base}{uid}")
        mid = f"{uid}00"
        add(CAT_MASTER, "ST_MasterSkillName", f"MasterSkillName{mid}")
        add(CAT_MASTER, "ST_MasterSkillDescription", f"MasterSkillDescription{mid}")

        # ④ 技能 + ⑤ 字幕：幻兵→LB 技能→DT_BtlEv→字幕
        sid = support.vision_skill.get(uid)
        if sid:
            add(CAT_SKILL, "ST_SkillName", f"SkillName{sid}", label=f"SkillName{sid}（LB）｜")
            add(CAT_SKILL, "ST_SkillDescription", f"SkillDescription{sid}", label=f"SkillDescription{sid}（LB）｜")
            for i, ck in enumerate(support.skill_cgmv.get(sid, [])):
                add(CAT_SUB, "ST_BtlLegendCGMV", ck, label=support.sub_label(sid, i, ck))

    # ⑥ 剧情台词：祠堂剧本按命名空间**整块**收（含没有语音的选项行）
    lmap = legend_index_map(db, ids)
    for uid in ids:
        idx = lmap.get(uid)
        if not idx:
            continue
        ns = f"ST_LegendEV_{idx:02d}"
        keys = sorted(k for (n, k) in db.texts if n == ns)
        for k in keys:
            add(CAT_STORY, ns, k)
        log(f"祠堂台词：{ns}（幻兵 {uid}）整块收 {len(keys)} 条")

    # ⑥-B 8 主角：台本里的台词（来自 ffrs_voice_story.json，含语音对应）
    hero_names = [HERO_SPEAKERS[u] for u in ids if u in HERO_SPEAKERS]
    if hero_names and STORY_VOICE.exists():
        try:
            sv = json.loads(STORY_VOICE.read_text(encoding="utf-8"))
            n_add = 0
            for nm in hero_names:
                for it in (sv.get("speakers") or {}).get(nm) or []:
                    ns, key = it.get("ns"), it.get("key")
                    if ns and key and db.has(ns, key):
                        before = len(cats[CAT_STORY])
                        add(CAT_STORY, ns, key, label=f"{nm}｜")
                        if len(cats[CAT_STORY]) > before:
                            n_add += 1
                        # ATC：顺带把标题行也列出来（便于搜索定位）
                        m_atc = re.fullmatch(r"ST_ATC(\d+)", ns)
                        if m_atc:
                            tkey = f"ATC_Title_{int(m_atc.group(1)):03d}"
                            if db.has("ST_ATC_Title", tkey):
                                add(CAT_STORY, "ST_ATC_Title", tkey,
                                    label=f"（标题）{nm}｜")
            if n_add:
                log(f"主角台词：{n_add} 条（{ '/'.join(hero_names) }，带语音）")
        except Exception as e:
            log(f"⚠ 主角台词索引读取失败：{e}")

    # 文本提及（四语任意一处含角色名/别名）—— 补上所有按 ID 猜不到的
    needles = [n for n in aliases if n and len(n) >= 2]
    mention = set()
    for n in needles:
        mention.update(db.mentions(n))
    for ns, key in sorted(mention):
        if ns in NAME_NS:
            # 名称类只按「key 尾号 == 角色 id」精确取；别人的名字里恰好含这几个字不算，
            # 否则会出现「名称」里列出别的角色（实测：搜「雷因」会把 UnitName127 也拉进来）。
            continue
        if ns in ("ST_UnitDescription", "ST_VisionDescription"):
            add(CAT_DESC, ns, key)
        elif ns in SKILL_NS:
            add(CAT_SKILL, ns, key)
        elif ns in SUB_NS:
            add(CAT_SUB, ns, key)
        elif ns in OTHER_NS_EXCLUDE:
            add(CAT_OTHER, ns, key)
        elif re.search(r"(LegendEV|ChrEv|EV_|EventDialog|CommonDialog|DialogChoice|SubEv|MainEvent|"
                       r"ATC|GimEv|ChapterTitle|Progress|Summary|QuestBoard|Trophy|"
                       r"^ST_C\d\d|^ST_FEV|^ST_Summon\d)", ns):
            add(CAT_STORY, ns, key)
        else:
            add(CAT_OTHER, ns, key)
    log(f"命中：提及文本 {len(mention)} 条")
    return [(c, cats[c]) for c in cats]


def _video_tools(VM, log=None) -> bool:
    """把视频工具里的 ffmpeg / cricodecs 路径灌进去（音频编码要用）。"""
    try:
        cfg = json.loads(VIDEO_SETTINGS.read_text(encoding="utf-8")) if VIDEO_SETTINGS.exists() else {}
    except Exception:
        cfg = {}
    ff, cs = cfg.get("ffmpeg", ""), cfg.get("cricodecs", "")
    if ff and Path(ff).exists():
        VM.App.FFMPEG = ff
    if cs and Path(cs).exists():
        VM.App.CRICODECS = cs
    ok = bool(getattr(VM.App, "FFMPEG", "") and getattr(VM.App, "CRICODECS", ""))
    if not ok and log:
        log("⚠ 找不到 ffmpeg / cricodecs（记在 ffrs_videomod_settings.json），语音替换不可用")
    return ok


# ──────────────────────────── 字幕时间轴 ────────────────────────────
def prepare_time_axis(paks_dir: Path, retoc: Path, skill: int, n_rows: int, log) -> dict | None:
    """定位该技能 LB 序列里「字幕轨」的通道，并把原始 chunk 缓存下来。

    返回 {chunk_id, path, bin, off, ticks, confident}；定位不到返回 None。
    """
    if not n_rows:
        return None
    cache = CACHE / "timeaxis"
    cache.mkdir(parents=True, exist_ok=True)
    meta_p = cache / f"{skill}.json"
    bin_p = cache / f"{skill}.bin"
    if not (meta_p.exists() and bin_p.exists()):
        utoc = Path(paks_dir) / "FFRS-Windows.utoc"
        rc, out = run([retoc, "list", utoc, "--path"], timeout=600)
        if rc != 0:
            return None
        pat = re.compile(rf"Sequencer/Battle/Skill/{skill}/\d+/SEQ_Battle_\d+_Master\.uasset")
        cid = rel = None
        for line in out.splitlines():
            if pat.search(line):
                parts = line.split()
                cid, rel = parts[1], parts[-1]
                break
        if not cid:
            log(f"  容器里没有技能 {skill} 的战斗序列（无法改时间轴）")
            return None
        rc, out = run([retoc, "get", utoc, cid, bin_p], timeout=600)
        if not bin_p.exists():
            return None
        meta_p.write_text(json.dumps({"chunk_id": cid, "path": rel}, ensure_ascii=False),
                          encoding="utf-8")
    meta = json.loads(meta_p.read_text(encoding="utf-8"))
    b = bytearray(bin_p.read_bytes())
    pick, _recs, secs = SEQ.pick_subtitle_section(b, n_rows)
    if not pick:
        log(f"  技能 {skill}：找到 {len(secs)} 个 section，但没有键数 = {n_rows} 的候选")
        return None
    return {"chunk_id": meta["chunk_id"], "path": meta["path"], "bin": str(bin_p),
            "off": pick["off"], "ticks": list(pick["ticks"]),
            "confident": pick["confident"]}


def build_time_chunks(taxis: dict, plan: dict, start_off: float, log) -> list:
    """plan: {skill: [新 tick,...]} → 写到临时目录，返回 [(chunk_id, path)]。"""
    root = CACHE / "_timechunks"
    shutil.rmtree(root, ignore_errors=True)
    (root / "chunks").mkdir(parents=True, exist_ok=True)
    paths = {}
    for skill, ticks in plan.items():
        info = taxis.get(skill)
        if not info:
            log(f"  ⚠ 技能 {skill} 没有时间轴信息，跳过")
            continue
        b = bytearray(Path(info["bin"]).read_bytes())
        starts = ticks["starts"] if isinstance(ticks, dict) else ticks
        ends = [t for t in (ticks.get("ends") or []) if t is not None] if isinstance(ticks, dict) else []
        # starts 里未填的（None）保持原值
        orig = list(info["ticks"])
        starts = [o if s is None else s for o, s in zip(orig, starts)]
        starts = [s if s is not None else o for s, o in zip(starts, orig)]
        hits, warn = SEQ.rewrite(b, info["off"], starts, new_ends=ends or None)
        SEQ.verify(b, info["off"], starts)
        (root / "chunks" / info["chunk_id"]).write_bytes(bytes(b))
        paths[info["chunk_id"]] = info["path"]
        log(f"  技能 {skill}：改 {hits} 处 → 影片内 "
            + " / ".join(f"{t / SEQ.TICK - start_off:.2f}s" for t in sorted(starts))
            + "（回读校验通过）")
        for w in warn:
            log("    ⚠ " + w)
    if not paths:
        return []
    (root / "manifest.json").write_text(json.dumps({
        "chunk_paths": paths,
        "version": "ReplaceIoChunkHashWithIoHash",
        "mount_point": MOUNT}, indent=2), encoding="utf-8")
    return list(paths.items())


# ──────────────────────────── 打补丁三件套 ────────────────────────────
def pak_seed(repak: Path, pak: Path, log) -> int:
    """读基础 pak 的 path hash seed。★ repak info 打的是 `Some(56889CD3)` —— 十六进制、无 0x 前缀。"""
    rc, out = run([repak, "info", pak], timeout=120)
    m = re.search(r"path hash seed:\s*(?:Some\()?\s*(0x)?([0-9A-Fa-f]+)", out)
    if not m:
        raise RuntimeError(f"读不到 pak seed：{out[-300:]}")
    raw = m.group(2)
    val = int(raw, 16) if (m.group(1) or re.search(r"[A-Fa-f]", raw)) else int(raw)
    log(f"基础 pak 的 seed = {raw} → 十进制 {val}")
    return val


def build_patch(db: TextDB, edits: dict, paks_dir: Path, name: str,
                repak: Path, retoc: Path, log,
                time_plan: dict | None = None, taxis: dict | None = None,
                start_off: float = 2.0, voice_targets: list | None = None,
                voice_banks: dict | None = None) -> list:
    """edits: {(ns,key): {lang: text}}；time_plan: {skill: [新 tick,...]}
    → 生成 <name>_P.pak/.utoc/.ucas，返回三个路径。"""
    taxis = taxis or {}
    time_plan = time_plan or {}
    voice_targets = voice_targets or []
    stage = CACHE / "_stage"
    shutil.rmtree(stage, ignore_errors=True)
    stage.mkdir(parents=True, exist_ok=True)
    for lang in LANGS:
        loc = db.by_lang[lang]
        per_lang = {nk: d[lang] for nk, d in edits.items()
                    if lang in d and d[lang] is not None and d[lang] != (loc.text(*nk) or "")}
        if not per_lang:
            continue
        out = stage / LOCRES_REL / lang / "Game.locres"
        loc.save_with_edits(out, per_lang)
        Locres.verify(out, per_lang, loc)
        log(f"  {lang}: 改了 {len(per_lang)} 条 → {out.stat().st_size:,} B（回读校验通过）")
    if not any(stage.rglob("Game.locres")):
        raise RuntimeError("没有任何修改，不用生成")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    pak = OUT_DIR / f"{name}_P.pak"
    if pak.exists():
        pak.unlink()
    seed = pak_seed(repak, Path(paks_dir) / "FFRS-Windows.pak", log)
    log(f"repak pack（seed={seed}）…")
    rc, out = run([repak, "pack", "-m", MOUNT, "--version", "V11", "-p", str(seed), stage, pak], timeout=900)
    if rc != 0:
        raise RuntimeError(f"repak pack 失败：{out[-400:]}")
    utoc = pak.with_suffix(".utoc")
    ucas = pak.with_suffix(".ucas")
    # ── 收集所有要进 utoc 的 raw chunk（字幕序列 + 语音音库），最后一次 pack-raw ──
    root = CACHE / "_chunks_final"
    shutil.rmtree(root, ignore_errors=True)
    (root / "chunks").mkdir(parents=True, exist_ok=True)
    paths = {}
    if time_plan and taxis:
        for cid, pth in build_time_chunks(taxis, time_plan, start_off, log):
            shutil.copy2(CACHE / "_timechunks" / "chunks" / cid, root / "chunks" / cid)
            paths[cid] = pth
    if voice_targets:
        import FFRS_VideoMod_Tool as VM
        if not _video_tools(VM, log):
            raise RuntimeError("缺少 ffmpeg / cricodecs，无法做语音替换（见 ffrs_videomod_settings.json）")
        ai = json.loads(AUDIO_INDEX.read_text(encoding="utf-8"))
        if voice_banks:
            ai.setdefault("banks", {}).update(voice_banks)
        log(f"语音替换：{len(voice_targets)} 条 …")
        vt = VM.build_audio_patch(ai, voice_targets, OUT_DIR, retoc, paks_dir, log,
                                  base=f"{name}_P_voice")
        d = CACHE / "_voice_raw"
        shutil.rmtree(d, ignore_errors=True)
        rc, out = run([retoc, "unpack-raw", vt, d], timeout=900)
        meta = json.loads((d / "manifest.json").read_text(encoding="utf-8"))
        for cid, pth in (meta.get("chunk_paths") or {}).items():
            shutil.copy2(d / "chunks" / cid, root / "chunks" / cid)
            paths[cid] = pth
        for f in (OUT_DIR / f"{name}_P_voice.pak", OUT_DIR / f"{name}_P_voice.utoc",
                  OUT_DIR / f"{name}_P_voice.ucas"):
            if f.exists():
                f.unlink()
        log(f"  音库 chunk 已并入（共 {len(paths)} 个 chunk）")
    if paths:
        (root / "manifest.json").write_text(json.dumps({
            "chunk_paths": paths, "version": "ReplaceIoChunkHashWithIoHash",
            "mount_point": MOUNT}, indent=2), encoding="utf-8")
        for f in (utoc, ucas):
            if f.exists():
                f.unlink()
        log(f"retoc pack-raw（{len(paths)} 个 chunk）…")
        rc, out = run([retoc, "pack-raw", root, utoc], timeout=900)
        if not utoc.exists():
            raise RuntimeError(f"pack-raw 失败：{out[-300:]}")
    else:
        log("retoc to-zen …")
        rc, out = run([retoc, "to-zen", "--version", "UE5_6", pak, utoc], timeout=900)
        if rc != 0:
            raise RuntimeError(f"retoc to-zen 失败：{out[-400:]}")
    files = [pak, utoc, ucas]
    for f in files:
        if not f.exists():
            raise RuntimeError(f"生成失败，缺 {f.name}")
    log("生成完成：" + "、".join(f"{f.name}（{f.stat().st_size:,} B）" for f in files))
    return files


def _skill_of(taxis: dict, chunk_id: str) -> int | None:
    for s, info in taxis.items():
        if info.get("chunk_id") == chunk_id:
            return s
    return None


def install(files, paks_dir: Path, log):
    for f in files:
        shutil.copy2(f, Path(paks_dir) / f.name)
        log(f"已安装 {f.name}")
    STATE.write_text(json.dumps({"installed": [f.name for f in files]}, ensure_ascii=False),
                     encoding="utf-8")


def restore(paks_dir: Path, log):
    if not STATE.exists():
        log("没有安装记录，无需还原")
        return
    rec = json.loads(STATE.read_text(encoding="utf-8"))
    for n in rec.get("installed", []):
        p = Path(paks_dir) / n
        if p.exists():
            p.unlink()
            log(f"已删除 {n}")
    STATE.unlink()
    log("还原完成")


# ──────────────────────────── 界面 ────────────────────────────
def load_settings():
    d = {"game_root": "", "repak": str(APP_DIR / "repak.exe"), "retoc": str(APP_DIR / "retoc.exe"),
         "base_view": (_BASE_VIEW_P or ""), "char": "", "mod_name": "",
         "import_dir": "", "out_dir": str(OUT_DIR)}
    if SETTINGS.exists():
        try:
            d.update(json.loads(SETTINGS.read_text(encoding="utf-8")))
        except Exception:
            pass
    return d


def save_settings(d):
    SETTINGS.write_text(json.dumps(d, indent=1, ensure_ascii=False), encoding="utf-8")


# ──────────────── 按角色持久化的暂存（关掉工具也不丢，下次调同一角色自动载入） ────────────────
def load_stash() -> dict:
    if STASH.exists():
        try:
            d = json.loads(STASH.read_text(encoding="utf-8"))
            if isinstance(d.get("characters"), dict):
                return d
        except Exception:
            pass
    return {"version": 1, "characters": {}}


def save_stash(d: dict):
    """写盘前先备份上一版；任何一次保存都不会让旧数据凭空消失。"""
    try:
        if STASH.exists() and STASH.stat().st_size > 20:
            shutil.copy2(STASH, STASH_BAK)
    except Exception:
        pass
    STASH.write_text(json.dumps(d, indent=1, ensure_ascii=False), encoding="utf-8")


class App:
    def __init__(self, host=None):
        self._host = host
        import tkinter as tk
        from tkinter import ttk
        self.tk, self.ttk = tk, ttk
        self.settings = load_settings()
        self.db = None
        self.support = None
        self.cats = []              # [(cat, [(label,ns,key)])]
        self.edits = {}             # {(ns,key): {lang: text}}  —— 已暂存
        self.work = {}              # {(ns,key): {lang: text}}  —— 工作副本（搜索/替换改这个）
        self.times = {}             # {(ns,key): float 秒}  —— 字幕时间轴（影片内秒数）
        self.taxis = {}             # {skill: 通道信息}     —— 生成时用
        self.sub_pos = {}           # {(ns,key): (skill, 行序号)}
        self.voice = {}             # {文本key: {entry,cue,dur}}  —— 该角色祠堂语音
        self.voices = {}            # {文本key: 替换用音频文件名} —— 已暂存的替换
        self.voice_preview = {}     # {条目号: wav 路径}
        self.voice_bank = ""        # VO_ADV_LEGENDEV_XX
        self.stash = load_stash()    # 持久化暂存：{version, characters:{key:{label,edits,times,updated}}}
        self.char_key = None        # 当前角色的暂存 key（按 ID 排序拼接）
        self.find_hits = []         # 上次搜索命中的 [(ns,key,lang)]
        self.cur = None             # (ns,key)
        self.aliases = []
        self.busy = False
        self._build()

    # ---- UI ----
    def _build(self):
        tk, ttk = self.tk, self.ttk
        self.root = getattr(self, "_host", None) or tk.Tk()
        self.root.title("FFRS 文本与语音修改工具 v2.4")
        self.root.geometry("1180x760")

        top = ttk.LabelFrame(self.root, text="① 路径设置")
        top.pack(fill="x", padx=8, pady=6)
        ttk.Label(top, text="游戏目录（含 FFRS 文件夹）").grid(row=0, column=0, sticky="w", padx=4, pady=3)
        self.v_root = tk.StringVar(value=self.settings["game_root"])
        ttk.Entry(top, textvariable=self.v_root, width=70).grid(row=0, column=1, columnspan=3, sticky="we", padx=4)
        ttk.Button(top, text="指定…", command=self.pick_root).grid(row=0, column=4, padx=4)
        ttk.Label(top, text="导入音频（替换用素材）").grid(row=1, column=0, sticky="w", padx=4, pady=3)
        self.v_import = tk.StringVar(value=self.settings.get("import_dir", ""))
        ttk.Entry(top, textvariable=self.v_import, width=70).grid(row=1, column=1, columnspan=3, sticky="we", padx=4)
        ttk.Button(top, text="指定…", command=self.pick_import).grid(row=1, column=4, padx=4)
        ttk.Label(top, text="导出路径（生成 MOD 放这里）").grid(row=2, column=0, sticky="w", padx=4, pady=3)
        self.v_out = tk.StringVar(value=self.settings.get("out_dir", str(OUT_DIR)))
        ttk.Entry(top, textvariable=self.v_out, width=70).grid(row=2, column=1, columnspan=3, sticky="we", padx=4)
        ttk.Button(top, text="指定…", command=self.pick_out).grid(row=2, column=4, padx=4)
        top.columnconfigure(3, weight=1)

        tools = ttk.LabelFrame(self.root, text="② 外部工具")
        tools.pack(fill="x", padx=8, pady=2)
        self.v_repak = tk.StringVar(value=self.settings["repak"])
        self.v_retoc = tk.StringVar(value=self.settings["retoc"])
        self.v_base = tk.StringVar()          # 不再让用户填，内部自动建（见 _paths）
        for i, (lab, var) in enumerate([("repak.exe", self.v_repak), ("retoc.exe", self.v_retoc)]):
            ttk.Label(tools, text=lab).grid(row=0, column=i * 3, sticky="w", padx=4)
            ttk.Entry(tools, textvariable=var, width=40).grid(row=0, column=i * 3 + 1, sticky="we", padx=4)
            ttk.Button(tools, text="选择…", width=7,
                       command=lambda v=var, t=lab: self.pick_file(v, t)).grid(row=0, column=i * 3 + 2, padx=(0, 10))
        ttk.Button(tools, text="检测工具", command=self.on_detect_tools).grid(row=0, column=6, padx=6)
        tools.columnconfigure(1, weight=1)
        tools.columnconfigure(4, weight=1)
        ttk.Label(tools, text="（抽表要用基础三件套视图，工具会自动建在工作目录下，不用管）").grid(
            row=1, column=0, columnspan=7, sticky="w", padx=4)

        mid = ttk.Frame(self.root)
        mid.pack(fill="both", expand=True, padx=8, pady=4)
        left = ttk.LabelFrame(mid, text="③ 角色文本列表（点条目 → 右侧编辑）")
        left.pack(side="left", fill="both", expand=True)
        hdr = ttk.Frame(left)
        hdr.pack(fill="x", padx=4, pady=(2, 4))
        ttk.Label(hdr, text="角色名 / 角色ID").pack(side="left")
        self.v_char = tk.StringVar(value=self.settings.get("char", ""))
        try:
            self.v_char.trace_add("write", lambda *_: self._save_cfg())
        except Exception:
            pass
        ttk.Entry(hdr, textvariable=self.v_char, width=24).pack(side="left", padx=4)
        self.btn_parse = ttk.Button(hdr, text="解析", command=self.on_parse)
        self.btn_xls_out = ttk.Button(hdr, text="导出台词", command=self.on_export_lines)
        self.btn_xls_in = ttk.Button(hdr, text="导入台词", command=self.on_import_lines)
        self.btn_parse.pack(side="left", padx=2)
        self.btn_xls_out.pack(side="left", padx=2)
        self.btn_xls_in.pack(side="left", padx=2)
        ttk.Label(hdr, text="（名称/ID 都行：光之战士、13100、summon13100）").pack(side="left", padx=4)
        self.tree = ttk.Treeview(left, columns=("state", "time"), show="tree headings", height=18)
        self.tree.heading("#0", text="分类 / 文本")
        self.tree.heading("state", text="状态")
        self.tree.heading("time", text="时间轴（秒）")
        self.tree.column("#0", width=430)
        self.tree.column("state", width=60, anchor="center")
        self.tree.column("time", width=90, anchor="center")
        self.tree.pack(side="left", fill="both", expand=True)
        sb = ttk.Scrollbar(left, orient="vertical", command=self.tree.yview)
        sb.pack(side="right", fill="y")
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.bind("<<TreeviewSelect>>", self.on_select)

        right = ttk.LabelFrame(mid, text="④ 四种文本（改完点「暂存此条」）")
        right.pack(side="right", fill="both", expand=True, padx=(6, 0))
        vbar = ttk.Frame(right)
        vbar.grid(row=0, column=0, sticky="we", padx=4, pady=(6, 2))
        ttk.Label(vbar, text="语音：").pack(side="left")
        self.btn_play = ttk.Button(vbar, text="试听", width=8, state="disabled", command=self.on_play)
        self.btn_play.pack(side="left", padx=2)
        self.btn_repl = ttk.Button(vbar, text="替换", width=8, state="disabled", command=self.on_voice_replace)
        self.btn_repl.pack(side="left", padx=2)
        self.v_voice = tk.StringVar(value="（选中带语音的条目后可用）")
        ttk.Label(vbar, textvariable=self.v_voice).pack(side="left", padx=6)
        self.vars = {}
        self.wid = {}
        for i, lang in enumerate(LANGS):
            ttk.Label(right, text=LANG_LABEL[lang]).grid(row=i * 2 + 1, column=0, sticky="nw", padx=4, pady=(4, 0))
            t = tk.Text(right, height=3, wrap="word", width=52)
            t.grid(row=i * 2 + 2, column=0, sticky="we", padx=4)
            t.bind("<Control-Return>", lambda e: (self.on_stage(), "break")[1])
            self.wid[lang] = t
        ttk.Label(right, text="（Ctrl+Enter = 暂存此条）").grid(row=9, column=0, sticky="w", padx=4)
        # 时间轴（只有 ⑤字幕 可填）：字幕在影片里出现的秒数
        tl = ttk.Frame(right)
        tl.grid(row=10, column=0, sticky="we", padx=4, pady=(2, 0))
        ttk.Label(tl, text="时间轴（秒，仅字幕可填）").pack(side="left")
        self.v_time = tk.StringVar()
        self.e_time = ttk.Entry(tl, textvariable=self.v_time, width=8, state="disabled")
        self.e_time.pack(side="left", padx=6)
        ttk.Label(tl, text="结束").pack(side="left", padx=(10, 2))
        self.v_time2 = tk.StringVar()
        self.e_time2 = ttk.Entry(tl, textvariable=self.v_time2, width=8, state="disabled")
        self.e_time2.pack(side="left")
        ttk.Label(tl, text="秒；留空=跟随原逻辑").pack(side="left", padx=4)
        ttk.Label(tl, text="影片起点").pack(side="left", padx=(10, 2))
        self.v_off = tk.StringVar(value=str(self.settings.get("movie_start", 2.0)))
        ttk.Entry(tl, textvariable=self.v_off, width=6).pack(side="left")
        ttk.Label(tl, text="秒（序列里影片从第几秒开始；440011 实测 ≈2.0）").pack(side="left", padx=4)
        row = ttk.Frame(right)
        row.grid(row=11, column=0, sticky="we", pady=6)
        ttk.Button(row, text="暂存此条", command=self.on_stage).pack(side="left", padx=4)
        ttk.Button(row, text="撤销此条", command=self.on_revert).pack(side="left", padx=4)
        ttk.Button(row, text="清空全部修改", command=self.on_clear_all).pack(side="left", padx=4)
        ttk.Button(row, text="清空该角色暂存", command=self.on_stash_clear).pack(side="left", padx=4)
        ttk.Button(row, text="删除预览音频", command=self.on_clear_preview).pack(side="left", padx=4)
        ttk.Label(row, text="（暂存会自动存进 ffrs_textmod_stash.json，下次解析同一角色自动载入）"
                  ).pack(side="left", padx=6)
        right.columnconfigure(0, weight=1)
        for t in self.wid.values():
            t.configure(state="disabled")

        # ── 搜索 / 替换（在当前角色列表内批量改，四语一起替换；不改现有四语输入框的设计）──
        sr = ttk.LabelFrame(right, text="⑥ 搜索 / 替换（范围＝当前角色列表，四种语言同时处理）")
        sr.grid(row=11, column=0, sticky="we", padx=4, pady=(8, 4))
        ttk.Label(sr, text="搜索").grid(row=0, column=0, padx=4, pady=3, sticky="w")
        self.v_find = tk.StringVar()
        ttk.Entry(sr, textvariable=self.v_find, width=24).grid(row=0, column=1, padx=4, sticky="we")
        ttk.Button(sr, text="搜索", width=8, command=self.on_find).grid(row=0, column=2, padx=4)
        ttk.Button(sr, text="下一条", width=8, command=self.on_find_next).grid(row=0, column=4, padx=(2, 4))
        self.v_find_n = tk.StringVar(value="未搜索")
        ttk.Label(sr, textvariable=self.v_find_n).grid(row=0, column=3, sticky="w", padx=4)
        ttk.Label(sr, text="替换为").grid(row=1, column=0, padx=4, pady=3, sticky="w")
        self.v_repl = tk.StringVar()
        ttk.Entry(sr, textvariable=self.v_repl, width=24).grid(row=1, column=1, padx=4, sticky="we")
        ttk.Button(sr, text="替换", width=8, command=self.on_replace).grid(row=1, column=2, padx=4)
        self.v_repl_n = tk.StringVar(value="未替换")
        ttk.Label(sr, textvariable=self.v_repl_n).grid(row=1, column=3, sticky="w", padx=4)
        bf = ttk.Frame(sr)
        bf.grid(row=2, column=0, columnspan=4, sticky="we", padx=4, pady=(2, 4))
        ttk.Button(bf, text="批量暂存", command=self.on_stage_batch).pack(side="left")
        ttk.Label(bf, text="（搜索/替换只改「工作副本」，点「批量暂存」才写进暂存；"
                           "「撤销此条」仍只作用于当前选中条目）").pack(side="left", padx=6)
        sr.columnconfigure(1, weight=1)

        bot = ttk.Frame(self.root)
        bot.pack(fill="x", padx=8)
        self.v_name = tk.StringVar(value=self.settings.get("mod_name", "TextMod"))
        ttk.Label(bot, text="MOD 名").pack(side="left")
        ttk.Entry(bot, textvariable=self.v_name, width=22).pack(side="left", padx=4)
        ttk.Button(bot, text="生成 MOD", command=self.on_build).pack(side="left", padx=4)
        ttk.Button(bot, text="安装到游戏", command=self.on_install).pack(side="left", padx=4)
        ttk.Button(bot, text="还原", command=self.on_restore).pack(side="left", padx=4)
        self.v_count = tk.StringVar(value="未修改")
        ttk.Label(bot, textvariable=self.v_count).pack(side="left", padx=10)

        # ★ 路径/工具统一由首页提供
        try:
            import kit.settings as _K
            _tools = _K.get("tools_dir")
            self.v_root.set(str(_K.get("game_root")))
            self.v_out.set(str(_K.output_mods()))
            self.v_repak.set(str(_tools + "/repak.exe"))
            self.v_retoc.set(str(_tools + "/retoc.exe"))
            for attr in ("v_audio", "v_audio_dir", "v_origin", "v_original"):
                if hasattr(self, attr):
                    try:
                        getattr(self, attr).set(str(_K.input_audio()))
                    except Exception:
                        pass
        except Exception:
            pass
        try:
            top.pack_forget(); tools.pack_forget()
        except Exception:
            pass
        logf = ttk.LabelFrame(self.root, text="⑤ 日志")
        logf.pack(fill="both", expand=False, padx=8, pady=6)
        self.log_t = tk.Text(logf, height=9, wrap="word")
        self.log_t.pack(side="left", fill="both", expand=True)
        sb2 = ttk.Scrollbar(logf, orient="vertical", command=self.log_t.yview)
        sb2.pack(side="right", fill="y")
        self.log_t.configure(yscrollcommand=sb2.set)
        self.log("修改只存在内存里；点「生成 MOD」才会落盘。关闭窗口即丢弃未生成的修改。")

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

    def pick_import(self):
        from tkinter import filedialog
        d = filedialog.askdirectory(title="选「导入音频」目录")
        if d:
            self.v_import.set(d)

    def pick_out(self):
        from tkinter import filedialog
        d = filedialog.askdirectory(title="选「导出路径」目录")
        if d:
            self.v_out.set(d)

    def pick_root(self):
        from tkinter import filedialog
        d = filedialog.askdirectory(title="选游戏根目录（含 FFRS 文件夹）")
        if d:
            self.v_root.set(d)

    # ---- 数据准备 ----
    def pick_file(self, var, label):
        from tkinter import filedialog
        p = filedialog.askopenfilename(title=f"选择 {label}",
                                       filetypes=[("exe", "*.exe"), ("所有文件", "*.*")])
        if p:
            var.set(p)

    def on_detect_tools(self):
        def job():
            for lab, var in (("repak.exe", self.v_repak), ("retoc.exe", self.v_retoc)):
                p = Path((var.get() or "").strip())
                if not p.exists():
                    self.log(f"✗ {lab}：找不到 {p}")
                    continue
                rc, out = run([p, "--version"], timeout=60)
                first = next((ln.strip() for ln in (out or "").splitlines() if ln.strip()), "(无输出)")
                self.log(f"✓ {lab}：{first}")
            try:
                paks, repak, retoc, base = self._paths()
                self.log(f"✓ 游戏 Paks：{paks}")
                self.log(f"✓ 基础容器视图：{base}（自动建立/复用，抽表用）")
                pak = Path(paks) / "FFRS-Windows.pak"
                if pak.exists():
                    self.log(f"✓ 基础 pak：{pak.stat().st_size / 1024 ** 3:.2f} GB")
                patches = [p.name for p in Path(paks).glob("*_P.utoc")]
                self.log("✓ 已装补丁容器：" + ("、".join(patches) if patches else "（无）"))
            except Exception as e:
                self.log("检测失败：" + str(e))
        threading.Thread(target=job, daemon=True).start()

    def _paths(self):
        root = Path(self.v_root.get().strip())
        if not root.exists():
            raise RuntimeError("游戏目录不存在")
        paks = root / "FFRS" / "Content" / "Paks"
        if not paks.exists():
            paks = root / "Content" / "Paks"    # 用户可能直接选了 FFRS 目录
        if not paks.exists():
            raise RuntimeError("游戏目录下找不到 FFRS/Content/Paks")
        repak, retoc = Path(self.v_repak.get()), Path(self.v_retoc.get())
        if not repak.exists():
            raise RuntimeError("repak.exe 路径不对（点「选择…」重新指定）")
        if not retoc.exists():
            raise RuntimeError("retoc.exe 路径不对（点「选择…」重新指定）")
        try:
            import kit.settings as _KS
            _bv = str(_KS.get("base_view") or "").strip()
            base = pathlib.Path(_bv) if _bv else _KS.build_base_cache()[0]
        except Exception:
            base = base_view(paks)
        self.v_base.set(str(base))
        return paks, repak, retoc, base

    def _ensure_db(self):
        if self.db is not None:
            return
        paks, repak, retoc, base = self._paths()
        self.log("准备四语文本 …")
        loc = extract_locres(paks, repak, self.log)
        self.db = TextDB({lang: Locres(p) for lang, p in loc.items()}, self.log)
        self.log(f"文本库就绪：{len(self.db.texts):,} 个 key × {len(LANGS)} 语言")

    def on_parse(self):
        if self.busy:
            return
        self.busy = True
        self.btn_parse.configure(state="disabled")
        threading.Thread(target=self._parse_job, daemon=True).start()

    def _parse_job(self):
        try:
            self._ensure_db()
            paks, repak, retoc, base = self._paths()
            q = self.v_char.get().strip()
            hits = self.db.find_character(q)
            if not hits:
                self.log(f"没找到角色：{q!r}")
                self.log("提示：可以填 名称（四语任一）/ 数据表ID（如 13100）/ 资产名（如 summon13100）；"
                         "unit0010、pc0010 这类是**资产文件夹名**，不等于数据表 ID，暂时映射不到 —— "
                         "请改用该角色的名字或数据表 ID。")
                return
            self.log("识别到：" + "；".join(f"ID {u}（{k} / {how}）" for u, k, how in hits))
            # 近似匹配时只取最接近的一个，别把一串候选全当成同一个角色
            if all("近似" in h[2] for h in hits):
                self.log(f"⚠ 「{q}」没有精确匹配，先按最接近的 ID {hits[0][0]} 解析；"
                         f"候选还有：" + "、".join(f"{u}({how})" for u, _k, how in hits[1:]) +
                         "。不对就用 ID 或换个写法。")
                hits = hits[:1]
            ids = [h[0] for h in hits]
            # 别名：该角色在四语下的所有名称
            aliases = set()
            for uid in ids:
                for ns in NAME_NS:
                    for k in self.db.ns.get(ns, []):
                        m = re.search(r"(\d{3,})$", k)
                        if m and int(m.group(1)) == uid:
                            aliases.update(v for v in (self.db.get(ns, k) or {}).values() if v)
            self.aliases = sorted(a for a in aliases if len(a) >= 2)
            self.log("别名：" + " / ".join(self.aliases))
            skill_ids = {int(m.group(1)) for (ns, k) in self.db.texts
                         if ns == "ST_SkillName" for m in [re.fullmatch(r"SkillName(\d+)", k)] if m}
            self.support = extract_support(paks, retoc, base, skill_ids, self.log)
            self.cats = collect(self.db, ids, self.aliases, self.support, self.log)
            # 字幕时间轴：为「这个角色的幻兵技能」准备通道（能失败，失败就只禁时间轴）
            self.taxis = {}
            sid = None
            for uid in ids:
                sid = self.support.vision_skill.get(uid)
                if sid:
                    break
            if sid:
                n_rows = len(self.support.skill_cgmv.get(sid, []))
                info = prepare_time_axis(paks, retoc, sid, n_rows, self.log)
                if info:
                    self.taxis[sid] = info
                    self.log(f"⑤ 字幕时间轴就绪：技能 {sid}，{n_rows} 条，"
                             f"通道 @{info['off']:#x}，原时刻 "
                             + " / ".join(f"{t / SEQ.TICK:.2f}s" for t in info["ticks"])
                             + f"（{'可信' if info['confident'] else '⚠ 低置信，仅供参考'}）")
                else:
                    self.log(f"⚠ 技能 {sid} 的字幕时间轴没定位到（时间轴输入不会写入）")
            # 载入该角色上次的持久化暂存（有的话直接接上继续改）
            n_e, n_t = self._stash_load(ids, label="/".join(self.aliases[:2]) or q)
            if n_e or n_t:
                self.log(f"📂 已载入该角色上次的暂存：{n_e} 条文本 / {n_t} 条时间轴"
                         f"（{STASH.name}，key={self.char_key}）")
            else:
                self.log(f"（该角色还没有持久化暂存，key={self.char_key}）")
            self._prepare_voice(paks, repak, retoc, base, ids, self.log)
            self.root.after(0, self._fill_tree)
        except Exception as e:
            self.log("解析失败：" + str(e))
            self.log(traceback.format_exc(limit=3))
        finally:
            self.busy = False
            self.root.after(0, lambda: self.btn_parse.configure(state="normal"))

    def _fill_tree(self):
        self.tree.delete(*self.tree.get_children())
        # 字幕 key → (技能, 行序号)：按 DT 行顺序与通道键升序一一对应
        self.sub_pos = {}
        if self.support:
            for sid, keys in self.support.skill_cgmv.items():
                for i, k in enumerate(keys):
                    self.sub_pos[("ST_BtlLegendCGMV", k)] = (sid, i)
        # 工作副本 = 原文；已暂存的覆盖上去
        self.work = {}
        total = 0
        for _cat, entries in self.cats:
            for _label, ns, key in entries:
                self.work[(ns, key)] = dict(self.db.get(ns, key) or {})
        for nk, d in self.edits.items():
            self.work[nk] = {**self.work.get(nk, {}), **d}
        for cat, entries in self.cats:
            node = self.tree.insert("", "end", text=f"{cat}（{len(entries)}）", open=True, values=("", ""))
            for label, ns, key in entries:
                st = "已改" if (ns, key) in self.edits else ""
                tshow = ""
                if ns == SUB_NS[0] and (ns, key) in self.times:
                    _st, _en = self._t_of(ns, key)
                    tshow = f"{_st:g}" + (f"→{_en:g}" if _en is not None else "")
                self.tree.insert(node, "end", text=label, values=(st, tshow),
                                 tags=(f"{ns}\t{key}",))
                total += 1
        self.find_hits = []
        self._find_i = 0
        self.v_find_n.set("未搜索")
        self.v_repl_n.set("未替换")
        self.log(f"列表就绪：{total} 条文本")
        self._update_count()

    def _update_count(self):
        n = sum(1 for d in self.edits.values() if any(d.get(l) is not None for l in LANGS))
        txt = f"已改 {n} 条" if n else "未修改"
        if self.times:
            txt += f" / 时间轴 {len(self.times)} 条"
        self.v_count.set(txt)

    # ---- 持久化暂存 ----
    @staticmethod
    def _stash_key(ids):
        return ",".join(str(i) for i in sorted({int(i) for i in ids}))

    def _stash_load(self, ids, label=""):
        """调取同一角色上次的暂存；返回 (文本条数, 时间轴条数)。"""
        self.char_key = self._stash_key(ids)
        chars = self.stash.get("characters") or {}
        ent = chars.get(self.char_key) or {}
        if not ent:                      # 兼容历史 key 写法（如 "2,1001" vs "1001,2" / 多一个空格）
            want = {str(i) for i in ids}
            for k, v in chars.items():
                if not isinstance(v, dict):
                    continue
                if {x.strip() for x in str(k).split(",") if x.strip()} == want:
                    ent = v
                    self.char_key = k
                    self.log(f"   （用历史 key「{k}」载入暂存）")
                    break
        self.edits = {tuple(k.split("|", 1)): dict(v) for k, v in (ent.get("edits") or {}).items()}
        self.voices = {tuple(k.split("|", 1)): v for k, v in (ent.get("voices") or {}).items()}
        self.times = {}
        for _k, _v in (ent.get("times") or {}).items():
            self.times[tuple(_k.split("|", 1))] = (
                [float(_v[0]), (float(_v[1]) if _v[1] is not None else None)]
                if isinstance(_v, (list, tuple)) else [float(_v), None])
        # 只保留当前列表里真实存在的 key，避免残留脏数据
        if self.cats:
            valid = {nk for _c, ents in self.cats for _l, ns, key in ents for nk in [(ns, key)]}
            self.edits = {k: v for k, v in self.edits.items() if k in valid}
            self.times = {k: v for k, v in self.times.items() if k in valid}
        if label:
            chars = self.stash.setdefault("characters", {})
            chars.setdefault(self.char_key, {}).setdefault("label", label)
        return len(self.edits), len(self.times)

    def _stash_save(self):
        if not self.char_key:
            return
        chars = self.stash.setdefault("characters", {})
        ent = chars.setdefault(self.char_key, {})
        if not self.edits and not self.times and (ent.get("edits") or ent.get("times")):
            self.log(f"   （当前没有任何暂存，保留 {self.char_key} 的旧记录不覆盖）")
            return
        ent["edits"] = {"|".join(k): v for k, v in self.edits.items()}
        ent["times"] = {"|".join(k): list(self._t_of(*k)) for k in self.times}
        ent["voices"] = {"|".join(k): v for k, v in self.voices.items()}
        ent["updated"] = datetime.now().isoformat(timespec="seconds")
        if not ent.get("label"):
            ent["label"] = self.v_char.get().strip()
        save_stash(self.stash)
        self.log(f"   暂存已保存到 {STASH.name}（{len(self.edits)} 条文本 / {len(self.times)} 条时间轴）")

    def on_stash_clear(self):
        if not self.char_key:
            self.log("还没解析角色")
            return
        (self.stash.get("characters") or {}).pop(self.char_key, None)
        save_stash(self.stash)
        self.edits.clear()
        self.times.clear()
        self.log(f"已清空该角色（{self.char_key}）的持久化暂存")
        self._fill_tree()
        self._update_count()

    # ---- 编辑 ----
    def on_select(self, _evt=None):
        sel = self.tree.selection()
        if not sel:
            return
        it = sel[0]
        tags = self.tree.item(it, "tags")
        if not tags or "\t" not in tags[0]:
            self.cur = None
            for t in self.wid.values():
                t.configure(state="normal")
                t.delete("1.0", "end")
                t.configure(state="disabled")
            self.v_time.set("")
            self.e_time.configure(state="disabled")
            return
        ns, key = tags[0].split("\t", 1)
        self.cur = (ns, key)
        cur = self.work.get(self.cur) or self.edits.get(self.cur, {})
        orig = self.db.get(ns, key) or {}
        for lang in LANGS:
            t = self.wid[lang]
            t.configure(state="normal")
            t.delete("1.0", "end")
            val = cur.get(lang, orig.get(lang, ""))
            t.insert("1.0", val or "")
            self._mark(t, (val or "") != (orig.get(lang) or ""))
        # 时间轴：只有字幕类可填
        if ns in SUB_NS:
            self.e_time.configure(state="normal")
            self.e_time2.configure(state="normal")
            st, en = self._t_of(ns, key)
            self.v_time.set("" if st is None else f"{st:g}")
            self.v_time2.set("" if en is None else f"{en:g}")
        else:
            self.e_time.configure(state="disabled")
            self.e_time2.configure(state="disabled")
            self.v_time.set("")
            self.v_time2.set("")
        self._refresh_voice_buttons()
        self.log(f"选中 {ns}/{key}")

    def _story_rows(self):
        """当前角色「⑥ 剧情台词」里的幻兵祠堂行：[(key, {lang: text}, ns)]"""
        out = []
        for cat, entries in self.cats:
            if cat != CAT_STORY:
                continue
            for _label, ns, key in entries:
                # 祠堂 + 8 主角/ATC 等有语音映射的台本行都进入 Excel
                if not (str(ns).startswith("ST_LegendEV") or key in self.voice):
                    continue
                out.append((key, self.db.get(ns, key) or {}, ns))
        return out

    XL_LANGS = [("zh-Hans", "简"), ("zh-Hant", "繁"), ("ja", "日"), ("en", "英")]
    XL_BLANK = "空白待填"      # 仅用于兼容旧表格；新表格一律留空

    def on_export_lines(self):
        """导出台词表：编号 | 原台词(简/繁/日/英) | 新台词(简/繁/日/英) | 替换语音"""
        if not self.cats:
            self.log("先解析角色")
            return
        rows = self._story_rows()
        if not rows:
            self.log("这个角色没有祠堂台词可导出")
            return
        from openpyxl import Workbook
        from openpyxl.styles import Font, Alignment, PatternFill
        wb = Workbook()
        ws = wb.active
        ws.title = "台词"
        head = ["编号"]
        head += [f"原台词({tag})" for _l, tag in self.XL_LANGS]
        head += [f"新台词({tag})" for _l, tag in self.XL_LANGS]
        head += ["替换语音"]
        ws.append(head)
        for c in ws[1]:
            c.font = Font(bold=True)
            c.alignment = Alignment(horizontal="center")
            c.fill = PatternFill("solid", fgColor="E8EEF7")
        for key, texts, ns in rows:
            nk = (ns, key)
            line = [key]
            line += [(texts.get(lang) or "").replace("\r\n", "\n").replace("\r", "\n")
                     for lang, _t in self.XL_LANGS]
            for lang, _t in self.XL_LANGS:
                _v = (self.edits.get(nk) or {}).get(lang) or ""
                line.append(_v.replace("\r\n", "\n").replace("\r", "\n"))
            line.append(self.voices.get(nk) or "")
            ws.append(line)
        widths = {"A": 20}
        for i, col in enumerate("BCDEFGHIJ", start=1):
            widths[col] = 34 if i <= 4 else 34
        widths["J"] = 46
        for col, w in widths.items():
            ws.column_dimensions[col].width = w
        ws.freeze_panes = "B2"
        out = Path(self.v_out.get().strip() or OUT_DIR)
        out.mkdir(parents=True, exist_ok=True)
        nm = (self.v_char.get().strip() or "角色").replace("/", "_")
        fp = out / f"{nm}_台词表.xlsx"
        wb.save(fp)
        self.log(f"已导出台词表：{fp}（{len(rows)} 行 × {len(head)} 列）")
        self.log("  只填要改的语言；留空 = 该语言不修改")

    def on_import_lines(self):
        """读回台词表，按列批量套用（未填写的语言视为不修改）"""
        from tkinter import filedialog
        fp = filedialog.askopenfilename(title="选台词表", filetypes=[("Excel", "*.xlsx")])
        if not fp:
            return
        try:
            from openpyxl import load_workbook
            wb = load_workbook(fp, data_only=True)
            ws = wb.active
            head = [str(c.value or "").strip() for c in ws[1]]
            ci = {h: i for i, h in enumerate(head)}
            if "编号" not in ci:
                self.log(f"表头不对（缺「编号」）：{head}")
                return
            cols = [(lang, tag, ci[f"新台词({tag})"]) for lang, tag in self.XL_LANGS
                    if f"新台词({tag})" in ci]
            if not cols:
                self.log("表头里没有「新台词(简/繁/日/英)」列，无法导入")
                return
            need = {key: (ns, key) for key, _t, ns in self._story_rows()}
            cnt = {lang: 0 for lang, _t, _i in cols}
            n_voice = 0
            miss = []
            for row in ws.iter_rows(min_row=2, values_only=True):
                key = str(row[ci["编号"]] or "").strip()
                if not key:
                    continue
                nk = need.get(key)
                if nk is None:
                    miss.append(key)
                    continue
                for lang, _t, idx in cols:
                    v = row[idx] if idx < len(row) else None
                    v = "" if v is None else str(v)
                    if v.strip() in ("", self.XL_BLANK):
                        continue                      # ★ 未填写 = 不修改
                    v = v.replace("\r\n", "\n").replace("\r", "\n").replace("\n", "\r\n")
                    self.edits.setdefault(nk, {})[lang] = v
                    cnt[lang] += 1
                if "替换语音" in ci:
                    vp = str(row[ci["替换语音"]] or "").strip()
                    if vp and vp != self.XL_BLANK:
                        _vp = Path(vp)
                        if not _vp.is_absolute():
                            _vp = Path(fp).parent / vp
                        vp = str(_vp)
                        if not _vp.is_file():
                            self.log(f"   ⚠ 语音不存在，跳过：{vp}")
                        else:
                            self.voices[nk] = vp
                            n_voice += 1
            self._fill_tree()
            self._update_count()
            self._stash_save()
            detail = "、".join(f"{tag} {cnt[lang]}" for lang, tag, _i in cols if cnt[lang]) or "无"
            self.log(f"导入完成：台词（{detail}）、语音 {n_voice} 条"
                     + (f"；不在本角色列表里 {len(miss)} 行已忽略" if miss else ""))
        except Exception as e:
            self.log(f"导入失败：{e}")

    def _prepare_voice(self, paks, repak, retoc, base, ids, log):
        """解析时准备语音：祠堂（整库）+ 8 主角（按台本行）。
        规则：只做日语 ja（用户 2026-10-23）。"""
        self.voice, self.voices, self.voice_preview, self.voice_bank = {}, {}, {}, ""
        self.voice_preview_banks, self.voice_banks = {}, {}
        self._voice_base, self._voice_retoc = Path(base), Path(retoc)
        lmap = legend_index_map(self.db, ids)
        idx = next((lmap[i] for i in ids if i in lmap), None)
        if idx:
            self._prepare_legend_voice(idx, base, retoc, log)
        elif any(i in HERO_SPEAKERS for i in ids):
            log("准备主角台词语音（台本行 → VO_ADV 音库）…")
        self._prepare_story_voice(ids, log)
        if not self.voice:
            log("该角色没有可用语音（祠堂/主角台本都没有）")
    def _prepare_legend_voice(self, idx, base, retoc, log):
        log(f"准备祠堂语音：LegendEV_{idx:02d} …")
        legdir = CACHE / "legend"
        legdir.mkdir(parents=True, exist_ok=True)
        nm = f"DT_LegendEV_{idx:02d}"
        if not any(legdir.rglob(f"{nm}.uasset")):
            run([retoc, "to-legacy", base, legdir, "-f", f"{nm}.uasset", "--no-shaders"], timeout=900)
        uag = _find_uassetgui()
        if not uag.exists():
            log(f"⚠ 找不到 UAssetGUI（{uag}），语音无法准备")
            return
        rows = VOICE.legend_rows(uag, legdir, idx, log)
        ai = json.loads(AUDIO_INDEX.read_text(encoding="utf-8"))
        idx_voice = VOICE.build_index(ai, idx, rows)
        self.voice_bank = VOICE.bank_of(idx)
        info = (ai.get("banks") or {}).get(self.voice_bank) or {}
        if info:
            self.voice_banks[self.voice_bank] = info
        for k, v in idx_voice.items():
            v["bank"] = self.voice_bank
            self.voice.setdefault(k, v)
        log(f"祠堂语音：{len(idx_voice)} 条可替换（音库 {self.voice_bank}）")
        try:
            import FFRS_VideoMod_Tool as VM
            _video_tools(VM, log)
            self.voice_preview_banks[self.voice_bank] = VOICE.ensure_preview(
                VM, self.voice_bank, info, Path(base), Path(retoc), VOICE_PREVIEW, log)
        except Exception as e:
            log(f"⚠ 祠堂语音预览解包失败（文本/字幕不受影响）：{e}")

    def _prepare_story_voice(self, ids, log):
        """8 主角：台本行 → 音库条目（数据来自 ffrs_voice_story.json）。"""
        names = [HERO_SPEAKERS[i] for i in ids if i in HERO_SPEAKERS]
        if not names:
            return
        if not STORY_VOICE.exists():
            log("⚠ 缺少 ffrs_voice_story.json（跑 Build_VoiceIndex.py），主角语音不可用")
            return
        try:
            data = json.loads(STORY_VOICE.read_text(encoding="utf-8"))
        except Exception as e:
            log(f"⚠ 主角语音索引读不了：{e}")
            return
        banks = data.get("banks") or {}
        n = 0
        for nm in names:
            for it in (data.get("speakers") or {}).get(nm) or []:
                bank = it.get("bank")
                if not bank or bank not in banks:
                    continue
                info = banks[bank]
                self.voice_banks.setdefault(bank, info)
                k = it.get("key")
                if not k or k in self.voice:
                    continue
                self.voice[k] = {"entry": int(it["entry"]), "bank": bank,
                                 "cue": it.get("cue"), "dur": it.get("dur")}
                n += 1
        log(f"主角语音：{n} 条可替换（{len(names)} 人，{len({v.get('bank') for v in self.voice.values()})} 个音库）")

    def _voice_targets(self):
        """{bank, entry, src} 列表，供 build_patch 做原位替换"""
        if not self.voice or not self.voices:
            return []
        d = Path(self.v_import.get().strip() or "")
        out = []
        for (ns, key), fn in self.voices.items():
            v = self.voice.get(key)
            if not v:
                continue
            _p = Path(fn)
            src = _p if _p.is_absolute() else (d / fn)
            if not src.exists():
                self.log(f"   ⚠ 语音素材缺失：{src}")
                continue
            out.append({"bank": v.get("bank") or self.voice_bank, "entry": v["entry"], "src": src})
        return out

    def on_clear_preview(self):
        d = VOICE_PREVIEW
        n = sum(1 for _ in d.rglob("*.wav")) if d.exists() else 0
        shutil.rmtree(d, ignore_errors=True)
        self.voice_preview = {}
        self.log(f"已删除预览音频（{n} 个 wav）")

    def _voice_of(self, ns, key):
        """当前条目对应的语音（无则 None）"""
        if ns != "ST_LegendEV" and not str(ns).startswith("ST_LegendEV"):
            pass
        return self.voice.get(key) if self.voice else None

    def _refresh_voice_buttons(self):
        if not self.cur:
            self.btn_play.configure(state="disabled")
            self.btn_repl.configure(state="disabled")
            self.v_voice.set("（选中带语音的条目后可用）")
            return
        ns, key = self.cur
        v = self.voice.get(key)
        if not v:
            self.btn_play.configure(state="disabled")
            self.btn_repl.configure(state="disabled")
            self.v_voice.set("这条没有语音")
            return
        self.btn_play.configure(state="normal")
        self.btn_repl.configure(state="normal")
        rep_fn = self.voices.get((ns, key))
        dur = v.get("dur")
        dur_s = f"{dur:.2f}s" if isinstance(dur, (int, float)) else "?"
        self.v_voice.set(f"原音 {dur_s}（条目 {v['entry']}，{v.get('bank') or self.voice_bank}）"
                         + (f"｜已换成 {rep_fn}" if rep_fn else ""))

    def on_play(self):
        if not self.cur:
            return
        v = self.voice.get(self.cur[1])
        if not v:
            return
        bank = v.get("bank") or self.voice_bank
        pv = self.voice_preview_banks.get(bank)
        if pv is None:
            try:
                import FFRS_VideoMod_Tool as VM
                _video_tools(VM, self.log)
                info = self.voice_banks.get(bank) or {}
                pv = VOICE.ensure_preview(VM, bank, info, self._voice_base, self._voice_retoc,
                                          VOICE_PREVIEW, self.log)
                self.voice_preview_banks[bank] = pv
            except Exception as e:
                self.log(f"预览解包失败：{e}")
                return
        wav = pv.get(v["entry"])
        if not wav or not wav.exists():
            self.log("这个条目没有可预览的 wav")
            return
        try:
            import winsound
            winsound.PlaySound(str(wav), winsound.SND_FILENAME | winsound.SND_ASYNC)
            self.log(f"试听：{wav.name}（{v['dur']:.2f}s）")
        except Exception as e:
            self.log(f"试听失败：{e}")

    def on_voice_replace(self):
        if not self.cur:
            return
        v = self.voice.get(self.cur[1])
        if not v:
            return
        d = Path(self.v_import.get().strip() or "")
        if not d.is_dir():
            self.log("先在「① 路径设置 → 导入音频」选一个目录")
            return
        files = sorted([f for f in d.iterdir() if f.suffix.lower() in (".wav", ".hca", ".mp3", ".ogg", ".flac", ".m4a")])
        if not files:
            self.log(f"「{d}」里没有可用的音频文件（wav/hca/mp3/ogg/flac/m4a）")
            return
        nk = self.cur
        key = nk[1]
        top = self.tk.Toplevel(self.root)
        top.title(f"选替换音频 → {key}")
        top.geometry("620x420")
        lb = self.tk.Listbox(top)
        for f in files:
            lb.insert("end", f.name)
        lb.pack(fill="both", expand=True, padx=8, pady=8)
        cur_name = self.voices.get(key)
        if cur_name:
            for i, f in enumerate(files):
                if f.name == cur_name:
                    lb.selection_set(i)
                    lb.see(i)
        bar = self.ttk.Frame(top)
        bar.pack(fill="x", padx=8, pady=(0, 8))
        def ok(_e=None):
            sel = lb.curselection()
            if not sel:
                return
            self.voices[nk] = files[sel[0]].name
            self.log(f"语音替换：{key} ← {files[sel[0]].name}")
            self._refresh_voice_buttons()
            self._stash_save()
            top.destroy()
        self.ttk.Button(bar, text="确定替换", command=ok).pack(side="right", padx=4)
        def clear():
            self.voices.pop(nk, None)
            self.log(f"语音替换：{key} 已恢复原音")
            self._refresh_voice_buttons()
            self._stash_save()
            top.destroy()
        self.ttk.Button(bar, text="恢复原音", command=clear).pack(side="right", padx=4)
        self.ttk.Button(bar, text="取消", command=top.destroy).pack(side="right", padx=4)
        lb.bind("<Double-Button-1>", ok)

    def _mark(self, widget, changed):
        widget.configure(bg="#fff4c2" if changed else "white")

    def on_stage(self):
        if not self.cur:
            self.log("先选一条文本")
            return
        ns, key = self.cur
        orig = self.db.get(ns, key) or {}
        d = {}
        for lang in LANGS:
            v = self.wid[lang].get("1.0", "end-1c")
            if v != (orig.get(lang) or ""):
                d[lang] = v
        if d:
            self.edits[(ns, key)] = d
            self.work.setdefault((ns, key), {}).update(d)
            self.log(f"已暂存 {ns}/{key}：" + "、".join(LANG_LABEL[l] for l in d))
        else:
            self.edits.pop((ns, key), None)
            self.work[(ns, key)] = dict(orig)
            self.log(f"{ns}/{key} 与原文一致，已从暂存里移除")
        # 时间轴（仅字幕）
        if ns in SUB_NS:
            raw = self.v_time.get().strip()
            if raw:
                try:
                    t = float(raw)
                    if t < 0:
                        raise ValueError
                    self.times[(ns, key)] = [t, (self._t_of(ns, key)[1])]
                    pos = self.sub_pos.get((ns, key))
                    tick = int(round((t + self._movie_start()) * SEQ.TICK))
                    extra = f" → 序列 tick {tick}（{tick // SEQ.TICKS_PER_FRAME} 帧）" if pos else ""
                    self.log(f"   时间轴：影片内 {t:g} 秒{extra}")
                    if not pos:
                        self.log("   ⚠ 这条字幕没有对应的序列轨道，时间轴不会写入")
                except ValueError:
                    self.log(f"   时间轴「{raw}」不是合法秒数，已忽略")
            else:
                self.times.pop((ns, key), None)
            cur = self.times.get((ns, key))
            if cur:
                raw2 = self.v_time2.get().strip()
                if raw2:
                    try:
                        t2 = float(raw2)
                        if t2 <= cur[0]:
                            self.log(f"   结束「{raw2}」不大于开始，已忽略")
                        else:
                            cur[1] = t2
                            self.log(f"   结束：影片内 {t2:g} 秒（时长 {t2 - cur[0]:g} 秒）")
                    except ValueError:
                        self.log(f"   结束「{raw2}」不是合法秒数，已忽略")
                else:
                    cur[1] = None
        self._refresh_row(ns, key)
        self._update_count()
        self._stash_save()

    # ---- 搜索 / 替换（只改工作副本，批量暂存才落实） ----
    def on_find(self):
        q = self.v_find.get()
        if not q:
            self.v_find_n.set("请输入搜索内容")
            return
        self.find_hits = []
        for (ns, key), d in self.work.items():
            for lang in LANGS:
                if q in (d.get(lang) or ""):
                    self.find_hits.append((ns, key, lang))
        self._find_i = 0
        n_key = len({(nk) for nk, _k, _l in self.find_hits})
        self.v_find_n.set(f"命中 {len(self.find_hits)} 处 / {n_key} 条（按「下一条」跳转）")
        self.log(f"搜索 {q!r}：{len(self.find_hits)} 处，涉及 {n_key} 条文本")
        for ns, key, lang in self.find_hits[:20]:
            self.log(f"   {ns}/{key} [{LANG_LABEL[lang]}]")

    def on_find_next(self):
        """跳到下一处搜索命中，并在列表里选中该条。"""
        if not self.find_hits:
            self.on_find()
            if not self.find_hits:
                return
        seen = []
        for ns, key, lang in self.find_hits:
            if (ns, key) not in seen:
                seen.append((ns, key))
        i = getattr(self, "_find_i", 0) % len(seen)
        ns, key = seen[i]
        self._find_i = i + 1
        # 在树里找到并选中
        for cat in self.tree.get_children():
            for it in self.tree.get_children(cat):
                tags = self.tree.item(it, "tags") or []
                if tags and tags[0] == f"{ns}\t{key}":
                    self.tree.selection_set(it)
                    self.tree.focus(it)
                    self.tree.see(it)
                    self.v_find_n.set(f"第 {i + 1}/{len(seen)} 条：{ns}/{key}")
                    return
        self.v_find_n.set("命中的条目不在当前列表里")

    def on_replace(self):
        q = self.v_find.get()
        if not q:
            self.v_find_n.set("请先搜索")
            return
        rep = self.v_repl.get()
        total = 0
        touched = set()
        for (ns, key), d in self.work.items():
            for lang in LANGS:
                v = d.get(lang)
                if v and q in v:
                    cnt = v.count(q)
                    d[lang] = v.replace(q, rep)
                    total += cnt
                    touched.add((ns, key))
        self.v_repl_n.set(f"替换 {total} 处 / {len(touched)} 条")
        self.log(f"替换 {q!r} → {rep!r}：{total} 处，涉及 {len(touched)} 条（还没暂存）")
        if self.cur:
            self.on_select()

    def on_stage_batch(self):
        """把工作副本里所有与原文不同的条目一次性写进暂存。"""
        n = 0
        for (ns, key), d in self.work.items():
            orig = self.db.get(ns, key) or {}
            diff = {lang: v for lang, v in d.items() if lang in LANGS and v != (orig.get(lang) or "")}
            if diff:
                self.edits[(ns, key)] = {**self.edits.get((ns, key), {}), **diff}
                n += 1
            elif (ns, key) in self.edits:
                self.edits.pop((ns, key), None)
        for cat_node in self.tree.get_children():
            for it in self.tree.get_children(cat_node):
                tags = self.tree.item(it, "tags")
                if tags and "\t" in tags[0]:
                    ns, key = tags[0].split("\t", 1)
                    self.tree.set(it, "state", "已改" if (ns, key) in self.edits else "")
        self.log(f"批量暂存完成：{n} 条进了暂存")
        self._update_count()
        self._stash_save()

    def on_revert(self):
        if not self.cur:
            return
        ns, key = self.cur
        self.edits.pop(self.cur, None)
        self.times.pop(self.cur, None)
        self.work[(ns, key)] = dict(self.db.get(ns, key) or {})
        self.log(f"撤销 {ns}/{key}")
        self.on_select()
        self._refresh_row(*self.cur)
        self._stash_save()

    def on_clear_all(self):
        n = len(self.edits)
        self.edits.clear()
        self.times.clear()
        for nk in list(self.work):
            self.work[nk] = dict(self.db.get(*nk) or {})
        self.log(f"已清空 {n} 条暂存（工作副本、时间轴也复位）")
        self._fill_tree()
        self.on_select()
        self._stash_save()

    def _refresh_row(self, ns, key):
        for node in self.tree.get_children():
            for it in self.tree.get_children(node):
                if self.tree.item(it, "tags") and self.tree.item(it, "tags")[0] == f"{ns}\t{key}":
                    self.tree.set(it, "state", "已改" if (ns, key) in self.edits else "")
                    _st, _en = self._t_of(ns, key)
                    self.tree.set(it, "time", "" if _st is None else
                                  f"{_st:g}" + (f"→{_en:g}" if _en is not None else ""))

    # ---- 生成 / 安装 / 还原 ----
    def on_build(self):
        if not self.edits and not self.times:
            self.log("还没有任何修改")
            return
        if not self.edits:
            self.log("时间轴修改需要和至少一条文本修改一起生成（三件套里的 pak 得有内容）；先改一处文本吧")
            return
        self._save_cfg()
        threading.Thread(target=self._build_job, daemon=True).start()

    def _t_of(self, ns, key):
        v = self.times.get((ns, key))
        if not v:
            return None, None
        if isinstance(v, (list, tuple)):
            return v[0], (v[1] if len(v) > 1 else None)
        return float(v), None

    def _movie_start(self) -> float:
        try:
            return float(self.v_off.get())
        except Exception:
            return 2.0

    def _time_plan(self):
        """把「每条字幕的影片内秒数」变成 {技能: [新 tick,...]}（未填的保持原时刻）。"""
        plan = {}
        for (ns, key), _v in self.times.items():
            pos = self.sub_pos.get((ns, key))
            if not pos:
                continue
            sid, row = pos
            info = self.taxis.get(sid)
            if not info:
                self.log(f"   ⚠ 技能 {sid} 没有时间轴通道，跳过 {key}")
                continue
            st, en = self._t_of(ns, key)
            slot = plan.setdefault(sid, {"starts": list(info["ticks"]),
                                         "ends": [None] * len(info["ticks"])})
            slot["starts"][row] = int(round((st + self._movie_start()) * SEQ.TICK))
            if en is not None:
                slot["ends"][row] = int(round((en + self._movie_start()) * SEQ.TICK))
        return plan

    def _build_job(self):
        try:
            paks, repak, retoc, _base = self._paths()
            name = (self.v_name.get() or "TextMod").strip()
            plan = self._time_plan()
            targets = self._voice_targets()
            if self.times:
                self.log(f"时间轴：{len(self.times)} 条字幕要改，涉及 {len(plan)} 个技能序列")
            self.log(f"生成 MOD：{name}_P …")
            files = build_patch(self.db, self.edits, paks, name, repak, retoc, self.log,
                                time_plan=plan, taxis=self.taxis, start_off=self._movie_start(),
                                voice_targets=targets, voice_banks=self.voice_banks)
            self.log("→ " + "、".join(str(f) for f in files))
            self.log("可以在游戏 Paks 里覆盖，或点「安装到游戏」")
        except Exception as e:
            self.log("生成失败：" + str(e))
            self.log(traceback.format_exc(limit=3))

    def on_install(self):
        try:
            paks, _r, _rt, _b = self._paths()
            name = (self.v_name.get() or "TextMod").strip()
            files = [OUT_DIR / f"{name}_P{s}" for s in (".pak", ".utoc", ".ucas")]
            miss = [f.name for f in files if not f.exists()]
            if miss:
                self.log("还没生成：" + "、".join(miss))
                return
            install(files, paks, self.log)
            self.log("安装完成（还原 = 点「还原」或删掉这三个文件）")
        except Exception as e:
            self.log("安装失败：" + str(e))

    def on_restore(self):
        try:
            paks, _r, _rt, _b = self._paths()
            restore(paks, self.log)
        except Exception as e:
            self.log("还原失败：" + str(e))

    def _save_cfg(self):
        self.settings.update({"game_root": self.v_root.get(), "repak": self.v_repak.get(),
                              "retoc": self.v_retoc.get(), "base_view": self.v_base.get(),
                              "char": self.v_char.get(), "mod_name": self.v_name.get(),
                              "movie_start": self._movie_start(),
                              "import_dir": self.v_import.get(), "out_dir": self.v_out.get()})
        save_settings(self.settings)

    def run(self):
        def on_close():
            self._save_cfg()
            self.root.destroy()
        self.root.protocol("WM_DELETE_WINDOW", on_close)
        self.root.mainloop()


# ──────────────────────────── 自检（不开界面）────────────────────────────
def selftest(query, root=None):
    st = load_settings()
    if root:
        st["game_root"] = root
    paks = Path(st["game_root"]) / "FFRS" / "Content" / "Paks"
    log = lambda m: print(m, flush=True)
    loc = extract_locres(paks, Path(st["repak"]), log)
    db = TextDB({lang: Locres(p) for lang, p in loc.items()}, log)
    log(f"文本库：{len(db.texts):,} key")
    hits = db.find_character(query)
    log("识别：" + "；".join(f"ID {u}（{k}/{how}）" for u, k, how in hits))
    ids = [h[0] for h in hits]
    aliases = set()
    for uid in ids:
        for ns in NAME_NS:
            for k in db.ns.get(ns, []):
                m = re.search(r"(\d{3,})$", k)
                if m and int(m.group(1)) == uid:
                    aliases.update(v for v in (db.get(ns, k) or {}).values() if v)
    aliases = sorted(a for a in aliases if len(a) >= 2)
    log("别名：" + " / ".join(aliases))
    skill_ids = {int(m.group(1)) for (ns, k) in db.texts
                 if ns == "ST_SkillName" for m in [re.fullmatch(r"SkillName(\d+)", k)] if m}
    sup = extract_support(paks, Path(st["retoc"]), Path(st["base_view"]), skill_ids, log)
    cats = collect(db, ids, aliases, sup, log)
    for cat, entries in cats:
        print(f"\n=== {cat}（{len(entries)}）")
        for label, ns, key in entries:
            d = db.get(ns, key) or {}
            print(f"   {ns}/{key}")
            for lang in LANGS:
                print(f"      {LANG_LABEL[lang]:<6} {d.get(lang, '')!r}")


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        i = sys.argv.index("--selftest")
        q = sys.argv[i + 1] if len(sys.argv) > i + 1 else "13100"
        root = sys.argv[i + 2] if len(sys.argv) > i + 2 else None
        selftest(q, root)
    else:
        App().run()
