# Oxygen Rate Fit User Manual

## Overview

**Oxygen Rate Fit** is a local tool for analyzing oxygen consumption curves from TXT files exported by instruments such as PyroScience. It reads the time and oxygen columns, automatically finds a suitable linear oxygen-consumption region, performs a linear fit, and reports the oxygen-rate in `umol/L/s`.

The software also supports manual continuous point selection, real-time display of `oxygen rate`, `R2`, and fitting point count, and one-click export of 600 DPI PNG figures.

## Distribution and Requirements

There are two recommended ways to use or share the software.

### Option A: Packaged User Version

This is the best option for sharing with users who are not familiar with Python.

If the software is packaged as a standalone Windows program, the user only needs:

- Windows
- The packaged software folder or executable
- A browser, which is already included in Windows systems

The user does **not** need to install Python or Python packages manually.

This option requires the developer to package the Python server and dependencies into an executable first, for example by using PyInstaller. After packaging, the launcher can start the local server directly from the bundled executable.

### Option B: Source-Code Version

This is the current developer/source version.

If the user runs the files directly from this folder, the computer needs:

- Windows
- Python 3.11 or a compatible Python 3 version
- Required Python packages, especially `matplotlib`

This is because `oxygen_rate_web.py` provides the local web server, data parsing, fitting, CSV writing, and PNG export. The browser page itself is only the interface.

If a user's computer does not have Python installed, the source-code version will not run directly. In that case, use the packaged user version instead.

## Start the Web App

For the source-code version:

1. Open the software folder.
2. Double-click `start_oxygen_rate_web.bat`.
3. Open or refresh:

```text
http://127.0.0.1:8765
```

Do not use the page by directly opening `index.html`. The page may display, but upload, fitting, saving, and PNG export require the local Python server.

## Input Data

The TXT file should contain a table header row with:

- `dt (s)` for time
- `Oxygen` for oxygen concentration

The program automatically searches for the required columns and extracts numeric data. Oxygen concentration is treated as `umol/L`, and oxygen-rate is reported as `umol/L/s`.

## Automatic Fitting

The automatic fitting mode is designed for curves with an oxygen peak followed by a falling oxygen-consumption region.

The software:

- Finds the oxygen peak.
- Searches the post-peak falling region.
- Looks for a stable linear window.
- Requires a negative slope for oxygen consumption.
- Prefers high-quality fits:
  - first `R2 >= 0.9999`
  - then `R2 >= 0.999`
  - otherwise the best available stable candidate
- Avoids obvious plateau points before the real oxygen-consumption region.

## Manual Fitting

Manual fitting can be used when the automatic window is not ideal.

You can select points in two ways:

- Enter **Start** and **End**, then click **Select range**.
- Click points directly on the curve.

The selected fitting region is always continuous. Every point between the selected start and end is included in the fit.

Click **Save manual fit** after selecting at least 3 points.

## Axis Range

Use the axis controls on the left side:

- `X min`
- `X max`
- `Y min`
- `Y max`

Click **Apply axes** to use custom ranges. Click **Auto range** to restore automatic scaling.

The current axis range is also used when exporting PNG figures.

## Output Files

For saved fits, output files are written to:

```text
<input folder>\oxygen_rate_fit_web\<sample name>\
```

Common output files include:

- `selected_oxygen_data.csv`: full parsed oxygen data.
- `rate_line_points.csv`: full data with fitting-window information.
- `rate_line_summary.txt`: slope, intercept, oxygen-rate, R2, and notes.
- `rate_line.png`: saved plot for normal saved outputs.

For folder/batch processing, the batch summary is saved as:

```text
<input folder>\oxygen_rate_fit_web\batch_summary.csv
```

## PNG Export

Click **Export PNG** to export a 600 DPI fitting figure.

Rules:

- At least 3 fitting points are required.
- There is no upper point-count limit.
- The current continuous fitting window is used.
- The current axis range is used.
- PNG is saved to the system Downloads folder.

PNG export is not automatic. It happens only when **Export PNG** is clicked.

## Command-Line Use

The core fitting script can also be run directly:

```powershell
& 'C:\Users\19104\AppData\Local\Programs\Python\Python311\python.exe' .\oxygen_rate_fit.py "G:\path\to\data_or_folder" --output-dir oxygen_rate_fit_output
```

This command-line mode is part of the source-code version, so Python is required.

## Troubleshooting

### The page opens but upload or fitting does not work

The page was probably opened directly as `index.html`. Start the local server first, then open:

```text
http://127.0.0.1:8765
```

### The user does not have Python

Use a packaged standalone version. The current source-code folder requires Python because the fitting and PNG export are performed by Python scripts.

### PNG export fails

Check that:

- At least 3 fitting points are selected.
- The local server is running.
- `matplotlib` is installed, if using the source-code version.
- **Export PNG** was clicked.

---

# Oxygen Rate Fit 使用手册

## 软件简介

**Oxygen Rate Fit** 是一个用于分析 oxygen-rate 的本地工具，可以读取 PyroScience 等仪器导出的 TXT 数据，自动提取时间和 oxygen 数据，识别合适的氧消耗线性区间，完成线性拟合，并输出 oxygen-rate，单位为 `umol/L/s`。

