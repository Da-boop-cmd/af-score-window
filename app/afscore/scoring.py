"""评分核心：分项归一化 → 加权总分 → 权重标定 → Pareto 优选。

三个可交付：
  1. 专家权重加权分（0–100），分项都可追溯
  2. 岭回归标定：用 175 个模型做训练集，学习"由结构特征预测 AF 自身 pTM/ipTM"
     的线性权重，并对新预测（只有 cif、没有 pTM 时）给出校准置信度
  3. Pareto 非支配排序：多目标下不互相支配的候选集，供实验优先验证
"""
from __future__ import annotations

from typing import Dict, List, Optional, Sequence

import numpy as np
import pandas as pd

# ---------------------------------------------------------------- 分项与权重
COMPONENTS = ["plddt", "plddt_core", "conf", "pae", "assembly",
              "interface", "epitope", "packing", "geometry", "coev"]

COMPONENT_LABEL = {
    "plddt": "pLDDT 均值",
    "plddt_core": "核心加权 pLDDT",
    "conf": "高置信残基占比",
    "pae": "PAE 全局",
    "assembly": "组装置信度 (pTM/ipTM)",
    "interface": "链间界面",
    "epitope": "表位暴露度",
    "packing": "疏水核心包埋",
    "geometry": "几何合理性",
    "coev": "共进化支持",
}

# 专家权重：单体蛋白没有 interface；无表位的对照没有 epitope，按可用项归一化
DEFAULT_WEIGHTS: Dict[str, float] = {
    "plddt": 0.18, "plddt_core": 0.07, "conf": 0.07, "pae": 0.13,
    "assembly": 0.16, "interface": 0.14, "epitope": 0.12,
    "packing": 0.07, "geometry": 0.07, "coev": 0.06,
}


def _clip01(x: float) -> float:
    if x is None or not np.isfinite(x):
        return float("nan")
    return float(min(max(x, 0.0), 1.0))


def components(f: Dict) -> Dict[str, float]:
    """把原始指标归一化到 0–1（越高越好）。缺失值保留 NaN。"""
    c: Dict[str, float] = {}
    c["plddt"] = _clip01(f.get("plddt_mean", np.nan) / 100.0)
    c["plddt_core"] = _clip01(f.get("plddt_weighted", np.nan) / 100.0)
    f90, f70 = f.get("frac_ge90", np.nan), f.get("frac_ge70", np.nan)
    c["conf"] = _clip01(0.5 * f90 + 0.5 * f70) if np.isfinite(f90) and np.isfinite(f70) else float("nan")

    pae = f.get("pae_mean", np.nan)
    c["pae"] = _clip01(np.exp(-pae / 8.0)) if np.isfinite(pae) else float("nan")

    multimer = f.get("n_chains", 1) and f.get("n_chains", 1) > 1
    if multimer:
        ptm, iptm = f.get("ptm", np.nan), f.get("iptm", np.nan)
        vals = [v for v in (ptm, iptm) if np.isfinite(v)]
        c["assembly"] = _clip01(max(vals)) if vals else float("nan")
    else:
        c["assembly"] = _clip01(f.get("ptm", np.nan))

    if multimer:
        # B1：优先用"最优局部链对"的界面分（整体链间 PAE 对 20 聚体没有分辨力）
        local = f.get("iface_score", np.nan)
        if np.isfinite(local):
            c["interface"] = _clip01(local)
        else:
            ipae = f.get("interchain_pae", np.nan)
            cpp = f.get("inter_contacts_per_pair", np.nan)
            a = np.exp(-ipae / 20.0) if np.isfinite(ipae) else np.nan
            b = _clip01(cpp / 60.0) if np.isfinite(cpp) else np.nan
            if np.isfinite(a) and np.isfinite(b):
                c["interface"] = _clip01(0.5 * a + 0.5 * b)
            else:
                c["interface"] = float("nan")
    else:
        c["interface"] = float("nan")

    # B2：表位暴露度按"跨模型波动"打折——排布不同导致暴露度飘，分数就不可信
    epi = f.get("epi_mean_exposure", np.nan)
    if np.isfinite(epi):
        base = _clip01((epi - 0.20) / 0.60)
        std = f.get("epi_exposure_std", np.nan)
        if np.isfinite(std):
            base *= (1.0 - 0.5 * min(std / 0.15, 1.0))
        c["epitope"] = _clip01(base)
    else:
        c["epitope"] = float("nan")

    hb = f.get("hydro_burial", np.nan)
    c["packing"] = _clip01((hb - 0.50) / 0.30) if np.isfinite(hb) else float("nan")

    clash = f.get("clash_per_1k", np.nan)
    ca_ok = f.get("ca_ok_frac", np.nan)
    if np.isfinite(clash):
        g = 1.0 / (1.0 + clash / 2.0)
        if np.isfinite(ca_ok):
            g *= min(ca_ok, 1.0)
        c["geometry"] = _clip01(g)
    else:
        c["geometry"] = float("nan")

    prec = f.get("coev_precision", np.nan)
    c["coev"] = _clip01(prec / 0.25) if np.isfinite(prec) else float("nan")
    return c


