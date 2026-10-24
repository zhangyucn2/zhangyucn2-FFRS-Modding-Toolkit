# -*- coding: utf-8 -*-
"""
FFRS 视频替换 MOD 工具  v1.0
==========================================
> v1.0 = 首个公开发布版。此前的 v1.1~v1.4 是内部迭代，变更记录保留在下方。

把任意常见格式的视频转成 FFRS（最终幻想共鸣）能识别的 USM，并生成/安装 MOD。

v1.4（内部迭代）变更：
  * ★ 新增第三模式「幻兵祠堂语音替换工具」：幻兵的闪回动画与音频库不是一一对应，
    所以这个模式直接列出该幻兵语音库的全部条目，**逐条**从「导入音频」里挑文件替换，
    每条都能试听（游戏内原音 / 导入的素材两侧都能听）。
  * ★ 新增独立入口 `FFRS_VideoMod_Simple.py`：把「简化模式」单做成给普通玩家的
    `FFRS视频替换MOD安装工具`（可打包成 exe，不需要任何外部程序）。
  * 修复：打包成 exe 后 `APP_DIR` 指向临时解压目录，导致「还原记录」丢失、玩家无法还原。
  * 修复：幻兵界面里「导入音频 / 导出路径」的标签与按钮没有文字（刷新文案时漏了这一组）。
  * 修复：界面下拉宽度不够，「幻兵祠堂语音替换工具」显示不全。
  * 「替换音频」新增「不替换」选项；音量改为可选档位（默认为原条目对齐）。
  * 下方提示区改成编号式「注意事项 ①②③…」。

v1.3 变更：★ 新增「音频替换」
  * 影片本身**不含音频** —— 音效是 CRIWARE 音库里独立的一条，由播放该影片的
    LevelSequence 桥段在同一时间点触发。所以只换画面会出现「新画面 + 老音效」的错配。
  * 「MOD 制作」模式新增：
        - **「导入音频」路径行**（wav/mp3/m4a/flac/ogg…）——和「导入视频」一样选目录或单文件，
          扫出的音频文件填进下拉
        - **「替换音频」下拉（单选）**：列的就是「导入音频」路径里的那些文件（带时长），
          多音频时在这里挑要用的那一条
        - **游戏内目标由「原视频」自动定位**：取该影片在桥段里触发的音效中**时长与影片
          最接近**的那条（与画面同步播放的就是它），旁边有「指定目标…」按钮可手动改
          （按 cue 名搜索，或直接填条目号）
        - 参数对比面板新增：游戏内目标 vs 替换音频 vs 影片时长，
          过长/过短/与影片时长差得多都会给出提醒
        - 生成时把**选中的那条导入音频**打包成 IoStore 补丁容器 `<视频MOD名>_P.{pak,utoc,ucas}`
          （如 `MV_summon300010_mod_P.*`），一眼能看出属于哪个 MOD
             · 音频在 Oodle 压缩块里，做不到像视频那样就地改 ucas，只能用补丁容器
             · 名字只要求带 `_P` 后缀，没有其它约束
        - ★ **响度对齐**：游戏音效都是接近满刻度母带过的（原条目峰值常达 -0.3 dBFS），
          而玩家素材常轻十几 dB —— 不补就「BGM 一开完全听不清」。
          替换时按 RMS 增益到原条目电平，再限幅防削顶，日志会打印实际增益
  * 「安装到游戏」= 原有的视频安装 + 把三件套复制进 Paks；
    「全部还原」会一并删除三件套（视频还原逻辑不变）
  * 简化模式「全部安装」现在也会把 MOD 目录里的 `*_P.{pak,utoc,ucas}` 一起装进去
    （之前只装 .usm，会「MOD 装了但音频没变」）
  * ⚠ 要再建音频补丁，必须先把已装的补丁**全部还原**：音库是从 Paks 现抽的，
    而补丁容器会被优先读到 —— 带着补丁去抽会拿到改过的音库。工具会检测并停下
  * 新增外部依赖 **retoc.exe + oo2core_9_win64.dll**（工具目录下，用于抽音库 / 打补丁容器）
  * 数据来自同目录的 **ffrs_audio_index.json**（由 Build_AudioIndex.py 生成）：
    扫「播放影片的桥段」把 (影片, 音效 cue) 配起来，再查各音库的 cue 表拿条目号
  * ⚠ 音频补丁会**整块覆盖**该音库（如 SE_BTL_PP 约 84 MB），不要与改同一音库的
    其它 MOD 混用；另外若游戏 Paks 里已有别的 _P 补丁，基线可能已被改过 ——
    工具会停下并提示先清理（音库是从 Paks 现抽的，补丁容器会被优先读到）

v1.2 变更：
  * 记住上次的原视频/替换视频路径与选中项，重开不用重新指认
  * 预览下方新增「参数对比与提醒」面板：分辨率/帧率/时长不一致时给出明确提示与处理建议
  * 去掉「时长模式」（实测改写游戏侧帧数无效 —— 游戏内播放窗口由游戏本身决定，
    见 Research/FFRS视频MOD_研究成果总结.md §7）
  * 修复别名生成的长度 bug：旧版对非召唤片名会令长度改变而安装失败，
    现在 MV_xxx -> MZ_xxx 对任意片名都等长，Event / Skill / Summon 三大类均可用
  * 修复解析完成后预览不自动刷新的问题
  * ★ 修复 Event 类（27 部）无法预览：cricodecs 的 -o 语义随流数变化
    （多流当目录、单流当文件），旧代码一律当目录用，对只有 @SFV 的单流影片必然失败
  * 预览改为「选中哪部解哪部」，不再只解前 20 部（旧版会让排在后面的 Skill/Summon 永远没预览）
  * 下拉里同名的影片（如 Skill/en 与 Skill/jp）现在显示相对路径以便区分
  * ★ 修复预览只覆盖开头几秒：抽样帧率改为按整片时长计算
    （旧版写死 fps=6 + 24 帧 = 只取开头 4 秒；Event 的长片有两分多钟，只预览到 3%）
  * ★ 修复切换路径后预览不更新：预览缓存按下标命名，换目录后会沿用旧画面，
    现在一换路径就清缓存（原视频/导入视频两侧都清）
  * ★ 新增「批量安装」（cue 列表）
  * 「批量安装…」按钮移到「安装到游戏」右侧，并改名为「安装选中…」

v1.1 变更：
  * 全部还原 / 选择性还原（带影片下拉菜单）
  * 重复安装可用（mod 已装时再装，靠别名回找记录）
  * 双流（视频+alpha）影片的两条流帧数同步改写

（以下为 v1.2 时期的说明，保留备查）
  * ★ 新增「简化模式」（左上角可切 简化模式 <-> MOD 制作）——**首次打开进简化模式，
    之后记住上次退出时的模式**（切到 MOD 制作做完 mod 再退出，下次直接进 MOD 制作）：
        - 只保留：MOD 目录、游戏目录、全部安装 / 安装选中…、全部还原 / 还原选中
        - 普通玩家拿到 MOD 后指定两个路径就能装/还原，看不到制作相关的功能
  * 「批量安装…」按钮移到「安装到游戏」右侧，并改名为「安装选中…」；
    两行按钮改用同一网格布局，「全部还原」对齐在「安装到游戏」下方、「还原选中」对齐在「安装选中…」下方
  * 安装候选列表只列**能装的**（就绪 / 已安装）；找不到原片的 MOD 与没有 MOD 的影片不再占行，
    数量改在汇总行里说明，不静默吞掉
  * 窗口尺寸随模式自动调整（简化模式紧凑、制作模式加高），不用手动拉窗口
  * 简化模式的提示改成编号的「使用说明」

技术链路（全部已实测验证）：
    video --ffmpeg--> VP9 IVF  --cricodecs--> USM
    alpha --ffmpeg--> MPEG-1   --cricodecs--> (USM 内 @ALP 流)

依赖：仅 Python 标准库（Tkinter）。外部工具 ffmpeg.exe / cricodecs.exe。

界面布局（对应需求）：
    [原视频(原USM)路径]                [选择]
    [导入视频路径]                     [选择]
    [导出路径]                         [指定]
    [解析] [原视频下拉] [替换视频下拉]
    |  原视频预览  |  替换视频预览   |
    [MOD 生成/安装]        [提示信息]
                                  右上角：语言下拉
"""

from __future__ import annotations

import json
import math
import os
import queue
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import threading
import time
import tkinter as tk
import wave
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

APP_NAME = "FFRS 视频替换 MOD 工具"
# ★ 打包成 exe 后 __file__ 指向 PyInstaller 的临时解压目录（_MEIxxxx），
#   设置的 json、尤其是「还原记录」backup.json 会被写进临时目录、退出即丢 ——
#   玩家就再也还原不了游戏了。frozen 时改用 exe 自身所在目录。
APP_DIR = (Path(sys.executable).resolve().parent if getattr(sys, "frozen", False)
           else Path(__file__).resolve().parent)
SETTINGS = APP_DIR / "ffrs_videomod_settings.json"
try:
    import kit.settings as _KIT
    SETTINGS = _KIT.state_file("ffrs_videomod_settings.json")
except Exception:
    pass

VIDEO_EXTS = {".mp4", ".mkv", ".avi", ".mov", ".webm", ".m4v", ".wmv", ".flv", ".ts", ".m2ts", ".mpg", ".mpeg"}
USM_EXT = ".usm"
# 从 USM 里解出来的视频流可能长这样（cricodecs 用 wav/sfv 存音频与 alpha）
VIDEO_STREAM_EXTS = {".ivf", ".m2v", ".vp9", ".bin"}

# ──────────────────────────── 国际化 ────────────────────────────
STRINGS = {
    "zh": {
        "title": "FFRS 视频替换 MOD 工具 v1.0",
        "title_simple": "FFRS视频替换MOD安装工具 v1.0",
        "lang": "语言 / Language",
        "grp_src": "路径设置",
        "orig_path": "原视频（原 .usm）",
        "new_path": "导入视频",
        "out_dir": "导出路径",
        "browse": "选择…",
        "browse_dir": "指定…",
        "grp_preview": "预览",
        "btn_parse": "解析",
        "lbl_orig_sel": "原视频",
        "lbl_new_sel": "替换视频",
        "preview_orig": "原视频预览",
        "preview_new": "替换视频预览",
        "btn_play": "播放",
        "btn_pause": "暂停",
        "no_file": "（未选择）",
        "info_title": "影片信息",
        "btn_build": "生成 MOD",
        "btn_install": "安装到游戏",
        "btn_restore": "还原游戏",
        "tip_head": "注意事项：",
        "tip_1": "①设置好素材和工具路径，点击「生成 MOD」即可。",
        "tip_2": "②「安装到游戏」= 把生成的 MOD 三件套（.pak / .utoc / .ucas）复制进游戏的 Content/Paks；删掉这三个文件即可还原。",
        "tip_3": "③替换视频的分辨率/帧率与原片不同没关系，工具会自动处理；只有【时长】需要你自己拿捏 —— 游戏内播放窗口由游戏本身决定，超出会被裁掉、不足会循环。",
        "tip_4": "④幻兵在祠堂中播放的闪回动画的旁白对应一个音频库，和闪回动画不是一一对应的关系，请在「替换音频」中选择「不替换」先完成干净的视频替换，再按需替换对应音频库中的音频。",
        "tip_5": "⑤如果需要替换幻兵祠堂中的旁白，请切换到「幻兵祠堂语音替换工具」。",
        "tip_6": "⑥MOD合并功能为可选项，目前一次只能合并一个MOD且只支持精灵片/数据类修改MOD。",
        "need_paths": "请检查是否已将原视频/素材视频放入 VideoMOD 目录；是否将音频素材放入 AudioMOD 目录。",
        "parsing": "解析中…",
        "parse_done": "解析完成：{n} 个原视频，{m} 个替换视频。",
        "parse_fail": "解析失败：{e}",
        "building": "正在生成…",
        "build_done": "生成完成：{p}",
        "build_fail": "生成失败：{e}",
        "installing": "正在安装…",
        "install_done": "已安装：{p}\n现在可以进游戏查看效果了。",
        "install_fail": "安装失败：{e}",
        "restore_done": "已还原游戏原始文件。",
        "no_records": "没有可还原的记录。",
        "confirm_install": "将把 MOD 三件套复制进游戏的 Paks 目录：\n  {p}\n\n删除这三个文件即可还原。继续吗？",
"confirm_restore": "将把游戏文件还原到原始状态。继续吗？",
        "err_no_game": "无法从填写的路径定位游戏。\n请填游戏目录（其下有 FFRS 文件夹），或直接填 Paks 目录。",
        "game_dir": "游戏目录（含 FFRS 文件夹）",
        "tools": "外部工具",
        "ffmpeg": "ffmpeg.exe",
        "cricodecs": "cricodecs.exe",
        "check": "检测工具",
        "tool_ok": "OK",
        "tool_missing": "缺失",
        "check_bad_names": "以下工具路径无效：{names}\n请重新指定这些工具的路径。",
        "check_ok": "工具路径均有效。",
        "check_bad": "有工具路径无效。",
        "log": "日志",
        "restore_all": "全部还原",
        "restore_sel": "还原选中",
        "restore_pick": "选择要还原的影片",
        "restore_none": "（无可还原项）",
        "restore_ok": "已还原：{p}",
        "restore_none_sel": "请先在下拉菜单里选择要还原的影片。",
        "installed_n": "已安装 {n} 部",
        "build_align": "按原片对齐：{n} 帧 = {os} 秒",
        "build_nometa": "警告：读不出替换视频的参数，请确认文件能正常播放。",
        "orig_none": "无原视频",
        "new_none": "无替换视频",
        "preview_loading": "（正在解出预览…）",
        # —— 批量安装 ——
        "batch_btn": "安装选中…",
        "batch_title": "选择要安装的 MOD",
        "batch_mods_dir": "MOD 目录",
        "batch_scan": "扫描/刷新",
        "batch_col_movie": "影片（游戏内）",
        "batch_col_mod": "对应 MOD",
        "batch_col_state": "状态",
        "batch_install_all": "全部安装",
        "batch_install_sel": "安装选中",
        "batch_close": "关闭",
        "batch_st_ready": "就绪",
        "batch_st_installed": "已安装",
        "batch_st_none": "—",
        "batch_st_orphan": "找不到对应原片",
        "batch_st_dup": "MOD 重名，无法确定",
        "batch_st_bad": "原片缺失",
        "batch_scanning": "正在扫描游戏影片清单…",
        "batch_summary": "可安装的 MOD：{n} 个",
        "batch_extra": "（另有 {o} 个 MOD 在游戏影片清单里找不到对应原片、{d} 处因重名无法确定，未列在上表）",
        "batch_none_sel": "请先在列表里选择要安装的影片。",
        "batch_confirm_all": "要安装列表里全部 {n} 个 MOD 吗？",
        "batch_confirm_sel": "要安装选中的 {n} 个 MOD 吗？",
        "batch_done": "批量安装完成：成功 {n} 部",
        "batch_fail": "安装失败 {p}：{e}",
        "batch_tip": "只列出【游戏里真实存在】的影片。安装 = 把 MOD 放进 Content/Streams/Movies/… 并把该影片的 MoviePath 重定向到它；删掉列表里的 MOD 文件即可让它从列表消失。还原请用主界面的「全部还原 / 还原选中」。",
        "batch_mods_missing": "MOD 目录不存在：\n{p}\n请点「浏览」选择存放 MOD 的文件夹。",
        "batch_nothing": "在\n{p}\n里没有找到能对上本游戏影片的 MOD。\n请确认 MOD 文件名形如 MV_xxxx_mod.usm。",
        # —— 模式切换 ——
        "mode_lbl": "界面",
        "mode_simple": "简化模式",
        "mode_full": "MOD 制作",
        "mod_dir": "MOD 目录",
        "game_paks": "游戏目录（或 Paks 目录）",
        "btn_install_all": "全部安装",
        "simple_tip": "使用说明：\n"
                      "①「MOD 目录」指向存放 MOD 的文件夹；\n"
                      "②「游戏目录」指向游戏根目录（里面有 FFRS 文件夹）；\n"
                      "③「全部安装 / 安装选中」将 MOD 目录中的 MOD 全部 / 按选择安装进游戏；\n"
                      "④「全部还原 / 还原选中」将已安装的 MOD 全部 / 按选择卸载。\n"
                      "\n"
                      "如果想自己制作 MOD，在左上角切到「MOD 制作」模式。",
        "langname": "中文",
        # —— 参数对比面板 ——
        "info_title": "参数对比与提醒",
        "info_hint": "点「解析」后，这里会列出原视频与替换视频的参数差异，并给出该怎么处理。",
        "info_orig": "原视频",
        "info_new": "替换视频",
        "info_line": "{w}x{h}   {fps} fps   {n} 帧   {s} 秒",
        "info_na": "参数不全",
        "info_all_ok": "✓ 分辨率 / 帧率 / 时长都一致，可以直接生成。",
        "info_fps_bad": "· 帧率不同（{a} → {b} fps）：工具会自动按原片帧率编码，你不用手动改。",
        "info_res_bad": "· 分辨率不同（{a} → {b}）：工具会自动缩放到原片分辨率，你不用手动改。",
        "info_long": "⚠ 替换片比原片【长】（{ns} 秒 vs {os} 秒）：游戏内的播放窗口只有原片那么长，超出的部分不会播出、会被裁掉。\n      建议把替换视频剪到 {os} 秒以内再导入。",
        "info_short": "⚠ 替换片比原片【短】（{ns} 秒 vs {os} 秒）：游戏内会循环播放来填满原片时长。\n      只想播一遍的话，请把替换视频补足到 {os} 秒左右。",
        # —— 音频替换 ——
        "audio_src": "导入音频",
        "lbl_audio_sel": "替换音频",
        "audio_none": "（不替换音频）",
        "audio_none_found": "（该影片未找到配对音频）",
        "audio_extracting": "首次使用：正在从游戏容器抽出音库 {bank} …",
        "audio_streaming": "音库 {bank} 是流式(pak)音库，本版暂不支持替换。",
        "audio_need_src": "已选要替换的音频，但没有填「导入音频」文件。",
        "audio_need_target": "填了「导入音频」，但没有选「替换音频」目标。",
        "audio_index_ok": "音频索引：{m} 部影片有配对音频，{b} 个音库。",
        # —— 参数对比（音频）——
        "info_audio_orig": "原音频",
        "info_audio_new": "替换音频",
        "info_audio_line": "{s} 秒   {cue}（{bank} 条目 {e}）",
        "info_audio_unknown": "参数不全",
        "info_audio_nofile": "（未选择）",
        "info_audio_long": "⚠ 替换音频比原音频【长】（{ns} 秒 vs {os} 秒）：超出的部分会被裁掉。",
        "info_audio_short": "⚠ 替换音频比原音频【短】（{ns} 秒 vs {os} 秒）：剩余时间会是静音。",
        "info_audio_sync": "⚠ 替换音频（{ns} 秒）与影片时长（{vs} 秒）差 {d} 秒，可能音画不同步。",
        "info_audio_sync_ok": "✓ 替换音频与影片时长基本对齐。",
        "tip_4": "④幻兵在祠堂中播放的闪回动画的旁白对应一个音频库，和闪回动画不是一一对应的关系，请在「替换音频」中选择「不替换」先完成干净的视频替换，再按需替换对应音频库中的音频。",
        "audio_working": "正在准备音频补丁：{bank} 条目 {e} …",
        "audio_build_done": "音频补丁已生成：{p}",
        "audio_installed": "已安装音频补丁：{p}",
        "audio_install_hint": "音频补丁会整块覆盖该音库。\n已安装时请勿再装其它改同一音库的 MOD。\n\n继续吗？",
        "audio_restored": "已移除音频补丁（{n} 个文件）。",
        "audio_conflict": ("游戏 Paks 里已有第三方补丁 {p}。\n"
                           "音库是从 Paks 现抽的，而补丁容器会被优先读到 —— "
                           "在已被改过的基线上替换会得到错误结果。\n\n"
                           "请先删掉它（或游戏根目录的「还原游戏」）再继续；\n"
                           "若之前已抽取过音库，请一并删除工具目录下的 _audio_cache 文件夹。"),
        "info_audio_at": "游戏内目标",
        "audio_no_list": "（未选择音频路径）",
        "audio_gain": "音量",
        "audio_gain_auto": "自动对齐原条目",
        "audio_gain_boost": "自动 {db} dB",
        "audio_gain_none": "不处理（原样）",
        "info_audio_whole": "整章语音库 {bank}（{n} 条台词）；按文件名顺序铺开导入的 {m} 个文件",
        "audio_skip": "不替换",
        "audio_skip_note": "不替换音频（只换画面）",
        # —— 幻兵祠堂语音替换工具 ——
        "mode_vision": "幻兵祠堂语音替换工具",
        "vis_grp_src": "路径设置",
        "vis_src": "导入音频",
        "vis_out": "导出路径",
        "vis_scan": "扫描/刷新",
        "vis_grp_list": "幻兵旁白（游戏内）",
        "vis_col_ingame": "音频（游戏内）",
        "vis_col_import": "导入音频",
        "vis_btn_audition": "试听",
        "vis_btn_build": "生成MOD",
        "vis_btn_install": "安装到游戏",
        "vis_btn_restore": "全部还原",
        "vis_skip": "（不替换）",
        "vis_tip_head": "注意事项：",
        "vis_tip_1": "①此工具只用来替换幻兵闪回动画的旁白语音，「MOD制作」中未检索到幻兵闪回动画，则此工具不可用。",
        "vis_tip_2": "②每一行都可以从「导入音频」下拉里挑一个文件替换该条旁白；选「（不替换）」则保留原样。",
        "vis_tip_3": "③生成的音频补丁会整块覆盖该语音库（十几 MB），请勿与改同一音库的 MOD 混用。",
        "vis_tip_4": "④要先在「MOD制作」里解析过幻兵闪回影片，本工具才知道要处理哪个幻兵。",
        "vis_tip_5": "⑤本工具调用的外部工具和「MOD制作」相同（游戏目录 / ffmpeg / cricodecs / retoc），如相关路径有变化请返回「MOD制作」界面修改。",
        "vis_unavailable": "未检索到幻兵闪回动画，此工具暂时不可用",
        "vis_scanning": "正在扫描幻兵闪回动画…",
        "vis_found": "检索到 {n} 个幻兵：{v}",
        "vis_none": "「MOD制作」里没有检索到幻兵闪回动画。",
        "vis_need_src": "请先指定「导入音频」路径。",
        "vis_nothing": "所有行都是「（不替换）」，没有需要生成的音频。",
        "vis_building": "正在生成音频补丁…",
        "vis_built": "已生成音频补丁：{p}",
        "vis_restored": "已移除音频补丁（{n} 个文件）。",
        "vis_preview_prep": "正在准备试听缓存：{bank} …",
        "vis_preview_ok": "试听缓存就绪：{bank}（{n} 条）",
        "vis_play_fail": "试听失败：{e}",
        "vis_entries": "{bank}：{n} 条旁白",
        "tool_ffmpeg": "ffmpeg.exe",
        "tool_cricodecs": "cricodecs.exe",
        "tool_path_empty": "（未填写）",
        "tool_path_bad": "外部工具路径无效：{label} = {p}",
        "tool_path_hint": "请到「MOD 制作」界面的「外部工具」里重新指定 ffmpeg / cricodecs / retoc，再点「检测工具」。",
        "build_cleaned": "已清理中间文件：{p}（已打进 pak）",
        "build_clean_fail": "中间文件清理失败：{p}（{e}）",
        "movie_patch_done": "影片补丁容器已生成：{p}",
        "no_patch": "还没生成 MOD（请先点「生成 MOD」）",
        "retoc": "retoc.exe（音频补丁用）",
        "repak": "repak.exe（影片打包用）",
        "confirm_overwrite": "检测到已安装同名 MOD：{p}\n是否覆盖？",
        "base_view_fail": "提示：无法建立基础容器视图（可能跨磁盘），将从 Paks 目录抽取音库；若已装音频 MOD，抽出的可能是已被改动过的基线。",
        "grp_merge": "MOD合并（可选）",
        "merge_path": "待合并MOD路径",
        "merge_bad": "待合并 MOD 路径无效：{p}",
        "merge_done": "已把待合并 MOD 打进容器：{p}",
    },
    "en": {
        "title": "FFRS Video Replacement MOD Tool v1.0",
        "title_simple": "FFRS Video Mod Installer v1.0",
        "lang": "Language / 语言",
        "grp_src": "Paths",
        "orig_path": "Original video (original .usm)",
        "new_path": "Replacement video",
        "out_dir": "Output folder",
        "browse": "Browse…",
        "browse_dir": "Choose…",
        "grp_preview": "Preview",
        "btn_parse": "Scan",
        "lbl_orig_sel": "Original",
        "lbl_new_sel": "Replacement",
        "preview_orig": "Original preview",
        "preview_new": "Replacement preview",
        "btn_play": "Play",
        "btn_pause": "Pause",
        "no_file": "(none)",
        "info_title": "Clip info",
        "btn_build": "Build MOD",
        "btn_install": "Install to game",
        "btn_restore": "Revert game",
        "tip_head": "Notes:",
        "tip_1": "1) Set the asset and tool paths, then click \"Build MOD\".",
        "tip_2": "2) \"Install to game\" copies the built MOD three-piece (.pak / .utoc / .ucas) into the game's Content/Paks; delete those three files to revert.",
        "tip_3": "3) A different resolution / frame rate is fine - the tool handles it. Only the LENGTH is up to you: the in-game window is fixed by the game, so longer gets cut and shorter gets looped.",
        "tip_4": "4) A vision's flashback movies share one narration voice bank rather than mapping one-to-one to each movie. Pick \"do not replace\" under \"Replace audio\" to finish a clean video-only replacement first, then replace entries in the matching bank as needed.",
        "tip_5": "5) To replace the narration of a vision's flashback, switch to the \"Vision Shrine Voice Tool\".",
        "tip_6": "6) MOD merge is optional: only one MOD can be merged at a time, and only sprite-sheet / data-type MODs are supported.",
        "need_paths": "Please choose both the original and the replacement video.",
        "parsing": "Scanning…",
        "parse_done": "Done: {n} original, {m} replacement file(s).",
        "parse_fail": "Scan failed: {e}",
        "building": "Building…",
        "build_done": "Built: {p}",
        "build_fail": "Build failed: {e}",
        "installing": "Installing…",
        "install_done": "Installed: {p}\nYou can now check it in-game.",
        "install_fail": "Install failed: {e}",
        "restore_done": "Game files restored.",
        "no_records": "Nothing to restore.",
        "confirm_install": "This will copy the MOD three-piece into the game's Paks folder:\n  {p}\n\nDelete those three files to revert. Continue?",
"confirm_restore": "Restore game files to their original state?",
        "err_no_game": "Could not locate the game from the given path.\nPlease set the game folder (containing the FFRS folder), or the Paks folder directly.",
        "game_dir": "Game folder (contains FFRS)",
        "tools": "External tools",
        "ffmpeg": "ffmpeg.exe",
        "cricodecs": "cricodecs.exe",
        "check": "Check tools",
        "tool_ok": "OK",
        "tool_missing": "missing",
        "check_bad_names": "These tool paths are invalid: {names}\nPlease re-specify them.",
        "check_ok": "All tool paths are valid.",
        "check_bad": "Some tool paths are invalid.",
        "log": "Log",
        "restore_all": "Revert all",
        "restore_sel": "Revert selected",
        "restore_pick": "Select a movie to revert",
        "restore_none": "(nothing)",
        "restore_ok": "Reverted: {p}",
        "restore_none_sel": "Pick a movie in the dropdown first.",
        "installed_n": "{n} installed",
        "build_align": "Matched to original: {n} frames = {os}s",
        "build_nometa": "WARN: cannot read replacement info; check the file plays normally.",
        "orig_none": "no original",
        "new_none": "no replacement",
        "preview_loading": "(extracting preview...)",
        # —— batch install ——
        "batch_btn": "Install selected...",
        "batch_title": "Choose MODs to install",
        "batch_mods_dir": "MOD folder",
        "batch_scan": "Scan / refresh",
        "batch_col_movie": "Movie (in game)",
        "batch_col_mod": "MOD file",
        "batch_col_state": "Status",
        "batch_install_all": "Install all",
        "batch_install_sel": "Install selected",
        "batch_close": "Close",
        "batch_st_ready": "Ready",
        "batch_st_installed": "Installed",
        "batch_st_none": "-",
        "batch_st_orphan": "no matching movie",
        "batch_st_dup": "duplicate MOD name",
        "batch_st_bad": "movie missing",
        "batch_scanning": "Scanning the game's movie list...",
        "batch_summary": "Installable MODs: {n}",
        "batch_extra": "  ({o} MOD(s) match no movie in this game, {d} name collision(s) - not listed above)",
        "batch_none_sel": "Select the movies you want to install first.",
        "batch_confirm_all": "Install all {n} MOD(s) in the list?",
        "batch_confirm_sel": "Install the {n} selected MOD(s)?",
        "batch_done": "Batch install finished: {n} succeeded",
        "batch_fail": "Failed {p}: {e}",
        "batch_tip": "Only movies that actually exist in the game are listed. Installing copies the MOD into Content/Streams/Movies/... and redirects that movie's MoviePath to it. Delete a MOD file to drop it from the list. To revert, use Revert all / Revert selected on the main window.",
        "batch_mods_missing": "MOD folder not found:\n{p}\nUse Browse to pick the folder holding your MODs.",
        "batch_nothing": "No MOD in\n{p}\nmatches a movie of this game.\nMake sure the file names look like MV_xxxx_mod.usm.",
        # —— mode switch ——
        "mode_lbl": "Mode",
        "mode_simple": "Simple",
        "mode_full": "MOD maker",
        "mod_dir": "MOD folder",
        "game_paks": "Game folder (or Paks folder)",
        "btn_install_all": "Install all",
        "simple_tip": "How to use:\n"
                      "1) Point \"MOD folder\" at the folder holding the MODs.\n"
                      "2) Point \"Game folder\" at the game root (the one containing the FFRS folder).\n"
                      "3) \"Install all / Install selected\" installs every MOD in that folder / only the ones you pick.\n"
                      "4) \"Revert all / Revert selected\" uninstalls all installed MODs / only the ones you pick.\n"
                      "\n"
                      "To create MODs yourself, switch the top-left dropdown to \"MOD maker\".",
        "langname": "English",
        # —— comparison panel ——
        "info_title": "Comparison & warnings",
        "info_hint": "Press Parse; differences between the two videos and how to handle them will show here.",
        "info_orig": "Original",
        "info_new": "Replacement",
        "info_line": "{w}x{h}   {fps} fps   {n} frames   {s}s",
        "info_na": "info unavailable",
        "info_all_ok": "OK - resolution / frame rate / length all match. Ready to build.",
        "info_fps_bad": "- Frame rate differs ({a} -> {b} fps): the tool re-encodes at the original rate automatically; nothing for you to do.",
        "info_res_bad": "- Resolution differs ({a} -> {b}): the tool scales to the original automatically; nothing for you to do.",
        "info_long": "WARNING: replacement is LONGER ({ns}s vs {os}s). The in-game playback window only lasts as long as the original, so the extra part is cut off.\n      Trim the replacement to {os}s or less before importing.",
        "info_short": "WARNING: replacement is SHORTER ({ns}s vs {os}s). The game loops it to fill the original length.\n      To play it once only, pad it to about {os}s.",
        # —— audio replacement ——
        "audio_src": "Audio to import",
        "lbl_audio_sel": "Replace audio",
        "audio_none": "(do not replace audio)",
        "audio_none_found": "(no paired audio found for this movie)",
        "audio_extracting": "First run: extracting bank {bank} from the game container...",
        "audio_streaming": "Bank {bank} is a streaming (pak) bank; not supported in this version.",
        "audio_need_src": "An audio target is selected but no audio file was imported.",
        "audio_need_target": "An audio file was imported but no audio target is selected.",
        "audio_index_ok": "Audio index: {m} movies have paired audio, {b} banks.",
        # —— info panel (audio) ——
        "info_audio_orig": "Orig audio",
        "info_audio_new": "New audio",
        "info_audio_line": "{s}s   {cue}({bank} entry {e})",
        "info_audio_unknown": "not enough info",
        "info_audio_nofile": "(not selected)",
        "info_audio_long": "WARNING: replacement audio is LONGER ({ns}s vs {os}s); the extra part is cut off.",
        "info_audio_short": "WARNING: replacement audio is SHORTER ({ns}s vs {os}s); the rest will be silent.",
        "info_audio_sync": "WARNING: replacement audio ({ns}s) differs from the movie length ({vs}s) by {d}s - audio/video may drift.",
        "info_audio_sync_ok": "OK - replacement audio roughly matches the movie length.",
        "audio_working": "Preparing audio patch: {bank} entry {e} ...",
        "audio_build_done": "Audio patch built: {p}",
        "audio_installed": "Audio patch installed: {p}",
        "audio_install_hint": "The audio patch overwrites the whole bank.\nDo not install another MOD that modifies the same bank.\n\nContinue?",
        "audio_restored": "Audio patch removed ({n} files).",
        "audio_conflict": "WARNING: a third-party patch {p} already exists in the game Paks. The bank baseline may already be modified. Remove it first.",
        "info_audio_at": "In-game target",
        "audio_no_list": "(no audio path selected)",
        "audio_gain": "Volume",
        "audio_gain_auto": "match original",
        "audio_gain_boost": "match {db} dB",
        "audio_gain_none": "leave as-is",
        "info_audio_whole": "whole voice bank {bank} ({n} lines); spreads the {m} imported files in filename order",
        "audio_skip": "do not replace",
        "audio_skip_note": "audio not replaced (video only)",
        # —— Vision Shrine Voice Tool ——
        "mode_vision": "Vision Shrine Voice Tool",
        "vis_grp_src": "Paths",
        "vis_src": "Audio to import",
        "vis_out": "Output folder",
        "vis_scan": "Scan / refresh",
        "vis_grp_list": "Vision narration (in game)",
        "vis_col_ingame": "Audio (in game)",
        "vis_col_import": "Import audio",
        "vis_btn_audition": "Preview",
        "vis_btn_build": "Build MOD",
        "vis_btn_install": "Install to game",
        "vis_btn_restore": "Restore all",
        "vis_skip": "(do not replace)",
        "vis_tip_head": "Notes:",
        "vis_tip_1": "1) This tool only replaces the narration of a vision's flashback. If no vision flashback was found in \"MOD Edit\", this tool is unavailable.",
        "vis_tip_2": "2) Each row can pick a file from the \"Audio to import\" folder to replace that line; pick \"(do not replace)\" to keep it as is.",
        "vis_tip_3": "3) The built patch overwrites the whole voice bank (tens of MB); do not mix with other mods of the same bank.",
        "vis_tip_4": "4) You must have scanned the vision flashback movies in \"MOD Edit\" first, so this tool knows which vision to work on.",
        "vis_tip_5": "5) This tool uses the same external tools as \"MOD Edit\" (game folder / ffmpeg / cricodecs / retoc). If any of those paths change, go back to the \"MOD Edit\" screen to update them.",
        "vis_unavailable": "No vision flashback found - this tool is currently unavailable.",
        "vis_scanning": "Scanning for vision flashbacks...",
        "vis_found": "Found {n} vision(s): {v}",
        "vis_none": "No vision flashback was found in \"MOD Edit\".",
        "vis_need_src": "Please specify the \"Audio to import\" folder first.",
        "vis_nothing": "Every row is \"(do not replace)\" - nothing to build.",
        "vis_building": "Building audio patch...",
        "vis_built": "Audio patch built: {p}",
        "vis_restored": "Audio patch removed ({n} files).",
        "vis_preview_prep": "Preparing preview cache: {bank} ...",
        "vis_preview_ok": "Preview cache ready: {bank} ({n} lines)",
        "vis_play_fail": "Preview failed: {e}",
        "vis_entries": "{bank}: {n} narration lines",
        "tool_ffmpeg": "ffmpeg.exe",
        "tool_cricodecs": "cricodecs.exe",
        "tool_path_empty": "(empty)",
        "tool_path_bad": "Invalid tool path: {label} = {p}",
        "tool_path_hint": "Re-specify ffmpeg / cricodecs / retoc under \"External tools\" on the \"MOD Edit\" screen, then click \"Check tools\".",
        "build_cleaned": "Cleaned intermediate file: {p} (already packed into the pak)",
        "build_clean_fail": "Could not clean intermediate file: {p} ({e})",
        "movie_patch_done": "Movie patch container built: {p}",
        "no_patch": "No MOD built yet (click \"Build MOD\" first)",
        "retoc": "retoc.exe (for audio patches)",
        "repak": "repak.exe (for movie packing)",
        "confirm_overwrite": "A MOD with the same name is already installed: {p}.\nOverwrite it?",
        "base_view_fail": "Note: could not build a base-container view (different disk?). Extracting from Paks directly; if an audio MOD is installed, the extracted bank may already be modified.",
        "grp_merge": "MOD merge (optional)",
        "merge_path": "MOD to merge",
        "merge_bad": "Invalid MOD path to merge: {p}",
        "merge_done": "Merged the other MOD into the container: {p}",
    },
}


