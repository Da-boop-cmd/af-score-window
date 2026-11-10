"""本地 Web 看板：把 out/ 里的评分结果用浏览器展示，局域网内可访问。

用法：
    python -m afscore.web                 # 默认 0.0.0.0:8765，自动打开浏览器
    python -m afscore.web --port 9000 --no-open
    python -m afscore.web --host 127.0.0.1     # 只允许本机

只有标准库依赖（http.server），不引入 Flask 等第三方包，离线可跑。
"""
from __future__ import annotations

import argparse
import glob
import json
import math
import os
import re
import socket
import sys
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlparse

import pandas as pd

from . import incremental
from .webui import INDEX_HTML

VERSION = "1.2.0"
MAX_UPLOAD = 400 * 1024 * 1024          # 单个 zip 上限 400 MB
BAD_NAME_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
MIME = {".png": "image/png", ".json": "application/json; charset=utf-8",
        ".html": "text/html; charset=utf-8"}

DESIGN_COLS = ["job", "model", "assembly_type", "linker", "epitope_type", "n_chains",
               "composite", "grade", "plddt_mean", "plddt_weighted", "ptm", "iptm",
               "pae_mean", "epi_mean_exposure", "epi_exposed_frac", "epi_plddt",
               "epi_exposure_std", "composite_std", "linker_exposure",
               "inter_contacts_per_pair", "iface_score", "iface_best_contacts",
               "iface_best_pae", "iface_best_pair", "iface_n_pairs", "c_interface",
               "c_assembly", "c_epitope", "c_plddt", "c_plddt_core", "c_conf",
               "c_pae", "c_packing", "c_geometry", "c_coev", "coev_precision",
               "clash_per_1k", "pareto_rank", "pareto_rank_epi", "pareto_rank_vlp"]

MODEL_COLS = ["job", "model", "composite", "grade", "plddt_mean", "ptm", "iptm",
              "epi_mean_exposure", "c_interface", "iface_score"]


def _clean(value):
    """numpy/pandas 值转成可 JSON 序列化的原生值；NaN/inf → None。"""
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
            return None
        return value
    try:
        import numpy as np
        if isinstance(value, np.generic):
            return _clean(value.item())
    except Exception:
        pass
    return value if isinstance(value, str) else str(value)


def _row_to_dict(row, cols):
    return {c: _clean(row[c]) for c in cols if c in row}


