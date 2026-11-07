# af-score 桌面版

AlphaFold3 多聚体预测结果的评分看板，打包成 Windows 桌面程序：
**WebView2 原生窗口 + 便携 Python 运行时**，解压即用，目标机器不需要装 Python。

- 内置 35 个设计 / 175 个模型的评分结果，打开就能看
- 放新包进 `incoming\` 可增量重算（单链约 2 秒、20 聚体约 40 秒）
- 支持排序、筛选、评分口径切换、Pareto 前沿、5 张结果图、设计详情

## 快速使用

1. 下载本仓库（`Code` → `Download ZIP`）或 `git clone`
2. 解压到任意目录（支持中文路径）
3. 双击 **`af-score.exe`**

第一次启动约 3–5 秒（后端起服务 + 加载数据），随后出现窗口。

> **被 Windows 拦截**（"Windows 已保护你的电脑"）：点「更多信息 → 仍要运行」；
> 或右键 `af-score.exe` → 属性 → 勾选「解除锁定」；
> 或直接双击 **`启动桌面版_兼容模式.cmd`**（不经过 exe，用 Edge 窗口打开）。

## 加了新数据怎么办

1. 把 `fold_*.zip` 放进 `incoming\`
2. 窗口里点「扫描新包」
3. 删掉 zip 再点一次扫描，对应设计会被移除

结果写在 `data\out\`；`config.json` 可把 `data` 指向共享目录（多人看同一份结果）。

## 目录结构

```
af-score.exe               C++ 外壳（Win32 + WebView2）
app\afscore\               程序代码（与 Web 版同源）
runtime\python\            嵌入式 Python 3.15 + numpy/pandas/matplotlib
data\out\                  结果：scores.csv / summary_by_design.csv / cache / figures
incoming\                  新包投放目录
config.json                数据目录配置
启动桌面版_调试.cmd          带控制台，出错看这里（同时写 data\shell.log）
启动桌面版_兼容模式.cmd      不经过 exe 的备用启动方式
build\                     构建脚本（launcher.cpp / build.bat / build_window.py）
```

## 技术说明

- **外壳**：Win32 窗口 + WebView2 控件，选空闲端口拉起后端，加载 `http://127.0.0.1:<port>/`；
  关窗时请求 `/api/quit` 让后端优雅退出，超时再终止。
- **后端**：`python -m afscore.web`，只监听 `127.0.0.1`，不对外暴露；
  扫描、评分、出图逻辑与 Web 版完全一致。
- **降级**：WebView2 不可用时自动改用 Edge 应用窗口。

### 自己构建

```powershell
# 需要 VS 2026（C++ 桌面工作负载）+ WebView2 SDK（build\sdk）
cd build
build.bat                                  # 编译 af-score.exe
python build_window.py --skip-download     # 组装运行时与数据
python build_window.py --zip               # 另外打成 zip
```

## 数据说明

仓库内 `data\out` 只含本项目 35 个设计的评分结果（约 3 MB），不含 1.5 GB 原始预测包。

## 许可

MIT，见 [LICENSE](LICENSE)。
