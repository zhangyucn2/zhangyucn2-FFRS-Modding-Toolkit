"""极简 i18n：按「中文原文 → 英文」查表，遍历控件树替换 text。

不侵入各工具代码——工具照旧用中文写字面量，Toolkit 在构建完成后调用 `apply_lang()`：
- 有翻译就换成英文，没有就保留中文（可随时往 DICT 里补）
- 语言切换时页面会重建，所以只需在构建后调用一次
"""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk

DICT = {
    "修改只存在内存里；点「生成 MOD」才会落盘。关闭窗口即丢弃未生成的修改。": "Changes stay in memory; they are written only when you click Build MOD. Closing discards them.",
    "先解析角色": "Parse a character first.",
    "先选一条文本": "Select a text entry first.",
    "先在「① 路径设置 → 导入音频」选一个目录": "Pick an audio folder in Paths -> Import audio first.",
    "准备四语文本 …": "Preparing 4-language texts ...",
    "（当前没有暂存，事件回写时间轴）": "(no stash; events rewrite the timeline)",
    "安装完成（还原 = 点「还原」或删掉这三个文件）": "Installed (restore = click Restore or delete the three files).",
    "可以在游戏 Paks 里覆盖，或点「安装到游戏」": "You can override in Paks, or click Install to game.",

    "输入 _tex PNG": "Input _tex PNG",
    "输入 _normal PNG": "Input _normal PNG",
    "扫描": "Scan",
    "扫描贴图": "Scan textures",
    "处理说明": "Instructions",
    "生成 _mreo 描边": "Generate _mreo outline",
    "修正 Normal 描边": "Correct Normal outline",
    "使用说明": "Help",
    "使用说明（哪种 MOD 用哪个合并 / 智能合并流程）": "Help (which merge for which mod / smart merge)",
    "智能合并（技能/数据）…": "Smart merge (skills/data)…",
    "简体中文": "Simplified Chinese",
    "繁體中文": "Traditional Chinese",
    "日文": "Japanese",
    "英文": "English",
    "（搜索/替换只改「工作副本」，点「批量暂存」才写进暂存；「撤销此条」仍只作用于当前选中条目）": "(search/replace edits a working copy; Stage all writes it; Undo affects only the selected entry)",
    "Language / 语言": "Language",

    "语言：": "Language:",
    # ---------- SkillMod ----------
    "① 原生技能（主角 · 按等级学会）": "① Native skills (hero · learned by level)",
    "② 幻兵精通（装配池 · 8 槽）": "② Vision mastery (loadout · 8 slots)",
    "③ 真·幻兵（幻兵自身技能）": "③ True Vision (vision's own skills)",
    "④ 召唤兽（AI 自动释放）": "④ Esper (auto-cast by AI)",
    "⑤ 技能修改": "⑤ Skill edit",
    "技能（ID 或中/英文名）": "Skill (ID or name)",
    "读取技能": "Load skill",
    "替换技能…": "Replace skill…",
    "效果槽详情…": "Effect slots…",
    "替换特效…": "Replace visuals…",
    "清 ID 记录": "Clear ID records",
    "分轨替换…": "Split anim/FX…",
    "编辑选中…": "Edit selected…",
    "撤销该条": "Undo entry",
    "MOD 名": "MOD name",
    "生成 MOD": "Build MOD",
    "效果槽（effectBundleList）": "Effect slots (effectBundleList)",
    "读取": "Load",

    # ---------- TextMod ----------
    "FFRS 文本与语音修改工具 v2.4": "FFRS Text & Voice Tool v2.4",
    "MOD 名": "MOD name",
    "① 路径设置": "① Paths",
    "② 外部工具": "② External tools",
    "③ 角色文本列表（点条目 → 右侧编辑）": "③ Character text list (click → edit right)",
    "④ 四种文本（改完点「暂存此条」）": "④ Four languages (press “Stage this entry”)",
    "⑤ 日志": "⑤ Log",
    "⑥ 搜索 / 替换（范围＝当前角色列表，四种语言同时处理）":
        "⑥ Search / replace (current list, all 4 languages)",
    "分类 / 文本": "Category / text",
    "删除预览音频": "Delete preview audio",
    "取消": "Cancel",
    "安装到游戏": "Install to game",
    "导入台词": "Import dialogue",
    "导入音频（替换用素材）": "Import audio",
    "导出台词": "Export dialogue",
    "导出路径（生成 MOD 放这里）": "Output path (MOD goes here)",
    "影片起点": "Movie start",
    "恢复原音": "Restore original audio",
    "批量暂存": "Stage all",
    "指定…": "Browse…",
    "搜索": "Search",
    "撤销此条": "Undo entry",
    "时间轴（秒）": "Timeline (s)",
    "时间轴（秒，仅字幕可填）": "Timeline (s, subtitles only)",
    "暂存此条": "Stage entry",
    "替换": "Replace",
    "替换为": "Replace with",
    "检测工具": "Check tools",
    "清空全部修改": "Clear all changes",
    "清空该角色暂存": "Clear stash",
    "游戏目录（含 FFRS 文件夹）": "Game folder (has FFRS)",
    "状态": "Status",
    "生成 MOD": "Build MOD",
    "确定替换": "Confirm replace",
    "秒（序列里影片从第几秒开始；440011 实测 ≈2.0）":
        "s (movie start in sequence; 440011 ≈2.0)",
    "秒；留空=跟随原逻辑": "s; empty = original",
    "结束": "End",
    "角色名 / 角色ID": "Character name / ID",
    "解析": "Parse",
    "试听": "Preview",
    "语音：": "Voice: ",
    "还原": "Restore",
    "选择…": "Choose…",
    "（Ctrl+Enter = 暂存此条）": "(Ctrl+Enter = stage entry)",
    "（名称/ID 都行：光之战士、13100、summon13100）":
        "(name or ID: Warrior of Light / 13100 / summon13100)",
    "（抽表要用基础三件套视图，工具会自动建在工作目录下，不用管）":
        "(extraction uses the base view; handled automatically)",
    "（搜索/替换只改「工作副本」，点「批量暂存」才写进暂存；":
        "(search/replace edits the working copy; press Stage all to keep)",
    "（暂存会自动存进 ffrs_textmod_stash.json，下次解析同一角色自动载入）":
        "(stash saved to ffrs_textmod_stash.json, reloaded automatically)",
    # ---------- SkillMod ----------
    "FFRS 技能修改工具 v1.5": "FFRS Skill Editor v1.5",
    "ID 可用": "ID available",
    "② 单位 / 幻兵（名称或 ID）": "② Unit / vision (name or ID)",
    "③ 日志": "③ Log",
    "下拉选择（枚举字段）": "Choose (enum)",
    "只能填数字": "Numbers only",
    "填数值 / 技能 ID（-1 = 空槽）；回车确定": "Value / skill ID (-1 = empty); Enter",
    "导出路径": "Output path",
    "技能（ID 或中/英文名）": "Skill (ID or name)",
    "搜索（ID 或名称，如 麻痹 / 增益 / 伤害 / 属性）":
        "Search (ID or name: paralyze / buff / damage / element)",
    "搜索（技能 ID / 中文名 / 英文名）": "Search (ID / CN name / EN name)",
    "撤销该条": "Undo entry",
    "新 ID（留空 = 直接替换；填了 = 生成新技能）":
        "New ID (empty = replace; filled = new skill)",
    "替换技能…": "Replace skill…",
    "此 ID 已存在": "ID already exists",
    "游戏目录": "Game folder",
    "生成新 ID": "New ID",
    "确定": "OK",
    "编辑选中…": "Edit selected…",
    "读取": "Load",
    "读取技能": "Load skill",
    "（新 ID 功能已暂时隐藏）": "(new-ID hidden)",
    "（行复制待实现）": "(row copy pending)",
    # ---------- ModMerge ----------
    "FFRS MOD 合并工具 v1.0（多 MOD → 一个三件套）": "FFRS MOD Merge v1.0 (many → one)",
    "pak 条目": "pak entries",
    "① 环境": "① Environment",
    "② 待合并的 MOD（可加多个；也支持依次合并：把上次的产物再当源加进来）":
        "② MODs to merge (add several; you can chain-merge)",
    "③ 日志": "③ Log",
    "分析": "Analyze",
    "刷新 Output": "Refresh Output",
    "合并": "Merge",
    "添加 MOD…": "Add MOD…",
    "源 / 位置": "Source / location",
    "移除选中": "Remove selected",
    "角色线索": "Character clue",
    "输出名": "Output name",
}