class State:
    """载入评分结果；扫描新包后调用 reload() 重新读取。"""

    def __init__(self, out_dir: str, predictions_dir: str | None = None,
                 incoming_dir: str | None = None):
        self.out_dir = os.path.abspath(out_dir)
        self.fig_dir = os.path.join(self.out_dir, "figures")
        self.predictions_dir = predictions_dir
        self.incoming_dir = incoming_dir
        self.last_scan = None
        self.data_version = "0"
        self.reload()

    def reload(self) -> None:
        summary = os.path.join(self.out_dir, "summary_by_design.csv")
        scores = os.path.join(self.out_dir, "scores.csv")
        self.last_scan = incremental.load_last_scan(self.out_dir)
        self.new_jobs = list(self.last_scan.get("new_jobs") or [])

        # 空白数据也要能打开：没有结果就进入"空状态"，由页面提示怎么导入
        if not os.path.exists(summary):
            self.has_data = False
            self.designs = []
            self.models = {}
            self.n_models = 0
            self.file_time = "—"
            self.figures = sorted(f for f in os.listdir(self.fig_dir) if f.endswith(".png")) \
                if os.path.isdir(self.fig_dir) else []
            self.loaded_mtime = 0
            self.data_version = "0-0"
            return

        self.has_data = True
        s = pd.read_csv(summary)
        m = pd.read_csv(scores) if os.path.exists(scores) else s.copy()
        s = s.sort_values("composite", ascending=False)
        self.designs = [_row_to_dict(r, DESIGN_COLS) for _, r in s.iterrows()]
        self.models = {}
        for job, grp in m.groupby("job"):
            grp = grp.sort_values("model")
            self.models[job] = [_row_to_dict(r, MODEL_COLS) for _, r in grp.iterrows()]
        self.n_models = int(len(m))
        self.file_time = time.strftime("%Y-%m-%d %H:%M",
                                       time.localtime(os.path.getmtime(summary)))
        self.figures = sorted(f for f in os.listdir(self.fig_dir) if f.endswith(".png")) \
            if os.path.isdir(self.fig_dir) else []
        scores_mtime = os.path.getmtime(scores) if os.path.exists(scores) else 0
        self.loaded_mtime = max(int(os.path.getmtime(summary)), int(scores_mtime))
        self.data_version = "%d-%d" % (self.loaded_mtime, len(self.designs))

    def _disk_mtime(self) -> int:
        """磁盘上结果文件的修改时间，用来发现"外部重算过、页面还没刷新"。"""
        disk = 0
        for f in ("summary_by_design.csv", "scores.csv"):
            p = os.path.join(self.out_dir, f)
            if os.path.exists(p):
                disk = max(disk, int(os.path.getmtime(p)))
        return disk

    # -------------------------------------------------- 状态与扫描
    def status(self) -> dict:
        files = incremental.collect(self.predictions_dir, self.incoming_dir)
        manifest = incremental.load_manifest(self.out_dir)
        pend = incremental.pending_names(files, manifest, self.out_dir)
        job = _active_job()
        return {
            "data_version": self.data_version,
            "designs": len(self.designs),
            "models": self.n_models,
            "file_time": self.file_time,
            "figures": len(self.figures),
            "pending": pend,
            "pending_count": len(pend),
            "scanning": bool(job),
            "job": job,
            "last_scan": self.last_scan,
            "new_jobs": list(getattr(self, "new_jobs", [])),
            "has_data": bool(getattr(self, "has_data", False)),
            "out_mtime": self._disk_mtime(),
            "state_mtime": self.loaded_mtime,
            "predictions_dir": self.predictions_dir or "",
            "incoming_dir": self.incoming_dir or "",
        }

    def health(self) -> dict:
        return {"status": "ok", "version": VERSION, "designs": len(self.designs),
                "models": self.n_models, "figures": len(self.figures),
                "out_dir": self.out_dir, "file_time": self.file_time,
                "data_version": self.data_version,
                "has_data": bool(getattr(self, "has_data", False))}

    def summary_payload(self) -> dict:
        return {
            "meta": {"n_designs": len(self.designs), "n_models": self.n_models,
                     "file_time": self.file_time, "version": VERSION,
                     "data_version": self.data_version,
                     "figures": [f"/figures/{f}" for f in self.figures]},
            "designs": self.designs,
        }


# ---------------------------------------------------------------- 扫描任务
_JOBS = {}                 # job_id -> 状态 dict
_JOBS_LOCK = threading.Lock()
_ACTIVE = []               # 长度 0 或 1，存放当前 job_id


def _active_job():
    jid = _ACTIVE[0] if _ACTIVE else None
    return _JOBS.get(jid) if jid else None


def _run_scan(state: "State", jid: str) -> None:
    def progress(done, total, name):
        _JOBS[jid].update(current=done, total=total, file=name)

    try:
        rep = incremental.scan(state.predictions_dir, state.incoming_dir,
                               state.out_dir, progress=progress)
    except BaseException as exc:            # 含 SystemExit：任何异常都要落到任务状态里
        _JOBS[jid].update(state="error",
                          error="%s: %s" % (type(exc).__name__, exc))
        with _JOBS_LOCK:
            if _ACTIVE:
                _ACTIVE.pop()
        return

    _JOBS[jid]["report"] = rep
    state.last_scan = rep
    try:
        state.reload()
    except BaseException as exc:            # 表重建成功但读不回来：提示用户手动刷新
        _JOBS[jid].update(state="error",
                          error="结果已更新，但重新载入失败（%s）" % exc)
    else:
        # 先 reload 再标记 done：避免"done 了但 _ACTIVE 还没释放"的竞态
        _JOBS[jid].update(state="done")
    finally:
        with _JOBS_LOCK:
            if _ACTIVE:
                _ACTIVE.pop()


def start_scan(state: "State"):
    """返回 (job_id, 冲突的 job_id)。已有任务在跑时第一个为 None。"""
    with _JOBS_LOCK:
        if _ACTIVE:
            return None, _ACTIVE[0]
        jid = time.strftime("%H%M%S") + "-" + str(int(time.time() * 1000) % 1000)
        _JOBS[jid] = {"id": jid, "state": "running", "current": 0, "total": 0,
                      "file": "", "started": time.strftime("%H:%M:%S"),
                      "report": None, "error": None}
        _ACTIVE.append(jid)
    threading.Thread(target=_run_scan, args=(state, jid), daemon=True).start()
    return jid, None


