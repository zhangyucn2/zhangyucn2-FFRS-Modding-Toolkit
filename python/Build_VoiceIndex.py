#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成「8 主角台词语音索引」ffrs_voice_story.json

规则（2026-10-23 实测）：
  * 台本表 Datatable/Event/Text/**：ContentText = locres key，Speaker = 日文名
  * 表名归一化后能对上 VO_ADV_<事件> 音库（去掉 DT_ / _TalkEvent / _NN 后缀）
  * 音库内嵌 AFS2 条目按顺序对应台本里的「有文本行」：
      - 有 _Cue 资源且 cue 行号连续时，entry = 行号-1
      - 没有 cue 但 行数 == 条目数 时，entry = 行下标
      - 其它情况跳过（partial）
  * 只导出 8 名主角的发言行（用户 2026-10-23 定的范围）

输出：python/ffrs_voice_story.json
  {
    "generated_from": ...,
    "banks": {name: {package, pak_path, subkey, entry_count, storage}},
    "speakers": {speaker: [{ns, key, bank, entry}, ...]}
  }
"""
import concurrent.futures
import json
import os
import pathlib
import re
import shutil
import struct
import subprocess
import sys

HERE = pathlib.Path(__file__).resolve().parent
TOOLS = HERE.parent / "tools"
RETOC = TOOLS / "retoc.exe"
FFRDT = TOOLS / "ffr-dt" / "ffr-dt.exe"
USMAP = TOOLS / "FFRS.usmap"
WORK = HERE / "save" / "_temp" / "voice_index"
OUT = HERE / "ffrs_voice_story.json"

HEROES = ["レイン", "ラスウェル", "フィーナ", "リド", "ニコル",
          "魔人フィーナ", "ジェイク", "サクラ"]


def base_paks() -> pathlib.Path:
    sys.path.insert(0, str(HERE))
    from kit import settings as K
    d = K.cache_root() / "base_paks"
    if not (d / "FFRS-Windows.utoc").exists():
        d, _s, _f = K.build_base_cache()
    return d


def run(args, timeout=7200):
    r = subprocess.run([str(a) for a in args], capture_output=True, text=True,
                       errors="replace", timeout=timeout)
    if r.returncode != 0:
        raise RuntimeError("命令失败: %s\n%s" % (args[0], (r.stderr or r.stdout)[-400:]))
    return r.stdout


def list_chunks(paks: pathlib.Path):
    out = run([RETOC, "list", paks / "FFRS-Windows.utoc", "--path"])
    paths = []
    for line in out.splitlines():
        line = line.strip()
        if not line or line.startswith("container") or line.startswith("type"):
            continue
        p = line.split()[-1]
        if p.startswith("../../../"):
            p = p[len("../../../"):]
        if p.startswith("FFRS/Content/"):
            p = p[len("FFRS/Content/"):]
        paths.append(p)
    return paths


def afs2_info(uexp: pathlib.Path):
    b = uexp.read_bytes()
    o = b.find(b"AFS2")
    if o < 0:
        return None
    cnt = struct.unpack_from("<I", b, o + 8)[0]
    align, subkey = struct.unpack_from("<HH", b, o + 12)
    return {"entry_count": cnt, "alignment": align, "subkey": subkey}


def extract(paks: pathlib.Path, out: pathlib.Path, names):
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    if not names:
        return
    args = [RETOC, "to-legacy", paks, out, "--no-shaders"]
    for n in names:
        args += ["-f", n]
    run(args)


def tojson(ua: pathlib.Path, dst: pathlib.Path):
    if dst.exists():
        return dst
    subprocess.run([str(FFRDT), "tojson", str(ua), str(dst), "--usmap", str(USMAP)],
                   capture_output=True)
    return dst if dst.exists() else None


def main():
    paks = base_paks()
    chunks = list_chunks(paks)
    tables = sorted({pathlib.Path(p).name for p in chunks
                     if "Datatable/Event/Text/" in p and p.endswith(".uasset")})
    atc_tables = sorted({pathlib.Path(p).name for p in chunks
                         if re.search(r"Datatable/Chat/Text/DT_ATC\d+_TalkEvent\.uasset$", p)})
    bank_paths = {}
    atc_banks = {}
    atc_rows = {}
    cue_counts = {}
    cue_nums = {}
    for p in chunks:
        if not p.endswith(".uasset"):
            continue
        ma = re.search(r"Sound/Cri/Voice/VO_ATC/(VO_ATC_ATC\d+)/([^/]+)\.uasset$", p)
        if ma:
            atc_banks.setdefault(ma.group(1), "Sound/Cri/Voice/VO_ATC/" + ma.group(1) + "/" + ma.group(1))
            continue
        if "Sound/Cri/Voice/VO_ADV/" not in p:
            continue
        m = re.match(r"(Sound/Cri/Voice/VO_ADV/([^/]+)/([^/]+))\.uasset$", p)
        if not m:
            continue
        pkg_path, bank, asset = m.groups()
        bank_paths.setdefault(bank, pkg_path)
        if asset.endswith("_Cue"):
            cue_counts[bank] = cue_counts.get(bank, 0) + 1
            mm = re.match(re.escape(bank) + r"_(\d+)_", asset)
            if mm:
                cue_nums.setdefault(bank, set()).add(int(mm.group(1)))
    print(f"台本表 {len(tables)} | VO_ADV 音库 {len(bank_paths)}")

    WORK.mkdir(parents=True, exist_ok=True)
    tdir = WORK / "tables"
    extract(paks, tdir, tables + atc_tables)
    print("已抽取台本表 ->", tdir)

    # 并行转 JSON
    stems = [pathlib.Path(t).stem for t in tables] + [pathlib.Path(t).stem for t in atc_tables]
    json_dir = WORK / "json"
    json_dir.mkdir(exist_ok=True)
    def job(stem):
        ua = next(tdir.rglob(stem + ".uasset"), None)
        if ua is None:
            return
        tojson(ua, json_dir / (stem + ".json"))
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as ex:
        list(ex.map(job, stems))
    print("JSON 完成:", len(list(json_dir.glob("*.json"))))

    def candidates(stem):
        s = stem[3:] if stem.startswith("DT_") else stem
        for suf in ("_TalkEvent", "_TalkEvent_2", "_NF", "_2"):
            if s.endswith(suf):
                s = s[:-len(suf)]
        out = [s]
        parts = s.split("_")
        for k in range(1, 4):
            if len(parts) > k:
                out.append("_".join(parts[:-k]))
        return out

    def bank_for(stem):
        for c in candidates(stem):
            b = "VO_ADV_" + c
            if b in bank_paths:
                return b
            if c in bank_paths:
                return c
        s = stem[3:] if stem.startswith("DT_") else stem
        hits = [b for b in bank_paths if s.startswith(b + "_")]
        return max(hits, key=len) if hits else None

    table_rows = {}
    for js in sorted(json_dir.glob("*.json")):
        try:
            rows = json.loads(js.read_text(encoding="utf-8"))["Exports"][0]["Table"]["Data"]
        except Exception:
            continue
        out = []
        for r in rows:
            p = {q["Name"]: q["Value"] for q in r["Value"]}
            k = p.get("ContentText")
            if isinstance(k, str) and k:
                out.append({"key": k, "speaker": p.get("Speaker")})
        table_rows[js.stem] = out
    print("有效台本表:", len(table_rows))

    # 需要抽取的音库
    used = {}
    for stem in table_rows:
        b = bank_for(stem)
        if b:
            used[b] = bank_paths[b]
    print("涉及音库:", len(used))
    bdir = WORK / "banks"
    atc_used = {}
    for t in atc_tables:
        m = re.match(r"DT_ATC(\d+)_TalkEvent$", pathlib.Path(t).stem)
        if m:
            b = "VO_ATC_ATC" + m.group(1)
            if b in atc_banks:
                atc_used[b] = atc_banks[b]
    extract(paks, bdir, [b + ".uasset" for b in used])
    bdir_atc = WORK / "banks_atc"
    extract(paks, bdir_atc, [b + ".uasset" for b in atc_used])
    banks = {}
    for bank, pkg_path in used.items():
        hits = [ux for ux in bdir.rglob(bank + ".uexp")]
        # 优先 ja 路径（用户规则：只做日语）
        exact = [h for h in hits if "/ja/" in str(h).replace("\\", "/")]
        if exact:
            ux = exact[0]
            ja_prefix = "L10N/ja/Sound/Cri/Voice/VO_ADV/%s/%s" % (bank, bank)
        else:
            ux = hits[0] if hits else None
            ja_prefix = pkg_path
        if ux is None:
            continue
        info = afs2_info(ux)
        if not info:
            continue
        banks[bank] = {
            "package": "/Game/" + ja_prefix,
            "pak_path": "FFRS/Content/" + ja_prefix,
            "entry_count": info["entry_count"],
            "subkey": info["subkey"],
            "storage": "memory",
        }

    speakers = {h: [] for h in HEROES}
    stats = {"tables": 0, "eq": 0, "cue": 0, "skip": 0}
    for stem, rows in table_rows.items():
        bank = bank_for(stem)
        if not bank or bank not in banks:
            continue
        n = banks[bank]["entry_count"]
        stats["tables"] += 1
        nums = cue_nums.get(bank)
        ns = "ST_" + re.sub(r"^DT_", "", stem)
        ns = re.sub(r"(_TalkEvent_2|_TalkEvent|_NF|_2)$", "", ns)
        # 决定映射方式
        mode = None
        if nums and len(nums) == n and nums == set(range(1, n + 1)):
            mode = "cue"
        elif len(rows) == n:
            mode = "row"
        if mode is None:
            stats["skip"] += 1
            continue
        stats["eq" if mode == "row" else "cue"] += 1
        for i, r in enumerate(rows):
            sp = r["speaker"]
            if sp not in speakers:
                continue
            entry = (i if mode == "row" else None)
            if mode == "cue":
                m = re.search(r"(\d{3})$", r["key"])
                if not m:
                    continue
                num = int(m.group(1))
                if num not in nums:
                    continue
                entry = num - 1
            if entry is None or entry >= n:
                continue
            speakers[sp].append({"ns": ns, "key": r["key"], "bank": bank, "entry": entry})

    # ── ATC（Active Time Chat）：DT_ATC{n}_TalkEvent ↔ ST_ATC{n} ↔ VO_ATC_ATC{n}
    atc_n = 0
    for b, pkg_path in atc_used.items():
        tname = "DT_ATC%s_TalkEvent" % re.search(r"(\d+)$", b).group(1)
        rows = table_rows.get(tname)
        if not rows:
            continue
        hits = [ux for ux in bdir_atc.rglob(b + ".uexp")] or [ux for ux in bdir.rglob(b + ".uexp")]
        exact = [h for h in hits if "/ja/" in str(h).replace("\\", "/")]
        ux = exact[0] if exact else (hits[0] if hits else None)
        if ux is None:
            continue
        info = afs2_info(ux)
        if not info:
            continue
        base_prefix = ("L10N/ja/Sound/Cri/Voice/VO_ATC/%s/%s" % (b, b)) if exact else pkg_path
        banks[b] = {"package": "/Game/" + base_prefix,
                    "pak_path": "FFRS/Content/" + base_prefix,
                    "entry_count": info["entry_count"], "subkey": info["subkey"],
                    "storage": "memory"}
        n = info["entry_count"]
        if len(rows) != n:
            stats["skip"] += 1
            continue
        stats["tables"] += 1; stats["eq"] += 1
        ns = "ST_ATC" + re.search(r"(\d+)$", b).group(1)
        for i, r in enumerate(rows):
            sp = r["speaker"]
            if sp in speakers:
                speakers[sp].append({"ns": ns, "key": r["key"], "bank": b, "entry": i})
                atc_n += 1

    data = {
        "generated_from": str(paks),
        "speakers": {k: v for k, v in speakers.items() if v},
        "banks": banks,
    }
    OUT.write_text(json.dumps(data, ensure_ascii=False, indent=0), encoding="utf-8")
    total = sum(len(v) for v in data["speakers"].values())
    print(f"完成 -> {OUT} ({OUT.stat().st_size/1024:.1f} KB)")
    print("映射统计:", stats)
    for k, v in data["speakers"].items():
        print(f"  {k}: {len(v)} 条")
    print("总条数:", total)
    shutil.rmtree(WORK, ignore_errors=True)


if __name__ == "__main__":
    main()
