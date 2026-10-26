"""FFRS Toolkit —— 统一入口（首页路径设置 + 浏览器式标签页）

用法：双击本文件，或 `python FFRS_Toolkit.py`

设计：
- 首页：各工具使用说明 + 统一路径设置 + 右上角中英切换
- 标签页：首页 | SpritePSD | VideoMod | TextMod | SkillMod | ModMerge
- 页面首次切换才构建；改路径会整体重建
- `state/` 存 json 设置，`Output/NEWMOD` 存所有 MOD 三件套
"""
from __future__ import annotations

import importlib
import pathlib
import sys
import tkinter as tk
import traceback
from tkinter import filedialog, messagebox, ttk

HERE = pathlib.Path(__file__).resolve().parent
PY_DIR = HERE / "python"          # 所有工具脚本与 kit 都在这里
sys.path.insert(0, str(PY_DIR))

from kit import settings as S  # noqa: E402
from kit.host import Host, ScrollPage   # noqa: E402

APP_TITLE = "FFRS Modding Toolkit"
__version__ = "0.9"          # 内部版本（不显示）

TOOL_PAGES = [
    ("SpritePSD", "FFRS_SpritePSD_Tool_v1_1"),
    ("OutlineNormal", "FFRS_OutlineNormal_Generator"),
    ("VideoMod", "FFRS_VideoMod_Tool"),
    ("TextMod", "FFRS_TextMod_Tool"),
    ("SkillMod", "FFRS_SkillMod_Tool"),
    ("ModMerge", "FFRS_ModMerge_Tool"),
]


# 标签页显示名（双语）
TAB_LABELS = {
    "SpritePSD":     {"zh": "精灵片解析还原工具",       "en": "Sprite Analyzer & Converter"},
    "OutlineNormal": {"zh": "描边贴图生成工具",         "en": "Outline Generator"},
    "VideoMod":      {"zh": "终结技动画演出替换工具",   "en": "Final Blow Animation Replacer"},
    "TextMod":       {"zh": "剧情台本及语音替换工具",   "en": "Story Script & Audio Replacer"},
    "SkillMod":      {"zh": "技能编辑或替换工具",       "en": "Skill Modification Tool"},
    "ModMerge":      {"zh": "模组合并工具",             "en": "Mod Merge Tool"},
}

