"""批处理流水线：遍历任务包 → 特征 → 评分 → 标定 → Pareto → 落盘。

带 job 级缓存（out/cache/<job>.csv），中断后可续跑；20 聚体任务单个要
40–60 s（5 个模型 × 200 MB 的 full_data），缓存是必需的。

拆成三步，供 CLI 与"扫描新包"共用：
    score_job(path)   —— 解析单个包，返回该任务的模型级特征表
    rebuild(out_dir)  —— 读全部缓存 → 合并 → 打分 → 标定 → 写两张表
    run(root, ...)    —— 批量：逐个评分（或命中缓存）后调 rebuild
"""
from __future__ import annotations

import glob
import os
import time
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from . import coev as coev_mod
from .io_af import iter_job_paths, iter_models, load_job_meta
from .metrics import chain_sequence, model_features
from .scoring import (COMPONENT_LABEL, COMPONENTS, DEFAULT_WEIGHTS, RidgeCalibrator,
                      add_scores)

CAL_FEATURES = ["c_plddt", "c_conf", "c_pae", "c_packing", "c_geometry", "c_coev"]


def _coev_for_job(job, model) -> Optional[coev_mod.CoevResult]:
    """挑一条非配对 MSA，用第一份模型的结构算接触精确率。

    多聚体任务的 a3m 是多链列拼接，按单链长度切段后再算。
    """
    if not job.msa_bytes:
        return None
    n_chains = max(len(model.struct.chain_list()), 1)
    target_len = model.struct.n_residues // n_chains
    best_raw, best_len = None, -1
    for name, raw in job.msa_bytes.items():
        if "unpaired" not in name:
            continue
        q, _ = coev_mod.parse_a3m(raw, max_seqs=3)
        if len(q) >= target_len and len(q) > best_len:
            best_raw, best_len = raw, len(q)
    if best_raw is None:
        return None
    ca_idx = model.struct.ca_idx()
    ca = model.struct.xyz[ca_idx[ca_idx >= 0]]
    return coev_mod.analyse(best_raw, ca[:target_len], seg_len=target_len)


def score_job(path: str) -> Optional[pd.DataFrame]:
    """解析单个任务包 → 该任务 5 个模型的特征表；解析不出模型时返回 None。

    坏包 / 0 字节包会抛异常，由调用方决定记失败还是跳过。
    """
    meta = load_job_meta(path)
    rows: List[Dict] = []
    coev_res = None
    for m in iter_models(path):
        if coev_res is None:
            coev_res = _coev_for_job(meta, m)
        f = model_features(meta, m, coev_res)
        f["linker"] = meta.design.get("linker", "")
        f["epitope_type"] = meta.design.get("epitope", "")
        f["assembly_type"] = meta.design.get("assembly", "")
        rows.append(f)
        del m
    if not rows:
        return None
    return pd.DataFrame(rows)


