"""FFRS 音频 Key 自动获取工具（公开版，不内置 key）。

输入游戏根目录后：
  1. 只复制基础容器（FFRS-Windows / global）到临时目录，避免 _P MOD 干扰
  2. 用 retoc 抽一个原始语音库（AFS2 内嵌 HCA）
  3. 用 cricodecs --recover-key 恢复 key，并实际解码验证
  4. 写入 tools/criwarekey.txt

用法：
  python FFRS_AudioKeyTool.py
  python FFRS_AudioKeyTool.py --game-root "D:\\...\\FINAL FANTASY RESONANCE" --no-gui
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from kit.audio_key import normalize_key, save_audio_key  # noqa: E402

APP_DIR = Path(__file__).resolve().parent
ROOT = APP_DIR.parent

# 基础语音库候选：任意一个能抽到 AFS2 即可
BANK_CANDIDATES = [
    "VO_BTL_CHR0060",
    "SE_BTL_PP",
    "VO_ADV_LEGENDEV_01",
    "VO_BTL_CHR0010",
]


def log(msg: str) -> None:
    print(msg, flush=True)


def find_tools(tools_dir: str | None = None) -> tuple[Path, Path]:
    cand = Path(tools_dir) if tools_dir else Path(os.environ.get("FFRS_TOOLS_DIR", ROOT / "tools"))
    retoc = cand / "retoc.exe"
    crico = cand / "cricodecs.exe"
    if not retoc.exists():
        raise RuntimeError(f"找不到 retoc.exe：{retoc}（请放到工具目录的 tools\\ 下）")
    if not crico.exists():
        raise RuntimeError(f"找不到 cricodecs.exe：{crico}")
    return retoc, crico


def game_paks(game_root: Path) -> Path:
    if (game_root / "FFRS" / "Content" / "Paks").is_dir():
        return game_root / "FFRS" / "Content" / "Paks"
    if (game_root / "FFRS-Windows.utoc").exists():
        return game_root
    raise RuntimeError(f"游戏目录下找不到 FFRS/Content/Paks：{game_root}")


def run(cmd: list[str], timeout: int = 900) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, errors="replace", timeout=timeout)


def prepare_base_paks(paks: Path, work: Path) -> Path:
    dst = work / "base_paks"
    dst.mkdir(parents=True, exist_ok=True)
    need = ["FFRS-Windows.utoc", "FFRS-Windows.ucas", "global.utoc", "global.ucas"]
    for name in need:
        src = paks / name
        if not src.exists():
            raise RuntimeError(f"缺少基础容器：{src}")
        shutil.copy2(src, dst / name)
    return dst


def parse_afs2(uexp: Path) -> Path | None:
    b = uexp.read_bytes()
    off = b.find(b"AFS2")
    if off < 0:
        return None
    a = b[off:]
    if len(a) < 20:
        return None
    ver, osz, isz, _ = struct.unpack_from("<BBBB", a, 4)
    cnt = struct.unpack_from("<I", a, 8)[0]
    if (ver, osz, isz) != (2, 4, 4) or not (0 < cnt < 100000):
        return None
    if 16 + cnt * 8 > len(a):
        return None
    return off


def extract_afs2(retoc: Path, base_paks: Path, work: Path, bank: str) -> Path | None:
    out = work / f"extract_{bank}"
    shutil.rmtree(out, ignore_errors=True)
    out.mkdir(parents=True, exist_ok=True)
    p = run([str(retoc), "to-legacy", str(base_paks), str(out), "-f", bank, "--no-shaders"], timeout=1200)
    if p.returncode != 0:
        log(f"  retoc 失败：{(p.stderr or p.stdout).strip()[-300:]}")
        return None
    uexps = [x for x in out.rglob("*.uexp") if parse_afs2(x) is not None]
    if not uexps:
        log("  没找到含 AFS2 的 uexp")
        return None
    # 优先非 L10N 的基础库
    uexps.sort(key=lambda x: ("L10N" in str(x), -x.stat().st_size))
    uexp = uexps[0]
    b = uexp.read_bytes()
    a = b[b.find(b"AFS2"):]
    dst = work / f"{bank}.afs2"
    dst.write_bytes(a)
    log(f"  AFS2: {uexp.relative_to(out)} ({len(a):,} 字节)")
    return dst


def recover_key(crico: Path, afs2: Path, work: Path) -> str | None:
    p = run([str(crico), "--recover-key", "-f", "hca", str(afs2), "--json"], timeout=1800)
    if p.returncode != 0 or not p.stdout.strip():
        log(f"  recover-key 失败：{(p.stderr or p.stdout).strip()[-300:]}")
        return None
    try:
        data = json.loads(p.stdout)
    except json.JSONDecodeError:
        log("  recover-key 输出不是 JSON")
        return None
    cands = data.get("candidates") or []
    if not cands:
        log("  没有候选 key")
        return None
    cands.sort(key=lambda c: float(c.get("score") or 0), reverse=True)
    best = cands[0]
    key = normalize_key(str(best.get("key") or ""))
    score = float(best.get("score") or 0)
    hca_count = int(data.get("hca_count") or 0)
    log(f"  候选 {len(cands)} 个，最高分 {score:.3f}，HCA 数 {hca_count}，key 长度 {len(key or '')}")
    if not key or score < 0.9 or hca_count <= 0:
        log("  最高分候选不可靠，放弃自动写入")
        return None
    # 实际解码验证
    dec = work / "verify"
    shutil.rmtree(dec, ignore_errors=True)
    dec.mkdir(parents=True, exist_ok=True)
    p2 = run([str(crico), str(afs2), "-o", str(dec), "--key", key, "-q"], timeout=1800)
    files = list(dec.glob("*"))
    if p2.returncode != 0 or not files:
        log(f"  解码验证失败：{(p2.stderr or p2.stdout).strip()[-300:]}")
        return None
    log(f"  解码验证通过（{len(files)} 个文件）")
    return key


def auto_recover(game_root: Path, tools_dir: str | None = None) -> str:
    retoc, crico = find_tools(tools_dir)
    paks = game_paks(game_root)
    workroot = APP_DIR / "save" / "_temp"
    workroot.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix="ffrs_key_", dir=str(workroot)))
    try:
        log(f"游戏目录：{game_root}")
        base = prepare_base_paks(paks, work)
        for bank in BANK_CANDIDATES:
            log(f"尝试音库：{bank}")
            afs2 = extract_afs2(retoc, base, work, bank)
            if not afs2:
                continue
            key = recover_key(crico, afs2, work)
            if key:
                target = save_audio_key(key)
                log(f"已写入：{target}")
                log(f"key：{key[:4]}...{key[-4:]}（已脱敏显示）")
                return key
        raise RuntimeError("自动获取失败。可手动运行 cricodecs --recover-key，或把 key 写入 tools\\criwarekey.txt")
    finally:
        if os.environ.get("FFRS_KEEP_TEMP") != "1":
            shutil.rmtree(work, ignore_errors=True)


def gui() -> None:
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk

    win = tk.Tk()
    win.title("FFRS 音频 Key 工具")
    win.geometry("760x520")

    frm = ttk.Frame(win, padding=12)
    frm.pack(fill="both", expand=True)
    ttk.Label(frm, text="游戏根目录（包含 FFRS/Content/Paks）").pack(anchor="w")
    row = ttk.Frame(frm)
    row.pack(fill="x", pady=4)
    var = tk.StringVar()
    ttk.Entry(row, textvariable=var).pack(side="left", fill="x", expand=True)
    ttk.Button(row, text="浏览…", command=lambda: var.set(filedialog.askdirectory() or var.get())).pack(side="left", padx=6)

    out = tk.Text(frm, height=20, wrap="word")
    out.pack(fill="both", expand=True, pady=8)

    def write(msg: str):
        out.insert("end", msg + "\n")
        out.see("end")

    def start():
        game = Path(var.get().strip())
        if not game.is_dir():
            messagebox.showwarning("提示", "请选择游戏根目录")
            return

        def job():
            try:
                write("开始…")
                auto_recover(game)
                write("完成。")
            except Exception as e:
                write(f"失败：{e}")
                write("可手动：cricodecs --recover-key -f hca <原始.hca>，把 key 写入 tools\\criwarekey.txt")
        threading.Thread(target=job, daemon=True).start()

    ttk.Button(frm, text="自动获取 Key", command=start).pack(anchor="e")
    win.mainloop()


def main() -> None:
    ap = argparse.ArgumentParser(description="FFRS 音频 Key 自动获取工具")
    ap.add_argument("--game-root", help="游戏根目录")
    ap.add_argument("--tools-dir", help="包含 retoc.exe / cricodecs.exe 的目录")
    ap.add_argument("--no-gui", action="store_true", help="命令行模式")
    args = ap.parse_args()
    if args.no_gui or args.game_root:
        key = auto_recover(Path(args.game_root), args.tools_dir)
        log(f"OK：{key[:4]}...{key[-4:]}")
    else:
        gui()


if __name__ == "__main__":
    main()
