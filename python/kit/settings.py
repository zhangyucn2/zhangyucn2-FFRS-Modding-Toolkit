"""统一设置：所有工具的路径与状态文件集中管理。

- `Toolkit/settings.json`   唯一路径配置（首页编辑）
- `Toolkit/state/`          所有 json 暂存/缓存集中放这里
- 各工具原有的 settings 文件名保持不变，只是换目录到 `state/`

目录约定（首页「检查路径」会自动建好）：
    <输入目录>/SpritePSD      美术素材（PSD/贴图）
    <输入目录>/VideoMod       视频素材
    <输出目录>/SpritePSD      美术类输出（SpritePSD + 描边/法线）
    <输出目录>/NEWMOD         所有 MOD 三件套（合并工具的输入就是这里）
"""
from __future__ import annotations

import json
import pathlib

KIT_DIR = pathlib.Path(__file__).resolve().parent          # Toolkit/python/kit
PY_DIR = KIT_DIR.parent                                     # Toolkit/python
TOOLKIT_DIR = PY_DIR.parent                                 # Toolkit
CONFIG_DIR = PY_DIR / "config"                              # 路径设置 + 各工具 settings
SAVE_DIR = PY_DIR / "save"                                  # 暂存/缓存 json
SAVE_DIR = PY_DIR / "save"                                   # 运行时数据根
TEMP_ROOT = SAVE_DIR / "_temp"                               # 临时文件（关闭时自动清）
CACHE_ROOT = SAVE_DIR / "_cache"                             # 缓存（保留，可手动清）
SETTINGS_PATH = CONFIG_DIR / "settings.json"
STATE_DIR = CONFIG_DIR
OUTPUT_DIR = TOOLKIT_DIR / "Output"
INPUT_DIR = TOOLKIT_DIR / "Input"

SUB_INPUT = ("SpritePSD", "VideoMod", "AudioMOD")
SUB_OUTPUT = ("SpritePSD", "NEWMOD", "Outlines")

HIDDEN_PATH_KEYS = {"ffmpeg", "cricodecs", "uassetgui", "ffrdt"}

PATH_FIELDS = [
    ("game_root",  ("游戏根目录", "Game root"),
     r"D:/SteamLibrary/steamapps/common/FINAL FANTASY RESONANCE", "dir"),
    ("input_dir",  ("输入/素材根目录", "Input / assets root"), str(TOOLKIT_DIR / "Input"), "dir"),
    ("output_dir", ("输出根目录", "Output root"), str(OUTPUT_DIR), "dir"),
    ("state_dir",  ("配置/暂存数据", "Config / state"), str(STATE_DIR), "dir"),
    ("base_view",  ("音频缓存（留空 = 自动构建）", "Audio cache (blank = auto)"), "", "dir"),
    ("usmap",      ("USMAP", "USMAP"), str(TOOLKIT_DIR / "tools" / "FFRS.usmap"), "file"),
    ("tools_dir",  ("外部工具目录", "External tools"), str(TOOLKIT_DIR / "tools"), "dir"),
    ("ffmpeg",     ("ffmpeg.exe", "ffmpeg.exe"), str(TOOLKIT_DIR / "tools" / "ffmpeg.exe"), "file"),
    ("cricodecs",  ("cricodecs.exe", "cricodecs.exe"), str(TOOLKIT_DIR / "tools" / "cricodecs.exe"), "file"),
    ("uassetgui",  ("UAssetGUI.exe", "UAssetGUI.exe"),
     str(TOOLKIT_DIR / "tools" / "UAssetGUI" / "UAssetGUI.exe"), "file"),
    ("ffrdt",      ("ffr-dt.exe", "ffr-dt.exe"),
     str(TOOLKIT_DIR / "tools" / "ffr-dt" / "ffr-dt.exe"), "file"),
]

DEFAULTS = {f[0]: f[2] for f in PATH_FIELDS}

_cache: dict | None = None