def rebuild(out_dir: str) -> pd.DataFrame:
    """从 out/cache/*.csv 重建 scores.csv 与 summary_by_design.csv，返回模型级表。"""
    cache_dir = os.path.join(out_dir, "cache")
    # 缓存必须是"模型级特征表"；残缺/外来文件跳过，避免一个坏文件拖垮整次重建
    need = {"job", "model", "plddt_mean"}
    frames: List[pd.DataFrame] = []
    for f in sorted(glob.glob(os.path.join(cache_dir, "*.csv"))):
        try:
            df = pd.read_csv(f)
        except Exception:                      # 半截文件不影响其余
            continue
        if not need.issubset(df.columns):
            continue
        frames.append(df)
    if not frames:
        raise RuntimeError("没有可用的预测结果")

    all_df = pd.concat(frames, ignore_index=True)
    # 设计变量始终从任务名重新解析，避免旧缓存里的列拖后腿
    from .io_af import _design_from_name
    for col, key in (("linker", "linker"), ("epitope_type", "epitope"),
                     ("assembly_type", "assembly")):
        all_df[col] = all_df["job"].map(lambda j: _design_from_name(j)[key])

    # B2：同一设计的 5 个采样模型之间，表位暴露度的波动（排布敏感度）
    if "epi_mean_exposure" in all_df.columns:
        all_df["epi_exposure_std"] = (all_df.groupby("job")["epi_mean_exposure"]
                                      .transform("std").fillna(0.0))
    else:
        all_df["epi_exposure_std"] = 0.0

    all_df = add_scores(all_df, DEFAULT_WEIGHTS)
    all_df["composite_std"] = all_df.groupby("job")["composite"].transform("std").fillna(0.0)

    # ---- 权重标定：用结构特征预测 AF 自身的 pTM/ipTM
    cal = all_df.copy()
    cal["y_target"] = np.where(cal["n_chains"] > 1, cal["iptm"], cal["ptm"])
    ok = np.all(np.isfinite(cal[CAL_FEATURES].to_numpy(float)), axis=1) & np.isfinite(cal["y_target"])
    calib: Dict[str, object] = {}
    if ok.sum() >= 12:
        X = cal.loc[ok, CAL_FEATURES].to_numpy(float)
        y = cal.loc[ok, "y_target"].to_numpy(float)
        model = RidgeCalibrator(CAL_FEATURES, lam=1.0)
        model.fit(X, y)
        cv = model.cross_validate(X, y, k=5)
        all_df.loc[ok, "cal_confidence"] = model.predict(X)
        coefs = dict(zip(CAL_FEATURES, model.coef.tolist()))
        calib = {"cv": cv, "coefficients": coefs, "n_used": int(ok.sum())}

    all_df.to_csv(os.path.join(out_dir, "scores.csv"), index=False)

    # ---- 设计层面汇总（每个任务取总分最高的模型）
    best = (all_df.sort_values("composite", ascending=False)
            .groupby("job", as_index=False).first())
    best.to_csv(os.path.join(out_dir, "summary_by_design.csv"), index=False)

    if calib:
        pd.Series({k: v for k, v in calib["cv"].items()}).to_csv(
            os.path.join(out_dir, "calibration_cv.csv"))
        pd.Series(calib["coefficients"]).to_csv(
            os.path.join(out_dir, "calibration_weights.csv"))
    return all_df


def patch_coev(root: str, out_dir: str, verbose: bool = True) -> int:
    """补算缓存里缺失的共进化列（早期版本对多聚体 a3m 匹配失败时会留空）。"""
    cache_dir = os.path.join(out_dir, "cache")
    fixed = 0
    for f in sorted(glob.glob(os.path.join(cache_dir, "*.csv"))):
        df = pd.read_csv(f)
        if "coev_precision" in df.columns and df["coev_precision"].notna().any():
            continue
        name = os.path.splitext(os.path.basename(f))[0]
        path = os.path.join(root, f"{name}.zip")
        if not os.path.exists(path):
            continue
        try:
            meta = load_job_meta(path)
            m0 = next(iter(iter_models(path, want_pae=False)))
            res = _coev_for_job(meta, m0)
        except Exception:
            continue
        if res is None:
            continue
        for k, v in res.summary().items():
            df[k] = v
        df.to_csv(f, index=False)
        fixed += 1
        if verbose:
            print(f"  补算共进化: {name} ({res.n_seqs} 条, Neff {res.n_eff:.0f}, prec {res.precision:.3f})", flush=True)
    return fixed


def run(root: str, out_dir: str, n_points: int = 32, use_cache: bool = True,
        verbose: bool = True) -> pd.DataFrame:
    os.makedirs(out_dir, exist_ok=True)
    cache_dir = os.path.join(out_dir, "cache")
    os.makedirs(cache_dir, exist_ok=True)

    paths = iter_job_paths(root)
    for k, path in enumerate(paths, 1):
        name = os.path.splitext(os.path.basename(path))[0]
        cache = os.path.join(cache_dir, f"{name}.csv")
        if use_cache and os.path.exists(cache):
            if verbose:
                print(f"[{k}/{len(paths)}] {name}: 命中缓存", flush=True)
            continue
        t = time.time()
        try:
            df = score_job(path)
        except Exception as e:                      # 0 字节 / 坏包
            print(f"[{k}/{len(paths)}] {name}: 跳过（{type(e).__name__}: {e}）", flush=True)
            continue
        if df is None:
            continue
        df.to_csv(cache, index=False)
        try:                                        # 记入增量清单，供看板扫描比对
            from . import incremental
            incremental.note(out_dir, name, path)
        except Exception:
            pass
        if verbose:
            print(f"[{k}/{len(paths)}] {name}: {len(df)} 个模型, {time.time() - t:.1f}s", flush=True)

    return rebuild(out_dir)