def tr(text: str) -> str:
    return DICT.get(text, text)


def apply_lang(widget: tk.Misc, lang: str = "en") -> None:
    """递归把控件树里能翻译的 text 换掉（中文 → 英文）。"""
    if lang != "en":
        return
    try:
        cur = None
        try:
            cur = widget.cget("text")
        except Exception:
            cur = None
        if isinstance(cur, str) and cur:
            new = tr(cur)
            if new != cur:
                try:
                    widget.configure(text=new)
                except Exception:
                    pass
        # Treeview 表头
        if isinstance(widget, ttk.Treeview):
            try:
                for col in widget["columns"]:
                    h = widget.heading(col, "text")
                    if h:
                        widget.heading(col, text=tr(h))
            except Exception:
                pass
    except Exception:
        pass
    for child in widget.winfo_children():
        apply_lang(child, lang)

# ──────────────────────────── 日志翻译（英文界面用） ────────────────────────────
import re as _re

_LOG_EXACT = {
    "提示：双击单元格可直接改技能 ID；技能名来自 ST_SkillName（四语里取简体/日文）":
        "Tip: double-click a cell to edit the skill ID; names come from ST_SkillName (zh-Hans/ja).",
    "提示：合并前会自动分析每个源，若角色线索不一致会弹确认框（仍可强制合并）。":
        "Tip: each source is analyzed first; if skill/data mods are detected you will be asked how to merge.",
    "提示：本工具的弹窗消息也会记录在这里。":
        "Tip: dialogs from this tool are also logged here.",
    "先选一行": "Select a row first.",
    "这一行不可编辑": "This row is not editable.",
    "请先从 ①②③④ 里双击一个技能进入 ⑤，再点「替换技能…」":
        "Double-click a skill in 1-4 to open it in 5, then press Replace skill...",
    "新技能需要知道『装进哪个槽』：请到 ①②③④ 里**双击那个槽位**进入 ⑤（只用「读取技能」看不出槽位），再点「替换技能…」并填新 ID":
        "A new skill needs a slot: double-click the slot in 1-4, then Replace skill... and enter a New ID.",
    "没有任何修改（也没暂存新技能 / 分轨替换）": "Nothing to build (no staged edits / new skills / splits).",
    "没有可生成的改动": "Nothing to build.",
    "ffr-dt patch …": "ffr-dt patch ...",
    "retoc to-zen …": "retoc to-zen ...",
}

