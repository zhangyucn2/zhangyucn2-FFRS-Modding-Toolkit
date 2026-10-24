#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
生成 FFRS 音频索引  ffrs_audio_index.json
================================================
给「视频替换工具」提供两张表：

  1. banks[]      每个 CRI 音库的 **cue 名 -> AWB 条目号 / 时长** 表
                  （手动指定音频时用）
  2. movie_audio{} 影片 -> 该影片播放时同步播放的音频条目（自动配对）
                  （「根据原视频检索需要同步替换的音频」）

★ 映射是怎么来的（为什么不是靠时长猜）
-----------------------------------------------------------------
影片资产里**没有**音频引用。关联发生在**播放影片的 LevelSequence 桥段**里：

    SEQ_Battle_430981_Master
      ├─ /Game/Movies/Summon/MV_summon300010                  ← 画面
      └─ .../Track/SEQ_Battle_430981_Sound_001（子桥段）
             └─ SoundAtomCue = .../SE_BTL_PP_SUMMON_SEIREN_MOVIE_Cue
                                                          ↑ 资产名去掉 _Cue
                                   == CRI cue 名 SE_BTL_PP_SUMMON_SEIREN_MOVIE
                                   == awb 条目 252

所以是**两跳查表**：扫桥段拿 (影片, cue 名)，再查各音库的 cue 表拿条目号。

★ cue 名 -> 条目号 必须用 `awb_wave_id`
-----------------------------------------------------------------
`cricodecs <ACB> --cue --list --verbose --json` 的每个 clip 里：
    "awb_wave_id"      ← 这才是 AFS2 条目号（替换时要写的号）
    "waveform_index"   ← 不是！文件名前缀用的是它，别混

用法:
    python Build_AudioIndex.py                 # 全量重建
    python Build_AudioIndex.py --only se_btl   # 只重建某个库（调试用）
