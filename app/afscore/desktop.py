"""桌面版入口：起本地服务 + 原生窗口（pywebview），窗口关闭即退出。

    python -m afscore.desktop --app-dir <应用根目录>
    python -m afscore.desktop --app-dir <根> --selftest    # 只验后端，不开窗

目录约定（相对 app-dir，可在 config.json 里改）：
    data/out        结果（scores.csv / summary / cache / figures）
    incoming        放新包
    predictions     可选，已有的预测包目录（为空则不启用）
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import threading
import urllib.request

from .web import State, _bind, make_handler

DEFAULT_CONFIG = {"data": "data/out", "incoming": "incoming", "predictions": ""}


# ---------------------------------------------------------------- 配置
def load_config(root: str) -> dict:
    cfg = dict(DEFAULT_CONFIG)
    path = os.path.join(root, "config.json")
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            if isinstance(data, dict):
                cfg.update({k: data[k] for k in DEFAULT_CONFIG if k in data})
        except Exception:
            pass
    return cfg


def _resolve(root: str, rel: str):
    if not rel:
        return None
    return rel if os.path.isabs(rel) else os.path.abspath(os.path.join(root, rel))


# ---------------------------------------------------------------- 单实例锁
def _alive(pid: int) -> bool:
    if os.name == "nt":
        import ctypes
        SYNCHRONIZE = 0x00100000
        handle = ctypes.windll.kernel32.OpenProcess(SYNCHRONIZE, False, pid)
        if not handle:
            return False
        ctypes.windll.kernel32.CloseHandle(handle)
        return True
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def acquire_lock(root: str) -> bool:
    path = os.path.join(root, "data", ".lock")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    try:
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as fh:
                pid = int((fh.read() or "0").strip())
            if pid and _alive(pid):
                return False
    except Exception:
        pass
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(str(os.getpid()))
    return True


def release_lock(root: str) -> None:
    try:
        os.remove(os.path.join(root, "data", ".lock"))
    except OSError:
        pass


def _message(text: str, title: str = "af-score") -> None:
    if os.name == "nt":
        import ctypes
        ctypes.windll.user32.MessageBoxW(0, text, title, 0x40)
    else:
        print(text, file=sys.stderr)


# ---------------------------------------------------------------- 服务
def start_server(root: str, cfg: dict, host: str, port: int):
    data = _resolve(root, cfg["data"])
    incoming = _resolve(root, cfg["incoming"])
    predictions = _resolve(root, cfg.get("predictions") or "")
    os.makedirs(data, exist_ok=True)
    if incoming:
        os.makedirs(incoming, exist_ok=True)
    state = State(data, predictions, incoming)
    httpd, actual = _bind(make_handler(state, True), host, port)
    httpd.daemon_threads = True
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return state, httpd, actual


# ---------------------------------------------------------------- 窗口
def _run_window(url: str, root: str) -> int:
    try:
        import webview
    except Exception as exc:                       # 没装 pywebview → 用 Edge 窗口
        print("pywebview 不可用（%s），改用 Edge 应用窗口" % exc, file=sys.stderr)
        return _run_edge(url, root)
    webview.create_window("AlphaFold3 评分看板", url, width=1440, height=920,
                          min_size=(1100, 700))
    webview.start()
    return 0


def _run_edge(url: str, root: str) -> int:
    import subprocess
    profile = os.path.join(root, "data", "edge")
    os.makedirs(profile, exist_ok=True)
    for exe in (os.path.join(os.environ.get("ProgramFiles(x86)", ""),
                             r"Microsoft\Edge\Application\msedge.exe"),
                os.path.join(os.environ.get("ProgramFiles", ""),
                             r"Microsoft\Edge\Application\msedge.exe")):
        if exe and os.path.exists(exe):
            # 独立的 user-data-dir：保证是独立进程，窗口关闭时进程才退出
            subprocess.run([exe, "--app=" + url, "--window-size=1456,940",
                            "--user-data-dir=" + profile])
            return 0
    import webbrowser
    webbrowser.open(url)
    _message("没有找到 WebView2 / Edge，已用默认浏览器打开：\n" + url)
    return 0


# ---------------------------------------------------------------- 主流程
def main(argv=None) -> int:
    ap = argparse.ArgumentParser("afscore.desktop")
    ap.add_argument("--app-dir", default=None, help="应用根目录（默认当前目录）")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=0, help="0 = 由系统分配")
    ap.add_argument("--selftest", action="store_true", help="只验后端，不开窗口")
    ap.add_argument("--no-window", action="store_true", help="同 --selftest")
    args = ap.parse_args(argv)

    root = os.path.abspath(args.app_dir or os.environ.get("AFSCORE_APP_DIR")
                           or os.getcwd())
    cfg = load_config(root)
    os.makedirs(os.path.join(root, "data"), exist_ok=True)

    if not acquire_lock(root):
        if args.selftest or args.no_window:
            print("another instance is running", file=sys.stderr)
        else:
            _message("af-score 已经在运行，请先关闭那个窗口。")
        return 3

    httpd = None
    try:
        _state, httpd, port = start_server(root, cfg, args.host, args.port)
        url = "http://%s:%d/" % (args.host, port)
        if args.selftest or args.no_window:
            with urllib.request.urlopen(url + "api/health", timeout=15) as resp:
                health = json.loads(resp.read().decode("utf-8"))
            print("selftest ok | url=%s designs=%s models=%s has_data=%s"
                  % (url, health.get("designs"), health.get("models"),
                     health.get("has_data")))
            return 0
        return _run_window(url, root)
    finally:
        if httpd is not None:
            try:
                httpd.shutdown()
                httpd.server_close()
            except Exception:
                pass
        release_lock(root)


if __name__ == "__main__":
    sys.exit(main())
