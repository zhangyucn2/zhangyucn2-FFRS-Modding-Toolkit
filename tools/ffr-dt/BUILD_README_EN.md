# ffr-dt — Origin & Build Notes

> **NOT ORIGINAL WORK.** ffr-dt is a C# tool from the FFR Vision Studio project
> (built on UAssetAPI). This toolkit only builds and uses it; no modifications were
> made here. Please do **not** redistribute the binaries in this folder. When needed,
> obtain or build it from the source repository below and comply with its LICENSE.

## Source repository

- Repository: <https://github.com/FFBE-JP-Translation/FFR-Vison-Studio>
- Source path: `mod-tools/src/ffr-dt/` (`ffr-dt.csproj`)
- Local snapshot used: `<本地 FFR-Vison-Studio 快照>`

## Origin of the binaries in this folder

| Item | Value |
|---|---|
| Built | 2026-10-20 01:36 |
| Method | local `dotnet build` of the source repository above |
| Output dir | `mod-tools/src/ffr-dt/bin/Release/net8.0/` |
| SHA256(ffr-dt.exe) | `2819A1FA645C0BD63AD1BFA46C445D5154BA0BC002ADE3B9F1FB07AE79D09944` |

## Build it yourself

```powershell
cd <source repo>\mod-tools
dotnet build src\ffr-dt\ffr-dt.csproj -c Release
# output: src\ffr-dt\bin\Release\net8.0\
```

- Requires: .NET SDK 8 or newer
- Target framework: `net8.0` (framework-dependent)

## Runtime requirement

`ffr-dt.exe` needs the **.NET 8 Desktop Runtime** (`Microsoft.NETCore.App 8.x`).

If the target machine has no .NET, publish a self-contained build instead:

```powershell
dotnet publish src\ffr-dt\ffr-dt.csproj -c Release -r win-x64 --self-contained true -p:PublishSingleFile=true
```

## Keep the whole folder together

`ffr-dt.exe` is only the apphost (~148 KB); the actual logic lives in `ffr-dt.dll`.
All of these files are required:

```
ffr-dt.exe
ffr-dt.dll
ffr-dt.deps.json
ffr-dt.runtimeconfig.json
Newtonsoft.Json.dll
UAssetAPI.dll
ZstdSharp.dll
```

## Commands used by this toolkit

```
ffr-dt tojson   <uasset> <json> --usmap <FFRS.usmap>
ffr-dt fromjson <json> <out>   --usmap <FFRS.usmap>
ffr-dt patch    <job.json>     --usmap <FFRS.usmap>
ffr-dt rows     <uasset> [json]
ffr-dt info     <uasset>
```

## Updating

Rebuild from the source repository when it is updated. The JSON schema used by
`patch` / `tojson` may change between versions — after upgrading, build a small test
MOD and verify before replacing the binaries in this folder.