def t(key: str, **kw) -> str:
    s = STRINGS[App.LANG].get(key, key)
    return s.format(**kw) if kw else s


# ──────────────────────────── 外部工具 ────────────────────────────
def run(cmd, cwd=None, timeout=3600):
    p = subprocess.run([str(c) for c in cmd], cwd=str(cwd) if cwd else None,
                       capture_output=True, timeout=timeout,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    return p.returncode, (p.stdout or b"").decode("utf-8", "replace"), (p.stderr or b"").decode("utf-8", "replace")


def probe(path: Path) -> dict | None:
    """用 ffmpeg 读取视频参数。"""
    try:
        rc, out, err = run([App.FFMPEG, "-hide_banner", "-i", path], timeout=60)
    except Exception:
        return None
    txt = err + out
    info = {}
    m = re.search(r"Stream #\d+:\d+.*?: Video: (\w+).*?, (\d{2,5})x(\d{2,5})", txt)
    if m:
        info["codec"], info["w"], info["h"] = m.group(1), int(m.group(2)), int(m.group(3))
    m = (re.search(r"(\d+(?:\.\d+)?) fps", txt)
         or re.search(r"(\d+(?:\.\d+)?) tbr", txt)
         or re.search(r"(\d+(?:\.\d+)?) tbn", txt))
    if m:
        info["fps"] = float(m.group(1))
    m = re.search(r"Duration: (\d+):(\d+):(\d+\.\d+)", txt)
    if m:
        info["duration"] = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))
    if "fps" in info and "duration" in info:
        info["frames"] = int(round(info["fps"] * info["duration"]))
    return info or None


def count_frames(path: Path) -> int | None:
    try:
        rc, out, err = run([App.FFMPEG, "-hide_banner", "-i", path, "-f", "null", "-"], timeout=900)
    except Exception:
        return None
    ms = re.findall(r"frame=\s*(\d+)", err + out)
    return int(ms[-1]) if ms else None


# ──────────────────────────── USM 解析 ────────────────────────────


def _work_root() -> Path:
    """cricodecs/ffmpeg 的工作目录。放工具目录下，别用 %TEMP%（实测在部分机器上写不出文件）。"""
    try:
        import kit.settings as _K4
        d = _K4.temp_root() / "work"
    except Exception:
        d = APP_DIR / "save" / "_temp" / "work"
    d.mkdir(parents=True, exist_ok=True)
    return d

def parse_usm(path: Path) -> dict | None:
    """读取 USM 的关键参数：分辨率 / 帧率 / 帧数 / 是否含 alpha。"""
    try:
        with path.open("rb") as f:
            head = f.read(0x4000)
    except Exception:
        return None
    if head[:4] != b"CRID":
        return None
    info = {"path": path, "size": path.stat().st_size,
            "has_alpha": False, "has_audio": False}
    d = path.read_bytes() if path.stat().st_size < 64 << 20 else head
    info["has_alpha"] = b"@ALP" in head
    info["has_audio"] = b"@SFA" in head
    # 用 cricodecs 读流信息（对标准格式有效）
    try:
        rc, out, err = run([App.CRICODECS, path, "-m"], timeout=120)
        t_ = out
        if "stream_count" in t_:
            info["streams"] = len(re.findall(r"type:\s*@", t_))
        sizes = re.findall(r"type:\s*(@\w+)\n\s+channel:\s*\d+\n(?:[^\n]*\n)*?\s*file_size:\s*(\d+)", t_)
        if not sizes:
            # 退化解析
            blk = t_.split("streams:")[-1]
            for part in blk.split("- index:")[1:]:
                mt = re.search(r"type:\s*(@\w+)", part)
                mf = re.search(r"file_size:\s*(\d+)", part)
                if mt and mf:
                    sizes.append((mt.group(1), mf.group(1)))
        info["stream_sizes"] = {k: int(v) for k, v in sizes}
    except Exception:
        pass
    # 从视频流的 IVF 头或 keyframe 推分辨率/帧率
    kf = head.find(b"\x82\x49\x83\x42")
    if kf >= 0 and kf + 10 <= len(head):
        bits = "".join(f"{b:08b}" for b in head[kf + 4:kf + 10])
        try:
            info["w"] = int(bits[3:15], 2) + 1
            info["h"] = int(bits[15:27], 2) + 1
        except Exception:
            pass
    ivf = head.find(b"DKIF")
    if ivf >= 0 and ivf + 28 <= len(head):
        w, h = struct.unpack_from("<HH", head, ivf + 12)
        rn, rd, fc = struct.unpack_from("<III", head, ivf + 16)
        if w and h:
            info["w"], info["h"] = w, h
        if rd:
            info["fps"] = rn / rd
        if fc:
            info["frames"] = fc
    return info


# ──────────────────────────── 预览帧 ────────────────────────────
def grab_frames(src: Path, outdir: Path, n: int = 24, scale: int = 480) -> list[Path]:
    """
    抽 n 帧做预览。

    ⚠ 采样率必须按**整片时长**算：早先写死 fps=6 配 -frames:v 24，等于永远只取开头 4 秒——
    召唤片才 8 秒还看不太出来，但 Event 的片子有两分多钟（MV_Opening 142 秒），
    那样只预览到开头 3%，看不出替换效果。
    """
    outdir.mkdir(parents=True, exist_ok=True)
    for f in outdir.glob("f_*.png"):
        f.unlink(missing_ok=True)
    dur = (probe(src) or {}).get("duration")
    if dur and dur > 0:
        rate = max(0.02, min(float(n) / float(dur), 30.0))     # 均匀铺满全片
        vf = f"fps={rate:.6f},scale={scale}:-2"
    else:
        vf = f"fps=6,scale={scale}:-2"                          # 读不出时长就退回旧行为
    run([App.FFMPEG, "-y", "-hide_banner", "-loglevel", "error", "-i", src,
         "-vf", vf, "-frames:v", str(n), outdir / "f_%03d.png"], timeout=900)
    return sorted(outdir.glob("f_*.png"))


# ──────────────────────────── 构建 USM ────────────────────────────
def build_usm(video: Path, out_usm: Path, ref: dict, log) -> bool:
    """按 ref（原 USM 参数）对齐地把 video 封成 USM。"""
    # ★ ffmpeg 要在这里写 video.ivf / alpha.m2v；%TEMP% 在部分机器上写不出文件（Permission denied）
    try:
        import uuid as _uuid
        work = _work_root() / f"usm_{_uuid.uuid4().hex[:8]}"
        work.mkdir(parents=True, exist_ok=True)
    except Exception:
        work = Path(tempfile.mkdtemp(prefix="ffrs_vmod_"))
    try:
        w, h, fps = ref.get("w", 1920), ref.get("h", 1080), ref.get("fps", 30) or 30
        frames = ref.get("frames")
        ivf = work / "video.ivf"
        # 视频时长/帧数必须与原片对齐，否则游戏内音频会与画面不同步
        cmd = [App.FFMPEG, "-y", "-hide_banner", "-loglevel", "error"]
        if frames:
            cmd += ["-stream_loop", "-1"]          # 不足则循环素材
        cmd += ["-i", video]
        if frames:
            cmd += ["-frames:v", str(int(frames))]
        # -r 必须显式给：否则输出会沿用源视频的帧率，而游戏侧固定按原片帧率(30)播，
        # 于是非 30fps 的素材时长会整体偏掉，还会与 30fps 的 alpha 流不同步。
        cmd += ["-r", str(fps)]
        cmd += ["-an", "-c:v", "libvpx-vp9", "-pix_fmt", "yuv420p",
                "-colorspace", "smpte170m", "-b:v", "2500k", "-g", "60",
                "-deadline", "good", "-cpu-used", "4", "-row-mt", "1",
                "-vf", f"scale={w}:{h}", "-f", "ivf", ivf]
        log(f"ffmpeg: 编码视频 {w}x{h} @{fps}fps")
        rc, o, e = run(cmd)
        if rc != 0 or not ivf.exists():
            log(e[-1500:]); return False

        args = [App.CRICODECS, "--build", "-f", "usm", ivf]
        if ref.get("has_alpha"):
            asfv = work / "alpha.sfv"
            # ★ 从素材自身的 alpha 通道生成（白=不透明）；素材没有 alpha 时才退回全白
            def _alpha_cmd(decoder_args=None):
                c = [App.FFMPEG, "-y", "-hide_banner", "-loglevel", "error"]
                if decoder_args:
                    c += decoder_args
                if frames:
                    c += ["-stream_loop", "-1"]
                c += ["-i", video]
                c += ["-vf", f"alphaextract,scale={w}:{h},fps={fps}"]
                if frames:
                    c += ["-frames:v", str(int(frames))]
                c += ["-an", "-c:v", "mpeg1video", "-pix_fmt", "yuv420p",
                      "-b:v", "40M", "-g", "12", "-f", "mpeg1video", asfv]
                return c
            rc, o, e = run(_alpha_cmd())
            if rc != 0 or not asfv.exists():
                # WebM/VP9 的 alpha 需要 libvpx 解码器才会被 alphaextract 读到
                if str(video).lower().endswith((".webm", ".ivf", ".mkv")):
                    rc, o, e = run(_alpha_cmd(["-c:v", "libvpx-vp9"]))
            if rc == 0 and asfv.exists():
                log("ffmpeg: 已从素材 alpha 通道生成 @ALP 流（保持透明）")
                args += ["--alpha", asfv]
            else:
                log("ffmpeg: 素材没有可用 alpha，退回全白（不透明）")
                acmd = [App.FFMPEG, "-y", "-hide_banner", "-loglevel", "error",
                        "-f", "lavfi", "-i", f"color=c=white:s={w}x{h}:r={fps}"]
                if frames:
                    acmd += ["-frames:v", str(int(frames))]
                acmd += ["-an", "-c:v", "mpeg1video", "-pix_fmt", "yuv420p",
                         "-b:v", "40M", "-g", "12", "-f", "mpeg1video", asfv]
                rc2, o2, e2 = run(acmd)
                if rc2 == 0 and asfv.exists():
                    args += ["--alpha", asfv]
        args += ["-o", out_usm]
        rc, o, e = run(args, timeout=1800)
        if rc != 0 or not out_usm.exists() or out_usm.stat().st_size == 0:
            log(e[-1500:]); return False
        log(f"cricodecs: 已生成 {out_usm.name} ({out_usm.stat().st_size:,} 字节)")
        return True
    finally:
        if not App.KEEP_TEMP:
            shutil.rmtree(work, ignore_errors=True)


# ──────────────────────────── 安装器 ────────────────────────────
# ManaMovie uexp 记录里紧跟固定 8 字节标记之后就是 FString MoviePath
HEAD_MARK = b"\x01\x06\x05\x04\x01\x02\x01\x03"
# ucas 里所有影片都长这样：Movies/<目录>/<名字>.usm
MOVIE_RE = re.compile(rb"Movies/([A-Za-z0-9_/]+\.usm)")


