"""溶剂可及表面积（Shrake–Rupley 数值积分，numpy 实现）。

为什么自己写：环境里 freesasa 装不上（PyPI 无 Windows 轮子），Biopython 的
ShrakeRupley 是纯 Python 逐原子循环，20 聚体（3.7 万原子）会慢到分钟级。
这里用格子哈希 + 每原子一次向量化，36k 原子约 3–5 s。

同时提供"链隔离"模式：只在同链原子之间计算遮挡，用来求界面埋藏面积
BSA = Σ SASA(单链) − SASA(复合物)。
"""
from __future__ import annotations

from typing import Dict, Optional

import numpy as np

from .struct3d import MAX_ASA, Structure

PROBE = 1.4


def fibonacci_sphere(n: int) -> np.ndarray:
    i = np.arange(n, dtype=np.float64) + 0.5
    phi = np.arccos(1.0 - 2.0 * i / n)
    theta = np.pi * (1.0 + 5.0 ** 0.5) * i
    return np.stack([np.cos(theta) * np.sin(phi),
                     np.sin(theta) * np.sin(phi),
                     np.cos(phi)], axis=1)


def _sasa_atoms(xyz: np.ndarray, radii: np.ndarray, chain: np.ndarray,
                n_points: int, same_chain_only: bool) -> np.ndarray:
    n = len(xyz)
    R = radii + PROBE
    pts = fibonacci_sphere(n_points)
    cell = float(R.max() + 0.5)
    keys = np.floor(xyz / cell).astype(np.int64)

    buckets: Dict[tuple, list] = {}
    for i in range(n):
        buckets.setdefault((int(keys[i, 0]), int(keys[i, 1]), int(keys[i, 2])), []).append(i)

    areas = np.zeros(n, dtype=np.float64)
    for i in range(n):
        cx, cy, cz = keys[i]
        cand: list = []
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for dz in (-1, 0, 1):
                    lst = buckets.get((cx + dx, cy + dy, cz + dz))
                    if lst:
                        cand.extend(lst)
        if not cand:
            areas[i] = 4.0 * np.pi * R[i] ** 2
            continue
        carr = np.asarray(cand, dtype=np.int64)
        carr = carr[carr != i]
        if same_chain_only:
            carr = carr[chain[carr] == chain[i]]
        if len(carr) == 0:
            areas[i] = 4.0 * np.pi * R[i] ** 2
            continue
        delta = xyz[carr] - xyz[i]
        near = carr[np.linalg.norm(delta, axis=1) < R[i] + R[carr]]
        if len(near) == 0:
            areas[i] = 4.0 * np.pi * R[i] ** 2
            continue
        surf = xyz[i] + pts * R[i]
        d = np.linalg.norm(surf[:, None, :] - xyz[near][None, :, :], axis=2)
        exposed = np.all(d >= R[near][None, :], axis=1)
        areas[i] = 4.0 * np.pi * R[i] ** 2 * exposed.mean()
    return areas


def sasa(struct: Structure, n_points: int = 64, same_chain_only: bool = False
         ) -> np.ndarray:
    """每原子 SASA（Å²）。"""
    radii = struct.atom_radii()
    chain = struct.chain.astype("U2")
    return _sasa_atoms(struct.xyz, radii, chain, n_points, same_chain_only)


def per_residue(atom_areas: np.ndarray, struct: Structure) -> np.ndarray:
    return np.bincount(struct.res_index, weights=atom_areas, minlength=struct.n_residues)


def relative_exposure(per_res: np.ndarray, sequence: str) -> np.ndarray:
    """相对暴露度 = SASA / 理论最大 ASA（0–1）。"""
    max_asa = np.array([MAX_ASA.get(a, 200) for a in sequence], dtype=float)
    return np.clip(per_res / max_asa, 0.0, 1.0)


def interface_bsa(struct: Structure, n_points: int = 64) -> Dict[str, float]:
    """界面埋藏面积：复合物 SASA 与各链单独 SASA 之差。"""
    chains = struct.chain_list()
    if len(chains) < 2:
        return {"bsa": 0.0, "bsa_per_res": 0.0}
    complex_area = float(sasa(struct, n_points, same_chain_only=False).sum())
    iso = 0.0
    for c in chains:
        m = struct.chain == c
        sub = Structure(
            xyz=struct.xyz[m], element=struct.element[m], atom_name=struct.atom_name[m],
            res_name=struct.res_name[m], chain=struct.chain[m], res_index=struct.res_index[m],
            res_seq=struct.res_seq[m], bfactor=struct.bfactor[m], hetero=struct.hetero[m],
            res_names=struct.res_names, res_chains=struct.res_chains,
        )
        iso += float(_sasa_atoms(sub.xyz, sub.atom_radii(), sub.chain.astype("U2"),
                                 n_points, False).sum())
    bsa = max(iso - complex_area, 0.0)
    return {"bsa": bsa, "bsa_per_res": bsa / max(struct.n_residues, 1)}