def composite(scores: Dict[str, float], weights: Optional[Dict[str, float]] = None
              ) -> tuple[float, Dict[str, float], float]:
    """加权总分。返回 (0–100 分, 实际使用的权重, 权重覆盖率)。"""
    w = dict(weights or DEFAULT_WEIGHTS)
    avail = {k: w[k] for k in COMPONENTS if k in w and np.isfinite(scores.get(k, np.nan))}
    if not avail:
        return float("nan"), {}, 0.0
    total_w = sum(w.values())
    used_w = sum(avail.values())
    s = sum(avail[k] * scores[k] for k in avail) / used_w
    total = sum(avail[k] * scores[k] for k in avail)
    return 100.0 * float(total / used_w), avail, used_w / total_w


def grade(score: float) -> str:
    if not np.isfinite(score):
        return "NA"
    if score >= 85:
        return "A 优秀"
    if score >= 70:
        return "B 良好"
    if score >= 55:
        return "C 中等"
    if score >= 40:
        return "D 偏弱"
    return "E 差"


# ---------------------------------------------------------------- 权重标定
class RidgeCalibrator:
    """标准化 + 岭回归；目标为 AF 自身的 pTM/ipTM，特征只用结构与 pLDDT 派生量。

    用途：当拿到一批只有坐标、没有 pTM 的输出时（例如只公开了 cif），
    仍能给出一个"校准过的置信度"。也用来检验专家权重是否合理。
    """

    def __init__(self, feature_names: Sequence[str], lam: float = 1.0):
        self.feature_names = list(feature_names)
        self.lam = lam
        self.mu: Optional[np.ndarray] = None
        self.sd: Optional[np.ndarray] = None
        self.coef: Optional[np.ndarray] = None
        self.b0 = 0.0
        self.r2 = float("nan")
        self.mae = float("nan")

    def _design(self, X: np.ndarray) -> np.ndarray:
        return (X - self.mu) / self.sd

    def fit(self, X: np.ndarray, y: np.ndarray) -> "RidgeCalibrator":
        X = np.asarray(X, dtype=float)
        y = np.asarray(y, dtype=float)
        self.mu = np.nanmean(X, axis=0)
        self.sd = np.nanstd(X, axis=0)
        self.sd[self.sd < 1e-9] = 1.0
        Z = self._design(X)
        Z = np.nan_to_num(Z, nan=0.0)
        n, d = Z.shape
        A = Z.T @ Z + self.lam * np.eye(d)
        self.coef = np.linalg.solve(A, Z.T @ y)
        self.b0 = float(y.mean())
        return self

    def predict(self, X: np.ndarray) -> np.ndarray:
        Z = np.nan_to_num(self._design(np.asarray(X, dtype=float)), nan=0.0)
        return self.b0 + Z @ self.coef

    def cross_validate(self, X: np.ndarray, y: np.ndarray, k: int = 5) -> Dict[str, float]:
        X = np.asarray(X, dtype=float)
        y = np.asarray(y, dtype=float)
        idx = np.arange(len(y))
        rng = np.random.default_rng(0)
        rng.shuffle(idx)
        folds = np.array_split(idx, k)
        preds = np.full(len(y), np.nan)
        for i in range(k):
            test = folds[i]
            train = np.concatenate([folds[j] for j in range(k) if j != i])
            m = RidgeCalibrator(self.feature_names, self.lam).fit(X[train], y[train])
            preds[test] = m.predict(X[test])
        ok = np.isfinite(preds) & np.isfinite(y)
        ss_res = float(((y[ok] - preds[ok]) ** 2).sum())
        ss_tot = float(((y[ok] - y[ok].mean()) ** 2).sum())
        self.r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else float("nan")
        self.mae = float(np.abs(y[ok] - preds[ok]).mean())
        return {"r2": self.r2, "mae": self.mae, "n": int(ok.sum())}


