af-score 桌面版 v1.2
================

启动：双击 af-score.exe（或 启动桌面版_调试.cmd 看详细报错）

【添加数据包】不用再手动放文件夹了：
  方式一：点工具栏「＋ 添加数据包」→ 选 zip（可多选）
  方式二：把 zip 直接拖进窗口
  上传完会自动扫描，右下角有进度；表格与图表自动更新
  同名包会提示是否覆盖

【删除设计】
  点表格最右列的「✕」，或详情面板底部「删除这个设计」
  确认框会说明：源包在 incoming 目录时一并删除源文件，否则只移除结果
  删除后自动重算排名与图表

【扫描新包】如果手动把 zip 放进了 incoming 目录，点「扫描新包」也可以

数据与配置：
  data\out       结果（scores.csv / summary_by_design.csv / figures）
  incoming       新包投放目录（上传的包会落在这里）
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