TXT = {
    "zh": {
        "win_title": "最终幻想共鸣模组制作工具集",
        "intro": """欢迎使用 最终幻想共鸣模组制作工具集（FFRS Modding Toolkit）。

先在首页把路径配好、点「保存并应用」，之后切到任意标签页即可直接使用——
各工具启动时都会读这里的路径，不需要再单独设置。

各工具用途：
  · 精灵片解析还原工具 —— 精灵图 PSD/贴图：解析、动画预览、导出；页底整合「描边贴图生成工具」
  · 描边贴图生成工具   —— 扫描贴图 → 生成 _mreo 描边 / 修正 _normal 法线
  · 终结技动画演出替换工具 —— 用 mp4 替换游戏内影片（自动配对音频库）
  · 剧情台本及语音替换工具 —— 台词/字幕/语音：locres 四语编辑、时间轴、xlsx 批量
  · 技能编辑或替换工具 —— 四类技能修改（原生 / 精通 / 觉醒 / 召唤兽），支持替换与新 ID
  · 模组合并工具       —— 多个 MOD 三件套合并成一个（输入自动指向 Output/NEWMOD）

目录约定（点「检查并创建目录」会自动建好）：
  <输入目录>/SpritePSD、<输入目录>/VideoMod        素材分开存放
  <输出目录>/SpritePSD                              美术类输出（SpritePSD + 描边法线）
  <输出目录>/NEWMOD                                 所有 MOD 三件套（合并工具自动读这里）
  python/config                                     设置与暂存（json）
  python/save/_temp                                 临时文件 —— 关闭工具时自动清空
  python/save/_cache                                缓存 —— 保留；可用下方「清除缓存及临时文件」手动清
  外部工具目录（只填这一项，工具会自动从里面找）：
    retoc.exe、repak.exe、ffmpeg.exe、cricodecs.exe、oo2core_9_win64.dll、
    UAssetGUI/UAssetGUI.exe、ffr-dt/ffr-dt.exe

每个工具右下角都有一个 ↻ 按钮（重载该工具）：如果读取/解析时卡住或报错，先点它重载再试。

「音频缓存」留空即可：工具首次抽音频时会自动在 save/_cache 下建一份「原版容器视图」
（硬链接，不额外占空间），不受已装 MOD 影响。""",
        "paths": "路径设置（保存后各工具立即可用）",
        "save": "保存并应用",
        "check": "检查并创建目录",
        "defaults": "一键填默认值",
        "browse": "浏览…",
        "ready": "就绪",
        "missing": "有 {n} 项路径无效（可在首页修正）",
        "saved": "路径已保存，并已写入各工具设置（切页生效）",
        "created": "已创建目录：\n\n",
        "checkok": "全部路径都存在 ✓",
        "checkbad": "以下路径不存在：\n\n",
        "lang": "语言",
        "loading": "{n} 已加载",
        "loadfail": "{n} 加载失败",
        "outline": "描边 / 法线生成",
        "clear": "清除缓存及临时文件",
        "mkbase": "创建数据缓存",
        "mkbase_ok": "数据缓存已就绪：{n} 个文件，{gb:.2f} GB\n{path}",
        "mkbase_fail": "创建数据缓存失败：{e}",
        "clear_ask": "将删除缓存与临时文件（不影响已生成的 MOD 和设置）。继续？",
        "cleared": "已清理 {mb} MB（{n} 个缓存目录）",
        "temp_cleared": "已清临时文件 {mb} MB",
    },
    "en": {
        "win_title": "FFRS Modding Toolkit",
        "intro": """Welcome to FFRS Modding Toolkit.

Set the paths on this page and press "Save & apply". Then switch to any tab —
every tool reads these paths at startup, no per-tool setup needed.

Tools:
  · Sprite Analyzer & Converter — sprite PSD/atlas: parse, preview, export; outline generator at page bottom
  · Outline Generator — scan textures, build _mreo outline / fix _normal map
  · Final Blow Animation Replacer — replace in-game movies with mp4 (auto-matches the audio bank)
  · Story Script & Audio Replacer — dialogue/subtitles/voice: locres (4 languages), timeline, xlsx
  · Skill Modification Tool — four skill categories; replace skills or create new IDs
  · Mod Merge Tool — merge several MOD sets into one (input defaults to Output/NEWMOD)

Folder layout (created by "Check & create folders"):
  <input>/SpritePSD, <input>/VideoMod    source assets, kept separate
  <output>/SpritePSD                     art output (SpritePSD + outline/normal)
  <output>/NEWMOD                        all MOD sets (ModMerge reads this)
  python/config                          settings and staged json
  python/save/_temp                      temp files — cleared automatically on exit
  python/save/_cache                     cache — kept; use "Clear cache & temp" to purge
  External tools folder (this is the only path you fill in):
    retoc.exe, repak.exe, ffmpeg.exe, cricodecs.exe, oo2core_9_win64.dll,
    UAssetGUI/UAssetGUI.exe, ffr-dt/ffr-dt.exe

Every tool has a ↻ button at bottom-right (reload that tool): if loading/parsing hangs or errors, reload it and retry.

"Audio cache" can stay blank: on first audio extraction the tool builds a base-container
view under save/_cache automatically (hard links, no extra disk space).""",
        "paths": "Paths (saved for every tool)",
        "save": "Save & apply",
        "check": "Check & create folders",
        "defaults": "Fill defaults",
        "browse": "Browse…",
        "ready": "Ready",
        "missing": "{n} path(s) invalid (fix on this page)",
        "saved": "Paths saved and pushed to every tool",
        "created": "Created folders:\n\n",
        "checkok": "All paths exist ✓",
        "checkbad": "These paths are missing:\n\n",
        "lang": "Language",
        "loading": "{n} loaded",
        "loadfail": "{n} failed to load",
        "outline": "Outline / Normal",
        "clear": "Clear cache & temp",
        "mkbase": "Create data cache",
        "mkbase_ok": "Data cache ready: {n} files, {gb:.2f} GB\n{path}",
        "mkbase_fail": "Failed to create data cache: {e}",
        "clear_ask": "Delete cache and temp files (your MODs and settings are not touched). Continue?",
        "cleared": "Cleared {mb} MB ({n} cache folders)",
        "temp_cleared": "Temp cleared: {mb} MB",
    },
}