# ---------------------------------------------------------------- Pareto
def pareto_ranks(objectives: np.ndarray) -> np.ndarray:
    """非支配排序：返回每个个体的前沿层级（0 = 第一前沿）。全部为"越大越好"。"""
    n = len(objectives)
    ranks = np.full(n, -1, dtype=int)
    remaining = set(range(n))
    level = 0
    while remaining:
        front = []
        for i in remaining:
            dominated = False
            for j in remaining:
                if i == j:
                    continue
                ge = np.all(objectives[j] >= objectives[i])
                gt = np.any(objectives[j] > objectives[i])
                if ge and gt:
                    dominated = True
                    break
            if not dominated:
                front.append(i)
        for i in front:
            ranks[i] = level
        remaining -= set(front)
        level += 1
    return ranks


def add_scores(df: pd.DataFrame, weights: Optional[Dict[str, float]] = None,
               pareto_objectives: Sequence[str] = ("composite", "c_assembly", "c_geometry"),
               epi_objectives: Sequence[str] = ("composite", "c_epitope", "c_assembly", "c_geometry")
               ) -> pd.DataFrame:
    """给特征表补上分项分、总分、等级、Pareto 前沿。

    两套前沿：
      pareto_rank      —— 全部模型，目标为 综合分 / 组装置信度 / 几何合理性
      pareto_rank_epi  —— 仅含表位的设计，额外加"表位暴露度"
    目标均为越大越好，缺失值不参与排序（rank = -1）。
    """
    comp_rows = []
    for _, row in df.iterrows():
        f = row.to_dict()
        c = components(f)
        total, used, cov = composite(c, weights)
        comp_rows.append({"composite": total, "weight_coverage": cov, "grade": grade(total),
                          **{f"c_{k}": c[k] for k in COMPONENTS}})
    comp = pd.DataFrame(comp_rows, index=df.index)
    out = pd.concat([df, comp], axis=1)

    def _ranks(frame: pd.DataFrame, cols: Sequence[str]) -> np.ndarray:
        cols = [c for c in cols if c in frame.columns]
        mat = frame[cols].to_numpy(dtype=float)
        ok = np.all(np.isfinite(mat), axis=1)
        r = np.full(len(frame), -1, dtype=int)
        if ok.any():
            r[ok] = pareto_ranks(mat[ok])
        return r

    out["pareto_rank"] = _ranks(out, pareto_objectives)
    epi_rows = out["c_epitope"].notna()
    out["pareto_rank_epi"] = -1
    if epi_rows.any():
        out.loc[epi_rows, "pareto_rank_epi"] = _ranks(out[epi_rows], epi_objectives)

    # 组装体内部的前沿：单体折叠天然占优，VLP 之间的取舍要单独排
    vlp_rows = out["n_chains"] > 1
    out["pareto_rank_vlp"] = -1
    if vlp_rows.any():
        out.loc[vlp_rows, "pareto_rank_vlp"] = _ranks(
            out[vlp_rows], ("composite", "c_assembly", "c_interface"))
    return out
