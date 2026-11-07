"""增量扫描：把新预测包放进 incoming/，只算新增/变更的，再重建表与图。

设计要点：
  * 指纹 = 文件大小 + 修改时间，存在 out/cache/manifest.json
  * 指纹没变且缓存存在 → 直接跳过（35 个老包不会重算）
  * 扫描结束后统一 rebuild() 并重画 5 张图，保证"表和图同时更新"
  * 单个包失败不影响其他包，失败项进 report["failed"]
"""
from __future__ import annotations

import glob
import json
import os
import time
from typing import Callable, Dict, List, Optional

from .pipeline import rebuild, score_job
from .report import make_figures

MANIFEST = "manifest.json"
LAST_SCAN = "last_scan.json"


# ---------------------------------------------------------------- 指纹与清单
def fingerprint(path: str) -> str:
    """文件指纹 = 大小 + 纳秒修改时间（整秒会漏掉"同大小、同秒"的替换）。"""
    st = os.stat(path)
    return "%d-%d" % (st.st_size, st.st_mtime_ns)


def _same(rec: Dict, path: str) -> bool:
    """比对清单指纹；兼容早期的整秒格式，避免升级后把老包全重算一遍。"""
    try:
        st = os.stat(path)
    except OSError:
        return False
    parts = str(rec.get("fp") or "").split("-")
    if len(parts) != 2:
        return False
    try:
        size, stamp = int(parts[0]), int(parts[1])
    except ValueError:
        return False
    if size != st.st_size:
        return False
    if len(parts[1]) <= 12:                    # 旧格式：整秒
        return stamp == int(st.st_mtime)
    return stamp == st.st_mtime_ns


def manifest_path(out_dir: str) -> str:
    return os.path.join(out_dir, "cache", MANIFEST)


def load_manifest(out_dir: str) -> Dict[str, dict]:
    p = manifest_path(out_dir)
    if not os.path.exists(p):
        return {}
    try:
        with open(p, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def save_manifest(out_dir: str, data: Dict[str, dict]) -> None:
    p = manifest_path(out_dir)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=1)
    os.replace(tmp, p)


def last_scan_path(out_dir: str) -> str:
    return os.path.join(out_dir, "cache", LAST_SCAN)


def save_last_scan(out_dir: str, report: dict) -> None:
    """记住"最近一批变化"（新增+更新），供页面刷新后继续标红。"""
    payload = {
        "finished": report.get("finished", ""),
        "added": sorted(report.get("added") or []),
        "updated": sorted(report.get("updated") or []),
        "removed": sorted(report.get("removed") or []),
        "skipped": int(report.get("skipped", 0)),
        "failed": [f.get("file") for f in (report.get("failed") or [])],
        "elapsed": report.get("elapsed", 0),
        "new_jobs": sorted((set(report.get("added") or []) | set(report.get("updated") or []))
                           - set(report.get("removed") or [])),
    }
    p = last_scan_path(out_dir)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=1)
    os.replace(tmp, p)