class Installer:
    """
    安装 = ① 把 USM 放进 <Game>/FFRS/Content/Streams/Movies/…/
           ② 把该影片的 MoviePath 重定向到一个 pak 外的新名字（等长替换 ucas 里的字符串）
    全部可还原（备份 ucas 的原始字节 + 记录状态）。
    """

    def __init__(self, game_root: Path, state: Path):
        self.root = game_root
        self.ucas = game_root / "FFRS/Content/Paks/FFRS-Windows.ucas"
        self.streams = game_root / "FFRS/Content/Streams"
        self.state_file = state

    def _load(self) -> dict:
        if not self.state_file.exists():
            return {}
        try:
            d = json.loads(self.state_file.read_text(encoding="utf-8"))
        except Exception:
            return {}
        # 旧格式迁移：{offset: {...}, "active":..., "movie_rel":...} -> {movie_rel: {...}}
        if "active" in d or "movie_rel" in d:
            old = {k: v for k, v in d.items() if isinstance(v, dict) and "offset" in v}
            mr = d.get("movie_rel")
            if mr and old:
                base = mr.split("/")[-1]
                alias = self._alias(base)
                d = {mr: {
                    "offsets": [v["offset"] for v in old.values()],
                    "orig": list(old.values())[0]["orig"],
                    "new": d.get("active", ""),
                    "dest": str(self.streams / "Movies" / mr.rsplit("/", 1)[0] / f"{alias}.usm"),
                }}
                self._save(d)
            else:
                d = {}
        return d

    def _save(self, s: dict) -> None:
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        self.state_file.write_text(json.dumps(s, ensure_ascii=False, indent=2), encoding="utf-8")

    def _read_at(self, off: int, n: int) -> bytes:
        with self.ucas.open("rb") as f:
            f.seek(off); return f.read(n)

    def _write_at(self, off: int, data: bytes) -> None:
        with self.ucas.open("r+b") as f:
            f.seek(off); f.write(data); f.flush(); os.fsync(f.fileno())

    def _find(self, needle: bytes) -> list[int]:
        hits, off, prev = [], 0, b""
        CH = 64 << 20
        with self.ucas.open("rb") as f:
            while True:
                b = f.read(CH)
                if not b:
                    break
                data = prev + b
                base = off - len(prev)
                i = data.find(needle)
                while i != -1:
                    hits.append(base + i)
                    i = data.find(needle, i + 1)
                prev = data[-len(needle):]
                off += len(b)
        return hits

    def _find_multi(self, needles: list[bytes]) -> dict[bytes, list[int]]:
        """一趟扫完 ucas，同时查找多个模式（ucas 有 4.4 GB，每多一趟多 ~2.7s）。"""
        needles = list(dict.fromkeys(needles))
        out = {n: [] for n in needles}
        mx = max(len(n) for n in needles)
        off, prev = 0, b""
        CH = 64 << 20
        with self.ucas.open("rb") as f:
            while True:
                b = f.read(CH)
                if not b:
                    break
                data = prev + b
                base = off - len(prev)
                for n in needles:
                    i = data.find(n)
                    while i != -1:
                        out[n].append(base + i)
                        i = data.find(n, i + 1)
                prev = data[-mx:]
                off += len(b)
        return out

    def find_moviepath(self, movie_name: str) -> list[int]:
        """在 ucas 里定位形如 Movies/<...>/<movie>_vp9.usm 的字符串（返回偏移表）。"""
        if "/" not in movie_name:
            return []
        return self._find(f"Movies/{movie_name}.usm".encode())

    def _frame_bases(self, movie_rel: str) -> list[tuple[int, int]]:
        """
        定位该影片 uexp 记录的起点，返回 [(头部标记偏移, path 字符串长度), ...]。

        ① 用原始 MoviePath 字符串定位；
        ② 用本工具生成的别名、以及 state 里记录的当前路径定位
           （**必须支持这一条**：mod 已安装时 ucas 里的路径已经不是原名了，
             只用原名去找会一无所获 —— 这正是之前"找不到帧数字段"的原因）；
        ③ 兜底：用固定头部字节 01 06 05 04 01 02 01 03 + 合法 .usm FString 定位。
        """
        cands = [f"Movies/{movie_rel}.usm"]
        rel_dir, _, base = movie_rel.rpartition("/")
        if base:
            try:
                cands.append(f"Movies/{rel_dir}/{self._alias(base)}.usm")
            except Exception:
                pass
        rec = self._load().get(movie_rel)
        if isinstance(rec, dict):
            for k in ("new", "orig"):
                if rec.get(k):
                    cands.append(str(rec[k]))

        cands = list(dict.fromkeys(cands))
        bases, seen = [], set()
        found = self._find_multi([c.encode() for c in cands])
        for s in cands:
            exp_len = len(s)
            for p in found.get(s.encode(), []):     # p = 路径字符串起点
                m = p - 12                          # 8 字节标记 + i32 长度前缀
                if m in seen or m < 12:
                    continue
                l = struct.unpack_from("<i", self._read_at(m + 8, 4), 0)[0]
                if l != exp_len + 1:                # 长度前缀必须自洽
                    continue
                seen.add(m); bases.append((m, exp_len))
        if bases:
            return bases

        for m in self._find(HEAD_MARK):             # ③ 固定头部字节兜底
            l = struct.unpack_from("<i", self._read_at(m + 8, 4), 0)[0]
            if not (0 < l < 128):
                continue
            s = self._read_at(m + 12, l - 1)
            if not s.endswith(b".usm") or not all(32 <= c < 127 for c in s):
                continue
            # 认领的路径必须与目标影片同名或同名别名, 否则可能是别的影片
            got = s.decode().rsplit("/", 1)[-1][:-4]
            if base and got not in (base, self._alias(base)):
                continue
            seen.add(m); bases.append((m, l - 1))
        return bases

    @staticmethod
    def _is_parent_uexp(seg: bytes) -> bool:
        """
        校验一段 90 字节是否符合父资产（PlatformManaMovie）uexp 的结构：
          0 ..9   [前导 10 字节]
         10 ..13  VideoTracks 数组长度 = 1
         14 ..40  第 1 条 ManaVideoTrackInfo（27 字节）
         41       [1 字节]
         42 ..45  AlphaTracks 数组长度 = 1
         46 ..72  第 2 条 ManaVideoTrackInfo
         ...
        第 1 条轨道：+14 起 → 尺寸 X 在 +17、Y 在 +21、DisplayX +25、DisplayY +29、
                     fps +33、TotalFrames +37。
        第 2 条轨道：+46 起 → fps +65、TotalFrames +69。
        """
        if len(seg) < 90:
            return False
        u32 = lambda o: struct.unpack_from("<I", seg, o)[0]
        f32 = lambda o: struct.unpack_from("<f", seg, o)[0]
        dx, dy = u32(17), u32(21)
        if not (0 < dx < 20000 and 0 < dy < 20000):
            return False
        if u32(25) != dx or u32(29) != dy:       # DisplayDimensions == TextureDimensions
            return False
        if u32(10) != 1 or u32(42) != 1:         # 两条轨道的数组长度都必须是 1
            return False
        f1, f2 = f32(33), f32(65)
        if not (10.0 <= f1 <= 120.0 and abs(f1 - f2) < 0.01):
            return False
        a, b = u32(37), u32(69)
        return a == b and 1 <= a <= 500000

    def _find_parent_frames(self, movie_rel: str, log=None) -> list[int]:
        """
        定位 **父资产**（`MV_xxx`，PlatformManaMovie）里的 TotalFrames。

        每部影片在 ucas 里有 4 个 TotalFrames：子资产 `MV_xxx_vp9` 的
        VideoTracks/AlphaTracks，以及父资产 `MV_xxx` 的 VideoTracks/AlphaTracks。
        父资产没有 FilePath 属性（靠 ManaMovie 对象引用指向子资产）。
        游戏数据表引用的是父资产，因此不改父资产，帧数改动可能完全看不到。

        定位方式：父资产的 **包路径**（`/Game/Movies/<rel 去掉 _vp9>`）出现在它 uexp
        之前的 uasset 里，从该处向后在有限窗口内做结构校验。**只在窗口内取值**，
        避免命中同分辨率同帧率的其它影片（那是会写坏别人数据的）。
        """
        base_name = movie_rel.rsplit("/", 1)[-1]
        if not base_name.endswith("_vp9"):
            return []                                  # 命名不符合约定 → 不动父资产
        parent_pkg = "/Game/Movies/" + movie_rel[:-4]
        out = []
        for hit in self._find(parent_pkg.encode()):
            # 每个锚点只取**紧邻其后**的第一个合法 uexp：窗口开大会抓到相邻影片的父资产
            win = self._read_at(hit, 1024)
            for off in range(0, max(0, len(win) - 90)):
                if self._is_parent_uexp(win[off:off + 90]):
                    start = hit + off
                    out += [start + 37, start + 69]
                    break
        return sorted(set(out))

    def find_frames_offsets(self, movie_rel: str) -> list[int]:
        """
        定位该影片 uexp 里"帧数"字段(u32)的绝对偏移。
        uexp 结构：[8字节标记][i32 len][FString MoviePath][...][u32 w][u32 h][f32 fps][u32 frames]
        以头部标记为原点：fps 在 36+len(path)、frames 在 40+len(path)；
        双流(带 alpha)影片有 2 组，第二组整体后移 32 字节 —— 两组都要改，
        否则 alpha 流与视频流帧数不一致。
        """
        offs = []
        for m, plen in self._frame_bases(movie_rel):
            seg = self._read_at(m, 512)
            canon = 40 + plen                       # ① 按结构推算的 frames 偏移
            fps_b = None
            if canon + 4 <= len(seg):
                fps = struct.unpack_from("<f", seg, canon - 4)[0]
                n = struct.unpack_from("<I", seg, canon)[0]
                if 10.0 <= fps <= 120.0 and 1 <= n <= 500000:
                    fps_b = seg[canon - 4:canon]
            if fps_b is None:                       # ② 在期望位置附近回退扫描 [fps][frames]
                lo = max(16, canon - 16)
                hi = min(len(seg) - 8, canon + 64)
                for i in range(lo, hi):
                    fps = struct.unpack_from("<f", seg, i)[0]
                    if 10.0 <= fps <= 120.0 and abs(fps - round(fps)) < 0.02:
                        n = struct.unpack_from("<I", seg, i + 4)[0]
                        if 1 <= n <= 500000:
                            fps_b = seg[i:i + 4]
                            break
            if fps_b is None:
                continue
            # ③ 用"相同的 fps 浮点字节"作为锚, 找出该记录里所有帧数字段（含第二条流）。
            #    窗口必须收紧：每条 uexp 记录里第一条流在 canon，第二条流紧跟其后
            #    （实测 +32 字节）。窗口放大会误抓相邻记录的帧数。
            lo, hi = max(0, canon - 8), min(len(seg), canon + 96)
            i = seg.find(fps_b, lo)
            while i != -1 and i < hi:
                if i + 8 <= len(seg):
                    n = struct.unpack_from("<I", seg, i + 4)[0]
                    if 1 <= n <= 500000:
                        offs.append(m + i + 4)
                i = seg.find(fps_b, i + 1)
        # ④ 父资产（PlatformManaMovie）里的两个 TotalFrames 也要一起改
        offs += self._find_parent_frames(movie_rel)
        return sorted(set(offs))
        return sorted(set(offs))

    def install(self, usm: Path, movie_rel: str, log, frames: int | None = None,
                hits: list | None = None) -> Path:
        """movie_rel 形如 'Summon/MV_summon300010_vp9'（相对 Movies/）。
        hits = 已知的 MoviePath 偏移（批量安装时由 scan_movie_paths() 一次算好传进来，省掉每部一次全盘扫描）。"""
        if not self.ucas.exists():
            raise RuntimeError(f"未找到 {self.ucas}")
        orig = f"Movies/{movie_rel}.usm"
        base = movie_rel.split("/")[-1]
        alias = self._alias(base)
        new = f"Movies/{movie_rel.rsplit('/',1)[0]}/{alias}.usm"
        assert len(new) == len(orig), (len(new), len(orig))
        st = self._load()
        rec = st.get(movie_rel) or {}

        if hits is None:
            # 未装过：原路径还在；已装过：现在 ucas 里是别名
            found = self._find_multi([orig.encode(), new.encode()])
            hits = found.get(orig.encode(), []) or found.get(new.encode(), [])
            if not hits and rec.get("offsets"):         # 再退一步：复用上次记录的偏移
                hits = [int(o) for o in rec["offsets"]]
        hits = [int(o) for o in (hits or [])]
        if not hits:
            raise RuntimeError(
                f"ucas 中未找到 MoviePath: {orig}\n"
                f"  可能原因：① 这部影片在游戏里不是 ManaMovie 资产（没有 FilePath），无法用本方式替换；"
                f"② 选错了文件（请选 .usm 原片，不要选解出来的 .ivf/.m2v）；"
                f"③ 该影片的文件名不在 ucas 里，试试同目录下的其它 .usm。")

        # ① 定位帧数字段（重装时保留首次记录的"原始帧数"，否则还原会还原成上一次的新值）
        foffs, folds = [], []
        if frames:
            foffs = self.find_frames_offsets(movie_rel)
            if rec.get("frames_orig") and len(rec["frames_orig"]) == len(foffs):
                folds = [int(v) for v in rec["frames_orig"]]
            else:
                folds = [struct.unpack_from("<I", self._read_at(o, 4), 0)[0] for o in foffs]

        # ② 改写 MoviePath（等长）
        for h in hits:
            self._write_at(h, new.encode())

        # ③ 改写帧数
        if frames and foffs:
            for o in foffs:
                self._write_at(o, struct.pack("<I", int(frames)))
            log(f"帧数: {folds} -> {int(frames)}  (共 {len(foffs)} 处)")
        elif frames:
            log("警告：未定位到 uexp 中的帧数字段，时长未改（仍按原片时长）")

        # ④ 落地 USM
        dest_dir = self.streams / "Movies" / movie_rel.rsplit("/", 1)[0]
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / f"{alias}.usm"
        shutil.copy2(usm, dest)

        st[movie_rel] = {"offsets": hits, "orig": orig, "new": new, "dest": str(dest),
                         "frames_offsets": foffs, "frames_orig": folds}
        self._save(st)
        log(f"已写入 {dest}")
        log(f"MoviePath: {orig}  ->  {new}")
        return dest

    def scan_movie_paths(self) -> dict:
        """
        一趟扫完 ucas，返回 {相对路径(不含 .usm): [该路径字符串的所有绝对偏移]}。

        为什么以 ucas 为准而不是扫 Export 目录：
          * 只有 ucas 里存在 MoviePath 的影片才能被重定向 —— 这份清单天然就是"可安装集合"
          * Export 目录常常不全（实测：`Skill/MV_Skill440010_vp9` 有资产但没导出）
        时间：约 3 秒（4.4 GB 扫一遍）。批量安装时只扫这一次，把偏移直接传给 install()。
        """
        out, CH, prev = {}, 64 << 20, b""
        mx = 48
        with self.ucas.open("rb") as f:
            off = 0
            while True:
                b = f.read(CH)
                if not b:
                    break
                base = off - len(prev)
                buf = prev + b
                for m in MOVIE_RE.finditer(buf):
                    rel = m.group(1).decode()[:-4]
                    # 已安装过的影片，ucas 里存的是别名（MZ_xxx）；还原成原名，
                    # 否则装完之后这份清单会"认不出"它，MOD 全变成找不到对应原片。
                    d, _, name = rel.rpartition("/")
                    name = self._un_alias(name)
                    rel = f"{d}/{name}" if d else name
                    out.setdefault(rel, []).append(base + m.start())
                prev = buf[-mx:] if len(buf) > mx else buf
                off += len(b)
        return out

    @staticmethod
    def _un_alias(base: str) -> str:
        """把别名还原成原名（_alias 的逆）：MZ_xxx -> MV_xxx。"""
        if len(base) >= 3 and base[:3] == "MZ_":
            return "MV_" + base[3:]
        return base

    def list_movie_paths(self) -> list[str]:
        return sorted(self.scan_movie_paths())

    @staticmethod
    def _alias(base: str) -> str:
        """
        生成**等长**别名。

        长度必须与原名完全一致 —— 我们要把 uexp 里的 MoviePath 字符串就地改写，
        长度一变就会破坏 IoStore 结构。所以这里只能做"等长替换"，不能插入字符。
        规则：前 3 字符 "MV_" -> "MZ_"；不以 "MV_" 开头则把首字符换成 "Z"（已是 Z 则换 Y）。
        对任意片名都成立，且新名不会与 pak 内已有名字冲突。
        """
        if len(base) >= 3 and base[:3] == "MV_":
            return "MZ_" + base[3:]
        if len(base) >= 1:
            return ("Z" if base[0] != "Z" else "Y") + base[1:]
        return base

    def list_installed(self) -> dict:
        return {k: v for k, v in self._load().items() if isinstance(v, dict) and "offsets" in v}

    def restore(self, log, only: str | None = None) -> int:
        """还原 ucas 中的 MoviePath 与落地文件。only=None 时全部还原。"""
        st = self._load()
        recs = self.list_installed()
        if not recs:
            raise RuntimeError("no-records")
        targets = [only] if only else list(recs)
        n = 0
        for m in targets:
            rec = recs.get(m)
            if not rec:
                continue
            for h in rec["offsets"]:
                self._write_at(int(h), rec["orig"].encode())
            for o, v in zip(rec.get("frames_offsets", []), rec.get("frames_orig", [])):
                self._write_at(int(o), struct.pack("<I", int(v)))
            d = Path(rec["dest"])
            if d.exists():
                d.unlink()
                log(f"已删除 {d}")
            st.pop(m, None)
            n += 1
            log(f"已还原 {m}")
        self._save(st)
        log(f"共还原 {n} 部影片")
        return n


# ──────────────────────────── 音频替换 ────────────────────────────
#
# 影片本身【不含音频】。音效是 CRIWARE 音库里独立的一条，由播放该影片的
# LevelSequence 桥段在同一时间点触发（桥段里画面轨与声音轨共现）。
# 影片 → 音频条目的对应关系由 Build_AudioIndex.py 静态扫桥段生成，
# 存在同目录的 ffrs_audio_index.json 里。
#
# 替换方式：**原位(in-place)改写** 音库 uexp 内嵌 AFS2 的条目槽位，
# 再用 retoc 打成 IoStore 补丁容器 <视频MOD名>_P.{pak,utoc,ucas}。
#
# ★ 为什么不能像视频那样就地改 ucas：音频在 Oodle 压缩块里，长度一变就散架。
# ★ subkey 必须用该音库自己的（从 AFS2 头读），否则从 AWB 解出来是噪声。

AUDIO_EXTS = {".wav", ".mp3", ".m4a", ".aac", ".flac", ".ogg", ".opus", ".wma", ".aiff"}
AUDIO_INDEX = APP_DIR / "ffrs_audio_index.json"
AUDIO_CACHE = APP_DIR / "_audio_cache"
try:
    import kit.settings as _K
    _bv = str(_K.get("base_view") or "").strip()
    AUDIO_CACHE = pathlib.Path(_bv).parent if _bv else (_K.cache_root() / "audio")
except Exception:
    pass
# 补丁容器名的默认值（仅当调用方没给 base 时使用）。
# UE 只要求文件名带 `_P` 后缀，名字随意；实际生成时用「视频 MOD 名 + _P」，
# 例如 MV_summon300010_mod_P，方便和视频 MOD 对上。
PATCH_BASE = "FFRS-Windows_P"
BITRATE_LADDER = [80000, 64000, 48000, 32000, 24000, 16000, 12000]


def load_audio_index() -> dict | None:
    if not AUDIO_INDEX.exists():
        return None
    try:
        with open(AUDIO_INDEX, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def audio_meta(path: Path) -> dict | None:
    """用 ffmpeg 读音频时长/采样率/声道。"""
    try:
        rc, out, err = run([App.FFMPEG, "-hide_banner", "-i", path], timeout=60)
    except Exception:
        return None
    txt = err + out
    info = {}
    m = re.search(r"Duration: (\d+):(\d+):(\d+\.\d+)", txt)
    if m:
        info["duration"] = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))
    m = re.search(r"Audio: \w+.*?, (\d+) Hz, (\w+)", txt)
    if m:
        info["sr"] = int(m.group(1))
        info["ch"] = 1 if m.group(2) == "mono" else 2
    return info or None


def _afs2_parse(buf: bytes):
    """AFS2 v2 头：magic(4) ver(1) off_size(1) id_size(1) pad(1) count(u32) align(u16) subkey(u16)。"""
    assert buf[:4] == b"AFS2", "不是 AFS2"
    ver, osz, isz, _ = struct.unpack_from("<BBBB", buf, 4)
    cnt = struct.unpack_from("<I", buf, 8)[0]
    align, subkey = struct.unpack_from("<HH", buf, 12)
    assert (ver, osz, isz) == (2, 4, 4), "只支持 AFS2 v2 / 4+4"
    offs = struct.unpack_from("<%dI" % cnt, buf, 16 + cnt * 4)
    return cnt, align, subkey, offs