"""
import argparse
import json
import os
import re
import shutil
import struct
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)

RETOC = os.path.join(REPO, "tools", "retoc.exe")
CRICODECS = os.path.join(REPO, "tools", "cricodecs.exe")
GAME = os.environ.get("FFRS_GAME_ROOT", r"D:/SteamLibrary/steamapps/common/FINAL FANTASY RESONANCE")
SEQ_DIR = os.path.join(HERE, "_index_work", "seq", "FFRS", "Content", "Sequencer")
OUT = os.path.join(HERE, "ffrs_audio_index.json")
WORK = os.path.join(HERE, "_index_work")

UE_VERSION = "UE5_6"

# 桥段里出现但不该当"音频"的引用（非 CueSheet 资产）
SKIP_BANKS = {"/Game/Sound/Cri/Mucha"}


def run(*args, quiet=True):
    r = subprocess.run([str(a) for a in args], capture_output=True, text=True,
                       errors="replace")
    if r.returncode != 0:
        if not quiet:
            print(r.stdout[-1500:], r.stderr[-1500:])
        raise RuntimeError("命令失败: %s\n%s" % (args[0], (r.stderr or r.stdout)[-500:]))
    return r.stdout


# ────────────────────────── ① 扫桥段：影片 -> cue ──────────────────────────

def scan_sequencers():
    """返回 {影片相对路径:set(cue 资产路径)}，影片路径形如 'Summon/MV_summon300010_vp9'。"""
    if not os.path.isdir(SEQ_DIR):
        raise SystemExit("找不到桥段导出目录: %s" % SEQ_DIR)
    files = {}
    for root, _d, names in os.walk(SEQ_DIR):
        for n in names:
            if not n.endswith(".uasset"):
                continue
            p = os.path.join(root, n)
            b = open(p, "rb").read()
            ps = p.replace("\\", "/")
            i = ps.find("/Content/")
            rel = ps[i + len("/Content/"):] if i >= 0 else os.path.basename(ps)
            pkg = "/Game/" + rel[:-len(".uasset")]
            files[pkg] = {
                "movies": {x.decode() for x in re.findall(rb"/Game/Movies/([A-Za-z0-9_/]+)", b)},
                # 存**完整**包路径：findall 给的是分组，别把 /Game/Sound/ 前缀丢了
                # （丢了会让后续 bank_pkg 错位 13 个字符，pak_path 全乱）
                "cues":   {"/Game/Sound/" + x.decode()
                           for x in re.findall(rb"/Game/Sound/([A-Za-z0-9_/]+)_Cue", b)},
                "refs":   {x.decode() for x in re.findall(rb"/Game/Sequencer/[A-Za-z0-9_/]+", b)},
            }

    out = {}
    for pkg, v in files.items():
        if not v["movies"]:
            continue
        cues = set(v["cues"])
        for r in v["refs"]:                      # 合并子桥段的声音轨
            if r in files:
                cues |= files[r]["cues"]
        for m in v["movies"]:
            # m 已经是相对路径（findall 取的是分组），如 'Summon/MV_summon300010'
            base = m.rsplit("/", 1)[-1]
            if not base.startswith("MV_"):
                continue                          # 排除 Sequencer 自己的辅助资产
            # 工具里的键用的是子资产（FileManaMovie，`.usm` 路径带 _vp9）；
            # 桥段有时引用的是子资产本身，此时名字已含 _vp9，别再叠一次
            key = m if base.endswith("_vp9") else m + "_vp9"
            out.setdefault(key, set()).update(cues)
    return out


def scan_legend_banks():
    """Legend 闪回影片 -> 该章的旁白语音库（整库级配对）。

    为什么 Legend 只能整库：桥段里**一个 cue 引用都没有**（逐层查过：
    Sequencer/Event/LegendEvent/**、DT_TalkEventData_LegendEvent 的
    EventSECueSheetName/ArgList、DT_LegendEV_* 的 Voice 字段 —— 全空），
    说明具体播哪句台词是**运行时由 C++ 决定**的，静态推不出来。
    但把整章语音库换掉，闪回里无论挑哪句播的都是替换后的音频 —— 效果等价。

    章号取自桥段目录名 Int_LegendEV_NN，影片取自桥段里的 /Game/Movies/ 引用。
    语音库路径：/Game/L10N/ja/Sound/Cri/Voice/VO_ADV/VO_ADV_LEGENDEV_NN/VO_ADV_LEGENDEV_NN
    """
    out = {}
    base = os.path.join(SEQ_DIR, "Event", "LegendEvent")
    for root, _d, names in os.walk(base):
        m = re.search(r"Int_LegendEV_(\d+)", root.replace("\\", "/"))
        if not m:
            continue
        chap = m.group(1)
        for n in names:
            if not n.endswith(".uasset"):
                continue
            b = open(os.path.join(root, n), "rb").read()
            for mv in re.findall(rb"/Game/Movies/([A-Za-z0-9_/]+)", b):
                k = mv.decode() + "_vp9"
                out.setdefault(k, set()).add(chap)
    return out


def legend_bank_pkg(chap: str) -> str:
    return ("/Game/L10N/ja/Sound/Cri/Voice/VO_ADV/VO_ADV_LEGENDEV_%s/VO_ADV_LEGENDEV_%s"
            % (chap, chap))


# ────────────────────────── ② 音库 cue 表 ──────────────────────────

def afs2_info(uexp_path):
    """从 uexp 里读 AFS2 头的 subkey / 条目数。"""
    d = open(uexp_path, "rb").read()
    o = d.find(b"AFS2")
    if o < 0:
        return None
    cnt = struct.unpack_from("<I", d, o + 8)[0]
    align, subkey = struct.unpack_from("<HH", d, o + 12)
    return {"afs2_offset": o, "entry_count": cnt, "alignment": align, "subkey": subkey}


def cue_table(uexp_path):
    """切出 ACB（从第一个 @UTF 到文件尾）交给 cricodecs，拿 cue -> 条目号/时长。"""
    d = open(uexp_path, "rb").read()
    o = d.find(b"@UTF")
    if o < 0:
        return {}
    acb = os.path.join(WORK, "_acb.bin")
    open(acb, "wb").write(d[o:])
    j = run(CRICODECS, acb, "--cue", "--list", "--verbose", "--json")
    # cricodecs 有时会在 JSON 前后混入日志行，截取最外层的对象
    s = j[j.find("{"): j.rfind("}") + 1]
    meta = json.loads(s)
    table = {}
    for it in meta.get("items", []):
        name = it.get("cue_name")
        if not name:
            continue
        ents, dur = [], 0
        for b in it.get("blocks", []):
            # ★ 时长在 block 上，不在 item 上（item 的 duration_us 常为 0）
            dur += int(b.get("duration_us") or 0)
            for c in b.get("clips", []):
                wid = c.get("awb_wave_id")
                if wid is None:
                    continue
                ents.append({"id": int(wid), "start_us": int(c.get("start_time_us") or 0)})
        rec = {"entries": ents, "duration_us": dur}
        # ★ 一条 cue plan 可能有多个【别名】cue 名（都指向同一份音频）。
        #   桥段引用的是别名，只按主名建索引会漏掉 —— 全部登记。
        names = {name}
        for s in it.get("sources", []):
            sn = s.get("source_cue_name")
            if sn:
                names.add(sn)
        for nm in names:
            table[nm] = rec
    return table


def base_paks_dir():
    """优先用首页维护的 base_paks 硬链接视图，避免抽到已装 MOD 的资产。"""
    try:
        sys.path.insert(0, HERE)
        from kit import settings as _K
        d = _K.cache_root() / "base_paks"
        if (d / "FFRS-Windows.utoc").exists():
            return str(d)
    except Exception:
        pass
    return os.path.join(GAME, "FFRS", "Content", "Paks")


def ensure_seq_export():
    """正式版没有现成 Export 目录：从基础视图抽 SEQ_ 资产到 WORK/seq。"""
    if os.path.isdir(SEQ_DIR) and os.listdir(SEQ_DIR):
        return
    dst = os.path.join(WORK, "seq")
    os.makedirs(dst, exist_ok=True)
    run(RETOC, "to-legacy", base_paks_dir(), dst, "-f", "SEQ_", "--no-shaders")
    print("      已抽取 SEQ_ 资产 ->", dst)


def extract_bank(bank_pkg):
    """用 retoc to-legacy 从游戏容器抽出某个音库的 uasset+uexp。返回 uexp 路径或 None。"""
    name = bank_pkg.rsplit("/", 1)[-1] + ".uasset"
    work = os.path.join(WORK, "legacy")
    shutil.rmtree(work, ignore_errors=True)
    os.makedirs(work, exist_ok=True)
    paks = base_paks_dir()
    if not os.path.isdir(paks):
        raise SystemExit("找不到游戏 Paks 目录: %s" % paks)
    run(RETOC, "to-legacy", paks, work, "-f", name, "--no-shaders")
    # 同一个包在 L10N/en、L10N/ja、基础路径下都可能抽出来（同名），
    # 要按包路径挑对应的那一份 —— 挑错就拿到别的语言的语音了。
    want = bank_pkg[len("/Game/"):].replace("/", os.sep)
    hits = []
    for root, _d, names in os.walk(work):
        for n in names:
            if n != name:
                continue
            ux = os.path.join(root, name[:-len(".uasset")] + ".uexp")
            if os.path.exists(ux):
                hits.append(ux)
    exact = [h for h in hits if want in h.replace("/", os.sep)]
    return (exact or hits)[0] if (exact or hits) else None


# ────────────────────────── ③ 组装 ──────────────────────────

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", help="只重建包含该子串的音库（调试）")
    args = ap.parse_args()

    os.makedirs(WORK, exist_ok=True)
    print("[0/3] 准备桥段资产")
    ensure_seq_export()
    print("[1/3] 扫桥段，建 影片 -> cue 名")
    pairs = scan_sequencers()
    cue_names = {}
    for movie, cues in pairs.items():
        for c in cues:
            bank_pkg, _, cname = c.rpartition("/")
            cue_names[cname] = bank_pkg
    print("      影片 %d 部，去重后 cue %d 个" % (len(pairs), len(cue_names)))

    banks_needed = {}
    for movie, cues in pairs.items():
        for c in cues:
            bank_pkg, _, cname = c.rpartition("/")
            if bank_pkg in SKIP_BANKS:
                continue
            banks_needed.setdefault(bank_pkg, set()).add(cname)

    # Legend 闪回：整库级配对（该章语音库整个换掉）
    legend = scan_legend_banks()
    for movie, chaps in legend.items():
        for chap in chaps:
            banks_needed.setdefault(legend_bank_pkg(chap), set())
    print("      涉及音库 %d 个（含 %d 个 Legend 语音库）"
          % (len(banks_needed), sum(1 for b in banks_needed if "LEGENDEV" in b)))

    print("[2/3] 逐库建 cue -> 条目号")
    banks_out = {}
    for bank_pkg in sorted(banks_needed):
        key = bank_pkg.rsplit("/", 1)[-1]
        if args.only and args.only.lower() not in key.lower():
            continue
        try:
            ux = extract_bank(bank_pkg)
            if not ux:
                print("      ⚠ %s 抽取失败，跳过" % key)
                continue
            info = afs2_info(ux) or {}
            table = cue_table(ux)
            n = info.get("entry_count") or 0
            maxid = max((e["id"] for c in table.values() for e in c["entries"]), default=-1)
            # 条目号超出内嵌 AFS2 的范围 -> 音频其实在 pak 里的独立 .awb（流式），
            # 走的是另一条替换路径（补丁 pak），不是本工具这一版支持的 uexp 原位替换。
            storage = "memory" if (n and maxid < n) else "streaming"
            banks_out[key] = {
                "package": bank_pkg,
                "pak_path": "FFRS/Content" + bank_pkg[len("/Game"):],
                "entry_count": n,
                "subkey": info.get("subkey"),
                "storage": storage,
                "cues": table,
            }
            print("      %-22s cue %-5d 条目 %-5s subkey %-6s %s"
                  % (key, len(table), n, info.get("subkey"),
                     "" if storage == "memory" else "← 流式(pak)，本版不支持"))
        except Exception as e:
            print("      ⚠ %s 失败: %s" % (key, e))
        finally:
            shutil.rmtree(os.path.join(WORK, "legacy"), ignore_errors=True)
            p = os.path.join(WORK, "_acb.bin")
            if os.path.exists(p):
                os.remove(p)

    print("[3/3] 解析成条目号并写 json")
    movie_audio = {}
    missing = []
    for movie, cues in sorted(pairs.items()):
        lst = []
        for c in sorted(cues):
            bank_pkg, _, cname = c.rpartition("/")
            bank = bank_pkg.rsplit("/", 1)[-1]
            b = banks_out.get(bank)
            if not b or cname not in b["cues"]:
                missing.append((movie, cname))
                continue
            for e in b["cues"][cname]["entries"]:
                lst.append({"bank": bank, "cue": cname, "entry": e["id"],
                            "start_us": e["start_us"],
                            "dur_us": b["cues"][cname]["duration_us"]})
        if lst:
            movie_audio[movie] = lst

    # Legend：整库级目标（whole=True）。多条桥段引用同一影片时可能对到多个章，
    # 取章号最小的一章（确定、可复现），并在日志里说明。
    whole_n = 0
    for movie, chaps in sorted(legend.items()):
        chap = sorted(chaps)[0]
        bank = "VO_ADV_LEGENDEV_%s" % chap
        b = banks_out.get(bank)
        if not b:
            continue
        ent = b.get("entry_count") or 0
        movie_audio.setdefault(movie, []).append(
            {"bank": bank, "cue": None, "entry": -1, "start_us": 0, "dur_us": 0,
             "whole": True, "entry_count": ent})
        whole_n += 1
        if len(chaps) > 1:
            print("      · %s 出现在多章 %s，取第 %s 章" % (movie, sorted(chaps), chap))

    idx = {
        "generated_from": GAME,
        "banks": banks_out,
        "movie_audio": movie_audio,
    }
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(idx, f, ensure_ascii=False, indent=1)
    size = os.path.getsize(OUT)
    print("      影片有配对的 %d 部 / 共 %d 部；cue 解析失败 %d 个"
          % (len(movie_audio), len(pairs), len(missing)))
    for m, c in missing[:15]:
        print("         ! %s -> %s" % (m, c))
    print("\n完成 -> %s  (%.1f KB)" % (OUT, size / 1024))
    shutil.rmtree(WORK, ignore_errors=True)


if __name__ == "__main__":
    main()