软件同时支持手动连续选点、实时显示 `oxygen rate`、`R2` 和拟合点数，并支持一键导出 600 DPI 的 PNG 拟合图。

## 分发方式与运行要求

这个软件可以有两种使用方式。

### 方式 A：打包后的普通用户版

这是最适合分享给普通用户的方式。

如果软件已经打包成独立的 Windows 程序，用户只需要：

- Windows 系统
- 打包好的软件文件夹或 exe 程序
- 浏览器，Windows 系统一般自带

用户不需要自己安装 Python，也不需要手动安装 `matplotlib` 等 Python 包。

这种方式需要开发者先把 Python 后端和依赖一起打包成可执行程序，例如使用 PyInstaller。打包后，启动程序可以直接运行本地服务。

### 方式 B：源码版

这是当前这个文件夹的开发/源码版本。

如果用户直接运行当前这些 `.py` 和 `.bat` 文件，则电脑需要：

- Windows 系统
- Python 3.11 或兼容的 Python 3 版本
- 必要的 Python 包，尤其是 `matplotlib`

原因是 `oxygen_rate_web.py` 负责本地网页服务、数据解析、线性拟合、CSV 写入和 PNG 导出。浏览器页面本身只是操作界面。

如果用户电脑没有安装 Python，源码版不能直接运行。此时建议使用打包后的普通用户版。

## 启动网页软件

对于源码版：

1. 打开软件所在文件夹。
2. 双击 `start_oxygen_rate_web.bat`。
3. 打开或刷新：

```text
http://127.0.0.1:8765
```

不要直接双击 `index.html` 作为常规使用方式。直接打开 HTML 可以看到页面，但上传、拟合、保存和 PNG 导出都需要本地 Python 服务。

## 输入数据

TXT 文件应包含表头：

- `dt (s)`：时间列
- `Oxygen`：氧浓度列

程序会自动寻找对应列并提取数值。oxygen 浓度按 `umol/L` 处理，oxygen-rate 输出单位为 `umol/L/s`。

## 自动拟合

自动拟合适用于先出现 oxygen peak，随后进入氧消耗下降区间的曲线。

软件会：

- 找到 oxygen 最大值点。
- 搜索 peak 后的下降区间。
- 寻找稳定的线性窗口。
- 要求氧消耗拟合斜率为负。
- 优先选择高质量拟合：
  - 优先 `R2 >= 0.9999`
  - 其次 `R2 >= 0.999`
  - 如果都不满足，则选择最稳定的可用候选
- 避免把平台期波动点误选为 oxygen consumption 区间。

## 手动拟合

当自动选区不理想时，可以手动调整。

手动选点有两种方式：

- 输入 **Start** 和 **End**，然后点击 **Select range**。
- 直接点击曲线上的点。

手动拟合区间始终保持连续。起点和终点之间的所有点都会参与拟合，不会出现中间断开的选点。

选择至少 3 个点后，点击 **Save manual fit**。

## 坐标轴范围

左侧可以调整：

- `X min`
- `X max`
- `Y min`
- `Y max`

点击 **Apply axes** 应用自定义坐标范围。点击 **Auto range** 恢复自动范围。

当前坐标轴范围也会用于 PNG 导出。

## 输出文件

保存拟合后，输出文件位于：

```text
<输入文件所在文件夹>\oxygen_rate_fit_web\<样品名>\
```

常见输出文件包括：

- `selected_oxygen_data.csv`：完整解析后的 oxygen 数据。
- `rate_line_points.csv`：完整数据及拟合区间信息。
- `rate_line_summary.txt`：斜率、截距、oxygen-rate、R2 和备注。
- `rate_line.png`：普通保存输出的拟合图片。

批量处理时，汇总文件保存为：

```text
<输入文件夹>\oxygen_rate_fit_web\batch_summary.csv
```

## PNG 导出

点击 **Export PNG** 可以导出 600 DPI 拟合图。

规则：

- 至少需要 3 个拟合点。
- 没有点数上限。
- 使用当前连续拟合区间。
- 使用当前坐标轴范围。
- PNG 保存到系统 Downloads 文件夹。

PNG 不会自动导出，只有点击 **Export PNG** 时才会生成。

## 命令行使用

核心脚本也可以直接运行：

```powershell
& 'C:\Users\19104\AppData\Local\Programs\Python\Python311\python.exe' .\oxygen_rate_fit.py "G:\path\to\data_or_folder" --output-dir oxygen_rate_fit_output
```

命令行模式属于源码版，因此需要 Python。

## 常见问题

### 页面可以打开，但不能上传或拟合

通常是因为直接打开了 `index.html`。请先启动本地服务，再打开：

```text
http://127.0.0.1:8765
```

### 用户电脑没有 Python 怎么办？

请使用打包后的独立版本。当前源码文件夹需要 Python，因为拟合和 PNG 导出是由 Python 脚本完成的。

### PNG 导出失败

请检查：

- 是否至少选择了 3 个拟合点。
- 本地服务是否正在运行。
- 如果使用源码版，Python 环境中是否安装了 `matplotlib`。
- 是否点击了 **Export PNG**。