def _afs2_tail(buf: bytes, offs, align: int) -> int:
    """AFS2 末尾有一块【尾部数据】(若干 @UTF 表 + 前置哈希/零)，
    它落在最后一个条目的槽位区间里 —— 写最后一个条目时必须截断，
    否则补零会把表抹掉（@UTF 数变少 = 补丁必坏）。"""
    last = (offs[-1] + align - 1) // align * align
    t = buf.find(b"@UTF", last)
    assert t > 0, "找不到尾部 @UTF"
    j = t - 1
    while j > 0 and buf[j] == 0:
        j -= 1
    start = min((j + 1) // 32 * 32, t - 0x50)
    assert start > last, "尾部块检测异常"
    return start


class AudioBankCache:
    """按需从游戏容器抽出音库的 uasset/uexp，缓存在工具目录下。"""

    def __init__(self, paks_dir: Path, retoc: Path, log):
        self.paks = Path(paks_dir)
        self.retoc = Path(retoc)
        self.log = log
        AUDIO_CACHE.mkdir(parents=True, exist_ok=True)
        self.view = self._base_view()

    def _base_view(self) -> Path:
        """返回一个**只含基础容器**的目录，供 to-legacy 抽音库。

        为什么：Paks 里若装着 _P 补丁，`retoc to-legacy <Paks目录>` 会优先读补丁，
        抽出来的音库就是"已被改过的"，在其上再做替换会叠床架屋。
        用**硬链接**把基础容器 + global 链到缓存目录 —— 同盘秒建、不占空间、不复制 4.4GB。
        硬链接不可用（跨盘/无权限）时退回直接用 Paks 目录，并写一条警告。
        """
        if not any(self.paks.glob("*_P.utoc")):
            return self.paks                     # 没装补丁，直接用
        d = AUDIO_CACHE / "base_paks"
        try:
            d.mkdir(parents=True, exist_ok=True)
        except Exception:
            return self.paks
        need = ("FFRS-Windows.pak", "FFRS-Windows.utoc", "FFRS-Windows.ucas",
                "global.utoc", "global.ucas")
        for n in need:
            src, dst = self.paks / n, d / n
            if not src.exists() or dst.exists():
                continue
            try:
                os.link(src, dst)
            except OSError:
                if self.log:
                    self.log(t("base_view_fail"))
                return self.paks
        return d

    def paths(self, bank: str) -> tuple[Path, Path]:
        return AUDIO_CACHE / f"{bank}.uasset", AUDIO_CACHE / f"{bank}.uexp"

    def ensure(self, bank: str, retoc_arg, pak_path: str = "") -> tuple[Path, Path]:
        ua, ux = self.paths(bank)
        if ua.exists() and ux.exists():
            return ua, ux
        self.log(t("audio_extracting", bank=bank))
        tmp = AUDIO_CACHE / "_tmp"
        shutil.rmtree(tmp, ignore_errors=True)
        tmp.mkdir(parents=True, exist_ok=True)
        rc, out, err = run([str(self.retoc), "to-legacy", str(self.view), str(tmp),
                            "-f", f"{bank}.uasset", "--no-shaders"], timeout=1800)
        if rc != 0:
            raise RuntimeError(f"retoc to-legacy 失败：{(err or out)[-300:]}")
        # ★ 同一个包在 L10N/en、L10N/ja、基础路径下是**三份同名资产**，
        #   to-legacy 会把它们全抽出来。必须按索引里记的 pak_path 精确挑，
        #   否则会随机拿到别的语言那份 —— 补丁的 ChunkId 也就对不上要覆盖的包。
        hits = []
        for root, _d, names in os.walk(tmp):
            for n in names:
                if n == f"{bank}.uasset":
                    cand = Path(root) / f"{bank}.uexp"
                    if cand.exists():
                        hits.append((Path(root) / n, cand))
        want = (pak_path or "").replace("/", os.sep)
        if want:
            exact = [(a, b) for a, b in hits if want in str(b).replace("/", os.sep)]
            hits = exact or hits
        if not hits:
            shutil.rmtree(tmp, ignore_errors=True)
            raise RuntimeError(f"在游戏容器里找不到音库 {bank}")
        src_ua, src_ux = hits[0]
        shutil.copy2(src_ua, ua)
        shutil.copy2(src_ux, ux)
        shutil.rmtree(tmp, ignore_errors=True)
        return ua, ux


    # ★ 响度：'auto' = 对齐到原条目 RMS；'auto' + extra = 对齐后再提升；
    #        'none' = 完全不动素材电平
AUDIO_GAIN_MODES = [
    ("auto", 0.0), ("auto", 3.0), ("auto", 6.0), ("auto", 9.0),
    ("auto", 12.0), ("auto", 18.0), ("none", 0.0),
]


def gain_label(i: int) -> str:
    mode, extra = AUDIO_GAIN_MODES[i]
    if mode == "none":
        return t("audio_gain_none")
    if extra <= 0:
        return t("audio_gain_auto")
    return t("audio_gain_boost", db="+%g" % extra)


def wav_peak_db(path: Path) -> float:
    """WAV 峰值（dBFS）。"""
    import array
    try:
        w = wave.open(str(path), "rb")
        a = array.array("h")
        a.frombytes(w.readframes(w.getnframes()))
        w.close()
    except Exception:
        return -99.0
    pk = max((abs(x) for x in a), default=0)
    return 20 * math.log10(pk / 32767) if pk > 0 else -99.0


def wav_rms(path: Path) -> float:
    """WAV 的 RMS（0-32767 量纲）。用来做响度对齐。"""
    import array
    try:
        w = wave.open(str(path), "rb")
        n, ch = w.getnframes(), w.getnchannels()
        a = array.array("h")
        a.frombytes(w.readframes(n))
        w.close()
    except Exception:
        return 0.0
    if not len(a):
        return 0.0
    s = 0
    for x in a:
        s += float(x) * x
    return math.sqrt(s / len(a))


def replace_audio_entry(uexp: bytearray, entry: int, src_wav: Path, hint: dict, log,
                        gain_mode: str = "auto", extra_db: float = 0.0):
    """把 uexp 里 AFS2 的某个条目【原位】换成 src_wav 编码出的 HCA。

    返回 (原时长秒, 新时长秒)。会做全部结构校验，任何一条不满足就抛错。
    """
    off = uexp.find(b"AFS2")
    if off < 0:
        raise RuntimeError("uexp 里找不到 AFS2")
    afs2 = bytes(uexp[off:])          # 用 bytes（memoryview 没有 .find，尾部块探测要用）
    cnt, align, subkey, offs = _afs2_parse(afs2)
    if not (0 <= entry < cnt):
        raise RuntimeError(f"条目号 {entry} 越界（该库共 {cnt} 条）")
    tail = _afs2_tail(afs2, offs, align)
    start = (offs[entry] + align - 1) // align * align
    end = offs[entry + 1] if entry + 1 < cnt else min(len(afs2), tail)
    room = end - start
    if room <= 0:
        raise RuntimeError("条目槽位异常")

    # ① 解出原条目，拿到它自己的采样率/声道/时长 —— 规格必须对齐，否则变速变调
    # 每次用全新的子目录（放在工具目录下，避免 %TEMP% 写不出文件）
    try:
        import uuid as _uuid
        tmp = _work_root() / f"audio_{_uuid.uuid4().hex[:8]}"
        tmp.mkdir(parents=True, exist_ok=True)
    except Exception:
        tmp = Path(tempfile.mkdtemp(prefix="ffrs_audio_work_"))
    afs2_file = tmp / f"{hint['bank']}.afs2"
    if not afs2_file.exists():
        afs2_file.write_bytes(afs2)
    probe_wav = tmp / f"probe_{hint['bank']}_{entry}.wav"
    rc, out, err = run([App.CRICODECS, str(afs2_file), "-o", str(probe_wav),
                        "--index", str(entry), "--key", hint["key"], "-q"], timeout=300)
    if rc != 0 or not probe_wav.exists():
        raise RuntimeError(f"解原条目失败：{(err or out)[-200:]}")
    pm = audio_meta(probe_wav) or {}
    rate, ch = int(pm.get("sr") or 48000), int(pm.get("ch") or 2)
    old_dur = float(pm.get("duration") or 0)
    old_rms = wav_rms(probe_wav)

    # ② 转成同规格
    conv = tmp / f"conv_{hint['bank']}_{entry}.wav"
    rc, out, err = run([App.FFMPEG, "-y", "-i", str(src_wav), "-ar", str(rate), "-ac", str(ch),
                        "-c:a", "pcm_s16le", "-loglevel", "error", str(conv)], timeout=900)
    if rc != 0:
        raise RuntimeError(f"音频转码失败：{(err or out)[-200:]}")
    new_dur = float((audio_meta(conv) or {}).get("duration") or 0)

    # ②b ★ 响度处理：游戏里的音效都是接近满刻度母带过的（实测原条目峰值 -0.3 dBFS），
    #     玩家拿来的素材常常轻十几 dB —— 不补的话 BGM 一开就完全听不清。
    #     mode='auto' 按 RMS 对齐到原条目；extra 再往上加（用户嫌小就加）；
    #     mode='none' 完全不动。最后都过一道限幅器防削顶。
    src_rms = wav_rms(conv)
    if gain_mode != "none" and old_rms > 0 and src_rms > 0:
        gain_db = 20 * math.log10(old_rms / src_rms) + float(extra_db)
        gain_db = max(-24.0, min(36.0, gain_db))
        if abs(gain_db) >= 0.5:
            conv2 = tmp / f"conv2_{hint['bank']}_{entry}.wav"
            rc, out, err = run([App.FFMPEG, "-y", "-i", str(conv), "-ar", str(rate), "-ac", str(ch),
                                "-af", "volume=%.2fdB,alimiter=limit=0.95" % gain_db,
                                "-c:a", "pcm_s16le", "-loglevel", "error", str(conv2)], timeout=900)
            if rc == 0 and conv2.exists():
                log("      · 音量：%+.1f dB（原条目 RMS %.0f / 素材 RMS %.0f）→ 处理后峰值 %.1f dBFS"
                    % (gain_db, old_rms, src_rms, wav_peak_db(conv2)))
                conv = conv2
            else:
                log("      · 音量处理失败，按原样使用")
    elif gain_mode == "none":
        log("      · 音量：不处理（按素材原样）峰值 %.1f dBFS" % wav_peak_db(conv))

    # ②c ★ 素材比原条目长时按原时长裁剪：
    #     游戏实际只播原条目这段（槽位也是按它开的），不裁必然"放不下"
    if old_dur > 0 and new_dur > old_dur * 1.02:
        trimmed = tmp / f"trim_{hint['bank']}_{entry}.wav"
        rc, out, err = run([App.FFMPEG, "-y", "-i", str(conv),
                            "-t", f"{old_dur:.3f}", "-ar", str(rate), "-ac", str(ch),
                            "-c:a", "pcm_s16le", "-loglevel", "error", str(trimmed)], timeout=900)
        if rc == 0 and trimmed.exists():
            log("      · 素材 %.2fs 超过原条目 %.2fs，已裁到原时长" % (new_dur, old_dur))
            conv = trimmed
            new_dur = float((audio_meta(conv) or {}).get("duration") or old_dur)

    # ③ 选槽位放得下的最高码率
    br = None
    for b in BITRATE_LADDER:
        if new_dur * b / 8 * 1.06 + 200 <= room:
            br = b
            break
    if br is None:
        # 再退一步：裁到 92% 时长重试一次（某些条目尾部有对齐填充）
        trimmed2 = tmp / f"trim2_{hint['bank']}_{entry}.wav"
        rc, out, err = run([App.FFMPEG, "-y", "-i", str(conv), "-t", f"{old_dur * 0.92:.3f}",
                            "-ar", str(rate), "-ac", str(ch), "-c:a", "pcm_s16le",
                            "-loglevel", "error", str(trimmed2)], timeout=900)
        if rc == 0 and trimmed2.exists():
            conv = trimmed2
            new_dur = float((audio_meta(conv) or {}).get("duration") or old_dur * 0.92)
            for b in BITRATE_LADDER:
                if new_dur * b / 8 * 1.06 + 200 <= room:
                    br = b
                    break
        if br is None:
            raise RuntimeError("音频太长，槽位放不下（原条目 %.2fs，槽位 %d 字节）—— "
                               "可把「替换音频」选成不替换后重新生成" % (old_dur, room))

    # ④ 编码（★ 必须带该库自己的 subkey）
    hca = tmp / f"enc_{hint['bank']}_{entry}_{br}.hca"
    rc, out, err = run([App.CRICODECS, "--encode", "-f", "hca", str(conv), "-o", str(hca),
                        "--key", hint["key"], "--subkey", str(subkey), "--bitrate", str(br), "-q"],
                       timeout=600)
    if rc != 0 or not hca.exists():
        raise RuntimeError(f"HCA 编码失败：{(err or out)[-200:]}")
    data = hca.read_bytes()
    if len(data) > room:
        raise RuntimeError("编码结果超出槽位（%d > %d）" % (len(data), room))

    # ⑤ 原位写回：只覆盖该条目槽位，其余补零
    uexp[off + start: off + start + len(data)] = data
    uexp[off + start + len(data): off + end] = b"\x00" * (room - len(data))
    log("    · 条目 %d：%.2fs -> %.2fs（%d Hz %dch，码率 %d，写入 %d/%d 字节）"
        % (entry, old_dur, new_dur, rate, ch, br, len(data), room))
    return old_dur, new_dur


# ────────────── 影片 pak（方案 B：.usm 按原始路径打进 pak）──────────────
# 实测（2026-10-17 游戏内确认）：把替换后的 .usm 按游戏里的**原始 pak 路径**
# 用 repak 打进一个 _P.pak，再 retoc to-zen 生成配对 utoc/ucas，
# 游戏就会直接播替换后的影片 —— **完全不改 ucas、不改资产、不放散文件**。
PAK_MOUNT = "../../../"
PAK_VERSION = "V11"
PAK_SEED_FALLBACK = "56889CD3"      # 本作 FFRS-Windows.pak 的 path hash seed


def pak_seed(paks_dir: Path, repak: Path) -> str:
    """读基础 pak 的 path hash seed（repak info 里是十六进制），转成 repak 要的十进制。"""
    try:
        rc, out, err = run([repak, "info", Path(paks_dir) / "FFRS-Windows.pak"], timeout=120)
        m = re.search(r"path hash seed:\s*Some\(([0-9A-Fa-f]+)\)", out + err)
        if m:
            return str(int(m.group(1), 16))
    except Exception:
        pass
    return str(int(PAK_SEED_FALLBACK, 16))


def build_movie_pak(usm: Path, movie_rel: str, out_pak: Path, repak: Path, log):
    """把 .usm 按原始 pak 路径（FFRS/Content/Streams/Movies/<rel>.usm）打成 pak。"""
    try:
        import uuid as _uuid2
        stage = _work_root() / f"pak_{_uuid2.uuid4().hex[:8]}"
        stage.mkdir(parents=True, exist_ok=True)
    except Exception:
        stage = Path(tempfile.mkdtemp(prefix="ffrs_pak_"))
    try:
        sub = movie_rel.rsplit("/", 1)[0] if "/" in movie_rel else ""
        d = stage / "FFRS" / "Content" / "Streams" / "Movies" / sub
        d.mkdir(parents=True, exist_ok=True)
        shutil.copy2(usm, d / (movie_rel.rsplit("/", 1)[-1] + ".usm"))
        seed = pak_seed(Path(out_pak).parent, repak)       # 占位，下面用真实 paks 目录覆盖
        rc, o, e = run([repak, "pack", "-m", PAK_MOUNT, "--version", PAK_VERSION,
                        "-p", seed, stage, out_pak], timeout=1800)
        if rc != 0 or not Path(out_pak).exists():
            raise RuntimeError("repak 打包失败：%s" % ((e or o)[-300:]))
        log("      · 影片 pak：%s（%d 字节，路径 FFRS/Content/Streams/Movies/%s.usm）"
            % (Path(out_pak).name, Path(out_pak).stat().st_size, movie_rel))
    finally:
        shutil.rmtree(stage, ignore_errors=True)



def extract_mod_assets(mod_dir: Path, work_root: Path, game_paks: Path, retoc: Path, log) -> Path:
    """把一个 IoStore MOD 三件套抽成 legacy 资产，供合并进我们的容器。

    坑：`retoc to-legacy` 需要输入目录里有 `global.utoc/global.ucas`（ScriptObjects），
    否则报 "chunk_type: ScriptObjects not found"。所以要把它一起拷进去。
    抽完的 `scriptobjects.bin` 是 global 带出来的，不能打进我们的 MOD，删掉。
    """
    src = Path(work_root) / "merge_src"
    leg = Path(work_root) / "merge_legacy"
    shutil.rmtree(src, ignore_errors=True)
    shutil.rmtree(leg, ignore_errors=True)
    src.mkdir(parents=True, exist_ok=True)
    leg.mkdir(parents=True, exist_ok=True)

    got = 0
    for ext in (".pak", ".utoc", ".ucas"):
        for f in sorted(Path(mod_dir).glob("*" + ext)):
            shutil.copy2(f, src / f.name)
            got += 1
    if got == 0:
        raise RuntimeError("待合并目录里没有 .pak/.utoc/.ucas")
    for n in ("global.utoc", "global.ucas"):
        g = Path(game_paks) / n
        if g.exists():
            shutil.copy2(g, src / n)

    rc, o, e = run([retoc, "to-legacy", src, leg, "--no-shaders"], timeout=1800)
    if rc != 0:
        raise RuntimeError("待合并 MOD 解析失败：%s" % ((e or o)[-300:]))
    (leg / "scriptobjects.bin").unlink(missing_ok=True)
    n_assets = sum(1 for p in leg.rglob("*.uasset"))
    log("      · 待合并 MOD：抽出 %d 个资产（%s）" % (n_assets, Path(mod_dir).name))
    return leg



def build_audio_patch(index: dict, targets: list, out_dir: Path, retoc: Path,
                      paks_dir: Path, log, base: str = PATCH_BASE,
                      gain_mode: str = "auto", extra_db: float = 0.0,
                      extra_legacy: Path | None = None) -> Path | None:
    """targets = [{'bank','entry','src'(Path)}] -> 生成 <base>.utoc，返回 utoc 路径。

    base 默认 FFRS-Windows_P；界面里会用「视频 MOD 名 + _P」（如 MV_summon300010_mod_P），
    这样音频三件套和视频 MOD 是一套东西，玩家一眼能对上。
    """
    if not targets and not extra_legacy:
        return None
    by_bank = {}
    for x in targets:
        by_bank.setdefault(x["bank"], []).append(x)

    cache = AudioBankCache(paks_dir, retoc, log)
    build_root = out_dir / "_audio_build"
    shutil.rmtree(build_root, ignore_errors=True)
    build_root.mkdir(parents=True, exist_ok=True)

    for bank, items in by_bank.items():
        info = index["banks"].get(bank) or {}
        if info.get("storage") != "memory":
            raise RuntimeError(t("audio_streaming", bank=bank))
        ua, ux = cache.ensure(bank, str(retoc), info.get("pak_path", ""))
        uexp = bytearray(ux.read_bytes())
        before_utf = uexp.count(b"@UTF")
        off = uexp.find(b"AFS2")

        # 展开成「逐条目」任务：
        #   普通目标 = 一条音频补一个条目；
        #   整库目标（Legend 闪回）= 把导入的一组音频**按文件名顺序铺开**到整库条目上，
        #   文件不够就循环使用（保证每个槽位都被换掉，闪回里挑哪句播都是替换后的音频）。
        jobs = []
        for it in items:
            if it.get("whole"):
                n = int(it.get("entry_count") or info.get("entry_count") or 0)
                srcs = [Path(p) for p in (it.get("srcs") or [])]
                if not n or not srcs:
                    raise RuntimeError("整库替换缺少条目数或音频文件")
                for i in range(n):
                    jobs.append((i, srcs[i % len(srcs)]))
                log("      · 整库替换：%s 共 %d 条，导入 %d 个文件按序铺开%s"
                    % (bank, n, len(srcs), "（循环使用）" if len(srcs) < n else ""))
            else:
                jobs.append((int(it["entry"]), Path(it["src"])))

        skipped = []
        for entry, src in jobs:
            try:
                replace_audio_entry(uexp, entry, src, {"bank": bank, "key": get_audio_key()}, log,
                                    gain_mode=gain_mode, extra_db=extra_db)
            except RuntimeError as e:
                msg = str(e)
                if ("槽位放不下" in msg) or ("超出槽位" in msg):
                    # 这条 cue 的槽位比素材短太多：跳过它，别让整个 MOD 生成失败
                    log(f"      ⚠ 条目 {entry} 槽位放不下，已跳过（画面替换不受影响）：{msg}")
                    skipped.append(entry)
                    continue
                raise
        if skipped:
            log(f"      ⚠ 共跳过 {len(skipped)} 条音频（槽位不足）：{skipped[:8]}")

        # 结构校验：长度 / ACB 区 / 尾部块 / @UTF 数 都不能变
        orig = ux.read_bytes()
        if len(uexp) != len(orig):
            raise RuntimeError("内部错误：uexp 长度变了")
        _afs2b = bytes(uexp[off:])
        _cnt, _align, _sk, _offs = _afs2_parse(_afs2b)
        t = _afs2_tail(_afs2b, _offs, _align)
        acb = orig.find(b"@UTF")
        if bytes(uexp[acb:off]) != orig[acb:off]:
            raise RuntimeError("内部错误：ACB 区被改动")
        if bytes(uexp[off + t:]) != orig[off + t:]:
            raise RuntimeError("内部错误：AFS2 尾部块被改动")
        if uexp.count(b"@UTF") != before_utf:
            raise RuntimeError("内部错误：@UTF 表数变了")

        d = build_root / bank
        d.mkdir(parents=True, exist_ok=True)
        (d / ux.name).write_bytes(bytes(uexp))
        shutil.copy2(ua, d / ua.name)

    # 把待合并 MOD 的资产一起放进 to-zen 的输入目录
    if extra_legacy:
        for p in Path(extra_legacy).rglob("*"):
            if p.is_file():
                dst = build_root / p.relative_to(extra_legacy)
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(p, dst)

    utoc = out_dir / f"{base}.utoc"
    rc, out, err = run([str(retoc), "to-zen", "--version", "UE5_6", str(build_root), str(utoc)],
                       timeout=1800)
    if rc != 0:
        raise RuntimeError(f"retoc to-zen 失败：{(err or out)[-300:]}")
    rc, out, err = run([str(retoc), "verify", str(utoc)], timeout=600)
    if rc != 0 or "verified" not in (out + err).lower():
        raise RuntimeError("补丁容器校验未通过")
    shutil.rmtree(build_root, ignore_errors=True)
    return utoc


from kit.audio_key import get_audio_key
AUDIO_STATE = APP_DIR / "ffrs_videomod_audio.json"    # 已安装的音频补丁记录（供还原）


def patch_conflict(paks: Path):
    """游戏 Paks 里已经有任何 _P 补丁容器 —— 返回该 utoc，否则 None。

    为什么**连本工具自己装的也算冲突**：音库是从 Paks 里现抽的，
    而 `retoc to-legacy` 会**优先读补丁容器** —— 补丁一旦装着，
    抽出来的音库就是**改过的**，在其上再替换会叠床架屋、时长也对不上。
    所以规则很简单：**要再建音频补丁，先「全部还原」把补丁卸掉。**
    （视频 MOD 不受影响 —— 它是就地改 ucas + 落地 .usm，不产生 _P 容器。）
    """
    for utoc in sorted(Path(paks).glob("*_P.utoc")):
        return utoc
    return None


def load_audio_state() -> dict:
    try:
        return json.loads(AUDIO_STATE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_audio_state(d: dict):
    try:
        AUDIO_STATE.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass


def install_audio_patch(utoc: Path, paks: Path):
    """把补丁容器三件套复制进 Paks 并记录，返回装进去的文件名列表。"""
    utoc = Path(utoc)
    names = [utoc.name, utoc.with_suffix(".ucas").name, utoc.with_suffix(".pak").name]
    for n in names:
        src = utoc.parent / n
        if not src.exists():
            raise RuntimeError(f"补丁文件缺失：{src}")
        shutil.copy2(src, Path(paks) / n)
    st = load_audio_state()
    st["files"] = names
    st["targets"] = st.get("targets", [])
    save_audio_state(st)
    return names


def install_audio_packs(mods_dir: Path, paks: Path) -> list:
    """把 MOD 目录下的音频补丁三件套（*_P.utoc/ucas/pak）装进 Paks，返回装进去的文件名。

    简化模式用：玩家拿到的 MOD 文件夹里除了 *.usm，还可能有音频三件套，
    要跟视频一起装，否则「装了 MOD 但音频没变」。
    """
    installed = []
    for utoc in sorted(Path(mods_dir).rglob("*_P.utoc")):
        trio = [utoc.with_suffix(e) for e in (".utoc", ".ucas", ".pak")]
        missing = [p.name for p in trio if not p.exists()]
        if missing:
            raise RuntimeError("音频补丁不完整，缺少：%s" % ", ".join(missing))
        for src in trio:
            shutil.copy2(src, Path(paks) / src.name)
            installed.append(src.name)
    if installed:
        st = load_audio_state()
        # 补丁容器同名只能存在一套（整块覆盖音库），以本次安装为准，别并上旧记录
        st["files"] = sorted(set(installed))
        save_audio_state(st)
    return installed


def remove_audio_patch(paks: Path) -> int:
    """删掉之前装进去的补丁容器三件套，返回删除个数。"""
    st = load_audio_state()
    n = 0
    for name in st.get("files", []):
        p = Path(paks) / name
        if p.exists():
            p.unlink()
            n += 1
    st["files"] = []
    save_audio_state(st)
    return n

PLAY_CACHE = AUDIO_CACHE / "play"          # 试听：非 wav 素材的转码缓存
PREVIEW_CACHE = AUDIO_CACHE / "preview"    # 试听：游戏内音频解出来的 wav


def play_audio(src, log=None):
    """试听一个音频文件。WAV 直接播，其它格式先用 ffmpeg 转成 WAV（带缓存）再播。"""
    try:
        import winsound
    except ImportError:
        raise RuntimeError("当前系统不支持试听（仅 Windows）")
    p = Path(src)
    if not p.exists():
        raise RuntimeError("文件不存在：%s" % p)
    if p.suffix.lower() != ".wav":
        PLAY_CACHE.mkdir(parents=True, exist_ok=True)
        safe = re.sub(r"[^0-9A-Za-z]+", "_", p.stem)[:36]
        out = PLAY_CACHE / ("%s_%s.wav" % (safe, str(p.stat().st_mtime_ns)[-8:]))
        if not out.exists():
            rc, o, e = run([App.FFMPEG, "-y", "-i", str(p), "-c:a", "pcm_s16le",
                            "-loglevel", "error", str(out)], timeout=600)
            if rc != 0 or not out.exists():
                raise RuntimeError((e or o)[-200:])
        p = out
    winsound.PlaySound(str(p), winsound.SND_FILENAME | winsound.SND_ASYNC)


def ensure_bank_preview(bank: str, info: dict, paks: Path, retoc: Path, log) -> dict:
    """把音库的全部条目解成 WAV 放进试听缓存，返回 {条目号: wav 路径}。

    幻兵旁白一次几十条，先用一条 cricodecs 命令整库导出（比逐条 --index 快得多），
    结果连同索引一起缓存，二次进入秒开。
    """
    d = PREVIEW_CACHE / bank
    idxf = d / "_entries.json"
    if idxf.exists():
        try:
            return {int(k): Path(v) for k, v in
                    json.loads(idxf.read_text(encoding="utf-8")).items()}
        except Exception:
            pass
    if log:
        log(t("vis_preview_prep", bank=bank))
    cache = AudioBankCache(paks, retoc, log)
    _ua, ux = cache.ensure(bank, str(retoc), info.get("pak_path", ""))
    d.mkdir(parents=True, exist_ok=True)
    afs2 = d / "_afs2.bin"
    if not afs2.exists():
        raw = ux.read_bytes()
        afs2.write_bytes(raw[raw.find(b"AFS2"):])
    rc, out, err = run([App.CRICODECS, str(afs2), "-o", str(d), "--key", get_audio_key(), "-q"],
                       timeout=1800)
    if rc != 0:
        raise RuntimeError((err or out)[-200:])
    m = {}
    for f in sorted(d.glob("*.wav")):
        mm = re.match(r"(\d+)_(\d+)\.wav$", f.name)
        if mm:
            m[int(mm.group(2))] = f
    idxf.write_text(json.dumps({str(k): str(v) for k, v in m.items()}, ensure_ascii=False),
                    encoding="utf-8")
    if log:
        log(t("vis_preview_ok", bank=bank, n=len(m)))
    return m


# ──────────────────────────── GUI ────────────────────────────
class Preview(tk.Frame):
    def __init__(self, master, title_key, **kw):
        super().__init__(master, bd=1, relief="solid", **kw)
        self.title_lbl = ttk.Label(self, text=t(title_key), anchor="center")
        self.title_lbl.pack(fill="x")
        self.canvas = tk.Canvas(self, bg="#202020", highlightthickness=0, height=180)
        self.canvas.pack(fill="both", expand=True)
        self.frames: list[Path] = []
        self.idx = 0
        self.playing = False
        self._img = None
        self.info = ttk.Label(self, text="", anchor="center", justify="center", wraplength=380)
        self.info.pack(fill="x")

    def set_title(self, key):
        self.title_lbl.config(text=t(key))

    def load(self, dirpath: Path, info_text: str):
        self.frames = sorted(dirpath.glob("f_*.png")) if dirpath and dirpath.exists() else []
        self.idx = 0
        self.info.config(text=info_text)
        self.show()

    def clear(self, text=""):
        self.frames = []
        self.canvas.delete("all")
        self.info.config(text=text)

    def show(self):
        if not self.frames:
            self.canvas.delete("all")
            return
        p = self.frames[self.idx % len(self.frames)]
        try:
            self._img = tk.PhotoImage(file=str(p))
            self.canvas.delete("all")
            cw = max(self.canvas.winfo_width(), 100)
            ch = max(self.canvas.winfo_height(), 100)
            self.canvas.create_image(cw // 2, ch // 2, image=self._img)
        except Exception:
            pass

    def tick(self):
        if self.playing and self.frames:
            self.idx += 1
            self.show()
        self.after(120, self.tick)

    def toggle(self):
        self.playing = not self.playing
        return self.playing


def match_mods(rels, mods):
    """
    把 MOD 文件对上原片。生成 MOD 时的命名是 `<原片名去掉 _vp9>_mod.usm`，据此反推。

    返回 (pairs, orphans, dups)：
        pairs   = [(rel, mod)]  能确定对应关系的
        orphans = [mod]         在游戏影片清单里找不到对应原片
        dups    = [rel]         MOD 重名，无法确定装哪个（不会乱装）
    """
    by_base = {}
    for m in mods:
        stem = m.stem
        if stem.endswith("_P"):          # 三件套的 utoc：MV_xxx_mod_P
            stem = stem[:-2]
        b = stem[:-4] if stem.endswith("_mod") else stem
        by_base.setdefault(b, []).append(m)

    used, pairs, dups = set(), [], []
    for rel in sorted(rels):
        name = rel.rsplit("/", 1)[-1]
        keys = [name] + ([name[:-4]] if name.endswith("_vp9") else [])
        hits = []
        for k in keys:
            hits += by_base.get(k, [])
        hits = [h for h in hits if h not in used]
        if len(hits) == 1:
            used.add(hits[0]); pairs.append((rel, hits[0]))
        elif len(hits) > 1:
            dups.append((rel, hits))
            for h in hits:              # 重名的 MOD 也算"已认领"，别再当成孤立项重复报一次
                used.add(h)
    return pairs, [m for m in mods if m not in used], dups


class BatchInstall(tk.Toplevel):
    """
    cue 式列表：把**游戏里真实存在的影片**列出来，和 MOD 目录里的文件对上，
    然后「全部安装」/「安装选中」。

    影片清单来自 ucas 扫描（只有 ucas 里有 MoviePath 的影片才可能被替换）。
    MOD 与影片的对应关系靠文件名：
        生成 MOD 时输出的是 <原片名去掉 _vp9>_mod.usm
        例如 MV_Opening_vp9  <-  MV_Opening_mod.usm
    同名匹配到多个（如 Skill/en 与 Skill/jp 同名）就标成"MOD 重名，无法确定"，不会乱装。
    """

    def __init__(self, master, root: Path, mods_dir: Path):
        super().__init__(master)
        self.app = master
        self.root = root
        self.mods_dir = mods_dir
        self.inst = Installer(root, APP_DIR / "ffrs_videomod_backup.json")
        self.rows: list = []          # [(rel, mod)]  —— 可安装的
        self.rowmap: dict = {}        # tree item id -> (rel, mod)
        self._result = None

        self.title(APP_NAME + " — " + t("batch_title"))
        self.geometry("940x640")
        self.minsize(760, 460)
        self.transient(master)
        self.build_ui()
        self.after(60, self.scan)

    # ---------- UI ----------
    def build_ui(self):
        top = ttk.Frame(self); top.pack(fill="x", padx=8, pady=(8, 4))
        self.mods_lbl = ttk.Label(top, text=t("batch_mods_dir") + ":")
        self.mods_lbl.pack(side="left")
        self.mods_var = tk.StringVar(value=str(self.mods_dir))
        ttk.Entry(top, textvariable=self.mods_var).pack(side="left", padx=4, fill="x", expand=True)
        self.pick_btn = ttk.Button(top, text=t("browse_dir"), width=10, command=self.pick_dir)
        self.pick_btn.pack(side="left")
        self.scan_btn = ttk.Button(top, text=t("batch_scan"), width=12, command=self.scan)
        self.scan_btn.pack(side="left", padx=4)

        cols = ("movie", "mod", "state")
        self.tree = ttk.Treeview(self, columns=cols, show="headings",
                                 selectmode="extended", height=18)
        self.tree.heading("movie", text=t("batch_col_movie"))
        self.tree.heading("mod", text=t("batch_col_mod"))
        self.tree.heading("state", text=t("batch_col_state"))
        self.tree.column("movie", width=380, anchor="w")
        self.tree.column("mod", width=300, anchor="w")
        self.tree.column("state", width=150, anchor="center")
        for tag, col in (("ready", "#0a6"), ("installed", "#06c"),
                         ("none", "#999"), ("bad", "#c00")):
            self.tree.tag_configure(tag, foreground=col)
        sb = ttk.Scrollbar(self, command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y", padx=(0, 8))
        self.tree.pack(fill="both", expand=True, padx=(8, 0))

        bot = ttk.Frame(self); bot.pack(fill="x", padx=8, pady=6)
        self.all_btn = ttk.Button(bot, text=t("batch_install_all"), command=lambda: self.do_install(True))
        self.all_btn.pack(side="left")
        self.sel_btn = ttk.Button(bot, text=t("batch_install_sel"), command=lambda: self.do_install(False))
        self.sel_btn.pack(side="left", padx=6)
        self.close_btn = ttk.Button(bot, text=t("batch_close"), command=self.destroy)
        self.close_btn.pack(side="right")
        self.sum_lbl = ttk.Label(bot, text="", foreground="#555")
        self.sum_lbl.pack(side="left", padx=14)

        self.tip = ttk.Label(self, text=t("batch_tip"), foreground="#555",
                             justify="left", wraplength=890)
        self.tip.pack(fill="x", padx=10, pady=(0, 8))

    def apply_lang(self):
        """语言切换时刷新本窗口的文案。"""
        try:
            self.title(APP_NAME + " — " + t("batch_title"))
            self.mods_lbl.config(text=t("batch_mods_dir") + ":")
            self.pick_btn.config(text=t("browse_dir"))
            self.scan_btn.config(text=t("batch_scan"))
            self.tree.heading("movie", text=t("batch_col_movie"))
            self.tree.heading("mod", text=t("batch_col_mod"))
            self.tree.heading("state", text=t("batch_col_state"))
            self.all_btn.config(text=t("batch_install_all"))
            self.sel_btn.config(text=t("batch_install_sel"))
            self.close_btn.config(text=t("batch_close"))
            self.tip.config(text=t("batch_tip"))
        except Exception:
            pass

    def pick_dir(self):
        p = filedialog.askdirectory(title=t("batch_mods_dir"), parent=self)
        if p:
            self.mods_var.set(p)
            self.mods_dir = Path(p)
            self.scan()

    # ---------- 扫描（线程安全：工作线程只塞结果，主线程轮询取）----------
    def scan(self):
        self.mods_dir = Path(self.mods_var.get().strip() or self.mods_dir)
        self.sum_lbl.config(text=t("batch_scanning"))
        self.app.log(t("batch_scanning"))
        mods_dir = self.mods_dir

        def work():
            try:
                table = self.inst.scan_movie_paths()
                mods = []
                if mods_dir.is_dir():
                    mods = sorted(list(mods_dir.rglob("*.usm")) +
                                  list(mods_dir.rglob("*_P.utoc")))   # 新版 MOD 是三件套
                self._result = (table, mods, None)
            except Exception as e:
                self._result = (None, None, e)

        threading.Thread(target=work, daemon=True).start()
        self._poll()

    def _poll(self):
        if self._result is None:
            self.after(150, self._poll)
            return
        table, mods, err = self._result
        self._result = None
        if err is not None:
            self.sum_lbl.config(text=str(err))
            self.app.log(f"扫描失败: {err}")
            return
        self.fill(table, mods)

    # ---------- 填表 ----------
    def fill(self, table: dict, mods: list):
        self.tree.delete(*self.tree.get_children())
        self.rowmap.clear()
        installed = set(self.inst.list_installed())
        pairs, orphans, dups = match_mods(list(table), mods)
        mod_of = dict(pairs)

        dup_of = dict(dups)
        for rel in sorted(table):
            mod = mod_of.get(rel)
            if rel in dup_of:
                state, tag = t("batch_st_dup"), "bad"
                modname = ", ".join(m.name for m in dup_of[rel])
            elif mod is None:
                continue                        # 没有对应 MOD 的影片不列出来
            elif rel in installed:
                state, tag = t("batch_st_installed"), "installed"
                modname = mod.name
            else:
                state, tag = t("batch_st_ready"), "ready"
                modname = mod.name
            iid = self.tree.insert("", "end", values=(rel, modname, state), tags=(tag,))
            if mod:
                self.rowmap[iid] = (rel, mod)

        self.rows = pairs
        # 列表里只放"能装的"；被筛掉的东西在汇总行里说明，不静默吞掉
        msg = t("batch_summary", n=len(pairs))
        if orphans or dups:
            msg += t("batch_extra", o=len(orphans), d=len(dups))
        self.sum_lbl.config(text=msg)
        self.app.log(msg)

    # ---------- 安装 ----------
    def do_install(self, all_: bool):
        if all_:
            todo = [(r, m) for r, m in self.rowmap.values() if r]
            if not todo:
                messagebox.showinfo(APP_NAME, t("batch_none_sel"), parent=self); return
            if not messagebox.askyesno(APP_NAME, t("batch_confirm_all", n=len(todo)), parent=self):
                return
        else:
            todo = []
            for iid in self.tree.selection():
                r, m = self.rowmap.get(iid, (None, None))
                if r:
                    todo.append((r, m))
            if not todo:
                messagebox.showinfo(APP_NAME, t("batch_none_sel"), parent=self); return
            if not messagebox.askyesno(APP_NAME, t("batch_confirm_sel", n=len(todo)), parent=self):
                return

        # 一趟扫出所有路径偏移，避免每装一部就全盘扫一次
        try:
            table = self.inst.scan_movie_paths()
        except Exception as e:
            self.app.log(f"扫描失败: {e}"); return

        ok = 0
        paks_dir = self.root / "FFRS" / "Content" / "Paks"
        for rel, mod in todo:
            try:
                if mod.suffix.lower() == ".utoc":          # 新版：三件套，直接复制
                    names = install_audio_patch(mod, paks_dir)
                    self.app.log(t("audio_installed", p=", ".join(names)))
                else:                                       # 老版：就地改 ucas
                    self.inst.install(mod, rel, self.app.log, hits=table.get(rel))
                ok += 1
            except Exception as e:
                self.app.log(t("batch_fail", p=rel, e=e))
        self.app.log(t("batch_done", n=ok))
        try:
            self.app.refresh_installed()
        except Exception:
            pass
        self.scan()

from kit.host import WindowMixin

class App(WindowMixin, tk.Frame):
    SHOW_MERGE = False     # ★ MOD 合并 UI 开关（功能已迁到 FFRS_ModMerge_Tool.py）
    LANG = "zh"
    FFMPEG = ""
    CRICODECS = ""
    RETOC = ""                       # 音频补丁容器需要（IoStore）
    REPAK = ""                       # 影片 .usm 要打进 pak（方案 B）
    SIMPLE_ONLY = False              # 打包成「安装器」exe 时置 True：标题换掉
    SHOW_VISION = False              # ★ 幻兵祠堂语音替换入口（已隐藏，语音替换用 TextMod）
    KEEP_TEMP = False

    def __init__(self, master=None):
        self._bind_window(master)
        self.settings = self._load_settings()
        # ★ 路径统一由首页决定，覆盖旧的持久化值
        try:
            import kit.settings as _K
            # 原视频必须由用户在游戏影片清单里选，不能强制成文件；
            # 但「原视频目录」如果还指着旧工作区/独立版，则重置到 <输入>/VideoMod
            self.settings["new_path"] = str(_K.input_video())
            _op = str(self.settings.get("orig_path") or "").strip()
            try:
                _under = bool(_op) and pathlib.Path(_op).resolve().is_relative_to(_K.TOOLKIT_DIR.resolve())
            except Exception:
                _under = False
            if not _under:
                self.settings["orig_path"] = str(_K.input_video())
                self.settings["orig_sel"] = ""
            self.settings["audio_src"] = str(_K.input_audio())
            self.settings["audio_path"] = str(_K.input_audio())
            self.settings["out_dir"] = str(_K.output_mods())
            self.settings["game_root"] = str(_K.get("game_root"))
            self.settings["ffmpeg"] = str(_K.get("ffmpeg"))
            self.settings["cricodecs"] = str(_K.get("cricodecs"))
        except Exception:
            pass
        App.LANG = self.settings.get("lang", "zh")
        App.FFMPEG = self.settings.get("ffmpeg", "")
        App.CRICODECS = self.settings.get("cricodecs", "")
        App.RETOC = self.settings.get("retoc", "") or str(APP_DIR / "retoc.exe")
        App.REPAK = self.settings.get("repak", "") or str(APP_DIR / "repak.exe")
        self.audio_index = load_audio_index()          # 影片 -> 音频 的配对表
        self.audio_list: list[Path] = []               # 「导入音频」路径里扫到的音频文件
        self.audio_src: Path | None = None             # 当前选中的替换音频文件
        self.audio_skip = True                         # 「不替换」：只换画面不动音频
        self.audio_meta_cache = {}
        self.v_rows: list = []          # 幻兵界面：每行一个条目
        self.v_preview: dict = {}       # 幻兵界面：{bank: {条目号: wav}}
        self.logq = queue.Queue()
        self.busy = False
        self.orig_list: list[Path] = []
        self.new_list: list[Path] = []
        self._previewing: set = set()      # 正在解预览帧的项，避免重复起线程
        self.batch_win = None              # 「MOD 批量安装」窗口（只在打开时创建）
        # 界面模式：首次打开（设置里没有）进简化模式；之后沿用上次退出时的模式
        self.mode = self.settings.get("mode", "full")
        if not App.SHOW_VISION:
            self.mode = "full"
        if self.mode not in App.MODES:
            self.mode = "full"
        if self.mode == "simple" and not App.SIMPLE_ONLY:
            self.mode = "full"        # 简化模式已从主界面移除
        try:
            self.tmpdir = _work_root() / f"gui_{os.getpid()}"
            self.tmpdir.mkdir(parents=True, exist_ok=True)
        except Exception:
            self.tmpdir = Path(tempfile.mkdtemp(prefix="ffrs_vmod_gui_"))
        self.build_ui()
        self.apply_lang()
        self._ready = False                       # 恢复完路径之前不许写设置
        self.after(400, self._restore_paths)      # 恢复上次的原视频/替换视频路径
        self.after(100, self._drain)
        self.after(120, lambda: (self.pv_orig.tick(), self.pv_new.tick()))
        self.after(300, self.refresh_installed)
        self.protocol("WM_DELETE_WINDOW", self._close)

    # ---------- settings ----------
    def _load_settings(self) -> dict:
        d = {"lang": "zh", "ffmpeg": "", "cricodecs": "", "game_root": "", "out_dir": "",
             "orig_path": "", "new_path": "", "orig_sel": "", "new_sel": "",
             "retoc": "", "repak": "", "audio_path": "", "audio_sel": "", "audio_gain": 0,
             "merge_path": "",
             "mode": "full"}          # 首次打开进简化模式；之后记住上次用的模式
        if SETTINGS.exists():
            try:
                d.update(json.loads(SETTINGS.read_text(encoding="utf-8")))
            except Exception:
                pass
        d.pop("dur_mode", None)          # 旧版本遗留
        return d

    def _save_settings(self):
        # ★ 启动期间禁止写盘：apply_lang() 里的 refresh_audio() 会一路走到这里，
        #   而那时 orig_var/new_var 还是空的（要等 _restore_paths 才填），
        #   一写就把上次存好的路径覆盖成空 —— 表现为"每次打开路径都丢"。
        if not getattr(self, "_ready", False):
            return
        self.settings.update({
            "lang": App.LANG, "ffmpeg": App.FFMPEG, "cricodecs": App.CRICODECS,
            "game_root": self.game_var.get(), "out_dir": self.out_var.get(),
            # 记住原视频/替换视频的路径与当前选中项，下次打开不用重新指认
            "orig_path": self.orig_var.get(), "new_path": self.new_var.get(),
            "orig_sel": self._sel_path(self.orig_box, self.orig_list),
            "new_sel": self._sel_path(self.new_box, self.new_list),
            "retoc": App.RETOC, "repak": App.REPAK,
            "audio_path": getattr(self, "audio_var", tk.StringVar()).get(),
            "audio_sel": getattr(self, "audio_sel_key", ""),
            "audio_gain": self._gain_idx(),
            "merge_path": getattr(self, "merge_var", tk.StringVar()).get(),
            "mode": getattr(self, "mode", "simple"),
        })
        try:
            SETTINGS.write_text(json.dumps(self.settings, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass

    @staticmethod
    def _sel_path(box, lst) -> str:
        """当前下拉选中项的完整路径（存路径而不是下标，列表顺序变了也不会错位）。"""
        i = box.current()
        return str(lst[i]) if 0 <= i < len(lst) else ""

    def _select_path(self, box, lst, want: str):
        """按下拉列表把选中项恢复成路径 want；找不到就选第一个。"""
        if not lst:
            return
        idx = next((i for i, p in enumerate(lst) if str(p) == want), 0)
        box.current(idx)

    # ---------- UI ----------
    def build_ui(self):
        self.geometry("1080x790")

        # ── 可滚动外层 ──
        # 规则：内容装得下就**不显示**滚动条；装不下（屏幕太小 或 用户把窗口拉小）才出现。
        # 顶栏 / 三种界面 / 日志都放进 inner，状态栏留在外面始终可见。
        self.s_busy = False
        self.s_outer = ttk.Frame(self)
        self.s_outer.pack(fill="both", expand=True)
        self.s_canvas = tk.Canvas(self.s_outer, highlightthickness=0)
        self.s_vsb = ttk.Scrollbar(self.s_outer, orient="vertical", command=self.s_canvas.yview)
        self.s_hsb = ttk.Scrollbar(self.s_outer, orient="horizontal", command=self.s_canvas.xview)
        self.s_canvas.configure(yscrollcommand=self.s_vsb.set, xscrollcommand=self.s_hsb.set)
        self.s_canvas.grid(row=0, column=0, sticky="nsew")
        self.s_outer.grid_rowconfigure(0, weight=1)
        self.s_outer.grid_columnconfigure(0, weight=1)
        # 两条滚动条初始都不摆放，需要时在 _update_scrollbars 里 grid

        inner = ttk.Frame(self.s_canvas)
        self.s_inner = inner
        self.s_win = self.s_canvas.create_window((0, 0), window=inner, anchor="nw")
        inner.bind("<Configure>", lambda e: self._scroll_region())
        self.s_canvas.bind("<Configure>", lambda e: self._update_scrollbars())
        for w in (self.s_canvas, inner):
            w.bind("<Enter>", lambda e: self.bind_all("<MouseWheel>", self._on_wheel))
            w.bind("<Leave>", lambda e: self.unbind_all("<MouseWheel>"))

        # ── 顶栏：模式切换（左）｜语言（右）──
        top = ttk.Frame(inner); top.pack(fill="x", padx=8, pady=(6, 0))
        self.mode_lbl = ttk.Label(top, text="")
        # 宽度要放得下「幻兵祠堂语音替换工具」（CJK 是双宽字符，12 会截断）
        self._hide_mode_lang = True     # 界面/语言切换统一在 Toolkit 首页
        self.mode_box = ttk.Combobox(top, state="readonly", width=24,
                                     values=[t("mode_simple"), t("mode_full")])
        if not self._hide_mode_lang: self.mode_box.pack(side="left", padx=(6, 0))
        self.mode_box.bind("<<ComboboxSelected>>", self._on_mode)

        self.lang_lbl = ttk.Label(top, text="")
        self.lang_box = ttk.Combobox(top, state="readonly", width=14,
                                     values=["中文", "English"])
        self.lang_box.set("中文" if App.LANG == "zh" else "English")
        self.lang_box.bind("<<ComboboxSelected>>", self._on_lang)
        if not self._hide_mode_lang: self.lang_box.pack(side="right")
        # 语言统一在 Toolkit 首页切换，这里不显示

        # ── 可切换的主体：简化模式 / MOD 制作 / 幻兵 ──
        self.body = ttk.Frame(inner); self.body.pack(fill="x")
        self.full_ui = ttk.Frame(self.body)
        self.simple_ui = ttk.Frame(self.body)
        self.vision_ui = ttk.Frame(self.body)
        self._build_full_ui(self.full_ui)
        self._build_simple_ui(self.simple_ui)
        self._build_vision_ui(self.vision_ui)

        # ── 日志（所有模式共用）──
        # ★ 日志放在滚动区**外面**：始终钉在窗口底部，不跟着内容一起滚
        lg = ttk.LabelFrame(self, text="")
        self.grp_log = lg
        self.log_txt = tk.Text(lg, height=6, wrap="none", font=("Consolas", 9))
        self.log_txt.pack(side="left", fill="both", expand=True)
        sb = ttk.Scrollbar(lg, command=self.log_txt.yview); sb.pack(side="right", fill="y")
        self.log_txt.configure(yscrollcommand=sb.set)

        self.status = ttk.Label(self, text="", anchor="w", relief="sunken")
        self.status.pack(fill="x", side="bottom")     # 状态栏固定在窗口底部
        # 日志在状态栏之上、滚动区之外
        lg.pack(side="bottom", fill="x", padx=8, pady=(0, 4), before=self.status)

        self.apply_mode()
        self.after(60, self._update_scrollbars)

    # ---------- MOD 制作模式 ----------
    def _build_full_ui(self, parent):
        # 路径
        self.grp_src = ttk.LabelFrame(parent, text="")
        self.grp_src.pack(fill="x", padx=8, pady=6)
        self.orig_var = tk.StringVar(); self.new_var = tk.StringVar()
        self.out_var = tk.StringVar(value=self.settings.get("out_dir", ""))
        self.audio_var = tk.StringVar(value=self.settings.get("audio_path", ""))
        self._row(self.grp_src, 0, "orig_path", self.orig_var, self._pick_orig)
        self._row(self.grp_src, 1, "new_path", self.new_var, self._pick_new)
        self._row(self.grp_src, 2, "audio_src", self.audio_var, self._pick_audio)
        self._row(self.grp_src, 3, "out_dir", self.out_var, self._pick_out)

        # 工具 + 游戏
        self.grp_tools = ttk.LabelFrame(parent, text="")
        self.grp_tools.pack(fill="x", padx=8)
        self.game_var = tk.StringVar(value=self.settings.get("game_root", ""))
        self.ff_var = tk.StringVar(value=App.FFMPEG)
        self.cc_var = tk.StringVar(value=App.CRICODECS)
        self.rt_var = tk.StringVar(value=App.RETOC)
        self.rp_var = tk.StringVar(value=App.REPAK)
        self._row(self.grp_tools, 0, "game_dir", self.game_var, lambda: self._pick_dir(self.game_var), folder=True)
        self._row(self.grp_tools, 1, "ffmpeg", self.ff_var, lambda: self._pick_file(self.ff_var), entry_w=46)
        self._row(self.grp_tools, 2, "cricodecs", self.cc_var, lambda: self._pick_file(self.cc_var), entry_w=46)
        # ★ 路径与外部工具统一由 Toolkit 首页提供，本页不再单独设置
        try:
            import kit.settings as _K
            _tools = _K.get("tools_dir") or str(APP_DIR)
            self.game_var.set(str(_K.get("game_root")))
            self.ff_var.set(str(_K.get("ffmpeg")))
            self.cc_var.set(str(_K.get("cricodecs")))
            App.FFMPEG = self.ff_var.get(); App.CRICODECS = self.cc_var.get()
            App.RETOC = str(_tools) + "/retoc.exe"; App.REPAK = str(_tools) + "/repak.exe"
            self.orig_var.set(str(_K.input_video()))
            self.new_var.set(str(_K.input_video()))
            self.audio_var.set(str(_K.input_audio()))
            self.out_var.set(str(_K.output_mods()))
        except Exception:
            pass
        try:
            self.grp_src.pack_forget()
            self.grp_tools.pack_forget()
        except Exception:
            pass
        self._row(self.grp_tools, 3, "retoc", self.rt_var, lambda: self._pick_file(self.rt_var), entry_w=46)
        self._row(self.grp_tools, 4, "repak", self.rp_var, lambda: self._pick_file(self.rp_var), entry_w=46)
        self.check_btn = ttk.Button(self.grp_tools, text="", command=self.check_tools)
        self.check_btn.grid(row=5, column=1, sticky="w", padx=6, pady=4)

        # ── MOD 合并（可选）：把别的三件套一起打进本 MOD ──
        # ★ 2026-10-17：合并功能已由独立工具 Tools/FFRS_ModMerge_Tool.py 取代（可合任意多个，
        #   pak 的 NonUFS + utoc 的 raw chunk 分开合并，不重 cook）。
        #   这里保留代码但**默认不显示**，降低误用风险；要恢复把 App.SHOW_MERGE 改回 True。
        self.grp_merge = ttk.LabelFrame(parent, text="")
        if self.SHOW_MERGE:
            self.grp_merge.pack(fill="x", padx=8, pady=(0, 0))
        self.merge_var = tk.StringVar(value=self.settings.get("merge_path", ""))
        self._row(self.grp_merge, 0, "merge_path", self.merge_var, self._pick_merge, folder=True)

        # 预览
        self.grp_prev = ttk.LabelFrame(parent, text="")
        self.grp_prev.pack(fill="both", expand=True, padx=8, pady=6)
        bar = ttk.Frame(self.grp_prev); bar.pack(fill="x", padx=6, pady=4)
        # ★ pack 顺序决定「宽度不够时谁先被挤掉」：先 pack 的先拿到空间。
        #   播放按钮必须最先占位（side=right），否则窗口略窄时它会第一个被压成 1px 而看不见。
        self.play_btn = ttk.Button(bar, text="", command=self.toggle_play)
        self.play_btn.pack(side="right")
        self.parse_btn = ttk.Button(bar, text="", command=self.do_parse)
        self.parse_btn.pack(side="left")
        self.lbl_o = ttk.Label(bar, text=""); self.lbl_o.pack(side="left", padx=(12, 4))
        self.orig_box = ttk.Combobox(bar, state="readonly", width=21)
        self.orig_box.pack(side="left"); self.orig_box.bind("<<ComboboxSelected>>", lambda e: (self.refresh_orig(), self._save_settings()))
        self.lbl_n = ttk.Label(bar, text=""); self.lbl_n.pack(side="left", padx=(12, 4))
        self.new_box = ttk.Combobox(bar, state="readonly", width=17)
        self.new_box.pack(side="left"); self.new_box.bind("<<ComboboxSelected>>", lambda e: (self.refresh_new(), self._save_settings()))
        # 替换音频：单选，内容随选中的原视频刷新（影片本身不含音频，音频由桥段单独触发）
        self.lbl_a = ttk.Label(bar, text=""); self.lbl_a.pack(side="left", padx=(12, 4))
        self.audio_box = ttk.Combobox(bar, state="readonly", width=19)
        self.audio_box.pack(side="left")
        self.audio_box.bind("<<ComboboxSelected>>", lambda e: self.on_audio_selected())
        # 音量：放在「替换音频」下拉和播放按钮之间。
        # ★ 不要绑 textvariable —— 只读下拉框会把变量的值（下标数字）当文本显示，
        #   变成「0 / 1 / 2…」而不是档位文字。用 current(i) 选条目才对。
        self.gain_lbl = ttk.Label(bar, text="")
        self.gain_lbl.pack(side="left", padx=(10, 4))
        self.gain_box = ttk.Combobox(bar, state="readonly", width=13)
        self.gain_box["values"] = [gain_label(i) for i in range(len(AUDIO_GAIN_MODES))]
        self.gain_box.pack(side="left")
        self.gain_box.bind("<<ComboboxSelected>>", lambda e: (self.update_info(), self._save_settings()))

        pane = ttk.Frame(self.grp_prev); pane.pack(fill="both", expand=True, padx=6, pady=(0, 6))
        self.pv_orig = Preview(pane, "preview_orig"); self.pv_orig.pack(side="left", fill="both", expand=True, padx=(0, 4))
        self.pv_new = Preview(pane, "preview_new"); self.pv_new.pack(side="left", fill="both", expand=True, padx=(4, 0))

        # 参数对比 / 提醒（预览下方）
        self.grp_info = ttk.LabelFrame(self.grp_prev, text="")
        self.grp_info.pack(fill="x", padx=6, pady=(0, 6))
        self.info_txt = tk.Text(self.grp_info, height=9, wrap="word", relief="flat",
                                background="#f5f5f5", font=("Microsoft YaHei UI", 9),
                                padx=8, pady=6)
        self.info_txt.pack(fill="x")
        self.info_txt.tag_configure("head", font=("Microsoft YaHei UI", 9, "bold"))
        self.info_txt.tag_configure("ok", foreground="#0a7a3a")
        self.info_txt.tag_configure("warn", foreground="#c05000")
        self.info_txt.tag_configure("mono", font=("Consolas", 9))
        self.info_txt.configure(state="disabled")

        # 底部按钮：单一网格，保证上下两行列对齐
        bot = ttk.Frame(parent); bot.pack(fill="x", padx=8, pady=(0, 8))
        g = ttk.Frame(bot); g.pack(fill="x")
        self.build_btn = ttk.Button(g, text="", command=self.do_build)
        self.build_btn.grid(row=0, column=0, sticky="w", pady=(0, 6))
        self.inst_btn = ttk.Button(g, text="", command=self.do_install)
        self.inst_btn.grid(row=0, column=1, sticky="w", padx=(6, 0), pady=(0, 6))
        self.batch_btn = ttk.Button(g, text="", command=self.do_batch)
        self.batch_btn.grid(row=0, column=2, sticky="w", padx=(6, 0), pady=(0, 6))

        self.rest_all_btn = ttk.Button(g, text="", command=self.do_restore)
        self.rest_all_btn.grid(row=1, column=1, sticky="w", padx=(6, 0))
        self.rest_sel_btn = ttk.Button(g, text="", command=self.do_restore_sel)
        self.rest_sel_btn.grid(row=1, column=2, sticky="w", padx=(6, 0))
        self.rest_box = ttk.Combobox(g, state="readonly", width=34)
        self.rest_box.grid(row=1, column=3, sticky="w", padx=(10, 0))
        self.inst_lbl = ttk.Label(g, text="", foreground="#0a6")
        self.inst_lbl.grid(row=1, column=4, sticky="w", padx=8)

        self.tip_lbl = ttk.Label(bot, text="", foreground="#555", justify="left", wraplength=1010)
        self.tip_lbl.pack(fill="x", pady=(8, 0))

    # ---------- 简化模式（给普通玩家）----------
    def _build_simple_ui(self, parent):
        self.s_grp = ttk.LabelFrame(parent, text="")
        self.s_grp.pack(fill="x", padx=8, pady=8)
        self._row(self.s_grp, 0, "mod_dir", self.out_var, self._pick_out)
        self._row(self.s_grp, 1, "game_paks", self.game_var, lambda: self._pick_dir(self.game_var), folder=True)

        bot = ttk.Frame(parent); bot.pack(fill="x", padx=8)
        g = ttk.Frame(bot); g.pack(fill="x")
        self.s_inst_btn = ttk.Button(g, text="", command=self.do_install_all)
        self.s_inst_btn.grid(row=0, column=0, sticky="w", pady=(0, 6))
        self.s_batch_btn = ttk.Button(g, text="", command=self.do_batch)
        self.s_batch_btn.grid(row=0, column=1, sticky="w", padx=(6, 0), pady=(0, 6))
        self.s_rest_all_btn = ttk.Button(g, text="", command=self.do_restore)
        self.s_rest_all_btn.grid(row=1, column=0, sticky="w")
        self.s_rest_sel_btn = ttk.Button(g, text="", command=self.do_restore_sel)
        self.s_rest_sel_btn.grid(row=1, column=1, sticky="w", padx=(6, 0))
        self.s_rest_box = ttk.Combobox(g, state="readonly", width=34)
        self.s_rest_box.grid(row=1, column=2, sticky="w", padx=(10, 0))
        self.s_inst_lbl = ttk.Label(g, text="", foreground="#0a6")
        self.s_inst_lbl.grid(row=1, column=3, sticky="w", padx=8)

        self.s_tip = ttk.Label(bot, text="", foreground="#555", justify="left", wraplength=1010)
        self.s_tip.pack(fill="x", pady=(8, 0))

    # ---------- 模式切换 ----------
    MODES = ("simple", "full", "vision")   # 内部支持：simple 留给独立安装器入口
    UI_MODES = ("full", "vision") if SHOW_VISION else ("full",)   # 幻兵祠堂入口默认隐藏


    # ---------- 幻兵祠堂语音替换工具（第三种模式）----------
    # 幻兵的闪回动画与音频库**不是一一对应**：一个幻兵的所有闪回共用同一个旁白库。
    # 所以这里不跟影片挂钩，而是直接列出该幻兵语音库的所有条目，逐条指定替换。
    def _build_vision_ui(self, parent):
        grp = ttk.LabelFrame(parent, text="")
        self.v_grp_src = grp
        grp.pack(fill="x", padx=8, pady=6)
        self.v_src_var = tk.StringVar(value=self.settings.get("audio_path", ""))
        self.v_out_var = tk.StringVar(value=self.settings.get("vis_out", "")
                                      or self.settings.get("out_dir", ""))
        self._row(grp, 0, "vis_src", self.v_src_var, self._v_pick_src)
        self._row(grp, 1, "vis_out", self.v_out_var, self._v_pick_out, folder=True)
        # 「扫描/刷新」放在前两个按钮下方，列对齐
        self.v_scan_btn = ttk.Button(grp, text="", width=12, command=self.vision_scan)
        self.v_scan_btn.grid(row=2, column=2, padx=8, pady=(3, 8))   # 与上面的「选择…/指定…」同列同宽

        # 本界面不重复放「外部工具」区 —— 直接复用「MOD 制作」里那组路径
        # （两边本来就是同一组 StringVar），注意事项里说明了这一点。
        self.v_grp_list = ttk.LabelFrame(parent, text="")
        self.v_grp_list.pack(fill="both", expand=True, padx=8)
        # 表头放进滚动区第 0 行 —— 和每一行用同一套 grid 列，才能跟数据列对齐
        wrap = ttk.Frame(self.v_grp_list); wrap.pack(fill="both", expand=True, padx=6, pady=(2, 6))
        self.v_canvas = tk.Canvas(wrap, height=360, highlightthickness=0)
        vsb = ttk.Scrollbar(wrap, orient="vertical", command=self.v_canvas.yview)
        self.v_rows_frame = ttk.Frame(self.v_canvas)
        self.v_win = self.v_canvas.create_window((0, 0), window=self.v_rows_frame, anchor="nw")
        self.v_canvas.configure(yscrollcommand=vsb.set)
        self.v_canvas.pack(side="left", fill="both", expand=True); vsb.pack(side="right", fill="y")
        self.v_rows_frame.bind("<Configure>", lambda e: self.v_canvas.configure(
            scrollregion=self.v_canvas.bbox("all")))
        self.v_canvas.bind("<Configure>", lambda e: self.v_canvas.itemconfigure(self.v_win, width=e.width))
        for w in (self.v_canvas, self.v_rows_frame):
            w.bind("<MouseWheel>", lambda e: self.v_canvas.yview_scroll(int(-e.delta / 120), "units"))

        bot = ttk.Frame(parent); bot.pack(fill="x", padx=8, pady=6)
        self.v_build_btn = ttk.Button(bot, text="", command=self.vision_build)
        self.v_build_btn.pack(side="left")
        self.v_inst_btn = ttk.Button(bot, text="", command=self.vision_install)
        self.v_inst_btn.pack(side="left", padx=6)
        self.v_rest_btn = ttk.Button(bot, text="", command=self.vision_restore)
        self.v_rest_btn.pack(side="left", padx=6)
        self.v_sum = ttk.Label(bot, text="", foreground="#555")
        self.v_sum.pack(side="left", padx=14)

        self.v_grp_tip = ttk.LabelFrame(parent, text="")
        self.v_grp_tip.pack(fill="x", padx=8, pady=(0, 6))
        self.v_tip = ttk.Label(self.v_grp_tip, text="", foreground="#555",
                               justify="left", wraplength=1000)
        self.v_tip.pack(fill="x", padx=8, pady=6)

    def vision_apply_lang(self):
        self.v_grp_src.config(text=t("vis_grp_src"))
        self.v_grp_list.config(text=t("vis_grp_list"))
        self.v_grp_tip.config(text=t("vis_tip_head"))
        self.v_scan_btn.config(text=t("vis_scan"))
        self.v_build_btn.config(text=t("vis_btn_build"))
        self.v_inst_btn.config(text=t("vis_btn_install"))
        self.v_rest_btn.config(text=t("vis_btn_restore"))
        # 表头是随列表一起建的（按需），没建出来就跳过
        if hasattr(self, "v_hdr_in"):
            self.v_hdr_in.config(text=t("vis_col_ingame"))
        if hasattr(self, "v_hdr_imp"):
            self.v_hdr_imp.config(text=t("vis_col_import"))
        self.v_tip.config(text="\n".join(t("vis_tip_%d" % i) for i in range(1, 6)))
        for r in getattr(self, "v_rows", []):
            r["play"].config(text=t("vis_btn_audition"))
            r["play2"].config(text=t("vis_btn_audition"))
            self._v_fill_combo(r)

    def _v_pick_src(self):
        p = filedialog.askdirectory(title=t("vis_src"))
        if p:
            self.v_src_var.set(p)
            self.vision_scan(silent=True)

    def _v_pick_out(self):
        p = filedialog.askdirectory(title=t("vis_out"))
        if p:
            self.v_out_var.set(p)

    # ---- 数据：从 MOD制作 已解析的影片里找幻兵闪回 ----
    def _vision_banks(self) -> dict:
        idx = self.audio_index or {}
        found = {}
        for o in list(getattr(self, "orig_list", [])):
            key = self._movie_key(o)
            if not key:
                continue
            for e in idx.get("movie_audio", {}).get(key, []):
                if e.get("whole") and str(e.get("bank", "")).startswith("VO_ADV_LEGENDEV_"):
                    found[e["bank"]] = e.get("entry_count") or 0
        return found

    def _vision_entries(self, bank: str) -> list:
        b = (self.audio_index or {}).get("banks", {}).get(bank, {})
        m = {}
        for cue, rec in (b.get("cues") or {}).items():
            for e in rec.get("entries") or []:
                m.setdefault(e["id"], (cue, rec.get("duration_us", 0)))
        return [(k, m[k][0], m[k][1]) for k in sorted(m)]

    def _vision_available(self) -> bool:
        if getattr(self, "v_rows", []):
            return True
        self.log(t("vis_unavailable"))
        messagebox.showinfo(APP_NAME, t("vis_unavailable"))
        return False

    def vision_scan(self, silent=False):
        # 原视频清单取自「MOD制作」；那儿没解析过就顺手扫一下原视频路径
        if not getattr(self, "orig_list", []) and hasattr(self, "orig_var"):
            p = Path(self.orig_var.get()) if self.orig_var.get() else None
            if p and p.exists():
                self._scan_orig(p)
        banks = self._vision_banks()
        for w in self.v_rows_frame.winfo_children():
            w.destroy()
        self.v_rows = []
        self.v_preview = {}
        if not banks:
            self.v_sum.config(text=t("vis_none"))
            self.log(t("vis_unavailable"))
            self._fit_window()
            return
        self.v_sum.config(text=t("vis_found", n=len(banks),
                                 v=", ".join(sorted(b.replace("VO_ADV_LEGENDEV_", "幻兵")
                                                    for b in banks))))
        self.log(t("vis_found", n=len(banks), v=", ".join(sorted(banks))))
        # 试听缓存：把整库音频先解出来（用户要的"提前放到缓存里方便试听"）
        for bank in sorted(banks):
            try:
                info = (self.audio_index or {}).get("banks", {}).get(bank, {})
                paks = self._vision_paks()
                if paks:
                    self.v_preview[bank] = ensure_bank_preview(bank, info, paks,
                                                               Path(App.RETOC), self.log)
            except Exception as e:
                self.log(t("vis_play_fail", e=e))
        self._vision_fill(banks)
        self._fit_window()

    def _vision_paks(self):
        root = self._game_root()
        return (root / "FFRS" / "Content" / "Paks") if root else None

    def _vision_fill(self, banks):
        for w in self.v_rows_frame.winfo_children():
            w.destroy()
        self.v_rows = []
        self.v_hdr_in = ttk.Label(self.v_rows_frame, text=t("vis_col_ingame"),
                                  anchor="w", foreground="#0a6")
        self.v_hdr_in.grid(row=0, column=0, sticky="w", padx=4, pady=(2, 4))
        self.v_hdr_imp = ttk.Label(self.v_rows_frame, text=t("vis_col_import"),
                                   anchor="w", foreground="#0a6")
        self.v_hdr_imp.grid(row=0, column=2, sticky="w", pady=(2, 4))
        r = 1
        for bank in sorted(banks):
            lab = ttk.Label(self.v_rows_frame, text=t("vis_entries", bank=bank, n=0),
                            foreground="#0a6")
            lab.grid(row=r, column=0, columnspan=4, sticky="w", padx=4, pady=(8, 2))
            r += 1
            ents = self._vision_entries(bank)
            for entry, cue, dur in ents:
                name = ttk.Label(self.v_rows_frame, anchor="w",
                                 text="%03d  %-34s %6.2fs" % (entry + 1, cue or "-", dur / 1e6))
                name.grid(row=r, column=0, sticky="w", padx=4, pady=1)
                pu = ttk.Button(self.v_rows_frame, text="", width=6,
                                command=lambda b=bank, e=entry: self._vision_play_ingame(b, e))
                pu.grid(row=r, column=1, padx=(4, 16), pady=1)
                var = tk.StringVar()
                combo = ttk.Combobox(self.v_rows_frame, state="readonly", width=30, textvariable=var)
                combo.grid(row=r, column=2, sticky="w", pady=1)
                p2 = ttk.Button(self.v_rows_frame, text="", width=6,
                                command=lambda v=var: self._vision_play_import(v))
                p2.grid(row=r, column=3, padx=(6, 4), pady=1)
                row = {"bank": bank, "entry": entry, "cue": cue, "dur_us": dur,
                       "var": var, "combo": combo, "play": pu, "play2": p2}
                self.v_rows.append(row)
                self._v_fill_combo(row)
                r += 1
        self.vision_apply_lang()

    def _v_fill_combo(self, row):
        lst = list(getattr(self, "audio_list", []))
        row["combo"]["values"] = [t("vis_skip")] + [f.name for f in lst]
        row["var"].set(t("vis_skip"))

    def _vision_src_of(self, row):
        i = row["combo"].current()
        lst = list(getattr(self, "audio_list", []))
        return lst[i - 1] if 1 <= i <= len(lst) else None

    def _vision_play_ingame(self, bank, entry):
        if not self._vision_available():
            return
        w = (self.v_preview.get(bank) or {}).get(entry)
        if not w:
            self.log(t("vis_play_fail", e="无试听缓存"))
            return
        try:
            play_audio(w)
        except Exception as e:
            self.log(t("vis_play_fail", e=e))

    def _vision_play_import(self, var):
        if not self._vision_available():
            return
        lst = list(getattr(self, "audio_list", []))
        try:
            i = [f.name for f in lst].index(var.get())
        except ValueError:
            self.log(t("vis_play_fail", e=var.get()))
            return
        try:
            play_audio(lst[i])
        except Exception as e:
            self.log(t("vis_play_fail", e=e))

    def vision_build(self):
        if not self._vision_available():
            return
        jobs = []
        for row in self.v_rows:
            src = self._vision_src_of(row)
            if src:
                jobs.append({"bank": row["bank"], "entry": row["entry"], "src": src})
        if not jobs:
            messagebox.showinfo(APP_NAME, t("vis_nothing")); return
        out = Path(self.v_out_var.get().strip() or APP_DIR)
        out.mkdir(parents=True, exist_ok=True)
        self.busy = True
        self.status.config(text=t("vis_building"))
        try:
            App.RETOC = self.rt_var.get()
            paks = self._vision_paks()
            if paks is None:
                raise RuntimeError(t("err_no_game"))
            utoc = build_audio_patch(self.audio_index, jobs, out, Path(App.RETOC), paks,
                                     self.log, base="VisionVoice_P")
            self.last_patch = utoc
            self.log(t("vis_built", p=Path(utoc).name))
            self.status.config(text=t("vis_built", p=Path(utoc).name))
        except Exception as e:
            self.log(t("build_fail", e=e)); self.status.config(text=t("build_fail", e=e))
        finally:
            self.busy = False

    def vision_install(self):
        if not self._vision_available():
            return
        patch = getattr(self, "last_patch", None)
        if not patch or not Path(patch).exists():
            messagebox.showinfo(APP_NAME, t("vis_nothing")); return
        paks = self._vision_paks()
        if paks is None:
            messagebox.showwarning(APP_NAME, t("err_no_game")); return
        if not messagebox.askyesno(APP_NAME, t("audio_install_hint")):
            return
        try:
            names = install_audio_patch(Path(patch), paks)
            self.log(t("audio_installed", p=", ".join(names)))
            self.status.config(text=t("audio_installed", p=", ".join(names)))
        except Exception as e:
            self.log(t("install_fail", e=e)); self.status.config(text=t("install_fail", e=e))

    def vision_restore(self):
        paks = self._vision_paks()
        if paks is None:
            messagebox.showwarning(APP_NAME, t("err_no_game")); return
        try:
            n = remove_audio_patch(paks)
            self.log(t("vis_restored", n=n))
            self.status.config(text=t("vis_restored", n=n))
        except Exception as e:
            self.log(t("install_fail", e=e))

    def _on_mode(self, _=None):
        i = self.mode_box.current()
        self.mode = App.UI_MODES[i] if 0 <= i < len(App.UI_MODES) else "full"
        self.apply_mode()
        self._save_settings()          # 记住，下次打开直接进这个模式

    def apply_mode(self):
        mode = getattr(self, "mode", "full")
        if mode not in App.MODES:
            mode = "full"
        # 简化模式只保留给独立安装器（FFRS_VideoMod_Simple.py，SIMPLE_ONLY=True）；
        # 主程序的下拉里已经没有它了。
        if mode == "simple" and not App.SIMPLE_ONLY:
            mode = "full"
        for fr in (self.simple_ui, self.full_ui, self.vision_ui):
            fr.pack_forget()
        {"simple": self.simple_ui, "full": self.full_ui,
         "vision": self.vision_ui}[mode].pack(fill="both", expand=True)
        if hasattr(self, "mode_box"):
            self.mode_box.current(App.UI_MODES.index(mode) if mode in App.UI_MODES else 0)
        if hasattr(self, "s_tip"):
            self.s_tip.config(wraplength=740)
        self.refresh_installed()
        if mode == "vision":
            self.vision_scan(silent=True)      # 进来自动扫一次
        self._fit_window()

    def _on_wheel(self, e):
        try:
            self.s_canvas.yview_scroll(int(-e.delta / 120), "units")
        except Exception:
            pass

    def _scroll_region(self):
        try:
            self.s_canvas.configure(scrollregion=self.s_canvas.bbox("all"))
        except Exception:
            pass
        self._update_scrollbars()

    def _update_scrollbars(self, _=None):
        """内容装得下就不显示滚动条；装不下（屏幕小 / 窗口被拉小）才出现。"""
        if getattr(self, "s_busy", False) or not hasattr(self, "s_inner"):
            return
        self.s_busy = True
        try:
            self.update_idletasks()
            nw, nh = self.s_inner.winfo_reqwidth(), self.s_inner.winfo_reqheight()
            cw, ch = self.s_canvas.winfo_width(), self.s_canvas.winfo_height()
            if cw <= 1 or ch <= 1:
                return
            vw = self.s_vsb.winfo_reqwidth() or 16
            hh = self.s_hsb.winfo_reqheight() or 16
            need_v = nh > ch
            need_h = nw > cw - (vw if need_v else 0)
            if need_h and not need_v:            # 横向滚动条本身也会占掉高度
                need_v = nh > ch - hh
            if need_v:
                self.s_vsb.grid(row=0, column=1, sticky="ns")
            else:
                self.s_vsb.grid_forget()
            if need_h:
                self.s_hsb.grid(row=1, column=0, sticky="ew")
            else:
                self.s_hsb.grid_forget()
            self.s_canvas.itemconfigure(
                self.s_win, width=max(nw, cw - (vw if need_v else 0)))
        except Exception:
            pass
        finally:
            self.s_busy = False

    def _fit_window(self):
        """按内容定窗口大小。

        * 屏幕装得下 → 窗口正好等于内容需要的大小（**不出现滚动条**）
        * 屏幕装不下 → 窗口用满可用区域，滚动条出现
        * 之后用户手动拉小窗口 → 内容超出，滚动条也会自动出现
        """
        try:
            self.update_idletasks()
            sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
            nw, nh = self.s_inner.winfo_reqwidth(), self.s_inner.winfo_reqheight()
            extra = (self.status.winfo_reqheight() or 21) + 24
            want_w, want_h = nw + 24, nh + extra
            max_w, max_h = sw - 60, sh - 90
            fits = want_w <= max_w and want_h <= max_h
            w = want_w if fits else min(max_w, max(want_w, 640))
            h = want_h if fits else min(max_h, max(want_h, 460))
            self.minsize(min(640, sw - 80), min(460, sh - 120))
            self.geometry("%dx%d" % (int(w), int(h)))
            self._update_scrollbars()
        except Exception:
            pass

    def _row(self, parent, r, key, var, cmd, folder=False, entry_w=60):
        lbl = ttk.Label(parent, text="", width=26)
        lbl.grid(row=r, column=0, sticky="w", padx=8, pady=3)
        lbl._key = key
        e = ttk.Entry(parent, textvariable=var, width=entry_w)
        e.grid(row=r, column=1, sticky="ew", padx=4, pady=3)
        parent.grid_columnconfigure(1, weight=1)
        b = ttk.Button(parent, text="", command=cmd, width=12)
        b.grid(row=r, column=2, padx=8, pady=3)
        b._key = "browse_dir" if folder else "browse"
        self._labeled = getattr(self, "_labeled", []) + [(lbl,), (b,)]

    def apply_lang(self):
        self.title(t("title_simple") if App.SIMPLE_ONLY else t("title"))
        for w in self.winfo_children():
            pass
        self.lang_lbl.config(text=t("lang"))
        self.mode_lbl.config(text=t("mode_lbl"))
        self.mode_box.config(values=[t("mode_full"), t("mode_vision")])
        _m = getattr(self, "mode", "full")
        self.mode_box.current(App.UI_MODES.index(_m) if _m in App.UI_MODES else 0)
        self.vision_apply_lang()
        self.grp_src.config(text=t("grp_src"))
        self.grp_tools.config(text=t("tools"))
        self.grp_prev.config(text=t("grp_preview"))
        self.grp_log.config(text=t("log"))
        self.grp_merge.config(text=t("grp_merge"))
        rows = [self.grp_src, self.grp_tools, self.s_grp, self.v_grp_src]
        if self.SHOW_MERGE:
            rows.insert(2, self.grp_merge)
        for row in rows:
            for child in row.winfo_children():
                if hasattr(child, "_key"):
                    child.config(text=t(child._key))
        # 简化模式
        self.s_grp.config(text=t("grp_src"))
        self.s_inst_btn.config(text=t("btn_install_all"))
        self.s_batch_btn.config(text=t("batch_btn"))
        self.s_rest_all_btn.config(text=t("restore_all"))
        self.s_rest_sel_btn.config(text=t("restore_sel"))
        self.s_tip.config(text=t("simple_tip"))
        self.check_btn.config(text=t("check"))
        self.parse_btn.config(text=t("btn_parse"))
        self.lbl_o.config(text=t("lbl_orig_sel") + ":")
        self.lbl_n.config(text=t("lbl_new_sel") + ":")
        self.lbl_a.config(text=t("lbl_audio_sel") + ":")
        self.gain_lbl.config(text=t("audio_gain"))
        cur = self._gain_idx()
        self.gain_box["values"] = [gain_label(i) for i in range(len(AUDIO_GAIN_MODES))]
        self.gain_box.current(cur)
        self.refresh_audio()
        # ★ 文案填完之后必须重算窗口尺寸：build_ui() 末尾那次算的时候标签还是空的，
        #   等这里把中文/英文填上，内容会变宽，窗口不够宽就会把最后 pack 的
        #   播放/暂停按钮挤成 1 像素宽（实测就是这个原因看不见）。
        self._fit_window()
        self.play_btn.config(text=t("btn_pause") if (self.pv_orig.playing or self.pv_new.playing) else t("btn_play"))
        self.pv_orig.set_title("preview_orig"); self.pv_new.set_title("preview_new")
        self.build_btn.config(text=t("btn_build"))
        self.inst_btn.config(text=t("btn_install"))
        self.rest_all_btn.config(text=t("restore_all"))
        self.rest_sel_btn.config(text=t("restore_sel"))
        self.batch_btn.config(text=t("batch_btn"))
        if getattr(self, "batch_win", None) is not None and self.batch_win.winfo_exists():
            self.batch_win.apply_lang()
        self.grp_info.config(text=t("info_title"))
        self.tip_lbl.config(text="\n".join(
            [t("tip_head")] + [t("tip_%d" % i) for i in range(1, 7)]))
        idx = self.audio_index or {}
        if idx:
            self.log(t("audio_index_ok", m=len(idx.get("movie_audio", {})),
                       b=len(idx.get("banks", {}))))
        self.status.config(text="")
        self.refresh_installed()
        self.update_info()          # 切换语言后按新语言重绘对比面板

    def refresh_installed(self):
        """刷新「选择要还原的影片」下拉与已安装计数（简化模式与制作模式各有一套控件）。"""
        try:
            root = self._game_root()
            vals = []
            if root is not None:
                vals = list(Installer(root, APP_DIR / "ffrs_videomod_backup.json").list_installed())
            pairs = ((getattr(self, "rest_box", None), getattr(self, "inst_lbl", None)),
                     (getattr(self, "s_rest_box", None), getattr(self, "s_inst_lbl", None)))
            for box, lbl in pairs:
                if box is None:
                    continue
                box["values"] = vals or [t("restore_none")]
                if vals:
                    if box.get() not in vals:
                        box.current(0)
                else:
                    box.set(t("restore_none"))
                if lbl is not None:
                    lbl.config(text=t("installed_n", n=len(vals)) if vals else "")
        except Exception:
            pass

    def _active_rest_box(self):
        """当前模式对应的「还原选中」下拉。"""
        if getattr(self, "mode", "simple") == "simple" and hasattr(self, "s_rest_box"):
            return self.s_rest_box
        return self.rest_box

    def _on_lang(self, _):
        App.LANG = "zh" if self.lang_box.get() == "中文" else "en"
        self.apply_lang(); self._save_settings()

    # ---------- 选择 ----------
    @staticmethod
    def _display_names(lst: list, root: Path) -> list:
        """下拉里显示的名字：默认只用文件名；**同名时补上相对路径**，否则分不清是哪一部
        （游戏里 Skill/en 与 Skill/jp 的影片就完全同名）。"""
        from collections import Counter
        base = [x.name for x in lst]
        dup = {n for n, c in Counter(base).items() if c > 1}
        out = []
        for x, n in zip(lst, base):
            if n not in dup:
                out.append(n); continue
            try:
                out.append(f"{x.parent.relative_to(root).as_posix()}/{n}")
            except Exception:
                out.append(f"{x.parent.name}/{n}")
        return out

    def _clear_previews(self, kind: str):
        """
        路径变了就丢掉旧的预览帧。

        预览缓存目录是按**下标**命名的（o0/o1… n0/n1…），换目录后下标又从 0 开始，
        于是"第 0 项"会沿用上一个目录留下的画面 —— 这就是"切了路径点解析还是旧视频"的原因。
        """
        for d in self.tmpdir.glob(f"{kind}*"):
            shutil.rmtree(d, ignore_errors=True)
        self._previewing = {k for k in self._previewing if k[0] != kind}

    def _scan_orig(self, p: Path):
        """路径 -> 原视频列表（文件则单个，目录则递归找 .usm）。"""
        self._clear_previews("o")
        self.orig_list = [p] if p.is_file() else sorted(p.rglob("*.usm"))
        self.orig_box["values"] = (self._display_names(self.orig_list, p if p.is_dir() else p.parent)
                                   or [t("orig_none")])

    def _scan_new(self, p: Path):
        self._clear_previews("n")
        self.new_list = ([p] if p.is_file()
                         else sorted(x for x in p.rglob("*") if x.suffix.lower() in VIDEO_EXTS))
        self.new_box["values"] = (self._display_names(self.new_list, p if p.is_dir() else p.parent)
                                  or [t("new_none")])

    def _restore_paths(self) -> bool:
        """启动时恢复上次的原视频/替换视频路径与选中项，不弹任何对话框。"""
        restored = False
        op = (self.settings.get("orig_path") or "").strip()
        if op and Path(op).exists():
            self.orig_var.set(op); self._scan_orig(Path(op))
            self._select_path(self.orig_box, self.orig_list, self.settings.get("orig_sel", ""))
            self.refresh_orig(); restored = True
        npth = (self.settings.get("new_path") or "").strip()
        if npth and Path(npth).exists():
            self.new_var.set(npth); self._scan_new(Path(npth))
            self._select_path(self.new_box, self.new_list, self.settings.get("new_sel", ""))
            self.refresh_new(); restored = True
        ap = (self.settings.get("audio_path") or "").strip()
        if ap and Path(ap).exists():
            self.audio_var.set(ap); self._scan_audio(Path(ap))
            self.audio_sel_key = self.settings.get("audio_sel", "") or ""
            self.refresh_audio(); restored = True
        self._ready = True                        # 之后才允许写设置
        if restored:
            self.log("已恢复上次的原视频/替换视频路径；点「解析」刷新预览与对比。")
        return restored

    def _pick_orig(self):
        p = filedialog.askdirectory(title=t("orig_path"))
        if not p:
            f = filedialog.askopenfilename(title=t("orig_path"),
                                           filetypes=[("USM", "*.usm"), ("All", "*.*")])
            if not f: return
            self.orig_var.set(f); self._scan_orig(Path(f))
        else:
            self.orig_var.set(p); self._scan_orig(Path(p))
        if self.orig_list:
            self.orig_box.current(0); self.refresh_orig()
        self._save_settings()

    def _pick_new(self):
        p = filedialog.askdirectory(title=t("new_path"))
        if not p:
            f = filedialog.askopenfilename(title=t("new_path"),
                                           filetypes=[("Video", " ".join("*" + e for e in VIDEO_EXTS)), ("All", "*.*")])
            if not f: return
            self.new_var.set(f); self._scan_new(Path(f))
        else:
            self.new_var.set(p); self._scan_new(Path(p))
        if self.new_list:
            self.new_box.current(0); self.refresh_new()
        self._save_settings()

    def _pick_out(self):
        p = filedialog.askdirectory(title=t("out_dir"))
        if p: self.out_var.set(p); self._save_settings()

    def _pick_merge(self):
        p = filedialog.askdirectory(title=t("merge_path"))
        if p:
            self.merge_var.set(p)
            self._save_settings()

    def _pick_audio(self):
        """和「导入视频」一样：选目录或选单个文件，选完扫描出音频清单填进下拉。"""
        p = filedialog.askdirectory(title=t("audio_src"))
        if not p:
            exts = " ".join("*" + e for e in sorted(AUDIO_EXTS))
            f = filedialog.askopenfilename(title=t("audio_src"),
                                           filetypes=[("Audio", exts), ("All", "*.*")])
            if not f:
                return
            p = f
        self.audio_var.set(p)
        self._scan_audio(Path(p))
        if self.audio_list:
            self.audio_box.current(0)
        self.refresh_audio()
        self.update_info()
        self._save_settings()

    def _scan_audio(self, p: Path):
        """扫描「导入音频」路径 + 首页的 Input/AudioMOD 里的音频文件。"""
        dirs = [p]
        try:
            import kit.settings as _K
            a = _K.input_audio()
            if a.exists() and a != p:
                dirs.append(a)
        except Exception:
            pass
        found: list[Path] = []
        for d in dirs:
            try:
                if d.is_file():
                    if d.suffix.lower() in AUDIO_EXTS:
                        found.append(d)
                else:
                    found += sorted(x for x in d.rglob("*") if x.suffix.lower() in AUDIO_EXTS)
            except Exception:
                pass
        self.audio_list = found
        self.audio_meta_cache = {}

    def _pick_dir(self, var):
        p = filedialog.askdirectory(title=t("game_dir"))
        if p: var.set(p); self._save_settings()

    def _pick_file(self, var):
        p = filedialog.askopenfilename(filetypes=[("EXE", "*.exe"), ("All", "*.*")])
        if p:
            var.set(p)
            if var is self.ff_var: App.FFMPEG = p
            elif var is self.cc_var: App.CRICODECS = p
            else: App.RETOC = p
            self._save_settings()

    # ---------- 工具 ----------
    def check_tools(self):
        App.FFMPEG = self.ff_var.get(); App.CRICODECS = self.cc_var.get()
        App.RETOC = self.rt_var.get(); App.REPAK = self.rp_var.get()
        # ★ 四个工具都要参与判定。旧版 ok 只看了 ffmpeg / cricodecs，
        #   retoc 或 repak 缺失时弹窗仍然报「均有效」—— 这就是"检测不到"的 bug。
        tools = [("ffmpeg", App.FFMPEG), ("cricodecs", App.CRICODECS),
                 ("retoc", App.RETOC), ("repak", App.REPAK)]
        bad = []
        for name, p in tools:
            exists = bool(p) and Path(p).is_file()
            self.log("%s: %s  (%s)" % (name, p or t("tool_path_empty"),
                                       t("tool_ok") if exists else t("tool_missing")))
            if not exists:
                bad.append(name)
        if self._game_root() is None:
            self.log(t("err_no_game"))
        self._save_settings()
        if bad:
            messagebox.showwarning(APP_NAME, t("check_bad_names", names=", ".join(bad)))
        else:
            messagebox.showinfo(APP_NAME, t("check_ok"))

    def log(self, s):
        try:
            import kit.i18n as _I
            s = _I.tr_log(str(s))
            self.logq.put(str(s))
        except Exception:
            self.logq.put(str(s))

    def _drain(self):
        try:
            while True:
                self.log_txt.insert("end", self.logq.get_nowait() + "\n"); self.log_txt.see("end")
        except queue.Empty:
            pass
        # 解析是在工作线程里跑完的，这里（主线程）负责刷新预览与对比面板
        if getattr(self, "_need_refresh", False):
            self._need_refresh = False
            try:
                self.refresh_orig(); self.refresh_new()
            except Exception:
                pass
        self.after(100, self._drain)

    # ---------- 解析 / 预览 ----------
    def do_parse(self):
        if not self.orig_list or not self.new_list:
            messagebox.showwarning(APP_NAME, t("need_paths")); return
        self.status.config(text=t("parsing"))
        threading.Thread(target=self._parse_worker, daemon=True).start()

    def _parse_worker(self):
        """只解析参数（快）+ 按需解预览帧。
        预览帧不再在这里全解 —— 一次性解几十部影片会卡很久，而且旧版只解前 20 个，
        导致排在后面的类别（Skill / Summon）永远没有预览。现在改成选中哪部解哪部。"""
        try:
            App.FFMPEG = self.ff_var.get(); App.CRICODECS = self.cc_var.get()
            self.log(f"原视频目录：{self.orig_var.get() or '（空）'}")
            self.log(f"替换视频目录：{self.new_var.get() or '（空）'}")
            self.log(f"音频素材目录：{self.audio_var.get() or '（空）'}")
            if not self.orig_list:
                try:
                    import kit.settings as _K
                    alt = _K.input_video()
                    if alt.exists():
                        self._scan_orig(alt)
                        self.orig_var.set(str(alt))
                        self.log(f"⚠ 原视频目录为空，已改用 {alt} 重新扫描（{len(self.orig_list)} 个）")
                except Exception:
                    pass
            self.orig_meta = {}
            for u in self.orig_list:
                m = parse_usm(u)
                self.orig_meta[str(u)] = m
                if m:
                    self.log(f"[原] {u.name}: {m.get('w')}x{m.get('h')} @{m.get('fps')} "
                             f"frames={m.get('frames')} alpha={m.get('has_alpha')} audio={m.get('has_audio')}")
                else:
                    self.log(f"[原] {u.name}: 解析失败（可能不是标准 USM）")
            self.new_meta = {}
            for v in self.new_list:
                m = probe(v)
                self.new_meta[str(v)] = m
                if m:
                    self.log(f"[新] {v.name}: {m.get('w')}x{m.get('h')} @{m.get('fps')} frames={m.get('frames')}")
            self._need_refresh = True      # 交给主线程的 _drain 刷新预览与对比面板
            self.status.config(text=t("parse_done", n=len(self.orig_list), m=len(self.new_list)))
        except Exception as e:
            self.log(t("parse_fail", e=e))
            self.status.config(text=t("parse_fail", e=e))

    def _preview_dir(self, kind: str, idx: int) -> Path:
        return self.tmpdir / f"{kind}{idx}"

    def _preview_frames(self, kind: str, idx: int):
        """某项的预览帧所在目录（两者布局不同：原片在 <dir>/f，替换片直接在 <dir>）。"""
        d = self._preview_dir(kind, idx)
        return (d / "f") if kind == "o" else d

    def _need_tools(self, usm: bool = False) -> bool:
        """预览/编码前检查外部工具路径；无效就给出明确提示而不是 WinError 2。"""
        need = [("cricodecs", App.CRICODECS, t("tool_cricodecs"))] if usm else []
        need.append(("ffmpeg", App.FFMPEG, t("tool_ffmpeg")))
        bad = [(k, p, label) for k, p, label in need if not (p and Path(p).is_file())]
        if bad:
            for k, p, label in bad:
                self.log(t("tool_path_bad", label=label, p=(p or t("tool_path_empty"))))
            self.log(t("tool_path_hint"))
            return False
        return True

    def _ensure_preview(self, kind: str, idx: int):
        # 先确认外部工具可用，否则线程里只会抛一个看不懂的 WinError 2
        lst = self.orig_list if kind == "o" else self.new_list
        if 0 <= idx < len(lst):
            if not self._need_tools(usm=(lst[idx].suffix.lower() == USM_EXT)):
                return
        self._ensure_preview_impl(kind, idx)

    def _ensure_preview_impl(self, kind: str, idx: int):
        """按需解出某一项的预览帧（只解当前选中的那一个）。"""
        lst = self.orig_list if kind == "o" else self.new_list
        if not (0 <= idx < len(lst)):
            return
        if any(self._preview_frames(kind, idx).glob("f_*.png")):
            return                                  # 已经解过
        key = (kind, idx)
        if key in self._previewing:
            return                                  # 正在解
        item = lst[idx]
        outdir = self._preview_dir(kind, idx)
        self._previewing.add(key)

        def work():
            try:
                if kind == "o":
                    self._preview_usm(item, outdir)
                else:
                    grab_frames(item, outdir)
            except Exception as e:
                self.log(f"预览失败 {item.name}: {e}")
            finally:
                self._previewing.discard(key)
                self._need_refresh = True           # 解完让主线程刷新画面

        threading.Thread(target=work, daemon=True).start()

    def _preview_usm(self, usm: Path, outdir: Path):
        """
        解出 USM 的视频流再抽帧。

        ⚠ cricodecs 的 -o 语义**随流数变化**（实测）：
            多流 USM（有 alpha / 音频） -> -o 当**目录**，在里面写出 xxx.ivf / xxx.sfv / …
            单流 USM（只有 @SFV）       -> -o 当**文件**，直接写那一个流；
                                          若该路径已存在（尤其是个目录）就报 "could not create file"
        本作 Event 类的 27 部都是单流，所以必须两种都试。
        """
        try:
            outdir.mkdir(parents=True, exist_ok=True)

            def first_video(d: Path):
                for f in sorted(d.glob("*")):
                    if f.is_file() and f.suffix.lower() in VIDEO_STREAM_EXTS:
                        return f
                return None

            # 每次从干净目录开始（残留文件会让 cricodecs 拒绝写入）
            for old in outdir.glob("*"):
                try:
                    old.unlink() if old.is_file() else __import__("shutil").rmtree(old, ignore_errors=True)
                except Exception:
                    pass
            self.log(f"[预览] cricodecs={App.CRICODECS}｜输入={usm}｜输出目录={outdir}")

            # ① 按"目录"用（多流影片）
            rc1, out1, err1 = run([App.CRICODECS, usm, "-o", outdir], timeout=1800)
            vid = first_video(outdir)
            if vid is None:
                self.log(f"[预览] 目录模式 rc={rc1} 输出={ (out1 or err1)[:200] }")

            # ② 按"文件"用（单流影片）
            if vid is None:
                dst = outdir / "stream.bin"
                rc2, out2, err2 = run([App.CRICODECS, usm, "-o", dst], timeout=1800)
                if dst.exists() and dst.stat().st_size > 0:
                    vid = dst
                else:
                    self.log(f"[预览] 文件模式 rc={rc2} 输出={ (out2 or err2)[:200] }")

            if vid is None:
                self.log(f"预览解流失败：{usm.name}（cricodecs 没解出视频流；详见上面两行 rc/输出）")
                return
            grab_frames(vid, outdir / "f")
        except Exception as e:
            self.log(f"preview fail {usm.name}: {e}")

    def refresh_orig(self):
        i = self.orig_box.current()
        if not (0 <= i < len(self.orig_list)):
            return
        info = self.orig_meta.get(str(self.orig_list[i])) if hasattr(self, "orig_meta") else None
        txt = ""
        if info:
            txt = f"{info.get('w')}x{info.get('h')} @{round(info.get('fps', 0), 3)}fps  " \
                  f"{'alpha ' if info.get('has_alpha') else ''}{'audio' if info.get('has_audio') else ''}"
        self.pv_orig.load(self._preview_frames("o", i), txt)
        if not any(self._preview_frames("o", i).glob("f_*.png")):
            self.pv_orig.clear(t("preview_loading"))
        self._ensure_preview("o", i)
        self.refresh_audio()          # 换了原片 -> 音频候选也要跟着变
        self.update_info()

    def refresh_new(self):
        i = self.new_box.current()
        if not (0 <= i < len(self.new_list)):
            return
        info = self.new_meta.get(str(self.new_list[i])) if hasattr(self, "new_meta") else None
        txt = ""
        if info:
            txt = f"{info.get('w')}x{info.get('h')} @{round(info.get('fps', 0), 3)}fps  frames={info.get('frames')}"
        self.pv_new.load(self._preview_frames("n", i), txt)
        if not any(self._preview_frames("n", i).glob("f_*.png")):
            self.pv_new.clear(t("preview_loading"))
        self._ensure_preview("n", i)
        self.update_info()

    # ---------- 替换音频 ----------
    # 「导入音频」选的是路径（和导入视频一样），下拉里列的是**该路径下扫到的音频文件**；
    # 游戏侧要替换的那条音效由**原视频**自动确定（见 auto_audio_target），必要时可手动改。

    def refresh_audio(self):
        """把「导入音频」路径里扫到的音频文件填进「替换音频」下拉。"""
        if not hasattr(self, "audio_box"):
            return
        lst = getattr(self, "audio_list", [])
        # ★ 第 0 项永远是「不替换」：幻兵的闪回动画和音频库不是一一对应，
        #   做纯视频替换时必须能明确地"不换音频"。
        vals = [t("audio_skip")]
        for f in lst:
            k = str(f)
            if k not in self.audio_meta_cache:
                self.audio_meta_cache[k] = audio_meta(f) or {}
            d = (self.audio_meta_cache[k] or {}).get("duration")
            vals.append(f.name if not d else "%s   (%.2fs)" % (f.name, d))
        keep = getattr(self, "audio_sel_key", "")
        self.audio_box["values"] = vals
        idx = 0
        if keep:
            try:
                idx = 1 + [str(x) for x in lst].index(keep)
            except ValueError:
                idx = 0
        self.audio_box.current(idx)
        self.on_audio_selected()

    def on_audio_selected(self, save=True):
        lst = getattr(self, "audio_list", [])
        i = self.audio_box.current()
        # 0 = 不替换；1.. = 导入目录里的第 1.. 个文件
        self.audio_skip = (i <= 0)
        self.audio_src = lst[i - 1] if 1 <= i <= len(lst) else None
        self.audio_sel_key = str(self.audio_src) if self.audio_src else ""
        if save:
            self._save_settings()
        self.update_info()

    def _gain_idx(self) -> int:
        try:
            i = self.gain_box.current()
            return min(max(int(i), 0), len(AUDIO_GAIN_MODES) - 1)
        except Exception:
            return 0

    def auto_audio_target(self):
        """由**原视频**自动定位要替换的音频条目。

        规则：取该影片在桥段里触发的音效中，**时长与影片最接近**的那条 ——
        与画面同步播放的就是它（实测：Siren 8.433s ↔ SEIREN_MOVIE 8.442s；
        Bahamut 15.133s ↔ BAHAMUT_MOVIE 15.148s；技能影片同理）。
        找不到配对的返回 None，此时可用「指定目标…」手动挑。
        """
        o, _n = self._selected()
        key = self._movie_key(o)
        if not key or not self.audio_index:
            return None
        movie_map = self.audio_index.get("movie_audio", {}) or {}
        entries = movie_map.get(key)
        if entries is None:
            # 原视频可能来自任意目录（不再含 Movies/ 前缀），按"文件名去扩展名"做唯一匹配
            stem = Path(str(o)).stem.lower()
            hits = [k for k in movie_map if k.split("/")[-1].lower() == stem]
            if len(hits) == 1:
                entries = movie_map[hits[0]]
                self.log(f"提示：原视频不在 Movies/ 结构下，已按文件名配对到 {hits[0]}（正常现象）")
            else:
                entries = []
        items = [e for e in (entries or [])
                 if (self.audio_index["banks"].get(e["bank"], {}) or {}).get("storage") == "memory"]
        if not items:
            return None
        # 整库级目标（Legend 闪回）优先度低于精确到条目的目标
        single = [e for e in items if not e.get("whole")]
        if not single:
            return items[0]
        vd = self._secs((getattr(self, "orig_meta", {}) or {}).get(str(o)) or {})
        if not vd:
            return single[0]
        return min(single, key=lambda e: abs(e.get("dur_us", 0) / 1e6 - vd))

    def current_audio_target(self):
        return self.auto_audio_target()

    @staticmethod
    def _movie_key(o) -> str | None:
        """把「原视频」路径转成索引里的键，如 'Summon/MV_summon300010_vp9'。"""
        if o is None:
            return None
        s = str(o).replace("\\", "/")
        m = re.search(r"Movies/(.+?)\.usm$", s)
        if m:
            return m.group(1)
        return Path(s).stem if s.endswith(".usm") else None

    # ---------- 参数对比 / 提醒 ----------
    @staticmethod
    def _secs(meta: dict):
        """从参数里推时长（秒）。USM 用 帧数/帧率，普通视频用 duration 或 帧数/帧率。"""
        if not meta:
            return None
        if meta.get("duration"):
            return float(meta["duration"])
        f, n = meta.get("fps"), meta.get("frames")
        if f and n:
            return float(n) / float(f)
        return None

    def update_info(self):
        """在预览下方重绘「原视频 vs 替换视频」的对比与提醒。"""
        if not hasattr(self, "info_txt"):
            return
        w = self.info_txt
        w.configure(state="normal")
        w.delete("1.0", "end")

        def put(s, tag=None):
            w.insert("end", s + "\n", tag or ())

        o = self._selected()[0]
        n = self._selected()[1]
        om = (self.orig_meta.get(str(o)) if hasattr(self, "orig_meta") and o else None)
        nm = (self.new_meta.get(str(n)) if hasattr(self, "new_meta") and n else None)

        if not om and not nm:
            put(t("info_hint"))
            w.configure(state="disabled")
            return

        def line(label, meta):
            if not meta:
                put(f"{label:<8} {t('info_na')}")
                return
            s = self._secs(meta)
            put(f"{label:<8} " + t("info_line",
                                   w=meta.get("w", "?"), h=meta.get("h", "?"),
                                   fps=round(meta.get("fps") or 0, 3),
                                   n=meta.get("frames", "?"),
                                   s=("?" if s is None else f"{s:.2f}")), "mono")

        line(t("info_orig"), om)
        line(t("info_new"), nm)

        # —— 音频：游戏侧目标（由原视频自动定位）vs 导入的替换音频 ——
        a_t = self.current_audio_target()
        a_path = getattr(self, "audio_src", None)
        a_meta = None
        if a_path and Path(a_path).exists():
            k = str(a_path)
            if k not in self.audio_meta_cache:
                self.audio_meta_cache[k] = audio_meta(Path(a_path)) or {}
            a_meta = self.audio_meta_cache[k]
        if getattr(self, "audio_skip", True):
            put(f"{t('info_audio_at'):<8} {t('audio_skip_note')}")
        elif a_t and a_t.get("whole"):
            put(f"{t('info_audio_at'):<8} " + t("info_audio_whole",
                bank=a_t.get("bank", "?"), n=a_t.get("entry_count", "?"),
                m=len(getattr(self, "audio_list", []))), "mono")
        elif a_t:
            put(f"{t('info_audio_at'):<8} " + t("info_audio_line",
                s="%.2f" % (a_t.get("dur_us", 0) / 1e6), cue=a_t.get("cue", "?"),
                bank=a_t.get("bank", "?"), e=a_t.get("entry", -1)), "mono")
        else:
            put(f"{t('info_audio_at'):<8} {t('info_audio_noaudio')}")
        if a_path and Path(a_path).exists():
            m = a_meta or {}
            put(f"{t('info_audio_new'):<8} %.2f 秒   %s  (%s Hz / %s ch)   %s"
                % (m.get("duration") or 0, Path(a_path).name,
                   m.get("sr", "?"), m.get("ch", "?"),
                   gain_label(self._gain_idx())), "mono")
        else:
            put(f"{t('info_audio_new'):<8} {t('info_audio_nofile')}")
        put("")

        warns = 0
        if om and nm:
            ow, oh = om.get("w"), om.get("h")
            nw, nh = nm.get("w"), nm.get("h")
            of, nf = om.get("fps"), nm.get("fps")
            os_, ns = self._secs(om), self._secs(nm)

            if of and nf and abs(of - nf) > 0.01:
                put(t("info_fps_bad", a=round(of, 3), b=round(nf, 3)))
            if ow and nw and (ow != nw or oh != nh):
                put(t("info_res_bad", a=f"{ow}x{oh}", b=f"{nw}x{nh}"))
            # 时长才是真正需要用户拿捏的：游戏内窗口由游戏决定
            if os_ and ns:
                if ns > os_ + 0.05:
                    put(t("info_long", ns=f"{ns:.2f}", os=f"{os_:.2f}"), "warn"); warns += 1
                elif ns < os_ - 0.05:
                    put(t("info_short", ns=f"{ns:.2f}", os=f"{os_:.2f}"), "warn"); warns += 1
                else:
                    put("· " + t("info_all_ok"), "ok")
            elif not nm.get("frames"):
                put("⚠ " + t("build_nometa"), "warn"); warns += 1
        else:
            put(t("info_hint"))

        # —— 音频提醒：替换音频 vs 原音频 / 影片时长 ——
        if getattr(self, "audio_skip", True) or (a_t and a_t.get("whole")):
            pass                      # 不替换 / 整库替换都没有「原音频长度」可比
        elif a_t and a_meta:
            od = a_t.get("dur_us", 0) / 1e6
            nd = float(a_meta.get("duration") or 0)
            if od > 0 and nd > 0:
                if nd > od + 0.05:
                    put(t("info_audio_long", ns=f"{nd:.2f}", os=f"{od:.2f}"), "warn"); warns += 1
                elif nd < od - 0.05:
                    put(t("info_audio_short", ns=f"{nd:.2f}", os=f"{od:.2f}"), "warn"); warns += 1
            vd = self._secs(om)
            if vd and nd and abs(nd - vd) > 0.5:
                put(t("info_audio_sync", ns=f"{nd:.2f}", vs=f"{vd:.2f}",
                      d=f"{abs(nd - vd):.2f}"), "warn"); warns += 1
            elif vd and nd:
                put("· " + t("info_audio_sync_ok"), "ok")

        w.configure(state="disabled")

    def toggle_play(self):
        new_state = not (self.pv_orig.playing or self.pv_new.playing)
        self.pv_orig.playing = self.pv_new.playing = new_state
        self.play_btn.config(text=t("btn_pause") if new_state else t("btn_play"))

    # ---------- 生成 / 安装 ----------
    def _selected(self):
        oi, ni = self.orig_box.current(), self.new_box.current()
        o = self.orig_list[oi] if 0 <= oi < len(self.orig_list) else None
        n = self.new_list[ni] if 0 <= ni < len(self.new_list) else None
        return o, n

    def do_build(self):
        if self.busy: return
        o, n = self._selected()
        if not o or not n:
            messagebox.showwarning(APP_NAME, t("need_paths")); return
        out = Path(self.out_var.get() or APP_DIR)
        out.mkdir(parents=True, exist_ok=True)
        self.busy = True; self.status.config(text=t("building"))
        threading.Thread(target=self._build_worker, args=(o, n, out), daemon=True).start()

    def _build_worker(self, o: Path, n: Path, out: Path):
        try:
            if not (App.FFMPEG and Path(App.FFMPEG).is_file()):
                raise RuntimeError(t("tool_path_bad", label=t("tool_ffmpeg"),
                                     p=(App.FFMPEG or t("tool_path_empty")))
                                   + "\n" + t("tool_path_hint"))
            if not (App.CRICODECS and Path(App.CRICODECS).is_file()):
                raise RuntimeError(t("tool_path_bad", label=t("tool_cricodecs"),
                                     p=(App.CRICODECS or t("tool_path_empty")))
                                   + "\n" + t("tool_path_hint"))
            App.FFMPEG = self.ff_var.get(); App.CRICODECS = self.cc_var.get(); App.RETOC = self.rt_var.get()
            ref = parse_usm(o) or {}
            info = probe(n) or {}
            fps_out = float(ref.get("fps") or 30) or 30.0
            orig_frames = int(ref.get("frames") or 0)
            # 始终按原片对齐（游戏内播放窗口由游戏本身决定，改写游戏侧帧数无效 —— 详见研究文档 §7）
            if orig_frames:
                self.log(t("build_align", n=orig_frames, os=f"{orig_frames / fps_out:.3f}"))
            else:
                self.log(t("build_nometa"))
            # 中间产物 .usm 放缓存目录 —— 它最终会被打进 pak，输出目录只留可安装的三件套
            build_cache = self.tmpdir / "build"
            build_cache.mkdir(parents=True, exist_ok=True)
            dest = build_cache / (o.stem.replace("_vp9", "") + "_mod.usm")
            ok = build_usm(n, dest, ref, self.log)
            if ok:
                self.status.config(text=t("build_done", p=dest.name))
                self.last_usm = dest
                self.log(f"{t('build_done', p=str(dest))}")
            else:
                self.status.config(text=t("build_fail", e="see log"))

            if not ok:
                return

            # —— 打包成补丁容器（方案 B）——
            # 实测：把 .usm 按游戏里的**原始 pak 路径**打进 _P.pak，再 to-zen 出配对
            # utoc/ucas，游戏就会直接播替换后的影片 —— 不改 ucas、不放散文件。
            self.last_patch = None
            root = self._game_root()
            if root is None:
                raise RuntimeError(t("err_no_game"))
            paks = root / "FFRS" / "Content" / "Paks"
            base_name = dest.stem + "_P"
            utoc = out / (base_name + ".utoc")

            # ⓪ MOD 合并（可选）：把别的三件套抽成 legacy 资产，稍后一起 to-zen
            merged = None
            merge_dir = (self.merge_var.get().strip()
                     if (getattr(self, "SHOW_MERGE", True) and hasattr(self, "merge_var")) else "")
            if merge_dir:
                if not Path(merge_dir).is_dir():
                    raise RuntimeError(t("merge_bad", p=merge_dir))
                merged = extract_mod_assets(Path(merge_dir), self.tmpdir, paks,
                                            Path(App.RETOC), self.log)

            # ① 音频（可选）先做：它产出 utoc/ucas + 一个空的 pak
            at = self.current_audio_target()
            asrc = getattr(self, "audio_src", None)
            whole = bool(at and at.get("whole"))
            skip = bool(getattr(self, "audio_skip", True))
            has_audio = False
            if not skip and at and (asrc or whole):
                # 生成阶段不再因为"游戏里已装了 MOD"而阻断：抽音库走的是基础容器视图
                # （见 AudioBankCache._base_view），拿到的永远是干净基线。
                # 是否覆盖已装 MOD 放到「安装到游戏」时再问。
                self.log(t("audio_working", bank=at["bank"], e=at["entry"]))
                if whole:
                    # 幻兵闪回：没有逐影片的 cue，改用整个语音库 —— 把导入目录里的
                    # 音频按文件名顺序铺开，闪回期间无论游戏挑哪句播都是替换后的音频
                    srcs = list(getattr(self, "audio_list", []))
                    if not srcs:
                        raise RuntimeError(t("audio_need_src"))
                    jobs = [{"bank": at["bank"], "whole": True,
                             "entry_count": at.get("entry_count"), "srcs": srcs}]
                else:
                    jobs = [{"bank": at["bank"], "entry": at["entry"], "src": Path(asrc)}]
                utoc = build_audio_patch(self.audio_index, jobs,
                                         out, Path(App.RETOC), paks, self.log, base=base_name,
                                         gain_mode=AUDIO_GAIN_MODES[self._gain_idx()][0],
                                         extra_db=AUDIO_GAIN_MODES[self._gain_idx()][1],
                                         extra_legacy=merged)
                has_audio = True
                self.log(t("audio_build_done", p=Path(utoc).name))
            elif at and not asrc and not skip:
                raise RuntimeError(t("audio_need_src"))
            elif asrc and not at and not skip:
                raise RuntimeError(t("audio_need_target"))

            # ①' 没有音频、但有待合并 MOD：只靠合并资产也要建出资产容器
            if not has_audio and merged is not None:
                utoc = build_audio_patch(self.audio_index, [], out, Path(App.RETOC), paks,
                                         self.log, base=base_name, extra_legacy=merged)
                has_audio = True
                self.log(t("merge_done", p=utoc.name))

            # ② 影片 pak（.usm 走原始路径）—— 覆盖上面那个空的 pak
            movie_rel = self._movie_rel(o)
            movie_pak = out / (base_name + ".pak")
            build_movie_pak(dest, movie_rel, movie_pak, Path(App.REPAK), self.log)

            # ③ 没有音频补丁时，影片 pak 自己也要配出 utoc/ucas（引擎挂 pak 会找 utoc）
            if not has_audio:
                rc, oo, ee = run([App.RETOC, "to-zen", "--version", "UE5_6",
                                  str(movie_pak), str(utoc)], timeout=1800)
                if rc != 0:
                    raise RuntimeError("retoc to-zen 失败：%s" % ((ee or oo)[-300:]))
                self.log(t("movie_patch_done", p=utoc.name))
            self.last_patch = utoc

            # ④ 清理过程文件：.usm 已经打进 pak 了，缓存里的副本删掉，
            #    输出目录只留可安装的三件套
            try:
                if dest.exists():
                    dest.unlink()
                    self.log(t("build_cleaned", p=dest.name))
                self.last_usm = None
            except Exception as e:
                self.log(t("build_clean_fail", p=dest.name, e=e))
        except Exception as e:
            self.log(t("build_fail", e=e)); self.status.config(text=t("build_fail", e=e))
        finally:
            self.busy = False

    def _game_root(self) -> Path | None:
        """
        从用户填写的路径解析出游戏根目录（其下含 FFRS/Content/Paks/FFRS-Windows.ucas）。
        接受用户填：游戏根目录 / FFRS / Content / Paks 目录，或 .ucas 文件本身。
        """
        raw = self.game_var.get().strip().strip('"')
        if not raw:
            return None
        p = Path(raw)
        if p.is_file():
            p = p.parent
        marker = "FFRS/Content/Paks/FFRS-Windows.ucas"
        # ① 自身或其任一祖先就是游戏根目录
        for cand in [p, *p.parents]:
            if (cand / marker).exists():
                return cand
        # ② 用户填的是 Paks 目录（其下有 FFRS-Windows.ucas）：向上回推 <根>/FFRS/Content/Paks
        if (p / "FFRS-Windows.ucas").exists():
            try:
                root = p.parents[2]          # Paks -> Content -> FFRS -> 根
                if (root / marker).exists():
                    return root
            except IndexError:
                pass
        return None

    def do_install(self):
        # 新流程只需要三件套（.usm 已经打进 pak 了），不再看中间文件
        root = self._game_root()
        if root is None:
            messagebox.showwarning(APP_NAME, t("err_no_game")); return
        patch = getattr(self, "last_patch", None)
        if not patch or not Path(patch).exists():
            messagebox.showwarning(APP_NAME, t("build_fail", e=t("no_patch"))); return
        if not messagebox.askyesno(APP_NAME, t("confirm_install", p=root)):
            return
        paks0 = root / "FFRS" / "Content" / "Paks"
        _u = Path(patch)
        _names = [_u.name, _u.with_suffix(".ucas").name, _u.with_suffix(".pak").name]
        if any((paks0 / n).exists() for n in _names):
            # 只有装的时候才需要问：同名 MOD 已存在，是否覆盖
            if not messagebox.askyesno(APP_NAME, t("confirm_overwrite", p=_u.stem)):
                return
        self.status.config(text=t("installing"))
        try:
            paks = root / "FFRS" / "Content" / "Paks"
            names = install_audio_patch(Path(patch), paks)      # 通用：复制 utoc/ucas/pak 并记录
            self.log(t("audio_installed", p=", ".join(names)))
            st = load_audio_state()
            st["targets"] = (st.get("targets") or []) + [
                {"movie": self._movie_rel(self._selected()[0]),
                 "audio": dict(self.current_audio_target() or {}) if not getattr(self, "audio_skip", True) else None}]
            save_audio_state(st)
            self.status.config(text=t("install_done", p=Path(patch).name))
            self.refresh_installed()
        except Exception as e:
            self.log(t("install_fail", e=e)); self.status.config(text=t("install_fail", e=e))

    def do_restore_sel(self):
        root = self._game_root()
        if root is None:
            messagebox.showwarning(APP_NAME, t("err_no_game")); return
        sel = self._active_rest_box().get()
        try:
            inst = Installer(root, APP_DIR / "ffrs_videomod_backup.json")
            # 以记录为准判断，别依赖下拉里的占位文案（切语言时文案会变）
            names = inst.list_installed()
            if not sel or sel not in names:
                messagebox.showinfo(APP_NAME, t("restore_none_sel")); return
            if not messagebox.askyesno(APP_NAME, t("confirm_restore")):
                return
            inst.restore(self.log, only=sel)
            self.status.config(text=t("restore_ok", p=sel))
            self.refresh_installed()
        except RuntimeError as e:
            if str(e) == "no-records":
                messagebox.showinfo(APP_NAME, t("no_records"))
            else:
                self.log(t("install_fail", e=e))
        except Exception as e:
            self.log(t("install_fail", e=e))

    def _movie_rel(self, usm: Path) -> str:
        """从原 USM 路径推出 'Event/Legend/MV_xxx_vp9' 形式（相对 Movies/）。

        原视频不一定放在 Export 的 Movies/ 结构里（可能在 <输入>/VideoMod），
        此时按**文件名**到游戏影片表里查唯一对应项，否则 pak 里路径会少一层目录 → MOD 不生效。
        """
        parts = list(usm.parts)
        if "Movies" in parts:
            i = parts.index("Movies")
            rel = "/".join(parts[i + 1:])
        else:
            rel = usm.name
            try:
                stem = usm.stem
                table = self._movie_table()
                hits = [k for k in (table or {}) if k.rsplit("/", 1)[-1] == stem]
                if len(hits) == 1:
                    self.log(f"提示：影片路径已按文件名解析为 {hits[0]}（正常现象）")
                    return hits[0]
                if hits:
                    self.log(f"[影片] ⚠ 同名影片有 {len(hits)} 个，无法唯一确定：{hits[:3]}")
            except Exception:
                pass
        return rel[:-4] if rel.lower().endswith(".usm") else rel

    def _movie_table(self):
        """{movie_rel: 信息} 来自游戏 ucas 扫描，缓存一次。"""
        tab = getattr(self, "_mtab", None)
        if tab is not None:
            return tab
        try:
            root = self._game_root()
            if root is None:
                self._mtab = {}
                return self._mtab
            inst = Installer(root, APP_DIR / "ffrs_videomod_backup.json")
            self._mtab = inst.scan_movie_paths() or {}
        except Exception as e:
            self.log(f"[影片] 读取游戏影片表失败：{e}")
            self._mtab = {}
        return self._mtab

    def do_install_all(self):
        """
        简化模式的「全部安装」：把 MOD 目录里能对上原片的 MOD 全部装进游戏。

        普通玩家拿到一个 MOD 文件夹，指定路径后点这里即可，不用碰制作模式。
        要挑着装就点「安装选中…」（打开 cue 列表）。
        """
        root = self._game_root()
        if root is None:
            messagebox.showwarning(APP_NAME, t("err_no_game")); return
        mods_dir = Path(self.out_var.get().strip() or APP_DIR)
        if not mods_dir.is_dir():
            messagebox.showwarning(APP_NAME, t("batch_mods_missing", p=mods_dir)); return
        self.status.config(text=t("batch_scanning"))
        try:
            inst = Installer(root, APP_DIR / "ffrs_videomod_backup.json")
            table = inst.scan_movie_paths()
            pairs, _orphans, _dups = match_mods(list(table), sorted(mods_dir.rglob("*.usm")))
            have_packs = any(mods_dir.rglob("*_P.utoc")) if mods_dir.is_dir() else False
            if not pairs and not have_packs:
                self.status.config(text="")
                messagebox.showinfo(APP_NAME, t("batch_nothing", p=mods_dir)); return
            if not messagebox.askyesno(APP_NAME, t("batch_confirm_all", n=len(pairs))):
                self.status.config(text=""); return
            ok = 0
            for rel, mod in pairs:
                try:
                    inst.install(mod, rel, self.log, hits=table.get(rel))
                    ok += 1
                except Exception as e:
                    self.log(t("batch_fail", p=rel, e=e))
            # ★ 音频补丁三件套也要一起装（否则「MOD 装了但音频没变」）
            try:
                packs = install_audio_packs(mods_dir, root / "FFRS" / "Content" / "Paks")
                if packs:
                    self.log(t("audio_installed", p=", ".join(packs)))
            except Exception as e:
                self.log(t("batch_fail", p="audio", e=e))
            self.log(t("batch_done", n=ok))
            self.status.config(text=t("batch_done", n=ok))
            self.refresh_installed()
        except Exception as e:
            self.log(f"install all fail: {e}")
            self.status.config(text=t("install_fail", e=e))

    def do_batch(self):
        """打开「MOD 批量安装」窗口（cue 列表：游戏里所有影片 × MOD 目录）。"""
        root = self._game_root()
        if root is None:
            messagebox.showwarning(APP_NAME, t("err_no_game")); return
        w = getattr(self, "batch_win", None)
        if w is not None and w.winfo_exists():
            w.lift(); w.focus(); return
        self.batch_win = BatchInstall(self, root, Path(self.out_var.get().strip() or APP_DIR))

    def do_restore(self):
        root = self._game_root()
        if root is None:
            messagebox.showwarning(APP_NAME, t("err_no_game")); return
        if not messagebox.askyesno(APP_NAME, t("confirm_restore")):
            return
        try:
            inst = Installer(root, APP_DIR / "ffrs_videomod_backup.json")
            try:
                inst.restore(self.log)
            except RuntimeError as e:
                if str(e) != "no-records":
                    raise
            # 音频补丁是整块覆盖式的，只在「全部还原」时一并移除
            n = remove_audio_patch(root / "FFRS" / "Content" / "Paks")
            if n:
                self.log(t("audio_restored", n=n))
            self.status.config(text=t("restore_done"))
            self.refresh_installed()
        except RuntimeError as e:
            if str(e) == "no-records":
                messagebox.showinfo(APP_NAME, t("no_records"))
            else:
                self.log(t("install_fail", e=e))
        except Exception as e:
            self.log(t("install_fail", e=e))

    def _close(self):
        self._save_settings()
        shutil.rmtree(self.tmpdir, ignore_errors=True)
        self.destroy()


if __name__ == "__main__":
    app = App()
    app.mainloop()
