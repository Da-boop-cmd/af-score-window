af-score 桌面版
================

启动：双击 af-score.exe（或 启动桌面版_调试.cmd 看详细报错）

第一次打开会显示已有结果；要加新数据：
  1. 把 fold_*.zip 放进 incoming\
  2. 在窗口里点「扫描新包」
  3. 删掉 zip 再点一次扫描，对应设计会被移除

数据与配置：
  data\out       结果（scores.csv / summary_by_design.csv / figures）
  incoming       新包投放目录
  config.json    可把 data 改成共享目录（如 \\server\share\out）

排查：
  data\shell.log  外壳启动日志（端口、后端、WebView2 状态）
  需要 Windows 10/11 x64，系统自带 Edge/WebView2
  杀软拦截时，把整个文件夹加入信任

如果双击 af-score.exe 被 Windows 拦（已保护你的电脑）：
  1. 点「更多信息」→「仍要运行」；或
  2. 右键 af-score.exe → 属性 → 勾选「解除锁定」→ 确定；或
  3. 直接双击 启动桌面版_兼容模式.cmd（不经过 exe，用 Edge 窗口打开）
  4. 仍然不行：Windows 安全中心 → 病毒和威胁防护 → 排除项 → 添加这个文件夹



