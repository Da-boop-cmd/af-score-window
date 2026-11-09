"""把 af-score 组装成"绿色版"桌面程序目录（可重复运行）。

产出（在 af-score-window\\ 下）：
    af-score.exe             C++ 外壳（WebView2 窗口）
    app\\afscore\\             程序代码（从 ..\\af-score\\afscore 复制）
    runtime\\python\\          嵌入式 Python 3.15 + 依赖
    data\\out\\                现成结果（scores/summary/cache/figures）
    incoming\\                 放新包
    config.json               数据目录配置
    启动桌面版_调试.cmd         带控制台，出问题看这里

用法：
    build_window.py                 # 标准包（含结果，约 65-75 MB）
    build_window.py --with-data     # 全量包（额外含 36 个预测 zip，约 1.6 GB）
    build_window.py --skip-download # 复用 build\\_cache 里已下载的 embed 包
"""
from __future__ import annotations

import argparse
import glob
import os
import shutil
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent          # af-score-window\build
WIN = HERE.parent                               # af-score-window
PROJ = HERE.parents[1] / "af-score"             # 成果\af-score
CACHE = HERE / "_cache"
PYVER = "3.15.0"
EMBED_URLS = [
    "https://mirrors.huaweicloud.com/python/{v}/python-{v}-embed-amd64.zip",
    "https://registry.npmmirror.com/-/binary/python/{v}/python-{v}-embed-amd64.zip",
    "https://www.python.org/ftp/python/{v}/python-{v}-embed-amd64.zip",
]
MIN_EMBED_BYTES = 12_000_000
SKIP_DIRS = {"__pycache__", "pip", "pip-25", "setuptools", "pkg_resources",
             "wheel", "_distutils_hack", "distutils-precedence.pth"}


def log(msg: str) -> None:
    print(msg, flush=True)


def rm(path: Path) -> None:
    if path.is_dir():
        shutil.rmtree(path, ignore_errors=True)
    elif path.exists():
        path.unlink()
    if path.exists():
        raise SystemExit("无法删除 %s（可能还有进程在用它，先关掉 af-score 窗口再试）" % path)


# ---------------------------------------------------------------- 1. 运行时
def ensure_embed() -> Path:
    CACHE.mkdir(parents=True, exist_ok=True)
    dst = CACHE / "python-embed.zip"
    if dst.exists() and dst.stat().st_size >= MIN_EMBED_BYTES:
        log("复用已下载的 embed 包（%.1f MB）" % (dst.stat().st_size / 1e6))
        return dst
    rm(dst)
    last = None
    for tpl in EMBED_URLS:
        url = tpl.format(v=PYVER)
        try:
            log("下载嵌入式 Python：%s" % url)
            with urllib.request.urlopen(url, timeout=10) as r, open(dst, "wb") as fh:
                total = int(r.headers.get("Content-Length") or 0)
                got = 0
                while True:
                    chunk = r.read(1 << 20)
                    if not chunk:
                        break
                    fh.write(chunk)
                    got += len(chunk)
                    if total:
                        print("\r  %.1f / %.1f MB" % (got / 1e6, total / 1e6),
                              end="", flush=True)
            print()
            if dst.stat().st_size >= MIN_EMBED_BYTES:
                return dst
            raise RuntimeError("下载不完整：%d 字节" % dst.stat().st_size)
        except Exception as exc:
            last = exc
            log("  失败：%s" % exc)
            rm(dst)
    raise SystemExit("三个镜像都下载失败：%s" % last)