def load() -> dict:
    global _cache
    if _cache is not None:
        return _cache
    d = {k: p for k, _lab, p, _t in PATH_FIELDS}
    if SETTINGS_PATH.exists():
        try:
            d.update(json.loads(SETTINGS_PATH.read_text(encoding="utf-8")))
        except Exception:
            pass
    # ★ 结构性目录必须在当前 Toolkit 下：拷贝到新位置后，旧绝对路径自动纠正
    fixed = False
    for key, default in (("input_dir", INPUT_DIR), ("output_dir", OUTPUT_DIR),
                         ("state_dir", STATE_DIR), ("tools_dir", TOOLKIT_DIR / "tools")):
        v = str(d.get(key) or "").strip()
        try:
            under = v and pathlib.Path(v).resolve().is_relative_to(TOOLKIT_DIR.resolve())
        except Exception:
            under = False
        if not under:
            d[key] = str(default)
            fixed = True
    if fixed:
        try:
            SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
            SETTINGS_PATH.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass
    # ★ 外部工具：Toolkit/tools 下有本地副本就用它（不再依赖工作区）
    _local = {
        "uassetgui": TOOLKIT_DIR / "tools" / "UAssetGUI" / "UAssetGUI.exe",
        "usmap": TOOLKIT_DIR / "tools" / "FFRS.usmap",
        "ffrdt": TOOLKIT_DIR / "tools" / "ffr-dt" / "ffr-dt.exe",
        "ffmpeg": TOOLKIT_DIR / "tools" / "ffmpeg.exe",
        "cricodecs": TOOLKIT_DIR / "tools" / "cricodecs.exe",
    }
    _changed = False
    for k, lp in _local.items():
        if not lp.exists():
            continue
        try:
            cur = pathlib.Path(str(d.get(k) or ""))
            same = cur.exists() and cur.resolve() == lp.resolve()
        except Exception:
            same = False
        if not same:
            d[k] = str(lp)
            _changed = True
    if _changed:
        try:
            SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
            SETTINGS_PATH.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass
    _cache = d
    return d


def save(d: dict) -> None:
    global _cache
    _cache = dict(d)
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    SAVE_DIR.mkdir(parents=True, exist_ok=True)
    SETTINGS_PATH.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")
    ensure_dirs(d)
    sync_to_tools(d)


def get(key: str, default: str = "") -> str:
    return str(load().get(key) or default)


def _p(key: str, fallback) -> pathlib.Path:
    v = str(load().get(key) or "").strip()
    return pathlib.Path(v) if v else pathlib.Path(fallback)


def input_root() -> pathlib.Path:
    return _p("input_dir", TOOLKIT_DIR / "Input")


def output_root() -> pathlib.Path:
    return _p("output_dir", OUTPUT_DIR)


def input_psd() -> pathlib.Path:
    return input_root() / "SpritePSD"


def input_video() -> pathlib.Path:
    return input_root() / "VideoMod"


def output_psd() -> pathlib.Path:
    return output_root() / "SpritePSD"


def output_mods() -> pathlib.Path:
    return output_root() / "NEWMOD"


def input_audio() -> pathlib.Path:
    return input_root() / "AudioMOD"


def output_outlines() -> pathlib.Path:
    return output_root() / "Outlines"


def ensure_dirs(d: dict | None = None, make_tools: bool = True) -> list[str]:
    """建好约定的目录；返回新建的目录列表。"""
    d = d or load()
    made = []
    targets = []
    for key, subs in (("input_dir", SUB_INPUT), ("output_dir", SUB_OUTPUT)):
        root = str(d.get(key) or "").strip()
        if not root:
            continue
        targets.append(pathlib.Path(root))
        targets += [pathlib.Path(root) / s for s in subs]
    if d.get("state_dir"):
        targets.append(pathlib.Path(str(d["state_dir"])))
    targets.append(CONFIG_DIR)
    targets.append(SAVE_DIR)
    if make_tools and d.get("tools_dir"):
        targets.append(pathlib.Path(str(d["tools_dir"])))
    for t in targets:
        try:
            if not t.exists():
                t.mkdir(parents=True, exist_ok=True)
                made.append(str(t))
        except Exception:
            pass
    return made


