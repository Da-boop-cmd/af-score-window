"""Web 看板的前端模板（纯 HTML/CSS/JS，无外部依赖，可离线运行）。

数据全部通过 /api/* 获取；图片走 /figures/<name>。
"""

INDEX_HTML = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>AlphaFold3 预测结果评分看板</title>
<style>
:root{
  --bg:#f6f8fb; --card:#ffffff; --ink:#1f2933; --muted:#6b7785;
  --line:#e3e8ef; --blue:#0053d6; --cyan:#65cbf3; --yellow:#ffdb13;
  --orange:#ff7d45; --green:#2f9e44; --red:#d64545;
}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);
  font-family:"Microsoft YaHei","PingFang SC",-apple-system,"Segoe UI",sans-serif;
  font-size:14px;line-height:1.6}
header{background:linear-gradient(135deg,#0b3d91,#0053d6);color:#fff;padding:22px 0 18px}
.wrap{max-width:1180px;margin:0 auto;padding:0 20px}
h1{margin:0 0 4px;font-size:22px;font-weight:600;letter-spacing:.5px}
.sub{opacity:.85;font-size:13px}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:12px;margin:18px 0 0}
.kpi{background:rgba(255,255,255,.12);border:1px solid rgba(255,255,255,.18);
  border-radius:10px;padding:10px 14px}
.kpi .v{font-size:20px;font-weight:600}
.kpi .k{font-size:12px;opacity:.8}
.ghost{margin-top:10px;padding:5px 12px;border-radius:8px;cursor:pointer;font-size:12px;
  background:rgba(255,255,255,.14);color:#fff;border:1px solid rgba(255,255,255,.35)}
.ghost:hover{background:rgba(255,255,255,.24)}
main{padding:22px 0 60px}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;
  padding:16px 18px;margin-bottom:18px;box-shadow:0 1px 2px rgba(16,24,40,.04)}
.card h2{margin:0 0 12px;font-size:16px;font-weight:600}
.card h2 .hint{font-weight:400;color:var(--muted);font-size:12px;margin-left:8px}
.toolbar{display:flex;flex-wrap:wrap;gap:10px;align-items:center;margin-bottom:12px}
.toolbar input,.toolbar select{padding:6px 10px;border:1px solid var(--line);
  border-radius:8px;font-size:13px;background:#fff;color:var(--ink)}
.toolbar input{width:220px}
.toolbar button{padding:6px 12px;border:1px solid var(--line);border-radius:8px;
  background:#fff;cursor:pointer;font-size:13px}
.toolbar button:hover{background:#eef3fb}
.count{color:var(--muted);font-size:12px;margin-left:auto}
table{width:100%;border-collapse:collapse;font-size:13px}
th,td{padding:7px 8px;text-align:right;border-bottom:1px solid var(--line);white-space:nowrap}
th:first-child,td:first-child{text-align:left}
th{position:sticky;top:0;background:#f9fbfd;font-weight:600;cursor:pointer;user-select:none;z-index:1}
th:hover{background:#eef3fb}
th .arw{color:var(--blue);font-size:10px;margin-left:3px}
tbody tr{cursor:pointer}
tbody tr:hover{background:#f2f7ff}
tbody tr.sel{background:#e6f0ff;box-shadow:inset 3px 0 0 var(--blue)}
.pill{display:inline-block;padding:1px 8px;border-radius:999px;font-size:11px;border:1px solid transparent}
.g-A{background:#e6efff;color:var(--blue);border-color:#c7d9ff}
.g-B{background:#e4f6fd;color:#0b7285;border-color:#c2e9f7}
.g-C{background:#fff8d6;color:#8a6d00;border-color:#f2e3a0}
.g-D{background:#ffeade;color:#a6400f;border-color:#f7cfb8}
.g-E{background:#ffe3e3;color:var(--red);border-color:#f5c2c2}
.tag{background:#eef2f7;color:#475467;padding:1px 7px;border-radius:6px;font-size:11px;margin-left:4px}
.detail{display:grid;grid-template-columns:1.1fr .9fr;gap:18px}
@media(max-width:900px){.detail{grid-template-columns:1fr}}
.metrics{display:grid;grid-template-columns:repeat(auto-fit,minmax(120px,1fr));gap:10px}
.metric{background:#f9fbfd;border:1px solid var(--line);border-radius:9px;padding:8px 10px}
.metric .k{color:var(--muted);font-size:11px}
.metric .v{font-size:16px;font-weight:600}
.bars{display:flex;align-items:flex-end;gap:10px;height:130px;padding:6px 2px 0}
.bar{flex:1;display:flex;flex-direction:column;justify-content:flex-end;align-items:center;height:100%}
.bar .fill{width:70%;background:linear-gradient(180deg,var(--cyan),var(--blue));
  border-radius:5px 5px 0 0;min-height:2px;transition:height .3s}
.bar.best .fill{background:linear-gradient(180deg,#ffe066,var(--orange))}
.bar .lab{font-size:11px;color:var(--muted);margin-top:4px}
.bar .val{font-size:11px;color:var(--ink);margin-bottom:3px}
.gal{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:14px}
.gal figure{margin:0;border:1px solid var(--line);border-radius:10px;overflow:hidden;background:#fff}
.gal img{width:100%;display:block}
.gal figcaption{padding:8px 10px;font-size:12px;color:var(--muted);border-top:1px solid var(--line)}
details{background:#f9fbfd;border:1px solid var(--line);border-radius:10px;padding:10px 14px;margin-top:10px}
summary{cursor:pointer;font-weight:600;font-size:14px}
.weight-tbl{width:100%;margin-top:10px;font-size:12.5px}
.weight-tbl td,.weight-tbl th{padding:5px 6px;border-bottom:1px solid var(--line);text-align:left}
.note{color:var(--muted);font-size:12px;margin-top:10px}
footer{color:var(--muted);font-size:12px;text-align:center;padding:0 0 30px}
.err{background:#ffe3e3;color:#a61b1b;padding:10px 14px;border-radius:8px;margin-bottom:12px}
.empty{color:var(--muted);padding:18px;text-align:center}
.mono{font-family:Consolas,monospace}
.banner{display:none;align-items:center;gap:12px;flex-wrap:wrap;
  padding:10px 14px;border-radius:10px;margin-bottom:16px;font-size:13px;
  border:1px solid transparent}
.banner.show{display:flex}
.banner.warn{background:#fff8d6;border-color:#f2e3a0;color:#7a5c00}
.banner.ok{background:#e6f7ea;border-color:#b7e4c7;color:#1b6b33}
.banner.bad{background:#ffe3e3;border-color:#f5c2c2;color:#a61b1b}
.banner .sp{flex:1}
.banner button{padding:5px 12px;border-radius:8px;border:1px solid rgba(0,0,0,.18);
  background:#fff;cursor:pointer;font-size:13px;color:#1f2933}
.banner button:hover{background:#f3f4f6}
.banner a{color:inherit;font-weight:600;text-decoration:underline}
.toolbar button[disabled]{opacity:.55;cursor:default}
tr.isnew td{background:#fffbe6}
.tag.new{background:#ffd666;color:#7a4d00}
button.primary{background:#0053d6;border-color:#0046b8;color:#fff;font-weight:600}
button.primary:hover{background:#0046b8}
#drop-mask{position:fixed;inset:0;background:rgba(0,83,214,.12);border:3px dashed #0053d6;
  display:none;align-items:center;justify-content:center;z-index:90;pointer-events:none}
#drop-mask.show{display:flex}
.drop-box{background:#fff;border-radius:14px;padding:22px 30px;font-size:16px;color:#0053d6;
  box-shadow:0 8px 30px rgba(0,0,0,.18);font-weight:600}
#up-panel{position:fixed;right:24px;bottom:24px;width:360px;max-width:calc(100vw - 32px);
  background:#fff;border-radius:14px;box-shadow:0 10px 34px rgba(0,0,0,.18);
  display:none;z-index:95;overflow:hidden;border:1px solid #e5e9f0}
#up-panel.show{display:block}
.up-head{padding:12px 14px;background:#f5f8ff;font-weight:600;font-size:14px;
  display:flex;justify-content:space-between;align-items:center;color:#1f2933}
#up-close{cursor:pointer;color:#7b8794;font-size:18px;line-height:1;padding:0 4px}
#up-list{max-height:240px;overflow:auto;padding:4px 14px}
.up-row{padding:8px 0;border-bottom:1px solid #f0f3f7;font-size:12px}
.up-row:last-child{border-bottom:none}
.up-name{display:flex;justify-content:space-between;gap:8px;color:#1f2933}
.up-name b{font-weight:600;word-break:break-all}
.up-name span{white-space:nowrap;color:#52606d}
.up-bar{height:5px;background:#eef2f7;border-radius:3px;margin-top:6px;overflow:hidden}
.up-fill{height:100%;width:0;background:#0053d6;transition:width .2s}
.up-row.ok .up-fill{background:#2f9e44}
.up-row.err .up-fill{background:#d64545}
.up-row.err .up-name span{color:#d64545}
.up-foot{padding:10px 14px;font-size:12px;color:#52606d;background:#fafbfc}
.act{width:34px;text-align:center}
.del-btn{border:none;background:transparent;color:#b0b7c3;cursor:pointer;font-size:14px;
  padding:2px 6px;border-radius:6px;line-height:1}
.del-btn:hover{background:#ffe3e3;color:#d64545}
button.danger{background:#d64545;border-color:#b93b3b;color:#fff;font-weight:600}
button.danger:hover{background:#b93b3b}
button.danger-ghost{margin-top:14px;background:#fff;border:1px solid #f0c2c2;color:#c92a2a}
button.danger-ghost:hover{background:#fff5f5}
#del-modal{position:fixed;inset:0;background:rgba(15,23,42,.45);display:none;
  align-items:center;justify-content:center;z-index:100}
#del-modal.show{display:flex}
.modal{background:#fff;border-radius:14px;padding:20px 22px;width:400px;
  max-width:calc(100vw - 40px);box-shadow:0 18px 50px rgba(0,0,0,.28)}
.modal h3{margin:0 0 10px;font-size:16px;color:#1f2933;word-break:break-all}
.modal-text{margin:0;font-size:13px;line-height:1.7;color:#52606d}
.modal-actions{display:flex;justify-content:flex-end;gap:10px;margin-top:18px}
.modal-actions button{padding:7px 16px;border-radius:9px;border:1px solid #d9dee7;
  background:#fff;cursor:pointer;font-size:13px}
/* 注意：这两条必须放在 .modal-actions button 之后，否则会被它的 background:#fff 覆盖 */
.modal-actions button.danger{background:#d64545;border-color:#b93b3b;color:#fff;font-weight:600}
.modal-actions button.danger:hover{background:#b93b3b}
.modal-actions button[disabled]{opacity:.6;cursor:default}
</style>
</head>
<body>
<header>
  <div class="wrap">
    <h1>AlphaFold3 预测结果评分看板</h1>
    <div class="sub" id="sub">加载中…</div>
    <button class="ghost" id="copy">复制本页链接</button>
    <div class="kpis" id="kpis"></div>
  </div>
</header>

<main class="wrap">
  <div id="err"></div>
  <div class="banner" id="banner"></div>

  <section class="card">
    <h2>设计排行榜 <span class="hint">点击任意一行查看该设计的 5 个采样模型</span></h2>
    <div class="toolbar">
      <input id="q" placeholder="搜索设计名…">
      <select id="f-assembly"><option value="">全部组装形态</option></select>
      <select id="f-linker"><option value="">全部连接肽</option></select>
      <select id="f-epitope"><option value="">全部表位</option></select>
      <select id="f-scheme">
        <option value="expert">口径：专家权重（与报告一致）</option>
        <option value="assembly">口径：组装优先</option>
        <option value="epitope">口径：表位优先</option>
        <option value="equal">口径：等权</option>
      </select>
      <button id="reset">重置</button>
      <button id="btn-add" class="primary">＋ 添加数据包</button>
      <button id="btn-scan">扫描新包</button>
      <button id="btn-reload">刷新数据</button>
      <input id="file-input" type="file" accept=".zip" multiple hidden>
      <span class="count" id="count"></span>
    </div>
    <div style="max-height:460px;overflow:auto">
      <table id="tbl">
        <thead><tr id="thead"></tr></thead>
        <tbody id="tbody"></tbody>
      </table>
    </div>
  </section>

  <section class="card" id="detail-card" style="display:none">
    <h2 id="detail-title">设计详情</h2>
    <div class="detail">
      <div>
        <div class="metrics" id="detail-metrics"></div>
        <div class="note">同一设计的 5 个采样模型（柱高 = 综合分，橙色为该设计最优模型）：</div>
        <div class="bars" id="model-bars"></div>
        <button id="del-detail" class="danger-ghost">删除这个设计</button>
      </div>
      <div>
        <div class="note">模型级明细</div>
        <table><thead><tr><th>模型</th><th>综合分</th><th>pLDDT</th><th>pTM</th><th>ipTM</th></tr></thead>
        <tbody id="model-tbl"></tbody></table>
      </div>
    </div>
  </section>

  <section class="card">
    <h2>结果图 <span class="hint">由 afscore 离线计算生成</span></h2>
    <div class="gal" id="gallery"></div>
  </section>

  <section class="card">
    <h2>评分方法</h2>
    <div class="note">综合分 = 100 × Σ(wᵢ·cᵢ)/Σwᵢ；缺失维度（单体无界面、对照无表位）按可用权重重新归一化。</div>
    <details>
      <summary>10 个评分维度与权重</summary>
      <table class="weight-tbl">
        <thead><tr><th>维度</th><th>权重</th><th>归一化方式</th></tr></thead>
        <tbody id="weight-body"></tbody>
      </table>
    </details>
    <details>
      <summary>Pareto 前沿是什么</summary>
      <div class="note" style="margin-top:8px">
        多目标优化里"不被任何其他方案全面压过"的集合。本看板有三套：全体模型（综合分/组装置信度/几何）、
        含表位设计（再加表位暴露度）、仅组装体（综合分/组装配信度/界面分）。表里的 ★ 表示进入了对应前沿。
      </div>
    </details>
    <details>
      <summary>数据与局限</summary>
      <div class="note" style="margin-top:8px">
        数据为 AlphaFold3 Server 输出（每个设计 5 个采样模型）；"好坏"是相对 AF 自身置信度的再组织，没有实验真值。
        20–21 聚体的 ipTM 仅 0.24–0.41，排序只能当实验优先级，不能当结论。
      </div>
    </details>
  </section>

  <footer>
    本页数据来自 <span class="mono">out/scores.csv</span> 与 <span class="mono">out/figures/</span>；
    局域网内其他电脑访问：<span class="mono" id="host"></span>
  </footer>
</main>

<!-- 拖拽导入遮罩 -->
<div id="drop-mask">
  <div class="drop-box">松开鼠标，导入 AlphaFold3 结果包（.zip）</div>
</div>

<!-- 上传进度面板 -->
<div id="up-panel">
  <div class="up-head">正在导入数据包 <span id="up-close">×</span></div>
  <div id="up-list"></div>
  <div class="up-foot" id="up-foot"></div>
</div>

<!-- 删除确认 -->
<div id="del-modal">
  <div class="modal">
    <h3 id="del-title">删除这个设计？</h3>
    <p class="modal-text">
      将从结果中移除该设计，并重算排名与图表。<br>
      若源包在 <span class="mono">incoming</span> 目录里，会同时删除源文件；<br>
      否则只移除结果，不删源文件。
    </p>
    <div class="modal-actions">
      <button id="del-cancel">取消</button>
      <button id="del-ok" class="danger">删除</button>
    </div>
  </div>
</div>

<script>
const WEIGHTS = [
  ["pLDDT 均值","0.18","均值/100"],
  ["核心加权 pLDDT","0.07","按埋藏度加权后的均值/100"],
  ["高置信残基占比","0.07","0.5·frac≥90 + 0.5·frac≥70"],
  ["PAE 全局","0.13","exp(−PAE/8)"],
  ["组装置信度","0.16","max(pTM, ipTM)（单体取 pTM）"],
  ["链间界面","0.14","0.5·exp(−链间PAE/20) + 0.5·min(每链对接触/60,1)"],
  ["表位暴露度","0.12","clip((表位相对SASA − 0.20)/0.60)"],
  ["疏水核心包埋","0.07","clip((疏水埋藏度 − 0.5)/0.3)"],
  ["几何合理性","0.07","1/(1+冲突/千原子/2)·Cα 连续性"],
  ["共进化支持","0.06","clip(MI-APC 接触精确率/0.25)"]
];
const COLS = [
  ["job","设计","s"],
  ["assembly_type","组装","s"],
  ["linker","连接肽","s"],
  ["epitope_type","表位","s"],
  ["composite","综合分","n",1],
  ["grade","等级","g"],
  ["plddt_mean","pLDDT","n",1],
  ["ptm","pTM","n",2],
  ["iptm","ipTM","n",2],
  ["epi_mean_exposure","表位暴露","n",2],
  ["c_interface","界面分","n",2],
  ["coev_precision","共进化","n",2],
  ["pareto_rank_epi","前沿","p"]
];
let DATA = null, MODELS = {}, VIEW = {q:"",assembly:"",linker:"",epitope:"",key:"composite",dir:-1};
let SEL = null, VERS = "0", LAST_REPORT = null;

const fmt = (v,d=2)=> (v===null||v===undefined||Number.isNaN(v)) ? "—" : Number(v).toFixed(d);
const el = id => document.getElementById(id);

/* ---------------- 评分口径：前端按分项分实时重算（不改已保存结果） ---------------- */
const KEYS = ["plddt","plddt_core","conf","pae","assembly","interface",
              "epitope","packing","geometry","coev"];
const SCHEMES = {
  expert:   {short:"专家", label:"专家权重（与报告一致）",
             w:{plddt:.18,plddt_core:.07,conf:.07,pae:.13,assembly:.16,
                interface:.14,epitope:.12,packing:.07,geometry:.07,coev:.06}},
  assembly: {short:"组装优先", label:"组装优先",
             w:{assembly:.32,interface:.26,pae:.15,plddt:.12,plddt_core:.05,
                conf:.04,packing:.03,geometry:.02,coev:.01,epitope:0}},
  epitope:  {short:"表位优先", label:"表位优先",
             w:{epitope:.32,assembly:.20,interface:.14,plddt:.14,pae:.10,
                coev:.05,packing:.02,geometry:.02,conf:.01,plddt_core:0}},
  equal:    {short:"等权", label:"等权",
             w:{plddt:.1,plddt_core:.1,conf:.1,pae:.1,assembly:.1,
                interface:.1,epitope:.1,packing:.1,geometry:.1,coev:.1}}
};
let RAW = [], SCHEME = "expert";
let NEW_JOBS = new Set(), LAST_ERROR = null;

/* 文件/设计名来自磁盘，渲染前转义，避免异常文件名把页面结构打乱 */
function esc(s){
  return String(s===null||s===undefined ? "" : s).replace(/[&<>"']/g, c => (
    {"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
}

function comp(d, w){
  let tot = 0, den = 0;
  for(const k of KEYS){
    const v = d["c_"+k];
    if(v===null||v===undefined||Number.isNaN(v)) continue;
    const wk = w[k] || 0;
    tot += wk * v; den += wk;
  }
  return den > 0 ? 100 * tot / den : null;
}

function gradeOf(s){
  if(s===null||s===undefined||Number.isNaN(s)) return "NA";
  return s>=85 ? "A 优秀" : s>=70 ? "B 良好" : s>=55 ? "C 中等" : s>=40 ? "D 偏弱" : "E 差";
}

function applyScheme(name){
  SCHEME = SCHEMES[name] ? name : "expert";
  const sc = SCHEMES[SCHEME];
  /* 只重算综合分与等级；前沿徽章保持库里（专家口径）的值，避免两套口径混在一起 */
  const rows = RAW.map(d=>{
    const c = comp(d, sc.w);
    return Object.assign({}, d, {composite:c, grade:gradeOf(c)});
  });
  DATA.designs = rows;
  SEL = null;
  el("detail-card").style.display = "none";
  renderKPIs(DATA.meta, rows);
  renderTable();
}

function showBanner(cls, text, actions){
  const b = el("banner");
  b.className = "banner show " + cls;
  b.innerHTML = `<span>${text}</span><span class="sp"></span>${actions || ""}`;
}
function hideBanner(){ const b = el("banner"); b.className = "banner"; b.innerHTML = ""; }

let SCANNING = false;

function setScanning(on){
  SCANNING = on;
  const b = el("btn-scan");
  if(b){ b.disabled = on; b.textContent = on ? "扫描中…" : "扫描新包"; }
}

async function fetchStatus(){
  return await (await fetch("/api/status")).json();
}

async function refreshStatus(st){
  try{
    st = st || await fetchStatus();
    if(st.scanning && st.job){
      const f = st.job.file ? `（${st.job.file}）` : "";
      showBanner("warn", `正在扫描 ${st.job.current}/${st.job.total}${f}，完成后会提示刷新`, "");
      setScanning(true);
      return;
    }
    setScanning(false);
    if(st.pending_count > 0){
      const names = st.pending.slice(0,3).join("、") + (st.pending_count>3 ? ` 等 ${st.pending_count} 个` : "");
      showBanner("warn", `待处理的新包：${names}`,
                 `<button onclick="startScan()">扫描新包</button>`);
      return;
    }
    if(st.designs === 0){
      showBanner("warn",
        "还没有结果数据：把 fold_*.zip 放进 incoming 目录后点「扫描新包」；或先运行 cli run 生成结果。",
        `<button onclick="startScan()">扫描新包</button>`);
      return;
    }
    if(st.out_mtime && st.state_mtime && st.out_mtime !== st.state_mtime){
      showBanner("warn", "结果文件已在磁盘上更新（可能来自命令行重算），页面还是旧的",
                 `<button onclick="refreshData(false)">刷新数据</button>`);
      return;
    }
    if(LAST_ERROR){
      showBanner("bad", LAST_ERROR,
                 `<button onclick="refreshData(false)">重试刷新</button>`);
      return;
    }
    if(LAST_REPORT){
      const r = LAST_REPORT;
      const nrm = (r.removed || []).length;
      showBanner("ok", `扫描完成：新增 ${r.added.length}、更新 ${r.updated.length}` +
                 (nrm ? `、移除 ${nrm}` : "") +
                 `、跳过 ${r.skipped}、失败 ${r.failed.length}，用时 ${r.elapsed}s`,
                 `<button onclick="refreshData(true)">刷新查看</button>`);
      return;
    }
    hideBanner();
  }catch(e){ /* 状态接口不可用时静默 */ }
}

async function startScan(){
  if(SCANNING) return;                  // 防连点：第二次直接忽略
  setScanning(true);
  LAST_ERROR = null;
  showBanner("warn", "正在启动扫描…", "");
  let resp;
  try{
    resp = await fetch("/api/scan", {method:"POST"});
  }catch(e){
    setScanning(false);
    LAST_ERROR = "扫描请求失败：" + e.message;
    showBanner("bad", LAST_ERROR, "");
    return;
  }
  if(resp.status === 409){
    setScanning(false);
    showBanner("bad", "已有扫描任务在运行，请稍候…", "");
    return;
  }
  const data = await resp.json();
  pollJob(data.job_id);
}

async function pollJob(id){
  let j;
  try{ j = await (await fetch("/api/jobs/" + id)).json(); }
  catch(e){ setTimeout(()=>pollJob(id), 2000); return; }

  if(j.state === "running"){
    const f = j.file ? `（${j.file}）` : "";
    showBanner("warn", `正在扫描 ${j.current}/${j.total}${f}，完成后会提示刷新`, "");
    setTimeout(()=>pollJob(id), 1200);
    return;
  }
  setScanning(false);
  if(j.state === "error"){
    LAST_ERROR = "扫描失败：" + (j.error || "未知错误");
    showBanner("bad", LAST_ERROR, "");
    return;
  }
  LAST_ERROR = null;
  const rep = j.report || {added:[],updated:[],removed:[],skipped:0,failed:[],elapsed:0};
  LAST_REPORT = rep;
  const gone = new Set(rep.removed || []);
  NEW_JOBS = new Set([...(rep.added || []), ...(rep.updated || [])].filter(n => !gone.has(n)));
  try{
    await loadAll(true);          // 扫描后服务端已 reload，直接重取数据
  }catch(e){
    LAST_ERROR = "扫描完成但载入失败：" + e.message;
  }
  if(rep.note){                   // 一个包都没有：给出导入指引而不是"扫描完成"
    showBanner("warn", rep.note, `<button onclick="startScan()">重新扫描</button>`);
    return;
  }
  refreshStatus();
}

function clearSelects(){
  for(const id of ["f-assembly","f-linker","f-epitope"]){
    const s = el(id);
    if(!s || !s.options) continue;
    while(s.options.length > 1) s.remove(1);
  }
}

/* 刷新后旧筛选值可能已不存在：不存在的就清掉，避免表格莫名变空 */
function hasOption(id, v){
  if(!v) return true;
  const s = el(id);
  if(!s || !s.options || s.options.length < 2) return true;
  for(let i = 0; i < s.options.length; i++){
    if(s.options[i].value === v) return true;
  }
  return false;
}

async function loadAll(keepView){
  const [s,m] = await Promise.all([fetch("/api/summary").then(r=>r.json()),
                                   fetch("/api/models").then(r=>r.json())]);
  const q = VIEW.q, a = VIEW.assembly, lk = VIEW.linker, ep = VIEW.epitope;
  DATA = s; MODELS = m.models || {};
  RAW = s.designs.slice();
  VERS = String(s.meta.data_version || "0");
  el("sub").textContent = `${s.meta.n_designs} 个设计 · ${s.meta.n_models} 个采样模型 · 数据文件 ${s.meta.file_time}`;
  el("host").textContent = location.host;
  clearSelects();
  fillSelects(s.designs);
  if(keepView){
    if(!hasOption("f-assembly", a)) a = "";
    if(!hasOption("f-linker", lk)) lk = "";
    if(!hasOption("f-epitope", ep)) ep = "";
    VIEW.q=q; VIEW.assembly=a; VIEW.linker=lk; VIEW.epitope=ep;
    el("q").value=q; el("f-assembly").value=a; el("f-linker").value=lk; el("f-epitope").value=ep;
  }
  SEL = null;                            // 数据换了，旧详情面板作废
  el("detail-card").style.display = "none";
  renderKPIs(s.meta, s.designs);
  if(SCHEME !== "expert") applyScheme(SCHEME); else renderTable();
  renderGallery(s.meta.figures);
}

async function refreshData(silent){
  try{
    const r = await fetch("/api/reload", {method:"POST"});
    if(!r.ok) throw new Error("HTTP " + r.status);
    await loadAll(true);
    LAST_REPORT = null;
    LAST_ERROR = null;
    const st = await fetchStatus();
    NEW_JOBS = new Set(st.new_jobs || []);
    renderTable();
    if(silent){
      refreshStatus();
    }else{
      showBanner("ok", "已刷新：从磁盘重新读取了最新结果", "");
      setTimeout(refreshStatus, 2500);
    }
  }catch(e){
    LAST_ERROR = "刷新失败：" + e.message;
    showBanner("bad", LAST_ERROR, "");
  }
}

async function boot(){
  el("tbody").innerHTML = `<tr><td colspan="${COLS.length + 1}" class="empty">加载中…</td></tr>`;
  try{
    await loadAll(false);
    renderWeights();
    const st = await fetchStatus();
    NEW_JOBS = new Set(st.new_jobs || []);   // 刷新页面后仍标出最近一批变化
    renderTable();
    refreshStatus(st);
    setInterval(refreshStatus, 5000);
  }catch(e){
    el("err").innerHTML = `<div class="err">加载失败：${e.message}</div>`;
  }
}

function renderKPIs(meta, rows){
  const best = rows[0] || {};
  const multi = rows.filter(r=>r.n_chains>1).sort((a,b)=>b.composite-a.composite)[0] || {};
  const epi = rows.filter(r=>r.epi_mean_exposure!=null);
  const epiAvg = epi.length ? epi.reduce((a,r)=>a+r.epi_mean_exposure,0)/epi.length : null;
  const front = rows.filter(r=>r.pareto_rank_epi===0).length;
  el("kpis").innerHTML = [
    [fmt(best.composite,1), "最高分（"+(best.job||"—")+"）"],
    [fmt(multi.composite,1), "多聚体最佳（"+(multi.job||"—")+"）"],
    [fmt(epiAvg,2), "表位平均暴露度"],
    [front, "表位 Pareto 前沿设计数"]
  ].map(([v,k])=>`<div class="kpi"><div class="v">${v}</div><div class="k">${k}</div></div>`).join("");
}

function fillSelects(rows){
  const uniq = k => [...new Set(rows.map(r=>r[k]).filter(v=>v!=null))];
  const add = (id, vals) => { const s=el(id); vals.forEach(v=>{const o=document.createElement("option");o.value=v;o.textContent=v;s.appendChild(o);}); };
  add("f-assembly", uniq("assembly_type"));
  add("f-linker", uniq("linker"));
  add("f-epitope", uniq("epitope_type"));
}

function visibleRows(){
  let rows = DATA.designs.slice();
  const q = VIEW.q.trim().toLowerCase();
  if(q) rows = rows.filter(r=>String(r.job).toLowerCase().includes(q));
  if(VIEW.assembly) rows = rows.filter(r=>r.assembly_type===VIEW.assembly);
  if(VIEW.linker) rows = rows.filter(r=>r.linker===VIEW.linker);
  if(VIEW.epitope) rows = rows.filter(r=>r.epitope_type===VIEW.epitope);
  const k = VIEW.key, d = VIEW.dir;
  rows.sort((a,b)=>{
    let x=a[k], y=b[k];
    if(x==null) return 1; if(y==null) return -1;
    if(typeof x==="number" && typeof y==="number") return (x-y)*d;
    return String(x).localeCompare(String(y),"zh")*d;
  });
  return rows;
}

function renderHead(){
  el("thead").innerHTML = COLS.map(([k,label,,])=>{
    const arw = VIEW.key===k ? `<span class="arw">${VIEW.dir>0?"▲":"▼"}</span>` : "";
    return `<th data-k="${k}">${label}${arw}</th>`;
  }).join("") + `<th class="act"></th>`;
  [...el("thead").children].forEach(th=>th.onclick=()=>{
    const k=th.dataset.k;
    if(!k) return;                       // 操作列不排序
    if(VIEW.key===k) VIEW.dir*=-1; else {VIEW.key=k;VIEW.dir=-1;}
    renderTable();
  });
}

function renderTable(){
  renderHead();
  const rows = visibleRows();
  const tag = SCHEME === "expert" ? "" : "（仅本页重算，★仍按专家口径）";
  el("count").textContent = `显示 ${rows.length} / ${DATA.designs.length} · 口径 ${SCHEMES[SCHEME].short}${tag}`;
  el("tbody").innerHTML = rows.map(r=>{
    const isNew = NEW_JOBS.has(r.job);
    const tds = COLS.map(([k,label,type,d=2])=>{
      if(k==="job"){
        return `<td>${esc(r.job)}${isNew?' <span class="tag new">新</span>':''}</td>`;
      }
      if(type==="s") return `<td>${esc(r[k] ?? "—")}</td>`;
      if(type==="g") return `<td><span class="pill g-${esc((r.grade||"NA")[0])}">${esc(r.grade ?? "—")}</span></td>`;
      if(type==="p") return `<td>${r.pareto_rank_epi===0?"★":(r.pareto_rank_vlp===0?"☆":"")}</td>`;
      return `<td>${fmt(r[k],d)}</td>`;
    }).join("");
    const del = `<td class="act"><button class="del-btn" data-del="${esc(r.job)}"
                 title="删除这个设计">✕</button></td>`;
    const klass = [SEL===r.job ? "sel" : "", isNew ? "isnew" : ""].filter(Boolean).join(" ");
    return `<tr data-job="${esc(r.job)}"${klass?` class="${klass}"`:""}>${tds}${del}</tr>`;
  }).join("") || `<tr><td colspan="${COLS.length + 1}" class="empty">${DATA.designs.length
      ? "没有匹配的设计"
      : "还没有结果数据 —— 把 fold_*.zip 放进 incoming 目录后点「扫描新包」"}</td></tr>`;
  [...el("tbody").querySelectorAll("tr[data-job]")].forEach(tr=>{
    tr.onclick = ()=> select(tr.dataset.job);
  });
  [...el("tbody").querySelectorAll("button[data-del]")].forEach(btn=>{
    btn.onclick = e => { e.stopPropagation(); openDelete(btn.dataset.del); };
  });
}

function select(job){
  SEL = job;
  renderTable();
  const d = DATA.designs.find(r=>r.job===job);
  if(!d) return;
  const ms = MODELS[job] || [];
  el("detail-card").style.display = "";
  el("detail-title").innerHTML = `${esc(job)}
    <span class="tag">${esc(d.assembly_type||"—")}</span>
    <span class="tag">${esc(d.epitope_type||"—")}</span>
    <span class="tag">${esc(d.linker||"—")}</span>
    <span class="pill g-${esc((d.grade||"NA")[0])}">${esc(d.grade||"—")}</span>`;
  const metrics = [
    ["综合分",fmt(d.composite,1)],
    ["pLDDT 均值",fmt(d.plddt_mean,1)],
    ["pTM",fmt(d.ptm)],
    ["ipTM",fmt(d.iptm)],
    ["表位暴露度",fmt(d.epi_mean_exposure)],
    ["暴露度波动 σ",fmt(d.epi_exposure_std,3)],
    ["局部界面分",fmt(d.iface_score)],
    ["最佳链对",d.iface_best_pair||"—"],
    ["最佳对接触",fmt(d.iface_best_contacts,0)],
    ["最佳对 PAE",fmt(d.iface_best_pae,1)],
    ["链间界面分(旧)",fmt(d.c_interface)],
    ["共进化精确率",fmt(d.coev_precision,3)]
  ];
  el("detail-metrics").innerHTML = metrics.map(([k,v])=>`<div class="metric"><div class="k">${k}</div><div class="v">${v}</div></div>`).join("");
  const best = Math.max(...ms.map(m=>m.composite));
  el("model-bars").innerHTML = ms.map(m=>{
    const h = Math.max(4, (m.composite/best)*100);
    const cls = (m.composite===best) ? "bar best" : "bar";
    return `<div class="${cls}"><div class="val">${fmt(m.composite,1)}</div>
      <div class="fill" style="height:${h}%"></div><div class="lab">#${m.model}</div></div>`;
  }).join("") || `<div class="empty">无模型数据</div>`;
  el("model-tbl").innerHTML = ms.map(m=>`<tr><td>#${m.model}</td><td>${fmt(m.composite,1)}</td>
      <td>${fmt(m.plddt_mean,1)}</td><td>${fmt(m.ptm)}</td><td>${fmt(m.iptm)}</td></tr>`).join("");
  el("detail-card").scrollIntoView({behavior:"smooth", block:"start"});
}

function renderGallery(figs){
  const cap = {
    fig1_scores_bar:"综合评分柱状图（每个设计取最优模型）",
    fig2_components_heatmap:"分项得分热图（按综合分排序）",
    fig3_pareto:"表位暴露 vs 组装稳定性（红圈为 Pareto 前沿）",
    fig4_epitope_track:"残基轨迹：pLDDT 与相对 SASA（红区为表位）",
    fig5_pae:"PAE 矩阵（绿色越深误差越大）"
  };
  if(!figs || !figs.length){
    el("gallery").innerHTML = `<div class="empty">out\\figures 下没有图片（先跑一次 cli run 生成图）</div>`;
    return;
  }
  el("gallery").innerHTML = (figs||[]).map(f=>{
    const name = f.split("/").pop();
    return `<figure><a href="/figures/${name}?v=${VERS}" target="_blank"><img src="/figures/${name}?v=${VERS}" loading="lazy"></a>
      <figcaption>${cap[name]||name}</figcaption></figure>`;
  }).join("");
}

function renderWeights(){
  el("weight-body").innerHTML = WEIGHTS.map(([a,b,c])=>`<tr><td>${a}</td><td>${b}</td><td>${c}</td></tr>`).join("");
}

el("q").oninput = e => { VIEW.q = e.target.value; renderTable(); };
el("f-assembly").onchange = e => { VIEW.assembly = e.target.value; renderTable(); };
el("f-linker").onchange = e => { VIEW.linker = e.target.value; renderTable(); };
el("f-epitope").onchange = e => { VIEW.epitope = e.target.value; renderTable(); };
el("f-scheme").onchange = e => applyScheme(e.target.value);
el("btn-scan").onclick = () => startScan();
el("btn-reload").onclick = () => refreshData(false);
el("reset").onclick = () => {
  VIEW = {q:"",assembly:"",linker:"",epitope:"",key:"composite",dir:-1};
  el("q").value=""; el("f-assembly").value=""; el("f-linker").value=""; el("f-epitope").value="";
  el("f-scheme").value = "expert";
  applyScheme("expert");
};
el("copy").onclick = async () => {  const btn = el("copy"), txt = btn.textContent;
  try{
    await navigator.clipboard.writeText(location.href);
    btn.textContent = "已复制 ✓";
  }catch(e){
    btn.textContent = location.host;   // http 下剪贴板不可用时，至少把地址显示出来
  }
  setTimeout(()=>{ btn.textContent = txt; }, 1800);
};

/* ---------------- 添加数据包：拖拽 / 选择 → 上传 → 自动扫描 ---------------- */
const MAX_UP = 400 * 1024 * 1024;      // 与后端 MAX_UPLOAD 一致
let UP_BUSY = false;

function showDrop(on){ el("drop-mask").classList.toggle("show", !!on); }

function upRow(name){
  const id = "up-" + Math.random().toString(36).slice(2, 8);
  const div = document.createElement("div");
  div.className = "up-row";
  div.id = id;
  div.innerHTML = `<div class="up-name"><b>${esc(name)}</b><span>等待</span></div>
                   <div class="up-bar"><div class="up-fill"></div></div>`;
  el("up-list").appendChild(div);
  return id;
}

function upSet(id, pct, text, cls){
  const row = document.getElementById(id);
  if(!row) return;
  row.querySelector(".up-name span").textContent = text;
  row.querySelector(".up-fill").style.width = Math.max(0, Math.min(100, pct)) + "%";
  row.classList.remove("ok", "err");
  if(cls) row.classList.add(cls);
}

function uploadOne(file, overwrite){
  return new Promise(resolve => {
    const id = upRow(file.name);
    if(!/\.zip$/i.test(file.name)){
      upSet(id, 100, "不是 zip", "err");
      return resolve({ok:false, error:"不是 .zip"});
    }
    if(file.size > MAX_UP){
      upSet(id, 100, "超过 400 MB", "err");
      return resolve({ok:false, error:"超过 400 MB"});
    }
    upSet(id, 0, "上传中…");
    const xhr = new XMLHttpRequest();
    xhr.open("PUT", "/api/upload?name=" + encodeURIComponent(file.name) +
                    (overwrite ? "&overwrite=1" : ""));
    xhr.upload.onprogress = e => {
      if(e.lengthComputable) upSet(id, e.loaded / e.total * 100,
                                   "上传中 " + Math.round(e.loaded / e.total * 100) + "%");
    };
    xhr.onload = () => {
      let body = {};
      try{ body = JSON.parse(xhr.responseText || "{}"); }catch(e){}
      if(xhr.status === 200){ upSet(id, 100, "完成", "ok"); resolve({ok:true}); }
      else if(xhr.status === 409){ upSet(id, 100, "同名已存在", "err"); resolve({ok:false, error:"exists"}); }
      else { upSet(id, 100, body.error || ("失败 " + xhr.status), "err");
             resolve({ok:false, error:body.error || ("HTTP " + xhr.status)}); }
    };
    xhr.onerror = () => { upSet(id, 100, "网络错误", "err"); resolve({ok:false, error:"网络错误"}); };
    xhr.send(file);
  });
}

async function uploadFiles(files){
  if(UP_BUSY) return;
  const list = [...files].filter(Boolean);
  if(!list.length) return;
  UP_BUSY = true;
  el("btn-add").disabled = true;
  el("up-panel").classList.add("show");
  el("up-list").innerHTML = "";
  el("up-foot").textContent = "准备上传 " + list.length + " 个文件…";

  let ok = 0;
  for(const f of list){
    let r = await uploadOne(f, false);
    if(!r.ok && r.error === "exists"){
      if(confirm("已存在同名文件：\n" + f.name + "\n\n覆盖它吗？")){
        r = await uploadOne(f, true);
      }
    }
    if(r.ok) ok += 1;
  }

  UP_BUSY = false;
  el("btn-add").disabled = false;
  if(ok){
    el("up-foot").textContent = `成功 ${ok} / ${list.length}，开始扫描…`;
    startScan();
    setTimeout(()=> el("up-panel").classList.remove("show"), 6000);
  }else{
    el("up-foot").textContent = `失败 ${list.length} 个，未开始扫描`;
  }
}

el("btn-add").onclick = () => el("file-input").click();
el("file-input").onchange = e => { uploadFiles(e.target.files); e.target.value = ""; };
el("up-close").onclick = () => el("up-panel").classList.remove("show");

["dragenter", "dragover"].forEach(t => document.addEventListener(t, e => {
  if(!e.dataTransfer) return;
  e.preventDefault();                      // 不拦的话 WebView2 会直接用浏览器打开文件
  if([...e.dataTransfer.types].includes("Files")) showDrop(true);
}));
document.addEventListener("dragleave", e => { if(!e.relatedTarget) showDrop(false); });
document.addEventListener("drop", e => {
  e.preventDefault();
  showDrop(false);
  if(e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files.length){
    uploadFiles(e.dataTransfer.files);
  }
});

/* ---------------- 删除设计 ---------------- */
let DEL_JOB = null;

function openDelete(job){
  DEL_JOB = job;
  el("del-title").textContent = "删除 " + job + " ？";
  el("del-modal").classList.add("show");
}
function closeDelete(){
  el("del-modal").classList.remove("show");
  DEL_JOB = null;
}

el("del-cancel").onclick = closeDelete;
el("del-modal").onclick = e => { if(e.target.id === "del-modal") closeDelete(); };
document.addEventListener("keydown", e => { if(e.key === "Escape") closeDelete(); });
el("del-detail").onclick = () => { if(SEL) openDelete(SEL); };

async function pollDelete(id, job){
  showBanner("warn", "正在删除 " + job + " 并重算图表…", "");
  for(;;){
    let j;
    try{ j = await (await fetch("/api/jobs/" + id)).json(); }
    catch(e){ await new Promise(r => setTimeout(r, 800)); continue; }
    if(j.state === "running"){ await new Promise(r => setTimeout(r, 600)); continue; }
    if(j.state === "error"){
      showBanner("bad", "删除失败：" + (j.error || "未知错误"), "");
      return;
    }
    await loadAll(true);
    const rep = j.report || {};
    const extra = rep.source_deleted ? "（源包已删除）" : "（源包不在 incoming，仅移除结果）";
    showBanner("ok", "已删除 " + job + extra,
               `<button onclick="hideBanner()">知道了</button>`);
    return;
  }
}

el("del-ok").onclick = async () => {
  if(!DEL_JOB) return;
  const job = DEL_JOB;
  const btn = el("del-ok");
  btn.disabled = true;
  btn.textContent = "删除中…";
  try{
    const resp = await fetch("/api/delete", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({job})
    });
    let d = {};
    try{ d = await resp.json(); }catch(e){}
    if(!resp.ok){
      closeDelete();
      showBanner("bad", d.error || ("删除失败 " + resp.status), "");
      return;
    }
    closeDelete();
    pollDelete(d.job_id, job);
  }catch(e){
    closeDelete();
    showBanner("bad", "删除失败：" + e.message, "");
  }finally{
    btn.disabled = false;
    btn.textContent = "删除";
  }
};

/* 调试/自动化测试用的只读入口（不影响页面） */
globalThis.AFSCORE = { applyScheme, SCHEMES,
                       get data(){ return DATA; },
                       get raw(){ return RAW; },
                       setNew(jobs){ NEW_JOBS = new Set(jobs || []); renderTable(); } };

boot();
</script>
</body>
</html>
"""