def _run_delete(state: "State", jid: str, job: str) -> None:
    """删除后重算：删空则清表，否则重建排名与图。"""
    try:
        from .pipeline import rebuild
        from .report import make_figures
        cache_dir = os.path.join(state.out_dir, "cache")
        remaining = glob.glob(os.path.join(cache_dir, "*.csv"))
        if not remaining:
            for name in ("summary_by_design.csv", "scores.csv"):
                path = os.path.join(state.out_dir, name)
                if os.path.exists(path):
                    os.remove(path)
            report = {"removed": [job], "designs": 0, "figures": {}}
        else:
            df = rebuild(state.out_dir)
            manifest = incremental.load_manifest(state.out_dir)
            lookup = {n: r.get("file") for n, r in manifest.items() if r.get("file")}
            figs = make_figures(df, os.path.join(state.out_dir, "figures"), lookup)
            report = {"removed": [job], "designs": int(df["job"].nunique()),
                      "figures": figs}
        _JOBS[jid]["report"] = report
        state.reload()
        _JOBS[jid].update(state="done")     # reload 之后再标 done，避免竞态
    except BaseException as exc:
        _JOBS[jid].update(state="error",
                          error="%s: %s" % (type(exc).__name__, exc))
    finally:
        with _JOBS_LOCK:
            if _ACTIVE:
                _ACTIVE.pop()


def start_delete(state: "State", job: str):
    with _JOBS_LOCK:
        if _ACTIVE:
            return None, _ACTIVE[0]
        jid = time.strftime("%H%M%S") + "-" + str(int(time.time() * 1000) % 1000)
        _JOBS[jid] = {"id": jid, "state": "running", "current": 0, "total": 1,
                      "file": job, "started": time.strftime("%H:%M:%S"),
                      "report": None, "error": None}
        _ACTIVE.append(jid)
    threading.Thread(target=_run_delete, args=(state, jid, job), daemon=True).start()
    return jid, None


def _safe_zip_name(raw: str):
    """只接受纯文件名（防路径穿越），且必须是 .zip。"""
    name = (raw or "").replace("\\", "/").split("/")[-1].strip()
    if not name or not name.lower().endswith(".zip"):
        return None
    if name in (".zip",) or name.startswith("."):
        return None
    name = BAD_NAME_CHARS.sub("_", name)
    if not name.lower().endswith(".zip"):
        return None
    return name


