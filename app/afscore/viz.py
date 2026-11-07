"""可视化：柱状图、分项热图、Pareto 散点、残基轨迹、PAE 热图。

配色沿用 AlphaFold 的 pLDDT 分级色，便于和官方图对照：
    ≥90 深蓝 / 70–90 浅蓝 / 50–70 黄 / <50 橙
"""
from __future__ import annotations

import os
from typing import List, Optional, Sequence

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib import font_manager
from matplotlib.colors import LinearSegmentedColormap

AF_COLORS = ["#FF7D45", "#FFDB13", "#65CBF3", "#0053D6"]
GRADE_COLOR = {"A 优秀": "#0053D6", "B 良好": "#65CBF3", "C 中等": "#FFDB13",
               "D 偏弱": "#FF9D5C", "E 差": "#FF7D45", "NA": "#BFBFBF"}


def _setup_font() -> None:
    names = {f.name for f in font_manager.fontManager.ttflist}
    for cand in ("Microsoft YaHei", "SimHei", "Noto Sans CJK SC", "DejaVu Sans"):
        if cand in names:
            plt.rcParams["font.sans-serif"] = [cand]
            break
    plt.rcParams["axes.unicode_minus"] = False
    plt.rcParams["figure.dpi"] = 130
    plt.rcParams["savefig.dpi"] = 200
    plt.rcParams["axes.edgecolor"] = "#444444"


def short_name(job: str) -> str:
    return job.replace("fold_", "")


# ---------------------------------------------------------------- 柱状图
def bar_scores(df: pd.DataFrame, path: str, top: int = 20,
               value_col: str = "composite") -> str:
    _setup_font()
    # 一个设计有 5 个采样模型：只取该设计的最优模型，避免同一名字重复出现
    d = (df.dropna(subset=[value_col])
         .sort_values(value_col, ascending=False)
         .groupby("job", as_index=False).first()
         .sort_values(value_col, ascending=False).head(top))
    labels = [short_name(j) for j in d["job"]]
    vals = d[value_col].to_numpy()
    colors = [GRADE_COLOR.get(g, "#BFBFBF") for g in d["grade"]]

    fig, ax = plt.subplots(figsize=(8.2, max(3.2, 0.34 * len(d) + 1.2)))
    y = np.arange(len(d))[::-1]
    ax.barh(y, vals, color=colors, height=0.72, edgecolor="white")
    ax.set_yticks(y)
    ax.set_yticklabels(labels, fontsize=8)
    ax.set_xlabel("综合评分（0–100）", fontsize=9)
    ax.set_xlim(0, max(100, vals.max() * 1.12))
    for yi, v in zip(y, vals):
        ax.text(v + 1, yi, f"{v:.1f}", va="center", fontsize=8, color="#333333")
    ax.set_title(f"AlphaFold3 预测评分（每个设计取最优模型，Top {len(d)}）", fontsize=11)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    ax.grid(axis="x", color="#E5E5E5", lw=0.6)
    ax.set_axisbelow(True)
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)
    return path


# ---------------------------------------------------------------- 分项热图
def heatmap_components(df: pd.DataFrame, path: str, cols: Sequence[str],
                       labels: Optional[Sequence[str]] = None) -> str:
    _setup_font()
    # 每个设计只保留最优模型，否则 175 条会把图拉成一米长
    d = (df.sort_values("composite", ascending=False)
         .groupby("job", as_index=False).first()
         .sort_values("composite", ascending=False))
    mat = d[list(cols)].to_numpy(dtype=float)
    cmap = LinearSegmentedColormap.from_list("af", ["#F7F7F7", "#65CBF3", "#0053D6"])
    cmap.set_bad("#D9D9D9")

    fig, ax = plt.subplots(figsize=(0.62 * len(cols) + 4.6, 0.30 * len(d) + 1.4))
    im = ax.imshow(np.ma.masked_invalid(mat), aspect="auto", cmap=cmap, vmin=0, vmax=1)
    ax.set_xticks(range(len(cols)))
    ax.set_xticklabels(list(labels or cols), rotation=38, ha="right", fontsize=8)
    ax.set_yticks(range(len(d)))
    ax.set_yticklabels([short_name(j) for j in d["job"]], fontsize=7)
    for i in range(mat.shape[0]):
        for j in range(mat.shape[1]):
            v = mat[i, j]
            if np.isfinite(v):
                ax.text(j, i, f"{v:.2f}", ha="center", va="center", fontsize=5.6,
                        color="white" if v > 0.55 else "#333333")
    cb = fig.colorbar(im, ax=ax, fraction=0.025, pad=0.015)
    cb.set_label("归一化分项得分（0–1）", fontsize=8)
    ax.set_title("分项得分热图（按综合分排序）", fontsize=11)
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)
    return path


