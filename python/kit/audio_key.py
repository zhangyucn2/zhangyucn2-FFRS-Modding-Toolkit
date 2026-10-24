"""FFRS 音频 key 的读取与保存。

公开版不内置 key。读取顺序：
  1. 环境变量 FFRS_AUDIO_KEY
  2. <工具根>/tools/criwarekey.txt
  3. <工具根>/tools/criwarekey.example.txt（仅当里面真的填了 key）

key 格式：0x + 14~16 位十六进制（HCA 有效位可能是 56 位）。
"""
from __future__ import annotations

import os
import re
from pathlib import Path

ENV_NAME = "FFRS_AUDIO_KEY"
_KEY_RE = re.compile(r"(?:0[xX])?([0-9A-Fa-f]{14,16})")


class AudioKeyMissing(RuntimeError):
    pass


def toolkit_root() -> Path:
    # python/kit/audio_key.py -> python/kit -> python -> 工具根
    return Path(__file__).resolve().parents[2]


def key_paths() -> list[Path]:
    root = toolkit_root()
    return [
        root / "tools" / "criwarekey.txt",
        root / "tools" / "criwarekey.example.txt",
        root / "python" / "config" / "criwarekey.txt",
    ]


def normalize_key(text: str) -> str | None:
    """从文本中取第一个 14~16 位十六进制 key，返回 0x 前缀形式。"""
    if not text:
        return None
    # 去掉 # / ; 注释行与行尾注释
    cleaned = []
    for line in text.splitlines():
        line = line.split("#", 1)[0].split(";", 1)[0].strip()
        if line:
            cleaned.append(line)
    m = _KEY_RE.search(" ".join(cleaned))
    if not m:
        return None
    digits = m.group(1).upper()
    return "0x" + digits


def _read_key_file(path: Path) -> str | None:
    try:
        if not path.is_file():
            return None
        return normalize_key(path.read_text(encoding="utf-8", errors="replace"))
    except OSError:
        return None


def find_audio_key() -> str | None:
    env = os.environ.get(ENV_NAME, "").strip()
    if env:
        key = normalize_key(env)
        if key:
            return key
    for path in key_paths():
        key = _read_key_file(path)
        if key:
            return key
    return None


def get_audio_key() -> str:
    key = find_audio_key()
    if key:
        return key
    raise AudioKeyMissing(
        "未配置音频 key。请把 key 写入 tools\\criwarekey.txt，"
        "或设置环境变量 FFRS_AUDIO_KEY；也可运行 python\\FFRS_AudioKeyTool.py 自动获取。"
    )


def save_audio_key(key: str, path: Path | None = None) -> Path:
    key = normalize_key(key) or ""
    if not key:
        raise ValueError("无效的音频 key（需要 14~16 位十六进制）")
    root = toolkit_root()
    target = path or (root / "tools" / "criwarekey.txt")
    target.parent.mkdir(parents=True, exist_ok=True)
    text = (
        "# FFRS 音频 key（cricodecs 用）\n"
        "# 由 FFRS_AudioKeyTool.py 自动写入；也可手动粘贴。\n"
        f"{key}\n"
    )
    target.write_text(text, encoding="utf-8")
    return target