def load_last_scan(out_dir: str) -> Dict:
    p = last_scan_path(out_dir)
    if not os.path.exists(p):
        return {}
    try:
        with open(p, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def note(out_dir: str, name: str, path: str) -> None:
    """记下某个包已算过（CLI 批量评分时逐条调用）。"""
    m = load_manifest(out_dir)
    m[name] = {"file": os.path.abspath(path), "fp": fingerprint(path),
               "scanned_at": time.strftime("%Y-%m-%d %H:%M:%S")}
    save_manifest(out_dir, m)


def bootstrap(files: Dict[str, str], out_dir: str) -> Dict[str, dict]:
    """清单不存在时，用"已有缓存 + 当前指纹"补一份，避免首次扫描把老包全当新包。"""
    manifest = load_manifest(out_dir)
    if manifest:
        return manifest
    for name, path in files.items():
        if os.path.exists(os.path.join(out_dir, "cache", "%s.csv" % name)):
            manifest[name] = {"file": os.path.abspath(path),
                              "fp": fingerprint(path), "scanned_at": "bootstrap"}
    save_manifest(out_dir, manifest)
    return manifest


def upgrade_manifest(out_dir: str) -> int:
    """把旧的"整秒"指纹就地升级为纳秒；仅当文件确实没变才改，避免误吞变更。"""
    m = load_manifest(out_dir)
    n = 0
    for name, rec in m.items():
        path = rec.get("file")
        old = str(rec.get("fp") or "")
        if not path or not os.path.exists(path) or len(old.split("-")[-1]) > 12:
            continue
        if not _same(rec, path):        # 文件已变，留给扫描处理
            continue
        rec["fp"] = fingerprint(path)
        n += 1
    if n:
        save_manifest(out_dir, m)
    return n


# ---------------------------------------------------------------- 收集与比对
def collect(predictions_dir: Optional[str], incoming_dir: Optional[str]) -> Dict[str, str]:
    """收集两处的 zip；同名时取修改时间较新的那个。"""
    files: Dict[str, str] = {}
    for d in (predictions_dir, incoming_dir):
        if not d or not os.path.isdir(d):
            continue
        for f in sorted(glob.glob(os.path.join(d, "*.zip"))):
            name = os.path.splitext(os.path.basename(f))[0]
            old = files.get(name)
            try:
                if old is not None and os.path.getmtime(old) >= os.path.getmtime(f):
                    continue
            except OSError:            # 文件在扫描期间被删/改名：保留已有的那份
                if old is not None:
                    continue
            files[name] = os.path.abspath(f)
    return files


def _inside(path: str, roots) -> bool:
    """path 是否位于 roots 之一（Windows 下忽略大小写）。"""
    p = os.path.normcase(os.path.abspath(path))
    for r in roots:
        if not r:
            continue
        base = os.path.normcase(os.path.abspath(r))
        if p == base or p.startswith(base + os.sep):
            return True
    return False


def pending_names(files: Dict[str, str], manifest: Dict[str, dict], out_dir: str,
                  settle: float = 2.0) -> List[str]:
    """需要处理的包：指纹变了，或还没算过；刚写入（<settle 秒）的先跳过。"""
    now = time.time()
    todo: List[str] = []
    for name, path in sorted(files.items()):
        try:
            st = os.stat(path)
        except OSError:
            continue
        cache = os.path.join(out_dir, "cache", "%s.csv" % name)
        cache_exists = os.path.exists(cache)
        rec = manifest.get(name)
        if rec and _same(rec, path) and (cache_exists or rec.get("failed")):
            continue            # 已算过，或已知是坏包（内容没变就不再报）
        if not rec and cache_exists:
            continue            # 有缓存但没有清单记录：视为已知（首次部署/清单丢失）
        if now - st.st_mtime < settle:          # 可能还在拷贝
            continue
        todo.append(name)
    return todo


# ---------------------------------------------------------------- 扫描主流程
def scan(predictions_dir: Optional[str] = None, incoming_dir: Optional[str] = None,
         out_dir: str = "out", settle: float = 2.0, make_figs: bool = True,
         progress: Optional[Callable[[int, int, str], None]] = None,
         verbose: bool = True) -> dict:
    """扫描并增量更新；返回报告 dict。"""
    t0 = time.time()
    os.makedirs(os.path.join(out_dir, "cache"), exist_ok=True)
    files = collect(predictions_dir, incoming_dir)
    manifest = load_manifest(out_dir)
    if not manifest and files:
        manifest = bootstrap(files, out_dir)
    else:
        upgrade_manifest(out_dir)          # 旧清单就地升级为纳秒指纹
        manifest = load_manifest(out_dir)
    todo = pending_names(files, manifest, out_dir, settle)

    report = {"added": [], "updated": [], "removed": [],
              "skipped": len(files) - len(todo),
              "failed": [], "total_files": len(files), "elapsed": 0.0,
              "designs": 0, "figures": {}, "started": time.strftime("%Y-%m-%d %H:%M:%S")}

    # 源包被删除：连同缓存和清单一起清掉（只清理我们扫描的目录，避免误删别处算过的设计）
    for name, rec in sorted(manifest.items()):
        src = rec.get("file") or ""
        if not src or name in files:
            continue
        if not _inside(src, (predictions_dir, incoming_dir)):
            continue
        if os.path.exists(src):
            continue
        cache = os.path.join(out_dir, "cache", "%s.csv" % name)
        try:
            if os.path.exists(cache):
                os.remove(cache)
        except OSError:
            continue
        del manifest[name]
        report["removed"].append(name)
        if verbose:
            print("  %s: 源包已删除，移除该设计" % name, flush=True)
    if report["removed"]:
        save_manifest(out_dir, manifest)

    for i, name in enumerate(todo, 1):
        path = files[name]
        if progress:
            progress(i - 1, len(todo), name)
        cache = os.path.join(out_dir, "cache", "%s.csv" % name)
        existed = os.path.exists(cache)
        try:
            df = score_job(path)
            if df is None:
                raise RuntimeError("没有解析出任何模型")
            df.to_csv(cache, index=False)
            manifest[name] = {"file": path, "fp": fingerprint(path),
                              "scanned_at": time.strftime("%Y-%m-%d %H:%M:%S")}
            (report["updated"] if existed else report["added"]).append(name)
            if verbose:
                print("  %s: %s（%d 个模型）" % (name, "更新" if existed else "新增", len(df)),
                      flush=True)
        except Exception as exc:
            report["failed"].append({"file": os.path.basename(path),
                                     "error": "%s: %s" % (type(exc).__name__, exc)})
            # 记下指纹：内容不变就不再重复报错；换个好包（指纹变化）会自动重试
            manifest[name] = {"file": path, "fp": fingerprint(path),
                              "scanned_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                              "failed": "%s: %s" % (type(exc).__name__, exc)}
            if verbose:
                print("  %s: 失败（%s）" % (name, exc), flush=True)
        save_manifest(out_dir, manifest)

    if progress:
        progress(len(todo), len(todo), "")

    have_summary = os.path.exists(os.path.join(out_dir, "summary_by_design.csv"))
    caches = glob.glob(os.path.join(out_dir, "cache", "*.csv"))

    if not caches:
        # 一个包都不剩：删掉结果表，页面回到"空状态"
        for f in ("summary_by_design.csv", "scores.csv"):
            p = os.path.join(out_dir, f)
            if os.path.exists(p):
                os.remove(p)
        report["designs"] = 0
        if report["removed"]:
            report["note"] = "已移除 %d 个设计（来源包已删除），当前没有数据" % len(report["removed"])
        else:
            report["note"] = "还没有可用的预测结果：把 fold_*.zip 放进 incoming 目录后再扫描"
    # 有变化（新增 / 更新 / 移除）或首次有包但还没表，才重建
    elif report["added"] or report["updated"] or report["removed"] or not have_summary:
        df = rebuild(out_dir)
        report["designs"] = int(df["job"].nunique())
        if make_figs:
            lookup = {n: rec.get("file") for n, rec in manifest.items() if rec.get("file")}
            report["figures"] = make_figures(df, os.path.join(out_dir, "figures"), lookup)
    else:
        try:
            import pandas as pd
            report["designs"] = int(pd.read_csv(
                os.path.join(out_dir, "summary_by_design.csv"))["job"].nunique())
        except Exception:
            report["designs"] = 0

    report["elapsed"] = round(time.time() - t0, 1)
    report["finished"] = time.strftime("%Y-%m-%d %H:%M:%S")
    # 只有真的换了数据才更新"最近一批"，避免顺手点一次扫描把红点擦掉
    if report["added"] or report["updated"]:
        save_last_scan(out_dir, report)
    return report