# ──────────────────────────── 临时 / 缓存 ────────────────────────────
def derive_tool_paths(d: dict) -> dict:
    """把 4 个外部工具路径按『工具目录』推导出来（界面上不再单列）。"""
    tools = pathlib.Path(str(d.get("tools_dir") or TOOLKIT_DIR / "tools"))
    out = dict(d)
    out["ffmpeg"] = str(tools / "ffmpeg.exe")
    out["cricodecs"] = str(tools / "cricodecs.exe")
    out["uassetgui"] = str(tools / "UAssetGUI" / "UAssetGUI.exe")
    out["ffrdt"] = str(tools / "ffr-dt" / "ffr-dt.exe")
    return out


def temp_root() -> pathlib.Path:
    TEMP_ROOT.mkdir(parents=True, exist_ok=True)
    return TEMP_ROOT


def cache_root() -> pathlib.Path:
    CACHE_ROOT.mkdir(parents=True, exist_ok=True)
    return CACHE_ROOT


def _dir_size(d: pathlib.Path, seen: set | None = None) -> int:
    """目录体积；硬链接只算一次（避免把同一份 5GB 容器算成 20GB）。"""
    seen = seen if seen is not None else set()
    total = 0
    try:
        for f in d.rglob("*"):
            if not f.is_file():
                continue
            try:
                st = f.stat()
                key = (st.st_dev, st.st_ino)
                if key in seen:
                    continue
                seen.add(key)
                total += st.st_size
            except Exception:
                continue
    except Exception:
        return 0
    return total


def _purge(d: pathlib.Path) -> int:
    """删除目录内容（保留目录本身），返回释放字节数。"""
    import shutil as _sh
    if not d.exists():
        return 0
    n = _dir_size(d)
    for child in d.iterdir():
        try:
            if child.is_dir():
                _sh.rmtree(child, ignore_errors=True)
            else:
                child.unlink(missing_ok=True)
        except Exception:
            pass
    return n


def cache_dirs() -> list:
    """所有"缓存"目录（保留型）。"""
    return [CACHE_ROOT, PY_DIR / "_skill_cache", PY_DIR / "_text_cache",
            PY_DIR / "_merge_cache", PY_DIR / "_audio_cache", SAVE_DIR / "_work",
            input_root() / "_cache"]


def clear_temp() -> int:
    """清临时文件（工具关闭时自动调用）。"""
    return _purge(TEMP_ROOT) + _purge(SAVE_DIR / "_work")


def clear_caches() -> tuple:
    """清所有缓存 + 临时；返回 (释放字节数, 清掉的目录数)。"""
    total = clear_temp()
    n = 0
    seen = set()
    for d in cache_dirs():
        sz = 0
        try:
            sz = _dir_size(d, seen)
        except Exception:
            sz = 0
        _purge(d)
        if sz:
            total += sz
            n += 1
    return total, n

def build_base_cache(force: bool = False) -> tuple:
    """建「原版容器视图」到 save/_cache/base_paks（硬链接，不占空间）。
    返回 (视图目录, 字节数, 文件列表)；失败抛异常。"""
    paks = pathlib.Path(get("game_root")) / "FFRS" / "Content" / "Paks"
    if not paks.exists():
        paks = pathlib.Path(get("game_root")) / "Content" / "Paks"
    if not paks.exists():
        raise RuntimeError(f"找不到游戏 Paks：{paks}")
    d = CACHE_ROOT / "base_paks"
    d.mkdir(parents=True, exist_ok=True)
    need = ("FFRS-Windows.pak", "FFRS-Windows.utoc", "FFRS-Windows.ucas",
            "global.utoc", "global.ucas")
    made, total = [], 0
    for n in need:
        src = paks / n
        if not src.exists():
            continue
        dst = d / n
        if dst.exists() and not force:
            made.append(n)
            total += dst.stat().st_size
            continue
        if dst.exists():
            dst.unlink()
        try:
            import os as _os
            _os.link(src, dst)
        except Exception:
            import shutil as _sh
            _sh.copy2(src, dst)
        made.append(n)
        total += dst.stat().st_size
    return d, total, made


def state_file(name: str) -> pathlib.Path:
    d = pathlib.Path(get("state_dir") or STATE_DIR)
    d.mkdir(parents=True, exist_ok=True)
    return d / name


