# ffr-dt —— 来源与构建说明

> **不是本项目原创。** ffr-dt 是 FFR Vision Studio 项目里的 C# 工具（基于 UAssetAPI），
> 本项目只是**构建并使用**它，未做修改。
> 请勿把本目录的二进制随意转发；需要时请从源仓库自行获取/构建，并遵守源仓库的 LICENSE。

## 源仓库

- 仓库：<https://github.com/FFBE-JP-Translation/FFR-Vison-Studio>
- 源码位置：`mod-tools/src/ffr-dt/`（`ffr-dt.csproj`）
- 本地快照：`<本地 FFR-Vison-Studio 快照>`

## 本目录二进制的来源

| 项 | 值 |
|---|---|
| 构建时间 | 2026-10-20 01:36 |
| 构建方式 | 从上述源仓库本地 `dotnet build` |
| 产物目录 | `mod-tools/src/ffr-dt/bin/Release/net8.0/` |
| SHA256(ffr-dt.exe) | `2819A1FA645C0BD63AD1BFA46C445D5154BA0BC002ADE3B9F1FB07AE79D09944` |

## 自行构建

```powershell
cd <源仓库>\mod-tools
dotnet build src\ffr-dt\ffr-dt.csproj -c Release
# 产物：src\ffr-dt\bin\Release\net8.0\
```

- 需要：.NET SDK 8 或更高
- 目标框架：`net8.0`（framework-dependent）

## 运行时要求

运行 `ffr-dt.exe` 需要 **.NET 8 Desktop Runtime**（`Microsoft.NETCore.App 8.x`）。

若目标机器没有 .NET，可自行发布自包含版本：

```powershell
dotnet publish src\ffr-dt\ffr-dt.csproj -c Release -r win-x64 --self-contained true -p:PublishSingleFile=true
```

## 必须整个目录一起带

`ffr-dt.exe` 只是 apphost（约 148 KB），实际逻辑在 `ffr-dt.dll`。以下文件缺一不可：

```
ffr-dt.exe
ffr-dt.dll
ffr-dt.deps.json
ffr-dt.runtimeconfig.json
Newtonsoft.Json.dll
UAssetAPI.dll
ZstdSharp.dll
```

## 本项目用到的命令

```
ffr-dt tojson   <uasset> <json> --usmap <FFRS.usmap>
ffr-dt fromjson <json> <out>   --usmap <FFRS.usmap>
ffr-dt patch    <job.json>     --usmap <FFRS.usmap>
ffr-dt rows     <uasset> [json]
ffr-dt info     <uasset>
```

## 更新提示

源仓库更新后重新构建即可。`patch` / `tojson` 的 JSON 结构可能随版本变化，
升级后请先跑一个小 MOD 验证，再替换本目录的二进制。
