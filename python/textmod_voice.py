"""幻兵祠堂（Legend）语音：文本行 ↔ 语音条目的定位 / 试听 / 替换。

实测（2026-10-19，FFRS demo）：

* 幻兵 ID → 祠堂剧本号 `LegendEV_XX`：见 `FFRS_TextMod_Tool.legend_index_map`
  （01=13100 ウォーリアオブライト、06=13108 ティナ、07=13110 クラウド）
* 剧本表 `Datatable/Event/Text/LegendEvent/DT_LegendEV_XX.uasset` 每行一个文本 key，
  字段 `WindowType` 区分行类型：**`Normal` = 选项行（没有语音）**，
  `Caption_Telop` / `Caption_TestWisdom` 等 = 旁白行（有语音）。
* 有语音的行按顺序编号 i=1..N，语音 cue 名 = `VO_ADV_LEGENDEV_XX_{i:03d}_9999`，
  `ffrs_audio_index.json` 里该 cue 的 `entries[0].id` 就是 AFS2 条目号（= i）。
  条目 0 是 DUMMY（静音）。
* 音库 uexp 里的 AFS2 可以**原位替换**（视频工具的既有链路），subkey 见下表。

只用日配（本作实际加载 ja）。
"""
import json
import re
import shutil
import struct
import subprocess
from pathlib import Path

# 幻兵祠堂音库的 subkey（实测；本作只有 01/06/07 三个祠堂）
SUBKEY = {1: 53119, 6: 44157, 7: 21590}

def bank_of(idx: int) -> str:
    return f"VO_ADV_LEGENDEV_{idx:02d}"


def cue_name(idx: int, entry: int) -> str:
    return f"VO_ADV_LEGENDEV_{idx:02d}_{entry:03d}_9999"


# ──────────────────────────── 剧本行 → 语音条目 ────────────────────────────
def _tojson(ua: Path, js: Path, uassetgui: Path) -> None:
    """优先用 ffr-dt（带 usmap）；没有就退回 UAssetGUI。
    UAssetGUI 在部分环境会把 DataTable 转成二进制兜底（没有 Table 节点），
    会直接报 KeyError: 'Table'。"""
    dt = mp = None
    try:
        import kit.settings as _K
        dt = Path(_K.get("ffrdt") or "")
        mp = Path(_K.get("usmap") or "")
    except Exception:
        dt = mp = None
    if dt and mp and dt.exists() and mp.exists():
        subprocess.run([str(dt), "tojson", str(ua), str(js), "--usmap", str(mp)],
                       capture_output=True, timeout=1800)
        return
    subprocess.run([str(uassetgui), "tojson", str(ua), str(js), "VER_UE5_6", "FFRS"],
                   capture_output=True, timeout=600)


def legend_rows(uassetgui: Path, legacy_dir: Path, idx: int, log) -> list:
    """读 DT_LegendEV_XX，返回 [(文本 key, WindowType)]（按表内顺序）。

    用 UAssetGUI tojson 一次性转出，并把 json 缓存进 legacy_dir。
    """
    name = f"DT_LegendEV_{idx:02d}"
    js = legacy_dir / f"{name}.json"
    if not js.exists():
        ua = next(legacy_dir.rglob(f"{name}.uasset"), None)
        if ua is None:
            raise RuntimeError(f"没找到 {name}.uasset")
        _tojson(ua, js, uassetgui)
        if not js.exists():
            raise RuntimeError(f"{name} 转 json 失败")
    d = json.loads(js.read_text(encoding="utf-8"))
    rows = (d["Exports"][0].get("Table") or {}).get("Data")
    if not rows:
        # 兜底：换成 ffr-dt 重转一次（旧缓存可能是 UAssetGUI 的二进制兜底）
        ua = next(legacy_dir.rglob(f"{name}.uasset"), None)
        if ua is not None:
            js.unlink(missing_ok=True)
            _tojson(ua, js, uassetgui)
            d = json.loads(js.read_text(encoding="utf-8"))
            rows = (d["Exports"][0].get("Table") or {}).get("Data")
    if not rows:
        raise RuntimeError(f"{name} 里没有行数据（转换器没解析出 DataTable）")
    out = []
    for r in rows:
        props = {p["Name"]: p["Value"] for p in r["Value"]}
        key = props.get("ContentText")
        if isinstance(key, str) and re.fullmatch(r"LegendEV_\d{2}_\d{3}", key):
            out.append((key, props.get("WindowType")))
    return out


def voiced_map(rows: list) -> dict:
    """{文本 key: 语音条目号}；`Normal` 行（选项）没有语音，不进表。"""
    m, i = {}, 0
    for key, wt in rows:
        if wt == "Normal":
            continue
        i += 1
        m[key] = i
    return m


def build_index(audio_index: dict, idx: int, rows: list) -> dict:
    """{文本 key: {"entry": n, "cue": name, "dur": 秒}}；只保留在音库里真实存在的 cue。"""
    bank = bank_of(idx)
    cues = ((audio_index.get("banks") or {}).get(bank) or {}).get("cues") or {}
    out = {}
    for key, n in voiced_map(rows).items():
        c = cue_name(idx, n)
        rec = cues.get(c)
        if not rec:
            continue
        out[key] = {"entry": rec["entries"][0]["id"], "cue": c,
                    "dur": round(rec.get("duration_us", 0) / 1e6, 2)}
    return out


# ──────────────────────────── 预览（解 WAV） ────────────────────────────
def ensure_preview(VM, bank: str, info: dict, paks: Path, retoc: Path,
                   work: Path, log) -> dict:
    """把音库条目解成 WAV 放 work/<bank>，返回 {条目号: wav}。

    已存在则直接复用（用户要求：解析时发现已在 temp 里就跳过解包）。
    """
    d = Path(work) / bank
    idxf = d / "_entries.json"
    if idxf.exists():
        try:
            return {int(k): Path(v) for k, v in json.loads(idxf.read_text(encoding="utf-8")).items()}
        except Exception:
            pass
    d.mkdir(parents=True, exist_ok=True)
    cache = VM.AudioBankCache(paks, retoc, log)
    _ua, ux = cache.ensure(bank, retoc, info.get("pak_path", ""))
    afs2 = d / "_afs2.bin"
    if not afs2.exists():
        raw = ux.read_bytes()
        afs2.write_bytes(raw[raw.find(b"AFS2"):])
    rc, out, err = VM.run([VM.App.CRICODECS, str(afs2), "-o", str(d), "--key", get_audio_key(), "-q"],
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
    log(f"语音解包完成：{bank} 共 {len(m)} 条 → {d}")
    return m