def install_python(zip_path: Path) -> None:
    py = WIN / "runtime" / "python"
    rm(WIN / "runtime")
    py.mkdir(parents=True)
    with zipfile.ZipFile(zip_path) as z:
        z.extractall(py)

    # 让嵌入式解释器能找到 app 与 site-packages
    pth = next(py.glob("python3*._pth"), None)
    if pth is None:
        raise SystemExit("找不到 _pth 文件")
    pth.write_text("python3%s.zip\n.\n..\\..\\app\nLib\\site-packages\nimport site\n"
                   % sys.version_info[1], encoding="utf-8")

    src = PROJ / ".venv" / "Lib" / "site-packages"
    dst = py / "Lib" / "site-packages"
    dst.mkdir(parents=True)
    log("复制依赖 ...")
    for item in src.iterdir():
        if item.name in SKIP_DIRS:
            continue
        target = dst / item.name
        if item.is_dir():
            shutil.copytree(item, target,
                            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        else:
            shutil.copy2(item, target)


# ---------------------------------------------------------------- 2. 程序
def install_app() -> None:
    app = WIN / "app" / "afscore"
    rm(WIN / "app")
    app.mkdir(parents=True)
    for f in (PROJ / "afscore").glob("*.py"):
        shutil.copy2(f, app / f.name)
    log("复制代码 %d 个模块" % len(list(app.glob('*.py'))))


# ---------------------------------------------------------------- 3. 结果
def install_results() -> None:
    out = WIN / "data" / "out"
    rm(WIN / "data")
    (out / "cache").mkdir(parents=True)
    (out / "figures").mkdir(parents=True)

    for name in ("scores.csv", "summary_by_design.csv",
                 "calibration_cv.csv", "calibration_weights.csv"):
        src = PROJ / "out" / name
        if src.exists():
            shutil.copy2(src, out / name)

    # 缓存：保留特征表，丢 manifest（里面的绝对路径换机器后没意义，首次扫描会重建）
    n = 0
    for f in (PROJ / "out" / "cache").glob("*.csv"):
        shutil.copy2(f, out / "cache" / f.name)
        n += 1
    for name in ("last_scan.json",):
        src = PROJ / "out" / "cache" / name
        if src.exists():
            shutil.copy2(src, out / "cache" / name)

    figs = list((PROJ / "out" / "figures").glob("*.png"))
    for f in figs:
        shutil.copy2(f, out / "figures" / f.name)
    log("复制结果：%d 个缓存、%d 张图" % (n, len(figs)))


# ---------------------------------------------------------------- 4. 数据（可选）
def install_data() -> str:
    src = PROJ.parents[1] / "alphafold预测结果数据相关附件" / "alphafold预测结果数据"
    if not src.is_dir():
        log("找不到预测数据目录，跳过：%s" % src)
        return ""
    dst = WIN / "data" / "predictions"
    dst.mkdir(parents=True, exist_ok=True)
    zips = sorted(src.glob("*.zip"))
    total = 0
    for z in zips:
        shutil.copy2(z, dst / z.name)
        total += z.stat().st_size
    log("复制预测数据 %d 个（%.1f GB）" % (len(zips), total / 1e9))
    return "data/predictions"


# ---------------------------------------------------------------- 5. 配置与启动器
def write_config(predictions: str) -> None:
    cfg = ('{\n  "data": "data/out",\n  "incoming": "incoming",\n'
           '  "predictions": "%s"\n}\n' % predictions)
    (WIN / "config.json").write_text(cfg, encoding="utf-8")

    inc = WIN / "incoming"
    inc.mkdir(parents=True, exist_ok=True)
    (inc / "放这里.txt").write_text(
        "把新的 AlphaFold3 结果包（fold_*.zip）放进这个文件夹，\n"
        "然后在窗口里点「扫描新包」，表格和图片会自动更新。\n", encoding="utf-8")

    (WIN / "启动桌面版_调试.cmd").write_text(
        "@echo off\r\n"
        "cd /d \"%~dp0\"\r\n"
        "set \"MPLCONFIGDIR=%~dp0data\\.mpl\"\r\n"
        "echo Starting af-score (debug mode, errors stay in this window) ...\r\n"
        "af-score.exe\r\n"
        "if errorlevel 1 pause\r\n", encoding="ascii")

    # 兼容模式：万一 af-score.exe 被杀软/SmartScreen 拦，用这个直接跑 Python 后端
    (WIN / "启动桌面版_兼容模式.cmd").write_text(
        "@echo off\r\n"
        "cd /d \"%~dp0\"\r\n"
        "set \"MPLCONFIGDIR=%~dp0data\\.mpl\"\r\n"
        "\"runtime\\python\\pythonw.exe\" -m afscore.desktop --app-dir \"%~dp0\"\r\n"
        "if errorlevel 1 pause\r\n", encoding="ascii")


def copy_exe() -> None:
    exe = HERE / "af-score.exe"
    if not exe.exists():
        raise SystemExit("缺少 build\\af-score.exe，请先运行 build.bat")
    shutil.copy2(exe, WIN / "af-score.exe")


def write_readme() -> None:
    (WIN / "README-桌面版.txt").write_text(
        "af-score 桌面版\n"
        "================\n\n"
        "启动：双击 af-score.exe（或 启动桌面版_调试.cmd 看详细报错）\n\n"
        "第一次打开会显示已有结果；要加新数据：\n"
        "  1. 把 fold_*.zip 放进 incoming\\\n"
        "  2. 在窗口里点「扫描新包」\n"
        "  3. 删掉 zip 再点一次扫描，对应设计会被移除\n\n"
        "数据与配置：\n"
        "  data\\out       结果（scores.csv / summary_by_design.csv / figures）\n"
        "  incoming       新包投放目录\n"
        "  config.json    可把 data 改成共享目录（如 \\\\server\\share\\out）\n\n"
        "排查：\n"
        "  data\\shell.log  外壳启动日志（端口、后端、WebView2 状态）\n"
        "  需要 Windows 10/11 x64，系统自带 Edge/WebView2\n"
        "  杀软拦截时，把整个文件夹加入信任\n\n"
        "如果双击 af-score.exe 被 Windows 拦（已保护你的电脑）：\n"
        "  1. 点「更多信息」→「仍要运行」；或\n"
        "  2. 右键 af-score.exe → 属性 → 勾选「解除锁定」→ 确定；或\n"
        "  3. 直接双击 启动桌面版_兼容模式.cmd（不经过 exe，用 Edge 窗口打开）\n"
        "  4. 仍然不行：Windows 安全中心 → 病毒和威胁防护 → 排除项 → 添加这个文件夹\n", encoding="utf-8")


# ---------------------------------------------------------------- 6. 自检
def verify() -> bool:
    py = WIN / "runtime" / "python" / "python.exe"
    ok = True
    r = subprocess.run([str(py), "-c", "import numpy, pandas, matplotlib;"
                        "print('deps', numpy.__version__, pandas.__version__)"],
                       capture_output=True, text=True)
    log("依赖检查: %s" % (r.stdout.strip() or r.stderr.strip()))
    ok &= r.returncode == 0

    r = subprocess.run([str(py), "-m", "afscore.desktop", "--app-dir", str(WIN),
                        "--selftest"], capture_output=True, text=True, cwd=str(WIN))
    out = (r.stdout + r.stderr).strip()
    log("selftest: %s" % out.replace("\n", " | "))
    ok &= r.returncode == 0
    return ok


def make_zip() -> Path:
    """打分发 zip：排除 build 工作区与运行痕迹。"""
    out = WIN.parent / "af-score-window.zip"
    rm(out)
    skip_dirs = {"build", "data/webview2"}
    count = 0
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for f in WIN.rglob("*"):
            if not f.is_file():
                continue
            rel = f.relative_to(WIN)
            posix = rel.as_posix()
            if posix.startswith("build/") or posix.startswith("data/webview2/"):
                continue
            if posix.startswith(".git/"):
                continue
            if f.name in ("shell.log", ".lock"):
                continue
            z.write(f, posix)
            count += 1
    log("zip: %s（%d 个文件, %.1f MB）" % (out, count, out.stat().st_size / 1e6))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--with-data", action="store_true", help="额外打包 36 个预测 zip")
    ap.add_argument("--skip-download", action="store_true")
    ap.add_argument("--zip", action="store_true", help="最后打成 af-score-window.zip")
    args = ap.parse_args()

    if not (PROJ / "out" / "scores.csv").exists():
        raise SystemExit("找不到 %s，请先跑一次 cli run" % (PROJ / "out" / "scores.csv"))

    zip_path = CACHE / "python-embed.zip"
    if args.skip_download and zip_path.exists():
        log("复用已下载的 embed 包")
    else:
        zip_path = ensure_embed()

    install_python(zip_path)
    install_app()
    install_results()
    pred = install_data() if args.with_data else ""
    copy_exe()
    write_config(pred)
    write_readme()

    ok = verify()
    size = sum(f.stat().st_size for f in WIN.rglob("*") if f.is_file())
    files = sum(1 for f in WIN.rglob("*") if f.is_file())
    dist = [f for f in WIN.rglob("*") if f.is_file() and "build" not in f.relative_to(WIN).parts]
    log("\n产出: %s" % WIN)
    log("  %d 个文件, %.1f MB（其中 build 工作区 %.1f MB）"
        % (files, size / 1e6, (size - sum(f.stat().st_size for f in dist)) / 1e6))
    log("  分发体积: %.1f MB / %d 个文件"
        % (sum(f.stat().st_size for f in dist) / 1e6, len(dist)))
    log("  自检: %s" % ("通过" if ok else "失败"))
    if args.zip:
        make_zip()
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
