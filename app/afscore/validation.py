"""实验数据校链（B3）：把 ELISA / 表达量等实测值，与预测分对齐做相关性检验。

这是"计算指导实验"闭环的前置件：等师姐的 ELISA OD 出来，只要按要求填一份 CSV，
就能回答"预测分高的设计，实测信号是不是也高"。

输入约定（列名允许几种常见写法）：
    design / job / 构建体   设计名（可带 fold_ 前缀，也可是裸名）
    od / value / 信号       实测值（数值）
    group / 分组            可选，如 阳性 / 阴性 / 大肠杆菌背景
    date / 批次             可选

输出：validation.json、validation_table.csv、fig6_score_vs_od.png
"""
from __future__ import annotations

import json
import os
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

DESIGN_ALIASES = ("design", "job", "构建体", "设计", "design_id", "name")
VALUE_ALIASES = ("od", "value", "OD", "信号", "signal", "measured")
GROUP_ALIASES = ("group", "分组", "组别")


# ---------------------------------------------------------------- 统计
def rankdata(a) -> np.ndarray:
    """平均秩（处理并列），不依赖 scipy。"""
    a = np.asarray(a, dtype=float)
    n = len(a)
    order = np.argsort(a, kind="mergesort")
    ranks = np.empty(n, dtype=float)
    sorted_a = a[order]
    i = 0
    while i < n:
        j = i
        while j + 1 < n and sorted_a[j + 1] == sorted_a[i]:
            j += 1
        avg = (i + j) / 2.0 + 1.0
        ranks[order[i:j + 1]] = avg
        i = j + 1
    return ranks


def pearson(x, y) -> float:
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    if len(x) < 3:
        return float("nan")
    x = x - x.mean()
    y = y - y.mean()
    den = np.sqrt((x ** 2).sum() * (y ** 2).sum())
    return float((x * y).sum() / den) if den > 0 else float("nan")


def spearman(x, y) -> float:
    if len(x) < 3:
        return float("nan")
    return pearson(rankdata(x), rankdata(y))


# ---------------------------------------------------------------- 读写
def _pick(cols: List[str], aliases) -> Optional[str]:
    low = {c.lower(): c for c in cols}
    for a in aliases:
        if a.lower() in low:
            return low[a.lower()]
    return None


def normalize_design(name: str) -> str:
    s = str(name).strip().lower()
    if s.endswith(".zip"):
        s = s[:-4]
    if s.startswith("fold_"):
        s = s[5:]
    return s


def load_assay(path: str) -> pd.DataFrame:
    df = pd.read_csv(path)
    dcol = _pick(list(df.columns), DESIGN_ALIASES)
    vcol = _pick(list(df.columns), VALUE_ALIASES)
    if dcol is None or vcol is None:
        raise ValueError("实验数据缺少设计名列或数值列；现有列：%s" % list(df.columns))
    gcol = _pick(list(df.columns), GROUP_ALIASES)
    out = pd.DataFrame({
        "design": df[dcol].map(normalize_design),
        "value": pd.to_numeric(df[vcol], errors="coerce"),
    })
    if gcol:
        out["group"] = df[gcol].astype(str)
    return out.dropna(subset=["value"])


def load_scores(path: str) -> pd.DataFrame:
    s = pd.read_csv(path)
    best = (s.sort_values("composite", ascending=False)
            .groupby("job", as_index=False).first())
    best["design"] = best["job"].map(normalize_design)
    return best


# ---------------------------------------------------------------- 主流程
def validate(scores_csv: str, assay_csv: str, out_dir: str,
             make_fig: bool = True) -> Dict:
    os.makedirs(out_dir, exist_ok=True)
    scores = load_scores(scores_csv)
    assay = load_assay(assay_csv)

    merged = assay.merge(scores[["design", "job", "composite", "plddt_mean",
                                 "ptm", "iptm", "epi_mean_exposure", "c_interface"]],
                         on="design", how="inner")
    report: Dict = {"n_assay": int(len(assay)), "n_matched": int(len(merged)),
                    "unmatched": sorted(set(assay["design"]) - set(scores["design"]))}
    if len(merged) >= 3:
        report["spearman"] = spearman(merged["composite"], merged["value"])
        report["pearson"] = pearson(merged["composite"], merged["value"])
        report["spearman_epitope"] = spearman(merged["epi_mean_exposure"].fillna(0), merged["value"]) \
            if merged["epi_mean_exposure"].notna().any() else float("nan")
    if "group" in merged.columns and len(merged):
        g = (merged.groupby("group")
             .agg(n=("value", "size"), od_mean=("value", "mean"),
                  score_mean=("composite", "mean"))
             .reset_index())
        report["by_group"] = g.to_dict(orient="records")
        g.to_csv(os.path.join(out_dir, "validation_by_group.csv"), index=False)

    merged.to_csv(os.path.join(out_dir, "validation_table.csv"), index=False)
    with open(os.path.join(out_dir, "validation.json"), "w", encoding="utf-8") as fh:
        json.dump(report, fh, ensure_ascii=False, indent=1)

    if make_fig and len(merged) >= 2:
        from . import viz
        report["figure"] = viz.scatter_assay(
            merged["composite"].to_numpy(float), merged["value"].to_numpy(float),
            merged["design"].tolist(), os.path.join(out_dir, "fig6_score_vs_od.png"),
            rho=report.get("spearman", float("nan")))
    return report