_LOG_RULES = [

    (_re.compile(r"^列表就绪：(\d+) 条文本$"), r"List ready: \1 text entr(ies)"),
    (_re.compile(r"^已暂存 ([^：]+)：(.*)$"), r"Staged \1: \2"),
    (_re.compile(r"^暂存已保存到 (.+)（(\d+) 条文本 / (\d+) 条时间轴）$"),
     r"Stash saved to \1 (\2 texts / \3 timeline)"),
    (_re.compile(r"^已清空 (\d+) 条暂存（工作副本、时间轴也复位）$"),
     r"Cleared \1 staged entr(ies) (working copy and timeline reset)"),
    (_re.compile(r"^已导出台词表：(.+)（(\d+) 行 × (\d+) 列）$"),
     r"Exported dialogue: \1 (\2 rows x \3 cols)"),
    (_re.compile(r"^安装失败：(.+)$"), r"Install failed: \1"),
    (_re.compile(r"^导入完成：台词（(.+)）、语音 (\d+) 条$"),
     r"Import done: dialogue (\1), voice \2"),
    (_re.compile(r"^导入失败：(.+)$"), r"Import failed: \1"),
    (_re.compile(r"^✓ 游戏 Paks：(.+)$"), r"OK game Paks: \1"),
    (_re.compile(r"^✓ 基础 pak：(.+)$"), r"OK base pak: \1"),
    (_re.compile(r"^✓ 基础容器视图：(.+)$"), r"OK base container view: \1"),
    (_re.compile(r"^扫描到 (\d+) 个 PNG：(.+)$"), r"Scanned \1 PNG(s): \2"),

    (_re.compile(r"^刷新：(.+) 里发现 (\d+) 个 MOD$"), r"Refresh: \1 has \2 MOD(s)"),
    (_re.compile(r"^已加入 (\d+) 个源，共 (\d+) 个$"), r"Added \1 source(s), total \2"),
    (_re.compile(r"^已恢复上次的原视频/替换视频路径；点「解析」刷新预览与对比。$"),
     r"Restored last original/replacement video paths; click Parse to refresh."),
    (_re.compile(r"^已暂存：(.+)$"), r"Staged: \1"),
    (_re.compile(r"^⑤ 已载入 (\d+)（(.+)）：(\d+) 个可改字段$"),
     r"5 Loaded \1 (\2): \3 editable fields"),
    (_re.compile(r"^提取技能名/单位名 …$"), r"Loading skill/unit names ..."),
    (_re.compile(r"^技能名 (\d+) 条 / 单位名 (\d+) 条$"), r"Skill names: \1 / unit names: \2"),
    (_re.compile(r"^已暂存新技能 (\d+)（源 (\d+)(.*)）→ 点「生成 MOD」时一起打包$"),
     r"Staged new skill \1 (donor \2\3) - click Build MOD to package together"),
    (_re.compile(r"^普通改动：(\d+) 处 / (\d+) 张表$"), r"Plain edits: \1 in \2 table(s)"),
    (_re.compile(r"^抽取 (.+) …$"), r"Extracting \1 ..."),
    (_re.compile(r"^生成完成 → (.+)（普通改动 (\d+) 处 / 新技能 (\d+) 个）$"),
     r"Build done -> \1 (plain edits: \2 / new skills: \3)"),
    (_re.compile(r"^生成失败：(.+)$"), r"Build failed: \1"),
    (_re.compile(r"^待打包的新技能：(.+)$"), r"Pending new skills: \1"),
    (_re.compile(r"^分轨：动画 (\d+)（(\d)/4）+ 特效 (\d+) → 技能 (\d+)$"),
     r"Split: animation \1 (\2/4) + effect \3 -> skill \4"),
    (_re.compile(r"^新技能 (\d+)：动画保留 (\d+)，特效用 (\d+)$"),
     r"New skill \1: keep animation \2, effect from \3"),
    (_re.compile(r"^效果槽详情：已暂存 (\d+) 处改动（技能 (\d+)）$"),
     r"Effect slots: staged \1 change(s) (skill \2)"),
    (_re.compile(r"^已暂存：用技能 (\d+) 的演出替换当前技能 (\d+) 的演出（(.+)）$"),
     r"Staged: use skill \1 visuals to replace skill \2 (\3)"),
    (_re.compile(r"^已暂存分轨：技能 (\d+) 用 (\d+) 的动画 + (\d+) 的特效$"),
     r"Staged split: skill \1 uses animation \2 + effect \3"),
    (_re.compile(r"^已跳过 (\d+) 个技能 MOD，只合并其他$"), r"Skipped \1 skill mod(s); merging the rest"),
    (_re.compile(r"^先智能合并技能：(.+)$"), r"Smart-merging skills first: \1"),
    (_re.compile(r"^智能合并开始：(.+)$"), r"Smart merge started: \1"),
    (_re.compile(r"^智能合并完成 → (.+)$"), r"Smart merge done -> \1"),
    (_re.compile(r"^智能合并失败：(.+)$"), r"Smart merge failed: \1"),
    (_re.compile(r"^已加入 (\d+) 个源，共 (\d+) 个$"), r"Added \1 source(s), total \2"),
    (_re.compile(r"^完成：(.+)$"), r"Done: \1"),
    (_re.compile(r"^合并失败：(.+)$"), r"Merge failed: \1"),
]


