# Third-party tools — origin & license notes

Most executables in this folder are **not original work of this project**. They are used
only to call/package game data. This project claims no rights over them; confirm each
license before redistributing.

## Tool list

| File | Origin | Purpose |
|---|---|---|
| `retoc.exe` | retoc (trumank) <https://github.com/trumank/retoc> | IoStore (`.utoc/.ucas`) read/write: `to-legacy` / `to-zen` / `unpack-raw` / `pack-raw` |
| `repak.exe` | repak (trumank) <https://github.com/trumank/repak> | `.pak` read/write; create empty `_P.pak` |
| `UAssetGUI/UAssetGUI.exe` | UAssetGUI (atenfyr) <https://github.com/atenfyr/UAssetGUI> | uasset ↔ JSON (this toolkit mostly uses ffr-dt now) |
| `ffr-dt/` | FFR Vision Studio <https://github.com/FFBE-JP-Translation/FFR-Vison-Studio><br>source `mod-tools/src/ffr-dt/` | DataTable read/patch, sequence cloning (`patch` / `tojson` / `fromjson`)<br>build & runtime notes: `BUILD_README_EN.md` |
| `ffr-dt/UAssetAPI.dll` | UAssetAPI (atenfyr) <https://github.com/atenfyr/UAssetAPI><br>**1.1.0.0** here (shipped with ffr-dt) | UE asset (uasset/uexp) read/write library; core dependency of ffr-dt, also used by UAssetGUI |
| `ffmpeg.exe` | FFmpeg <https://ffmpeg.org/> | video encoding (VP9 / alpha for USM replacement) |
| `cricodecs.exe` | community tool (keep its original attribution when redistributing) | CRIWARE (USM / HCA) decode & encode |
| `oo2core_9_win64.dll` | Oodle (RAD Game Tools) | Oodle decompression (used by retoc / repak) — check its license |
| `FFRS.usmap` | mapping file generated from this game (UE 5.6) | used by UAssetAPI / ffr-dt; **not an executable**, has its own path setting on the Home tab |

> **UAssetAPI** is a library, not an executable. It is loaded with `ffr-dt/` (`UAssetAPI.dll`, version 1.1.0.0). Do not extract or redistribute it separately; it is updated together with ffr-dt. See the upstream repository for its license.

## Notes

- This project only invokes these tools and is not responsible for their behaviour or licensing.
- Before distributing the whole toolkit, verify each license; when unsure, **provide the source
  links only** and let users download the tools themselves.
- **Do not redistribute the ffr-dt binaries on their own.** See `ffr-dt/BUILD_README_EN.md`.