# ---------------------------------------------------------------- Pareto 散点
def scatter_pareto(df: pd.DataFrame, path: str, x: str = "epi_mean_exposure",
                   y: str = "c_assembly", rank_col: str = "pareto_rank_epi",
                   n_label: int = 4) -> str:
    _setup_font()
    d = df.dropna(subset=[x, y]).copy()
    if d.empty:
        return ""
    fig, ax = plt.subplots(figsize=(6.8, 5.2))
    multi = d[d["n_chains"] > 1]
    mono = d[d["n_chains"] <= 1]
    sc = ax.scatter(mono[x], mono[y], c=mono["composite"], cmap="viridis", s=38,
                    marker="o", edgecolor="white", linewidth=0.6, zorder=3, label="单体")
    ax.scatter(multi[x], multi[y], c=multi["composite"], cmap="viridis", s=44,
               marker="s", edgecolor="white", linewidth=0.6, zorder=3, label="多聚体")

    front = d[d[rank_col] == 0] if rank_col in d.columns else d.iloc[0:0]
    ax.scatter(front[x], front[y], s=120, facecolor="none", edgecolor="#D62728",
               linewidth=1.2, zorder=4)
    # 只标注综合分最高的几个前沿点，标在点的左上侧，避免压到星团
    for _, r in front.sort_values("composite", ascending=False).head(n_label).iterrows():
        ax.annotate(short_name(r["job"]), (r[x], r[y]), textcoords="offset points",
                    xytext=(-10, 10), ha="right", fontsize=6.5, color="#7F1D1D",
                    arrowprops=dict(arrowstyle="-", lw=0.5, color="#D62728"))
    ax.set_xlim(d[x].min() - 0.02, d[x].max() + 0.06)

    cb = fig.colorbar(sc, ax=ax, fraction=0.04, pad=0.02)
    cb.set_label("综合评分", fontsize=8)
    ax.set_xlabel("表位平均相对暴露度（SASA/理论最大）", fontsize=9)
    ax.set_ylabel("组装置信度（多聚体取 max(pTM, ipTM)）", fontsize=9)
    ax.set_title("表位暴露 vs 组装稳定性（红圈为 Pareto 第一前沿）", fontsize=11)
    ax.grid(color="#EEEEEE", lw=0.6)
    ax.legend(fontsize=8, loc="lower left", frameon=False)
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)
    return path


# ---------------------------------------------------------------- 残基轨迹
def residue_track(plddt: np.ndarray, rel_sasa: np.ndarray, path: str,
                  title: str = "", epitope_ranges: Optional[List[tuple]] = None,
                  epitope_names: Optional[List[str]] = None) -> str:
    _setup_font()
    n = len(plddt)
    x = np.arange(1, n + 1)
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(8.4, 4.4), sharex=True,
                                   gridspec_kw={"height_ratios": [1, 1]})

    band = np.where(plddt >= 90, 3, np.where(plddt >= 70, 2, np.where(plddt >= 50, 1, 0)))
    colors = np.array(AF_COLORS)[band]
    ax1.bar(x, plddt, color=colors, width=1.0, linewidth=0)
    ax1.set_ylim(0, 100)
    ax1.set_ylabel("pLDDT", fontsize=9)
    ax1.axhline(70, color="#999999", lw=0.7, ls="--")
    ax1.set_title(title, fontsize=11)

    ax2.fill_between(x, rel_sasa, color="#2B6CB0", alpha=0.35)
    ax2.plot(x, rel_sasa, color="#2B6CB0", lw=0.8)
    ax2.set_ylabel("相对 SASA", fontsize=9)
    ax2.set_xlabel("残基序号", fontsize=9)
    ax2.set_ylim(0, 1.05)

    if epitope_ranges:
        for (s, e), nm in zip(epitope_ranges, epitope_names or [""] * len(epitope_ranges)):
            for ax in (ax1, ax2):
                ax.axvspan(s, e, color="#D62728", alpha=0.12, lw=0)
            ax2.annotate(nm, ((s + e) / 2, 0.95), ha="center", fontsize=7.5, color="#D62728")
    for ax in (ax1, ax2):
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)
        ax.grid(axis="y", color="#F0F0F0", lw=0.6)
        ax.set_axisbelow(True)
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)
    return path


# ---------------------------------------------------------------- PAE 热图
def pae_heatmap(pae: np.ndarray, path: str, title: str = "") -> str:
    _setup_font()
    fig, ax = plt.subplots(figsize=(5.6, 4.8))
    im = ax.imshow(pae, cmap="Greens", vmin=0, vmax=min(30, float(np.nanmax(pae))))
    cb = fig.colorbar(im, ax=ax, fraction=0.046, pad=0.02)
    cb.set_label("PAE (Å)", fontsize=8)
    ax.set_xlabel("token (残基)", fontsize=8)
    ax.set_ylabel("token (残基)", fontsize=8)
    ax.set_title(title, fontsize=10)
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)
    return path


# ---------------------------------------------------------------- 预测分 vs 实测
def scatter_assay(scores, values, labels, path: str, rho: float = float("nan"),
                  title: str = "预测分 vs 实测值") -> str:
    """B3：校链用散点图（横轴综合分、纵轴实测值，虚线为线性拟合）。"""
    _setup_font()
    x = np.asarray(scores, dtype=float)
    y = np.asarray(values, dtype=float)
    fig, ax = plt.subplots(figsize=(6.4, 4.8))
    ax.scatter(x, y, s=52, c="#0053d6", edgecolor="white", linewidth=0.7, zorder=3)
    if len(x) >= 2:
        k, b = np.polyfit(x, y, 1)
        xs = np.linspace(float(x.min()), float(x.max()), 50)
        ax.plot(xs, k * xs + b, color="#d64545", lw=1.2, ls="--", zorder=2)
    for xi, yi, lab in zip(x, y, labels):
        ax.annotate(str(lab), (xi, yi), textcoords="offset points",
                    xytext=(5, 4), fontsize=6, color="#444444")
    ax.set_xlabel("预测综合分", fontsize=9)
    ax.set_ylabel("实测值（OD 等）", fontsize=9)
    ax.set_title(title + ("（Spearman ρ = %.2f）" % rho if np.isfinite(rho) else ""),
                 fontsize=11)
    ax.grid(color="#EEEEEE", lw=0.6)
    ax.set_axisbelow(True)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)
    return path
