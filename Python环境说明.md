# Python 环境说明

## 结论

- **主用版本：Python 3.14（64 位）** —— 本工具链实际测试/运行的就是它
- 本机路径：`C:\Python314\python.exe`
- 启动脚本 `启动 Toolkit.bat` 用的是 PATH 里的 `python`（找不到则退回 `py`）
- 本机还装了 **Python 3.11.6**，但**缺少第三方依赖**，直接用会打不开部分页面

## 两个版本的本机情况

| 版本 | 路径 | 第三方依赖 | 能否直接用 |
|---|---|---|---|
| **3.14.3** | `C:\Python314\python.exe` | ✅ 齐全 | ✅ 推荐 |
| 3.11.6 | `%LOCALAPPDATA%\Programs\Python\Python311\python.exe` | ❌ 缺 numpy/Pillow/scipy/opencv/openpyxl | ⚠️ 需先 pip 安装 |

## 依赖清单

### 标准库（装 Python 时自带）

`tkinter`（GUI，Windows 官方安装包默认包含）、`json`、`re`、`subprocess`、`pathlib`、`threading`、`sqlite3` 等。

> `tkinter` 必须可用；精简版/绿色版 Python 可能缺它。

### 第三方包（需要 pip 安装）

| 包（import 名） | 用途 | 本机 3.14 版本 |
|---|---|---|
| `numpy` | 图像/数组计算（精灵片、描边） | 2.5.3 |
| `Pillow`（`PIL`） | 图片读写（精灵片、描边） | 12.3.0 |
| `scipy` | 形态学/距离变换（描边工具） | 1.18.1 |
| `opencv-python`（`cv2`） | 模板匹配/图像处理（精灵片） | 5.0.0 |
| `openpyxl` | Excel 导入/导出（文本工具台词表） | 3.1.5 |

安装命令：

```powershell
python -m pip install numpy Pillow scipy opencv-python openpyxl
```

> 3.11 想用的话，先装这三个最容易缺的即可跑大部分页面：
> `python -m pip install numpy Pillow scipy opencv-python openpyxl`

## 各工具实际需要什么

| 页面 / 工具 | 需要的第三方包 |
|---|---|
| 技能修改 | 无（纯标准库） |
| 模组合并 | 无（纯标准库） |
| 终结技动画替换（Final Blow） | 无（调用外部 ffmpeg/cricodecs） |
| 剧情台本及语音替换（Story Script） | `openpyxl`（只在导入/导出 Excel 台词表时用） |
| 精灵片解析还原（Sprite Analyzer） | `numpy`、`Pillow`、`opencv-python` |
| 描边贴图生成（Outline Generator） | `numpy`、`Pillow`、`scipy` |

## 自检命令

```powershell
python -V
python -c "import tkinter, numpy, PIL, scipy, cv2, openpyxl; print('deps OK')"
```

两条都通过就没问题。

## 其它依赖

- **.NET 8 Desktop Runtime**：`tools/ffr-dt/ffr-dt.exe` 需要（详见 `tools/ffr-dt/BUILD_说明.md`）
- 外部工具（retoc/repak/ffmpeg/cricodecs/UAssetGUI）是 exe，不需要 Python
- 不需要虚拟环境；如果机器上有多个 Python，确保 PATH 里的 `python` 是 3.14，
  或直接 `py -3.14 FFRS_Toolkit.py` 启动

## 换机器部署

1. 安装 Python 3.14（64 位，勾选 "tcl/tk and IDLE"）
2. `python -m pip install numpy Pillow scipy opencv-python openpyxl`
3. 装 .NET 8 Desktop Runtime
4. 运行上面的自检命令
5. 双击 `启动 Toolkit.bat`