def tool_settings(name: str) -> dict:
    p = state_file(name)
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def _write_tool_settings(name: str, obj: dict) -> None:
    try:
        state_file(name).write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass


def sync_to_tools(d: dict | None = None) -> None:
    """把首页路径写进各工具原本读的 settings 文件（放 state/），工具一启动就能直接用。"""
    d = d or load()
    tools = str(d.get("tools_dir") or TOOLKIT_DIR / "tools")
    game = str(d.get("game_root") or "")
    in_psd, in_vid = str(input_psd()), str(input_video())
    out_psd, out_mod = str(output_psd()), str(output_mods())

    video = tool_settings("ffrs_videomod_settings.json")
    video.setdefault("lang", "zh")
    video.setdefault("speed", "0.5x")
    video.setdefault("texture_mode", "all")
    video["game_root"] = game
    video["gameRoot"] = game
    video["video_src"] = in_vid
    video["audio_src"] = str(input_audio())
    video["output_dir"] = out_mod
    video["ffmpeg"] = str(d.get("ffmpeg") or "")
    video["cricodecs"] = str(d.get("cricodecs") or "")
    video["retoc"] = str(pathlib.Path(tools) / "retoc.exe")
    video["repak"] = str(pathlib.Path(tools) / "repak.exe")
    video["tools_dir"] = tools
    _write_tool_settings("ffrs_videomod_settings.json", video)

    text = tool_settings("ffrs_textmod_settings.json")
    text["game_root"] = game
    text["output_dir"] = out_mod
    text["tools_dir"] = tools
    text["audio_src"] = str(input_audio())
    _write_tool_settings("ffrs_textmod_settings.json", text)

    merge = tool_settings("ffrs_modmerge_settings.json")
    merge["game_root"] = game
    merge["output_dir"] = out_mod
    merge["add_dir"] = out_mod
    merge["tools_dir"] = tools
    merge["state_dir"] = str(d.get("state_dir") or STATE_DIR)
    _write_tool_settings("ffrs_modmerge_settings.json", merge)

    skill = tool_settings("ffrs_skillmod_settings.json")
    skill["game_root"] = game
    skill["output_dir"] = out_mod
    skill["tools_dir"] = tools
    skill["uassetgui"] = str(d.get("uassetgui") or "")
    skill["usmap"] = str(d.get("usmap") or "")
    skill["ffrdt"] = str(d.get("ffrdt") or "")
    _write_tool_settings("ffrs_skillmod_settings.json", skill)

    psd = tool_settings("FFRS_SpritePSD_Tool_settings.json")
    psd["game_root"] = game
    paths = psd.get("paths") or {}
    paths["input"] = in_psd
    paths["output"] = out_psd
    psd["paths"] = paths
    _write_tool_settings("FFRS_SpritePSD_Tool_settings.json", psd)

    outline = tool_settings("outline_normal_generator_settings.json")
    outline["lang"] = str(d.get("ui_lang") or "zh")
    outline["scan_dir"] = in_psd
    outline["output_dir"] = str(output_outlines())
    _write_tool_settings("outline_normal_generator_settings.json", outline)

    # 统一 UI 语言（首页右上角切换）
    lang = str(d.get("ui_lang") or "zh")
    for name in ("ffrs_videomod_settings.json", "FFRS_SpritePSD_Tool_settings.json"):
        obj = tool_settings(name)
        obj["lang"] = lang
        obj["language"] = lang
        _write_tool_settings(name, obj)


def check(d: dict | None = None) -> list[tuple[str, str, bool]]:
    d = d or load()
    rows = []
    for k, _labels, _default, kind in PATH_FIELDS:
        if k in HIDDEN_PATH_KEYS:
            continue
        p = str(d.get(k) or "")
        if k == "base_view" and not p:
            rows.append((k, p, True))      # 留空 = 自动构建，不算无效
            continue
        ok = bool(p) and (pathlib.Path(p).is_dir() if kind == "dir" else pathlib.Path(p).is_file())
        rows.append((k, p, ok))
    return rows
