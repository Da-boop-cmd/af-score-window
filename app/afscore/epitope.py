"""表位定位与暴露度——把通用 AF 评分改造成"本项目专用"评分的关键模块。

设计目标：PepMV 衣壳表面展示 BVDV NS3 的 B 细胞表位。对这类构建体，
"模型整体置信度高"并不等于"设计成功"——真正要回答的是：
  * 表位所在的片段在颗粒表面**暴露**吗（不然抗体结合不到）？
  * 表位本身折得**可信**吗（pLDDT）？
  * 连接肽有没有被埋进衣壳里（会破坏组装 / 反而降低暴露）？

做法：在展示单体的序列里按子串精确匹配表位与连接肽，拿到残基区间，
再用结构的相对 SASA 给出暴露度。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Tuple

import numpy as np

# 4 个 NS3 B 细胞表位（按在 NS3 中的顺序）
EPITOPES: Dict[str, str] = {
    "E1": "VCKKITEHEKCHINI",
    "E2": "EYGVK",
    "E3": "FIVTGLKRMAVTVGEQA",
    "E4": "YSGEDPANLRVVTSQSPYVIVATNAIESGVLE",
}
LINKER = "GGSSGG"
P2A = "NFDLLKLAGDVESNPGP"


@dataclass
class EpitopeHit:
    name: str
    start: int          # 0-based，含
    end: int            # 0-based，不含
    seq: str


def locate(sequence: str) -> List[EpitopeHit]:
    """在给定链序列里找表位片段（可能重复出现，全部返回）。"""
    hits: List[EpitopeHit] = []
    for name, motif in EPITOPES.items():
        start = 0
        while True:
            i = sequence.find(motif, start)
            if i < 0:
                break
            hits.append(EpitopeHit(name=name, start=i, end=i + len(motif), seq=motif))
            start = i + 1
    hits.sort(key=lambda h: h.start)
    return hits


def exposure(rel_sasa: np.ndarray, hits: List[EpitopeHit]) -> Dict[str, float]:
    """表位残基的相对 SASA（0–1）汇总。"""
    if not hits:
        return {"epi_mean_exposure": float("nan"), "epi_exposed_frac": float("nan"),
                "epi_n_res": 0.0, "epi_plddt": float("nan")}
    vals = []
    for h in hits:
        vals.extend(rel_sasa[h.start:min(h.end, len(rel_sasa))].tolist())
    v = np.asarray([x for x in vals if np.isfinite(x)], dtype=float)
    return {"epi_mean_exposure": float(v.mean()) if len(v) else float("nan"),
            "epi_exposed_frac": float((v > 0.25).mean()) if len(v) else float("nan"),
            "epi_n_res": float(len(v)),
            "epi_plddt": float("nan")}


def linker_exposure(sequence: str, rel_sasa: np.ndarray) -> float:
    """连接肽（GGSSGG）平均暴露度：太低说明柔性区被压进衣壳。"""
    idx: List[int] = []
    start = 0
    while True:
        i = sequence.find(LINKER, start)
        if i < 0:
            break
        idx.extend(range(i, i + len(LINKER)))
        start = i + 1
    if not idx:
        return float("nan")
    v = np.asarray([rel_sasa[i] for i in idx if i < len(rel_sasa)], dtype=float)
    return float(v.mean()) if len(v) else float("nan")
