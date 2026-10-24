# Python Environment

## Summary

- **Primary version: Python 3.14 (64-bit)** — the version this toolkit is tested and run with
- Local path: `C:\Python314\python.exe`
- `启动 Toolkit.bat` uses `python` from PATH (falls back to `py`)
- **Python 3.11.6 is also installed** on this machine, but it is **missing the third-party
  packages**, so some pages will fail to open with it

## The two versions on this machine

| Version | Path | Third-party packages | Usable as-is |
|---|---|---|---|
| **3.14.3** | `C:\Python314\python.exe` | ✅ complete | ✅ recommended |
| 3.11.6 | `%LOCALAPPDATA%\Programs\Python\Python311\python.exe` | ❌ missing numpy/Pillow/scipy/opencv/openpyxl | ⚠️ pip install first |

## Dependencies

### Standard library (bundled with Python)

`tkinter` (GUI; included in the official Windows installer), `json`, `re`, `subprocess`,
`pathlib`, `threading`, `sqlite3`, etc.

> `tkinter` must be available; stripped/portable Python builds may lack it.

### Third-party packages (install with pip)

| Package (import name) | Used for | Version on 3.14 here |
|---|---|---|
| `numpy` | array/image math (sprites, outline) | 2.5.3 |
| `Pillow` (`PIL`) | image I/O (sprites, outline) | 12.3.0 |
| `scipy` | morphology/distance transforms (outline tool) | 1.18.1 |
| `opencv-python` (`cv2`) | template matching / image processing (sprites) | 5.0.0 |
| `openpyxl` | Excel import/export (dialogue sheets) | 3.1.5 |

Install:

```powershell
python -m pip install numpy Pillow scipy opencv-python openpyxl
```

> To use 3.11, install the same packages into it first.

## What each tool actually needs

| Page / Tool | Third-party packages |
|---|---|
| Skill Modification | none (stdlib only) |
| Mod Merge | none (stdlib only) |
| Final Blow Animation Replacer | none (calls bundled ffmpeg/cricodecs) |
| Story Script & Audio Replacer | `openpyxl` (only for Excel dialogue import/export) |
| Sprite Analyzer & Converter | `numpy`, `Pillow`, `opencv-python` |
| Outline Generator | `numpy`, `Pillow`, `scipy` |

## Self-check

```powershell
python -V
python -c "import tkinter, numpy, PIL, scipy, cv2, openpyxl; print('deps OK')"
```

Both must pass.

## Other requirements

- **.NET 8 Desktop Runtime** for `tools/ffr-dt/ffr-dt.exe` (see `tools/ffr-dt/BUILD_README_EN.md`)
- External tools (retoc/repak/ffmpeg/cricodecs/UAssetGUI) are native executables; no Python needed
- No virtualenv required. If multiple Pythons are installed, make sure `python` on PATH is 3.14,
  or start with `py -3.14 FFRS_Toolkit.py`

## Deploying to another machine

1. Install Python 3.14 (64-bit; enable "tcl/tk and IDLE")
2. `python -m pip install numpy Pillow scipy opencv-python openpyxl`
3. Install the .NET 8 Desktop Runtime
4. Run the self-check commands above
5. Double-click `启动 Toolkit.bat`