class Toolkit(tk.Tk):
    def __init__(self):
        super().__init__()
        self._cfg = S.load()
        self.lang = str(self._cfg.get("ui_lang") or "zh")
        self.title(self.T("win_title"))
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        self.geometry(f"{min(1560, sw - 80)}x{min(980, sh - 80)}+20+10")
        self.minsize(1100, 720)
        self._pages: dict[str, tk.Frame] = {}
        self._built: dict[str, tuple] = {}
        self._paths: dict[str, tk.StringVar] = {}

        self.nb = ttk.Notebook(self)
        self.nb.pack(fill="both", expand=True)
        self.home = ttk.Frame(self.nb)
        self.nb.add(self.home, text="首页" if self.lang == "zh" else "Home")
        self._build_home()
        for name, _mod in TOOL_PAGES:
            f = ttk.Frame(self.nb)
            self.nb.add(f, text=self._tab_label(name))
            self._pages[name] = f
        self.nb.bind("<<NotebookTabChanged>>", self._on_tab)

        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.status = tk.StringVar(value=self.T("ready"))
        bar = ttk.Frame(self)
        bar.pack(fill="x", side="bottom")
        ttk.Label(bar, textvariable=self.status, anchor="w").pack(side="left", padx=8, pady=2)
        ttk.Button(bar, text="↻", width=3, command=self._reload_all).pack(side="right", padx=6, pady=2)

        try:
            S.clear_temp()          # 清上次异常退出留下的临时文件
        except Exception:
            pass
        # 启动时同步一次：保证各工具 settings 与首页一致
        try:
            S.save(self._cfg)
        except Exception:
            pass
        self._refresh_status()

    def _tab_label(self, name: str) -> str:
        d = TAB_LABELS.get(name, {})
        return d.get(self.lang) or d.get("zh") or name

    def T(self, key, **kw):
        d = TXT.get(self.lang, TXT["zh"])
        return d.get(key, key).format(**kw) if kw else d.get(key, key)

    # ---------------- 首页 ----------------
    def _build_home(self):
        for w in self.home.winfo_children():
            w.destroy()
        self._paths = {}
        wrap = ttk.Frame(self.home, padding=12)
        wrap.pack(fill="both", expand=True)

        head = ttk.Frame(wrap)
        head.pack(fill="x")
        ttk.Label(head, text="FFRS Modding Toolkit", font=("Segoe UI", 16, "bold")).pack(side="left")
        self.lang_box = ttk.Combobox(head, state="readonly", values=["中文", "English"], width=9)
        self.lang_box.set("中文" if self.lang == "zh" else "English")
        self.lang_box.pack(side="right")
        ttk.Label(head, text=self.T("lang") + "：").pack(side="right", padx=(0, 4))
        self.lang_box.bind("<<ComboboxSelected>>", self._lang_changed)

        txt = tk.Text(wrap, height=15, wrap="word")
        txt.insert("1.0", self.T("intro"))
        txt.configure(state="disabled")

        box = ttk.LabelFrame(wrap, text=self.T("paths"), padding=8)
        d = S.load()
        _row = 0
        for (key, labels, _default, kind) in S.PATH_FIELDS:
            if key in getattr(S, "HIDDEN_PATH_KEYS", set()):
                continue
            r = _row
            _row += 1
            label = labels[0] if self.lang == "zh" else labels[1]
            ttk.Label(box, text=label, width=26, anchor="w").grid(row=r, column=0, sticky="w", pady=2)
            var = tk.StringVar(value=str(d.get(key) or ""))
            self._paths[key] = var
            ttk.Entry(box, textvariable=var, width=76).grid(row=r, column=1, sticky="we", padx=4)
            ttk.Button(box, text=self.T("browse"), width=8,
                       command=lambda k=key, t=kind: self._browse(k, t)).grid(row=r, column=2, padx=2)
            var.trace_add("write", lambda *_: self._refresh_status())
        box.columnconfigure(1, weight=1)

        bar = ttk.Frame(wrap)
        bar.pack(side="bottom", fill="x", pady=8)
        box.pack(side="bottom", fill="x")
        txt.pack(fill="both", expand=True, pady=(6, 8))
        ttk.Button(bar, text=self.T("save"), command=self._save).pack(side="left")
        ttk.Button(bar, text=self.T("check"), command=self._check).pack(side="left", padx=6)
        ttk.Button(bar, text=self.T("defaults"), command=self._defaults).pack(side="left")
        ttk.Button(bar, text=self.T("mkbase"), command=self._make_base_cache).pack(side="left", padx=6)
        ttk.Button(bar, text=self.T("clear"), command=self._clear_cache).pack(side="left")

    def _lang_changed(self, _e=None):
        self.lang = "zh" if self.lang_box.get() == "中文" else "en"
        cfg = self._collect()
        cfg["ui_lang"] = self.lang
        S.save(cfg)
        self._build_home()
        try:
            self.nb.tab(0, text="首页" if self.lang == "zh" else "Home")
        except Exception:
            pass
        for i, (name, _m) in enumerate(TOOL_PAGES, start=1):
            try:
                self.nb.tab(i, text=self._tab_label(name))
            except Exception:
                pass
        self.title(self.T("win_title"))
        self._reload_all()
        for _n, _m in TOOL_PAGES:
            try:
                self._ensure_page(_n)
            except Exception:
                pass
        self._refresh_status()

    def _browse(self, key, kind):
        cur = self._paths[key].get()
        if kind == "dir":
            p = filedialog.askdirectory(initialdir=cur or str(HERE))
        else:
            p = filedialog.askopenfilename(initialdir=str(pathlib.Path(cur or HERE).parent))
        if p:
            self._paths[key].set(p)

    def _defaults(self):
        for key, var in self._paths.items():
            row = next((x for x in S.PATH_FIELDS if x[0] == key), None)
            if row:
                var.set(row[2])

    def _collect(self):
        cfg = {k: v.get().strip() for k, v in self._paths.items()}
        cfg["ui_lang"] = self.lang
        try:
            cfg = S.derive_tool_paths(cfg)
        except Exception:
            pass
        return cfg

    def _save(self):
        S.save(self._collect())
        self.status.set(self.T("saved"))
        self._reload_all()

    def _check(self):
        cfg = self._collect()
        made = S.ensure_dirs(cfg)
        S.save(cfg)
        rows = S.check(cfg)
        bad = [k for k, p, ok in rows if not ok]
        if bad:
            messagebox.showwarning(self.T("check"), self.T("checkbad") + "\n".join(bad), parent=self)
        else:
            msg = self.T("checkok")
            if made:
                msg += "\n\n" + self.T("created") + "\n".join(made)
            messagebox.showinfo(self.T("check"), msg, parent=self)
        self._refresh_status()

    def _make_base_cache(self):
        """把原版三件套硬链接成视图（抽音频/抽表用，不占额外空间）。"""
        try:
            d, total, files = S.build_base_cache()
            msg = self.T("mkbase_ok", n=len(files), gb=total / 1073741824, path=d)
            self.status.set(msg.splitlines()[0])
            messagebox.showinfo(self.T("mkbase"), msg, parent=self)
        except Exception as e:
            messagebox.showerror(self.T("mkbase"), self.T("mkbase_fail", e=e), parent=self)

    def _clear_cache(self):
        if not messagebox.askyesno(self.T("clear"), self.T("clear_ask"), parent=self):
            return
        try:
            total, n = S.clear_caches()
            self.status.set(self.T("cleared", mb=f"{total / 1048576:.1f}", n=n))
        except Exception as e:
            self.status.set(f"清理失败：{e}")

    def _on_close(self):
        try:
            for name, inst in list(self._built.items()):
                save = getattr(inst[0], "_save_cfg", None) or getattr(inst[0], "save_settings", None)
                if callable(save):
                    try:
                        save()
                    except Exception:
                        pass
        finally:
            try:
                mb = S.clear_temp() / 1048576
                if mb >= 0.1:
                    print(self.T("temp_cleared", mb=f"{mb:.1f}"))
            except Exception:
                pass
            self.destroy()

    def _refresh_status(self):
        rows = S.check(self._collect())
        missing = sum(1 for _k, _p, ok in rows if not ok)
        self.status.set(self.T("ready") if not missing else self.T("missing", n=missing))

    # ---------------- 标签页 ----------------
    def _on_tab(self, _evt=None):
        idx = self.nb.index(self.nb.select())
        if idx == 0:
            return
        self._ensure_page(list(self._pages)[idx - 1])

    def _ensure_page(self, name):
        if name in self._built:
            return
        frame = self._pages[name]
        mod_name = dict(TOOL_PAGES)[name]
        try:
            extra = []
            if False:
                box = ttk.LabelFrame(frame, text=self.T("outline"), padding=4)
                box.pack(side="bottom", fill="x", padx=6, pady=4)
                try:
                    ol_mod = importlib.import_module("FFRS_OutlineNormal_Generator")
                    ol_host = Host(box, title="outline")
                    extra = [ol_mod.App(ol_host), ol_host]
                except Exception:
                    ttk.Label(box, text="outline/normal failed: " + traceback.format_exc(limit=2),
                              foreground="#b00").pack(anchor="w")
            container = frame
            mod = importlib.import_module(mod_name)
            App = getattr(mod, "App")
            logf = None
            if name == "SpritePSD":
                logf = ttk.LabelFrame(frame, text="Log", padding=3)
                logf.pack(side="bottom", fill="x", padx=6, pady=(2, 4))
                logtxt = tk.Text(logf, height=5, wrap="word")
                logtxt.pack(fill="x")
                logtxt.insert("end", "Tip: dialogs from this tool are also logged here.\n"
                              if getattr(self, "lang", "zh") == "en"
                              else "提示：本工具的弹窗消息也会记录在这里。\n")
                logtxt.configure(state="disabled")

                def _log(msg, _t=logtxt):
                    try:
                        import kit.i18n as _I
                        msg = _I.tr_log(str(msg))
                    except Exception:
                        pass
                    try:
                        _t.configure(state="normal")
                        _t.insert("end", str(msg) + "\n")
                        _t.see("end")
                        _t.configure(state="disabled")
                    except Exception:
                        pass

                orig_mb = getattr(mod, "messagebox", None)
                if orig_mb is not None and not hasattr(orig_mb, "_kit_wrapped"):
                    class _MBShim:
                        _kit_wrapped = True
                        def __getattr__(self, item):
                            fn = getattr(orig_mb, item)
                            if not callable(fn):
                                return fn
                            def wrapper(*a, **k):
                                try:
                                    _log(f"[{item}] " + " | ".join(str(x) for x in a if x is not None))
                                except Exception:
                                    pass
                                # 提示类不弹窗（只进日志）；确认类仍然弹
                                if item.startswith("show"):
                                    return None
                                return fn(*a, **k)
                            return wrapper
                    mod.messagebox = _MBShim()
            host = Host(container, title=name)
            inst = None
            last_err = None
            for make in (lambda: App(host=host), lambda: App(master=host), lambda: App(host)):
                try:
                    inst = make()
                    break
                except TypeError as e:
                    last_err = e
            if inst is None:
                raise last_err or RuntimeError("App() 无法实例化")
            if self.lang == "en":
                try:
                    import kit.i18n as _I18N
                    _I18N.apply_lang(host, "en")
                except Exception:
                    pass
            self._built[name] = (inst, host, extra + ([logf] if logf is not None else []))
            self.status.set(self.T("loading", n=name))
        except Exception:
            err = traceback.format_exc()
            tk.Label(frame, text=f"{name}\n\n{err}", justify="left", fg="#b00",
                     anchor="nw").pack(fill="both", expand=True, padx=10, pady=10)
            self.status.set(self.T("loadfail", n=name))

    def _reload_all(self):
        for name, frame in self._pages.items():
            inst = self._built.pop(name, None)
            if inst:
                try:
                    save = getattr(inst[0], "_save_cfg", None) or getattr(inst[0], "save_settings", None)
                    if callable(save):
                        save()
                except Exception:
                    pass
                objs = (inst[2] if len(inst) > 2 else []) + [inst[0], inst[1]]
                for obj in objs:
                    try:
                        obj.destroy()
                    except Exception:
                        pass
            for w in frame.winfo_children():
                w.destroy()
        if self.nb.index(self.nb.select()) != 0:
            self._on_tab()


def main():
    Toolkit().mainloop()


if __name__ == "__main__":
    main()
