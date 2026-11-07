"""出图：把评分表画成 5 张图，供 CLI 与"扫描新包"共用。

fig1 排名柱状图、fig2 分项热图、fig3 Pareto 散点 —— 只依赖表格；
fig4 残基轨迹、fig5 PAE —— 需要一个具体模型，因此要能按任务名找到 zip。
"""
from __future__ import annotations

import os
from typing import Callable, Dict, Optional

import pandas as pd

from . import viz
from .epitope import locate
from .io_af import load_job
from .metrics import chain_residues, chain_sequence, sasa_profile
from .scoring import COMPONENT_LABEL, COMPONENTS


def make_figures(df: pd.DataFrame, out_dir: str,
                 job_paths: Dict[str, str] | Callable[[str], Optional[str]],
                 n_points: int = 48) -> Dict[str, str]:
    """重画 5 张图。job_paths 可以是 {任务名: zip 路径}，也可以是解析函数。

    找不到 zip 时跳过 fig4/fig5（其余三张照画），保证扫描流程不因缺包失败。
    """
    os.makedirs(out_dir, exist_ok=True)
    resolve = job_paths if callable(job_paths) else (lambda j: job_paths.get(j))
    paths: Dict[str, str] = {}

    ccols = [f"c_{c}" for c in COMPONENTS]
    paths["bar"] = viz.bar_scores(df, os.path.join(out_dir, "fig1_scores_bar.png"))
    paths["heat"] = viz.heatmap_components(
        df, os.path.join(out_dir, "fig2_components_heatmap.png"),
        ccols, [COMPONENT_LABEL[c] for c in COMPONENTS])
    if "epi_mean_exposure" in df.columns:
        paths["pareto"] = viz.scatter_pareto(df, os.path.join(out_dir, "fig3_pareto.png"))

    # 取"含表位设计里综合分最高"的模型；若该 zip 不可用则顺延到下一个
    if "epi_mean_exposure" in df.columns:
        cand = df.dropna(subset=["epi_mean_exposure"]).sort_values("composite", ascending=False)
        for _, row in cand.iterrows():
            zp = resolve(row["job"])
            if not zp or not os.path.exists(zp):
                continue
            try:
                job = load_job(zp)
                m = job.models[min(int(row["model"]), len(job.models) - 1)]
                _, _, rel = sasa_profile(m, n_points=n_points)
                ch = row["epi_chain"] if isinstance(row.get("epi_chain"), str) else "A"
                idx = chain_residues(m, ch)
                seq = chain_sequence(m, ch)
                hits = locate(seq)
                paths["track"] = viz.residue_track(
                    m.plddt[idx], rel[idx], os.path.join(out_dir, "fig4_epitope_track.png"),
                    title=f"{viz.short_name(row['job'])} · model {int(row['model'])} · 链 {ch}",
                    epitope_ranges=[(h.start + 1, h.end) for h in hits],
                    epitope_names=[h.name for h in hits])
                if m.pae is not None and m.pae.size < 4_000_000:
                    paths["pae"] = viz.pae_heatmap(
                        m.pae, os.path.join(out_dir, "fig5_pae.png"),
                        title=f"{viz.short_name(row['job'])} · model {int(row['model'])} PAE")
                break
            except Exception:
                continue
    return paths