_LOG_FRAG = [
    ("[预览]", "[preview]"), ("输入=", "input="), ("输出目录=", "out dir="),
    ("输出=", "output="), ("目录模式", "dir mode"), ("原视频", "original video"),
    ("替换视频", "replacement video"), ("解析", "Parse"),
    ("元素属性", "element"), ("目标类型", "TargetType"), ("技能属性", "skillAttrType"),
    ("伤害类型", "DamageType"), ("效果类型", "skillEffectType"), ("技能名字", "skill name"),
    ("已暂存", "staged"), ("替换为", "replaced with"), ("演出", "visuals"),
    ("动画", "animation"), ("特效", "effect"), ("技能", "skill"), ("幻兵", "vision"),
    ("召唤兽", "esper"), ("主角", "hero"), ("属性", "attribute"), ("字段", "field"),
    ("可改字段", "editable fields"), ("行", "row"), ("槽", "slot"), ("已经", "already"),
]


def tr_log(msg: str) -> str:
    """英文界面下把日志里的常见中文换成英文；未覆盖的原样返回。"""
    try:
        import kit.settings as _K
        if str(_K.get("ui_lang") or "zh") != "en":
            return msg
    except Exception:
        return msg
    t = str(msg)
    if t in _LOG_EXACT:
        return _LOG_EXACT[t]
    if t in DICT:
        return DICT[t]
    out = t
    for rx, rep in _LOG_RULES:
        if rx.match(out):
            out = rx.sub(rep, out)
            break
    for a, b in _LOG_FRAG:
        out = out.replace(a, b)
    return out
