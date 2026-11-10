# af-score 桌面版 v1.2

AlphaFold3 多聚体预测结果的评分看板，打包成 Windows 桌面程序：
**WebView2 原生窗口 + 便携 Python 运行时**，解压即用，目标机器不需要装 Python。

- 内置 35 个设计 / 175 个模型的评分结果，打开就能看
- **窗口内直接添加数据包**：点按钮选 zip 或拖进窗口，自动扫描入库
- **窗口内删除设计**：行尾 ✕ → 确认 → 删源包与缓存 + 重算排名与图表
- 支持排序、筛选、评分口径切换、Pareto 前沿、5 张结果图、设计详情

## 快速使用

1. 下载本仓库（`Code` → `Download ZIP`）或 `git clone`
2. 解压到任意目录（支持中文路径）
3. 双击 **`af-score.exe`**

第一次启动约 3–5 秒（后端起服务 + 加载数据），随后出现窗口（默认 1680×1050，屏幕小会自动适配）。

> **被 Windows 拦截**（"Windows 已保护你的电脑"）：点「更多信息 → 仍要运行」；
> 或右键 `af-score.exe` → 属性 → 勾选「解除锁定」；
> 或直接双击 **`启动桌面版_兼容模式.cmd`**（不经过 exe，用 Edge 窗口打开）。

## 添加数据包

不用手动放文件夹了：

- **点工具栏「＋ 添加数据包」** → 选 `.zip`（可多选）
- 或**把 zip 拖进窗口**（蓝色虚线遮罩，松手即可）

右下角显示每个文件的上传进度，全部传完会**自动扫描**，表格与图表自动刷新。
同名包会提示是否覆盖。

约束：只接受 `.zip`、单包 ≤ 400 MB、扫描进行中不收新包、上传与删除仅限本机。

## 删除设计

- 表格最右列点 **✕**，或详情面板底部 **「删除这个设计」**
- 确认框会说明：将从结果移除并重算；源包在 `incoming\` 时一并删除源文件，
  否则（如内置的 35 个基础设计）只移除结果
- 删除后自动重算排名与 5 张图；删空则回到「还没有数据」的空状态

删除不可撤销；需要保留原始 zip 的话，请先把它挪出 `incoming\`。

## 目录结构

```
af-score.exe               C++ 外壳（Win32 + WebView2）
app\afscore\               程序代码（与 Web 版同源）
runtime\python\            嵌入式 Python 3.15 + numpy/pandas/matplotlib
data\out\                  结果：scores.csv / summary_by_design.csv / cache / figures
incoming\                  数据包目录（上传的包落在这里）
config.json                数据目录配置
启动桌面版_调试.cmd          带控制台，出错看这里（同时写 data\shell.log）
启动桌面版_兼容模式.cmd      不经过 exe 的备用启动方式
【必读】使用说明.txt         中文详细说明（仅在 zip 分发包里，不入库）
build\                     构建脚本（launcher.cpp / build.bat / build_window.py）
```

## 技术说明

- **外壳**：Win32 窗口 + WebView2 控件，选空闲端口拉起后端，加载 `http://127.0.0.1:<port>/`；
  关窗时请求 `/api/quit` 让后端优雅退出，超时再终止。
- **后端**：`python -m afscore.web`，只监听 `127.0.0.1`，不对外暴露；
  扫描、评分、出图逻辑与 Web 版完全一致。
- **新增接口**：`PUT /api/upload?name=<zip>&overwrite=0|1`（流式落盘 + zip 魔数校验）、
  `POST /api/delete {"job": "..."}`（删源包/缓存/清单后后台重算）。
  两者都只允许本机调用，且扫描/重算进行中返回 409。
- **降级**：WebView2 不可用时自动改用 Edge 应用窗口。

### 自己构建

```powershell
# 需要 VS 2026（C++ 桌面工作负载）+ WebView2 SDK（build\sdk）
cd build
python make_icon.py                        # 生成图标（可选）
build.bat                                  # 编译 af-score.exe
python build_window.py --skip-download     # 组装运行时与数据
python build_window.py --zip               # 另外打成 zip
```

## 数据说明

仓库内 `data\out` 只含本项目 35 个设计的评分结果（约 3 MB），不含 1.5 GB 原始预测包。

## 许可

MIT，见 [LICENSE](LICENSE)。