def make_handler(state: State, quiet: bool, on_quit=None):
    class Handler(BaseHTTPRequestHandler):
        server_version = "afscore-web/" + VERSION

        def _local(self) -> bool:
            """写操作只允许本机（桌面壳恒为 127.0.0.1）。"""
            addr = self.client_address[0] if self.client_address else ""
            return addr in ("127.0.0.1", "::1")

        def _send(self, code, body: bytes, ctype: str):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _json(self, payload: dict, code: int = 200):
            body = json.dumps(payload, ensure_ascii=False, allow_nan=False).encode("utf-8")
            self._send(code, body, MIME[".json"])

        def _error(self, code: int, message: str):
            self._json({"error": message, "code": code}, code=code)

        def do_HEAD(self):  # noqa: N802
            """只回头部，方便 curl -I / 探活脚本。"""
            path = urlparse(self.path).path
            code, ctype, size = 404, MIME[".json"], 0
            if path in ("/", "/index.html"):
                code, ctype, size = 200, MIME[".html"], len(INDEX_HTML.encode("utf-8"))
            elif path.startswith("/figures/"):
                name = unquote(path[len("/figures/"):])
                if name in state.figures:
                    code, ctype = 200, MIME[".png"]
                    try:
                        size = os.path.getsize(os.path.join(state.fig_dir, name))
                    except OSError:
                        code = 404
            elif path in ("/api/health", "/api/status", "/api/summary",
                          "/api/models", "/favicon.ico"):
                code = 200
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(size))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()

        def do_GET(self):  # noqa: N802
            try:
                self._route(urlparse(self.path).path)
            except BrokenPipeError:
                pass
            except Exception as exc:                     # 兜底：单次请求异常不影响服务
                try:
                    self._error(500, "内部错误: %s" % exc)
                except Exception:
                    pass

        def do_POST(self):  # noqa: N802
            path = urlparse(self.path).path
            length = int(self.headers.get("Content-Length") or 0)
            payload = None
            if path == "/api/delete":                    # 删除需要读 JSON body
                if length > 65536:
                    self._drain(length)
                    self._error(413, "请求体过大")
                    return
                try:
                    payload = json.loads(self.rfile.read(length) or b"{}") if length else {}
                except Exception:
                    self._error(400, "JSON 解析失败")
                    return
            elif length:                                 # 其他接口丢弃请求体
                try:
                    self.rfile.read(length)
                except Exception:
                    pass
            if path == "/api/delete":
                self._delete(payload or {})
                return
            if path == "/api/quit":
                # 只允许本机调用：给桌面壳（C++ 窗口）关窗时用
                if self.client_address[0] not in ("127.0.0.1", "::1"):
                    self._error(403, "仅限本机")
                    return
                self._json({"ok": True})
                if on_quit:
                    threading.Thread(target=on_quit, daemon=True).start()
                return
            if path == "/api/reload":
                try:
                    state.reload()
                except SystemExit as exc:
                    self._error(500, "结果文件不可用: %s" % exc)
                    return
                self._json({"designs": len(state.designs),
                            "data_version": state.data_version,
                            "out_mtime": state.loaded_mtime})
                return
            if path == "/api/scan":
                jid, busy = start_scan(state)
                if jid is None:
                    self._json({"error": "已有扫描任务在运行", "job_id": busy}, code=409)
                else:
                    self._json({"job_id": jid})
                return
            self._error(404, "未知路径: " + path)

        def do_PUT(self):  # noqa: N802
            path = urlparse(self.path).path
            if path == "/api/upload":
                self._upload()
                return
            self._error(404, "未知路径: " + path)

        def _drain(self, length: int) -> None:
            """提前拒绝时也要把请求体读掉，否则客户端会看到连接被重置。"""
            todo = max(length, 0)
            if todo > 2 * 1024 * 1024 * 1024:        # 异常大的请求体：读 2 GB 后断开
                todo = 2 * 1024 * 1024 * 1024
                self.close_connection = True
            while todo > 0:
                try:
                    chunk = self.rfile.read(min(1 << 20, todo))
                except OSError:
                    break
                if not chunk:
                    break
                todo -= len(chunk)

        def _upload(self):
            """接收浏览器拖入/选择的 zip，落到 incoming 目录。"""
            length = int(self.headers.get("Content-Length") or 0)

            if not self._local():
                self._drain(length)
                self._error(403, "仅限本机操作")
                return
            qs = parse_qs(urlparse(self.path).query)
            name = _safe_zip_name(qs.get("name", [""])[0])
            if not name:
                self._drain(length)
                self._error(400, "文件名不合法：需要 .zip，且不能带路径")
                return
            if _ACTIVE:
                self._drain(length)
                self._error(409, "正在扫描，请稍后再试")
                return
            incoming = state.incoming_dir
            if not incoming:
                self._drain(length)
                self._error(400, "未配置 incoming 目录")
                return
            if length <= 0:
                self._error(411, "缺少 Content-Length")
                return
            if length > MAX_UPLOAD:
                self._drain(length)
                self._error(413, "文件超过 400 MB")
                return

            os.makedirs(incoming, exist_ok=True)
            target = os.path.join(incoming, name)
            overwrite = qs.get("overwrite", ["0"])[0] == "1"
            if os.path.exists(target) and not overwrite:
                self._drain(length)
                self._error(409, "同名文件已存在")
                return

            tmp = target + ".part"
            head = b""
            try:
                with open(tmp, "wb") as fh:
                    remaining = length
                    while remaining > 0:
                        chunk = self.rfile.read(min(1 << 20, remaining))
                        if not chunk:
                            break
                        if len(head) < 4:
                            head += chunk[:4 - len(head)]
                        fh.write(chunk)
                        remaining -= len(chunk)
                if head[:4] != b"PK\x03\x04":       # zip 魔数
                    os.remove(tmp)
                    self._error(400, "不是有效的 zip 文件")
                    return
                os.replace(tmp, target)
                # 上传是完整写入，直接把 mtime 往前挪几秒，
                # 绕开 scan 的 2 秒防抖（否则"上传完立刻扫描"会被当成正在拷贝而跳过）
                try:
                    past = time.time() - 5
                    os.utime(target, (past, past))
                except OSError:
                    pass
            except OSError as exc:
                try:
                    os.remove(tmp)
                except OSError:
                    pass
                self._error(500, "写入失败：%s" % exc)
                return
            self._json({"name": name, "size": length})

        def _delete(self, payload: dict):
            """删除一个设计：源包（若在 incoming）+ 缓存 + 清单，然后后台重算。"""
            if not self._local():
                self._error(403, "仅限本机操作")
                return
            if _ACTIVE:
                self._error(409, "正在扫描或重算，请稍后再试")
                return
            job = str(payload.get("job") or "").strip()
            if not job:
                self._error(400, "缺少 job")
                return

            cache = os.path.join(state.out_dir, "cache", job + ".csv")
            manifest = incremental.load_manifest(state.out_dir)
            rec = manifest.get(job)
            if not os.path.exists(cache) and not rec:
                self._error(404, "没有这个设计")
                return

            # 1) 源包：只删 incoming 目录内的文件（基础设计没有源包，只移结果）
            src_deleted = False
            src = (rec or {}).get("file") or ""
            if src:
                incoming = state.incoming_dir or ""
                try:
                    inside = bool(incoming) and os.path.commonpath(
                        [os.path.abspath(src), os.path.abspath(incoming)]
                    ) == os.path.abspath(incoming)
                except ValueError:
                    inside = False
                if inside and os.path.exists(src):
                    try:
                        os.remove(src)
                        src_deleted = True
                    except OSError as exc:
                        self._error(500, "删除源包失败：%s" % exc)
                        return

            # 2) 缓存与清单
            try:
                if os.path.exists(cache):
                    os.remove(cache)
            except OSError as exc:
                self._error(500, "删除缓存失败：%s" % exc)
                return
            if rec:
                manifest.pop(job, None)
                incremental.save_manifest(state.out_dir, manifest)

            # 3) 后台重建排名与图表
            jid, busy = start_delete(state, job)
            if jid is None:
                self._error(409, "已有任务在运行")
                return
            self._json({"job_id": jid, "source_deleted": src_deleted})

        def _route(self, path: str):
            if path in ("/", "/index.html"):
                self._send(200, INDEX_HTML.encode("utf-8"), MIME[".html"])
                return
            if path == "/api/health":
                self._json(state.health())
                return
            if path == "/api/status":
                self._json(state.status())
                return
            if path.startswith("/api/jobs/"):
                jid = path.rsplit("/", 1)[-1]
                job = _JOBS.get(jid)
                if job is None:
                    self._error(404, "没有这个任务: " + jid)
                else:
                    self._json(job)
                return
            if path == "/api/summary":
                self._json(state.summary_payload())
                return
            if path == "/api/models":
                self._json({"models": state.models})
                return
            if path.startswith("/figures/"):
                name = unquote(path[len("/figures/"):])
                if name in state.figures:                # 白名单，防目录穿越
                    with open(os.path.join(state.fig_dir, name), "rb") as fh:
                        self._send(200, fh.read(), MIME[".png"])
                else:
                    self._error(404, "没有这张图: " + name)
                return
            if path == "/favicon.ico":
                self._send(204, b"", "image/x-icon")
                return
            self._error(404, "未知路径: " + path)

        def log_message(self, fmt, *args):
            if not quiet:
                sys.stderr.write("[web] %s - %s\n" % (self.address_string(), fmt % args))
    return Handler


