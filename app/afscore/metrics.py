"""特征工程：把一条预测模型提炼成可打分的指标向量。

分组：
  置信度  pLDDT（均值/分位/核心加权）、PAE（均值、<5Å 占比、链间）
  几何    原子冲突、主链 Cα-Cα 是否合理、回转半径与经验值之比
  包埋    SASA 总量、疏水残基埋藏度
  界面    链间接触数、界面残基占比、每链对接触数
  表位    表位残基平均相对暴露度、暴露比例、连接肽暴露度（项目专用）
  共进化  MSA 深度/N_eff、MI-APC 接触精确率（作业级，一次算好复用）
"""
from __future__ import annotations

from typing import Dict, List, Optional

import numpy as np

from . import coev as coev_mod
from . import epitope as epi_mod
from . import symmetry
from .io_af import Job, Model
from .sasa import per_residue, relative_exposure, sasa
from .struct3d import (HYDROPHOBIC, backbone_geometry, clash_analysis,
                       interface_analysis, interchain_pae)


def chain_residues(model: Model, chain: str) -> np.ndarray:
    ch = np.asarray(model.struct.res_chains)
    return np.where(ch == chain)[0]


def chain_sequence(model: Model, chain: str) -> str:
    idx = chain_residues(model, chain)
    return "".join(model.struct.sequence[i] for i in idx)


def sasa_profile(model: Model, n_points: int = 32):
    """返回 (每原子面积, 每残基面积, 每残基相对暴露度)。"""
    a = sasa(model.struct, n_points=n_points)
    pr = per_residue(a, model.struct)
    rel = relative_exposure(pr, model.struct.sequence)
    return a, pr, rel


def epitope_features(model: Model, rel_sasa: np.ndarray) -> Dict[str, float]:
    """在所有链里找表位；取表位残基最多的那条链作为展示链。"""
    seq_all = np.asarray(model.struct.res_chains)
    best: Optional[Dict[str, float]] = None
    best_hits = None
    for chain in model.struct.chain_list():
        idx = chain_residues(model, chain)
        seq = "".join(model.struct.sequence[i] for i in idx)
        hits = epi_mod.locate(seq)
        if not hits:
            continue
        # 把该链的局部相对暴露度映射回全局残基号
        rel_local = rel_sasa[idx]
        f = epi_mod.exposure(rel_local, hits)
        if best is None or f["epi_n_res"] > best["epi_n_res"]:
            best = f
            best_hits = (chain, hits, seq, rel_local)
    if best is None:
        return {"epi_mean_exposure": float("nan"), "epi_exposed_frac": float("nan"),
                "epi_n_res": 0.0, "epi_plddt": float("nan"), "linker_exposure": float("nan"),
                "epi_chain": "", "epi_positions": ""}

    chain, hits, seq, rel_local = best_hits
    idx = chain_residues(model, chain)
    plddt_local = model.plddt[idx]
    epi_plddt = float(np.mean([plddt_local[h.start:min(h.end, len(plddt_local))].mean()
                               for h in hits]))
    best["epi_plddt"] = epi_plddt
    best["linker_exposure"] = epi_mod.linker_exposure(seq, rel_local)
    best["epi_chain"] = chain
    best["epi_positions"] = ";".join(f"{h.name}:{h.start + 1}-{h.end}" for h in hits)
    return best


def geometric_features(model: Model) -> Dict[str, float]:
    st = model.struct
    cl = clash_analysis(st)
    geo = backbone_geometry(st)
    rg = st.radius_of_gyration()
    n = max(st.n_residues, 1)
    rg_exp = 2.2 * (n ** 0.38)
    return {
        "clashes": cl["clashes"], "clash_per_1k": cl["clash_per_1k"], "severe": cl["severe"],
        "ca_ok_frac": geo["ca_ok_frac"],
        "rg": rg, "rg_ratio": rg / rg_exp if rg_exp else float("nan"),
    }


def confidence_features(model: Model) -> Dict[str, float]:
    p = np.asarray(model.plddt, dtype=float)
    out = {
        "plddt_mean": float(p.mean()), "plddt_std": float(p.std()),
        "frac_ge90": float((p >= 90).mean()), "frac_ge70": float((p >= 70).mean()),
        "frac_lt50": float((p < 50).mean()),
        "ptm": model.ptm, "iptm": model.iptm,
        "fraction_disordered": model.fraction_disordered,
    }
    pae = model.pae
    if pae is not None and pae.size:
        L = pae.shape[0]
        iu = np.triu_indices(L, k=1)
        v = pae[iu]
        out["pae_mean"] = float(v.mean())
        out["pae_frac_lt5"] = float((v < 5.0).mean())
        out["interchain_pae"] = interchain_pae(pae, model.token_chain)
    else:
        out["pae_mean"] = float("nan")
        out["pae_frac_lt5"] = float("nan")
        out["interchain_pae"] = float("nan")
    return out


def model_features(job: Job, model: Model, coev_result: Optional[coev_mod.CoevResult] = None
                   ) -> Dict:
    """一个模型的全部指标（含画图用的每残基数组）。"""
    feats: Dict = {"job": job.name, "model": model.index}
    feats.update(confidence_features(model))
    feats.update(geometric_features(model))

    _, per_res, rel = sasa_profile(model)
    feats["sasa_total"] = float(per_res.sum())
    feats["sasa_per_res"] = float(per_res.sum() / max(model.n_residues, 1))
    feats["burial_mean"] = float((1.0 - rel).mean())
    is_hydro = np.array([a in HYDROPHOBIC for a in model.struct.sequence])
    feats["hydro_burial"] = float((1.0 - rel[is_hydro]).mean()) if is_hydro.any() else float("nan")
    w = 0.5 + 0.5 * (1.0 - rel)
    feats["plddt_weighted"] = float((model.plddt * w).sum() / w.sum())

    feats.update(epitope_features(model, rel))
    ifaces = interface_analysis(model.struct)
    feats.update(ifaces)
    # B1：多聚体额外算"最优局部链对"界面（整体 PAE 对 20 聚体没有分辨力）
    if ifaces.get("n_chains", 1) > 1:
        feats.update(symmetry.analyse(model.struct, model.pae, model.token_chain))
    feats["expected_chains"] = float(sum(c for _, c in job.sequences)) if job.sequences else float("nan")

    if coev_result is not None:
        feats.update(coev_result.summary())
    feats["_per_res"] = {"rel_sasa": rel, "plddt": np.asarray(model.plddt)}
    return feats