def lan_ips():
    ips = set()
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ips.add(info[4][0])
    except OSError:
        pass
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        ips.add(s.getsockname()[0])
    except OSError:
        pass
    finally:
        s.close()
    return sorted(ip for ip in ips if not ip.startswith("127."))


def _port_free(port: int, host: str = "127.0.0.1") -> bool:
    """探测端口是否已被占用。

    Windows 上 SO_REUSEADDR 允许重复绑定，光靠 bind 抛错判断不出来，
    所以先尝试连一下：连得上说明已有服务在听。
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.3)
        return s.connect_ex((host, port)) != 0


def _bind(handler_cls, host: str, port: int, tries: int = 10):
    """端口被占用时自动往后找，返回 (server, 实际端口)。port=0 时由系统分配。"""
    last = None
    for p in range(port, port + tries):
        if p != 0 and not _port_free(port if p == port else p):
            last = OSError("端口 %d 已有服务在监听" % p)
            continue
        try:
            srv = ThreadingHTTPServer((host, p), handler_cls)
            return srv, int(srv.server_address[1])
        except OSError as exc:
            last = exc
    raise SystemExit("端口 %d-%d 都不可用：%s" % (port, port + tries - 1, last))


def serve(data: str = "out", host: str = "0.0.0.0", port: int = 8765,
          open_browser: bool = True, quiet: bool = False,
          predictions: str | None = None, incoming: str | None = None) -> None:
    incoming = os.path.abspath(incoming or os.path.join(os.getcwd(), "incoming"))
    os.makedirs(incoming, exist_ok=True)
    if predictions is None:
        # 只有在"已经算过一次"时才自动探测数据目录，避免空目录一启动就提示要全量导入
        if os.path.exists(os.path.join(data, "summary_by_design.csv")):
            cand = os.path.abspath(os.path.join(
                os.getcwd(), "..", "..", "alphafold预测结果数据相关附件", "alphafold预测结果数据"))
            predictions = cand if os.path.isdir(cand) else None
    else:
        predictions = os.path.abspath(predictions)

    state = State(data, predictions, incoming)
    _holder = {}

    def _quit():
        srv = _holder.get("srv")
        if srv is not None:
            try:
                srv.shutdown()
            except Exception:
                pass

    httpd, actual = _bind(make_handler(state, quiet, on_quit=_quit), host, port)
    _holder["srv"] = httpd
    httpd.daemon_threads = True

    print("=" * 64)
    print("AlphaFold3 评分看板 v%s 已启动" % VERSION)
    if getattr(state, "has_data", False):
        print("  设计 %d 个 · 模型 %d 个 · 数据时间 %s" %
              (len(state.designs), state.n_models, state.file_time))
    else:
        print("  暂无结果数据 —— 页面会给出导入步骤（放包到 incoming 后点「扫描新包」）")
    print("  本机访问 : http://127.0.0.1:%d/" % actual)
    if host == "0.0.0.0":
        ips = lan_ips()
        for ip in ips:
            print("  局域网   : http://%s:%d/" % (ip, actual))
        if not ips:
            print("  （未检测到局域网 IP，可能未连网）")
        print("  提示：Windows 首次会弹防火墙提示，需允许“专用网络”；")
        print("        组员打不开时，先确认在同一 Wi-Fi，再用上面的局域网地址。")
    if actual != port:
        print("  注意：端口 %d 被占用，已改用 %d" % (port, actual))
    print("  新包目录 : %s" % incoming)
    if predictions:
        print("  预测数据 : %s" % predictions)
    print("  用法     : 把新的 fold_*.zip 放进上面的「新包目录」，页面会提示，点「扫描新包」即可")
    print("  停止服务 : Ctrl+C")
    print("=" * 64, flush=True)

    if open_browser:
        threading.Timer(0.8, lambda: webbrowser.open("http://127.0.0.1:%d/" % actual)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止。")
    finally:
        httpd.server_close()


def main(argv=None):
    ap = argparse.ArgumentParser("afscore.web", description="评分结果 Web 看板（局域网可访问）")
    ap.add_argument("--data", default="out", help="含 scores.csv / figures 的目录")
    ap.add_argument("--host", default="0.0.0.0", help="监听地址；127.0.0.1 表示仅本机")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--no-open", action="store_true", help="不自动打开浏览器")
    ap.add_argument("--quiet", action="store_true", help="不打印每个请求")
    ap.add_argument("--predictions", default=None, help="已有预测结果目录（用于检测同名包被替换）")
    ap.add_argument("--incoming", default=None, help="新包目录，默认 ./incoming")
    args = ap.parse_args(argv)
    serve(args.data, args.host, args.port, not args.no_open, args.quiet,
          args.predictions, args.incoming)


if __name__ == "__main__":
    main()
