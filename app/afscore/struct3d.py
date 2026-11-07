"""结构对象与几何量：链、接触、冲突、回转半径、界面分析。

只依赖 numpy。原子按"重原子"处理（AF3 输出不含氢）。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Tuple

import numpy as np

VDW_RADII: Dict[str, float] = {
    "H": 1.20, "C": 1.70, "N": 1.55, "O": 1.52, "S": 1.80,
    "P": 1.80, "SE": 1.90, "F": 1.47, "CL": 1.75, "BR": 1.85,
    "I": 1.98, "B": 1.92, "SI": 2.10, "FE": 2.00, "ZN": 1.39,
    "MG": 1.73, "CA": 2.31, "NA": 2.27, "K": 2.75, "MN": 1.79,
    "CU": 1.40, "CO": 1.35, "NI": 1.63,
}

THREE_TO_ONE = {
    "ALA": "A", "ARG": "R", "ASN": "N", "ASP": "D", "CYS": "C",
    "GLN": "Q", "GLU": "E", "GLY": "G", "HIS": "H", "ILE": "I",
    "LEU": "L", "LYS": "K", "MET": "M", "PHE": "F", "PRO": "P",
    "SER": "S", "THR": "T", "TRP": "W", "TYR": "Y", "VAL": "V",
    "MSE": "M", "SEC": "U", "PYL": "O", "UNK": "X",
}

HYDROPHOBIC = set("AVILMFWYC")

# Tien et al. 2013 的理论最大 ASA（Gly-X-Gly），用于把 SASA 归一化成"相对暴露度"
MAX_ASA = {
    "A": 129, "R": 274, "N": 195, "D": 193, "C": 167, "Q": 225, "E": 223,
    "G": 104, "H": 224, "I": 197, "L": 201, "K": 236, "M": 224, "F": 240,
    "P": 159, "S": 155, "T": 172, "W": 285, "Y": 263, "V": 174, "X": 200,
}


@dataclass
class Structure:
    xyz: np.ndarray
    element: np.ndarray
    atom_name: np.ndarray
    res_name: np.ndarray
    chain: np.ndarray
    res_index: np.ndarray          # 全局连续残基号
    res_seq: np.ndarray            # 文件内作者编号
    bfactor: np.ndarray
    hetero: np.ndarray
    res_names: List[str] = field(default_factory=list)
    res_chains: List[str] = field(default_factory=list)

    @property
    def n_atoms(self) -> int:
        return int(self.xyz.shape[0])

    @property
    def n_residues(self) -> int:
        return len(self.res_names)

    @property
    def sequence(self) -> str:
        return "".join(THREE_TO_ONE.get(r, "X") for r in self.res_names)

    def ca_idx(self) -> np.ndarray:
        out = -np.ones(self.n_residues, dtype=np.int32)
        m = self.atom_name == "CA"
        out[self.res_index[m]] = np.where(m)[0]
        return out

    def ca_coords(self) -> np.ndarray:
        idx = self.ca_idx()
        return self.xyz[idx[idx >= 0]]

    def plddt_per_residue(self) -> np.ndarray:
        out = np.zeros(self.n_residues, dtype=np.float64)
        np.add.at(out, self.res_index, self.bfactor)
        cnt = np.bincount(self.res_index, minlength=self.n_residues).astype(float)
        cnt[cnt == 0] = 1.0
        return out / cnt

    def radius_of_gyration(self) -> float:
        ca = self.ca_coords()
        if len(ca) < 2:
            return float("nan")
        d = ca - ca.mean(axis=0)
        return float(np.sqrt((d ** 2).sum(axis=1).mean()))

    def chain_list(self) -> List[str]:
        seen, out = set(), []
        for c in self.res_chains:
            if c not in seen:
                seen.add(c)
                out.append(c)
        return out

    def chain_of_residue(self) -> np.ndarray:
        return np.asarray(self.res_chains)

    def atom_radii(self) -> np.ndarray:
        return np.array([VDW_RADII.get(str(e).upper(), 1.70) for e in self.element])


def build_structure(xyz, element, atom_name, res_name, chain, res_seq, bfactor, hetero) -> Structure:
    res_key: Dict[Tuple[str, int], int] = {}
    res_index = np.empty(len(xyz), dtype=np.int32)
    res_names: List[str] = []
    res_chains: List[str] = []
    for i in range(len(xyz)):
        key = (str(chain[i]), int(res_seq[i]))
        if key not in res_key:
            res_key[key] = len(res_key)
            res_names.append(str(res_name[i]))
            res_chains.append(str(chain[i]))
        res_index[i] = res_key[key]
    return Structure(
        xyz=np.asarray(xyz, dtype=np.float64), element=np.asarray(element, dtype="<U2"),
        atom_name=np.asarray(atom_name, dtype="<U4"), res_name=np.asarray(res_name, dtype="<U3"),
        chain=np.asarray(chain, dtype="<U2"), res_index=res_index,
        res_seq=np.asarray(res_seq, dtype=np.int32), bfactor=np.asarray(bfactor, dtype=np.float64),
        hetero=np.asarray(hetero, dtype=bool), res_names=res_names, res_chains=res_chains,
    )


# ---------------------------------------------------------------- 邻域 / 几何
def neighbor_pairs(xyz: np.ndarray, cutoff: float, res_index: np.ndarray,
                   min_res_sep: int = 0) -> np.ndarray:
    """格子哈希找距离 < cutoff 的原子对，可要求 |Δres| ≥ min_res_sep。"""
    n = len(xyz)
    if n == 0:
        return np.zeros((0, 2), dtype=np.int64)
    cell = max(cutoff, 1e-3)
    keys = np.floor(xyz / cell).astype(np.int64)
    buckets: Dict[Tuple[int, int, int], List[int]] = {}
    for i in range(n):
        buckets.setdefault((int(keys[i, 0]), int(keys[i, 1]), int(keys[i, 2])), []).append(i)

    out: List[Tuple[int, int]] = []
    for (cx, cy, cz), members in buckets.items():
        cand: List[int] = []
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for dz in (-1, 0, 1):
                    cand.extend(buckets.get((cx + dx, cy + dy, cz + dz), ()))
        if not cand:
            continue
        carr = np.asarray(cand, dtype=np.int64)
        for a in members:
            d = np.linalg.norm(xyz[carr] - xyz[a], axis=1)
            near = carr[(d < cutoff) & (carr > a)]
            for b in near:
                if abs(int(res_index[a]) - int(res_index[b])) >= min_res_sep:
                    out.append((a, int(b)))
    return np.asarray(out, dtype=np.int64) if out else np.zeros((0, 2), dtype=np.int64)


def clash_analysis(struct: Structure, tolerance: float = 0.5) -> Dict[str, float]:
    """原子级冲突：只统计 |Δres|≥2 的原子对（排除 1-2/1-3/1-4 键连）。

    判据 d < r_i + r_j - 0.5 Å；另给出物理上不可能的严重重叠数。
    """
    radii = struct.atom_radii()
    pairs = neighbor_pairs(struct.xyz, float(2 * radii.max() + 1.0), struct.res_index, min_res_sep=2)
    if len(pairs) == 0:
        return {"clashes": 0.0, "clash_per_1k": 0.0, "severe": 0.0}
    a, b = pairs[:, 0], pairs[:, 1]
    rsum = radii[a] + radii[b]
    d = np.linalg.norm(struct.xyz[a] - struct.xyz[b], axis=1)
    n_clash = int((d < rsum - tolerance).sum())
    n_sev = int((d < 0.85 * rsum).sum())
    return {"clashes": float(n_clash),
            "clash_per_1k": 1000.0 * n_clash / max(struct.n_atoms, 1),
            "severe": float(n_sev)}


def backbone_geometry(struct: Structure) -> Dict[str, float]:
    ca = struct.ca_idx()
    good = ca[ca >= 0]
    if len(good) < 3:
        return {"ca_ok_frac": 0.0, "rg_ratio": float("nan")}
    p = struct.xyz[good]
    d = np.linalg.norm(np.diff(p, axis=0), axis=1)
    d = d[d < 6.0]
    ok = float(np.mean((d > 3.6) & (d < 4.0))) if len(d) else 0.0
    return {"ca_ok_frac": ok}


def contact_map(ca: np.ndarray, cutoff: float = 8.0) -> np.ndarray:
    if len(ca) == 0:
        return np.zeros((0, 0), dtype=bool)
    d = np.linalg.norm(ca[:, None, :] - ca[None, :, :], axis=-1)
    return d < cutoff


def slice_chains(struct: Structure, chains) -> Structure:
    """取若干条链组成子结构（残基号重新连续化）。"""
    keep = np.isin(struct.chain, list(chains))
    if not keep.any():
        raise ValueError("没有选中任何链")
    res_old = struct.res_index[keep]
    uniq = sorted(set(int(r) for r in res_old))
    remap = {old: new for new, old in enumerate(uniq)}
    res_new = np.array([remap[int(r)] for r in res_old], dtype=np.int32)
    return Structure(
        xyz=struct.xyz[keep], element=struct.element[keep],
        atom_name=struct.atom_name[keep], res_name=struct.res_name[keep],
        chain=struct.chain[keep], res_index=res_new,
        res_seq=struct.res_seq[keep], bfactor=struct.bfactor[keep],
        hetero=struct.hetero[keep],
        res_names=[struct.res_names[r] for r in uniq],
        res_chains=[struct.res_chains[r] for r in uniq],
    )


def interface_analysis(struct: Structure, cutoff: float = 8.0) -> Dict[str, float]:
    """链间界面：Cα 接触数、每个链对的平均接触、界面残基占比。"""
    chains = struct.chain_of_residue()
    uniq = struct.chain_list()
    if len(uniq) < 2:
        return {"n_chains": float(len(uniq)), "inter_contacts": 0.0,
                "inter_contacts_per_pair": 0.0, "inter_residue_frac": 0.0,
                "n_pairs": 0.0}
    ca_idx = struct.ca_idx()
    ca = struct.xyz[[i for i in ca_idx if i >= 0]]
    ch = chains[[i for i in np.where(ca_idx >= 0)[0]]]
    d = np.linalg.norm(ca[:, None, :] - ca[None, :, :], axis=-1)
    cm = d < cutoff
    diff = ch[:, None] != ch[None, :]
    np.fill_diagonal(cm, False)
    inter = cm & diff
    n_inter = float(inter.sum() / 2)
    n_pairs = len(uniq) * (len(uniq) - 1) / 2
    involved = np.where(inter.any(axis=1))[0]
    return {"n_chains": float(len(uniq)),
            "inter_contacts": n_inter,
            "inter_contacts_per_pair": n_inter / max(n_pairs, 1),
            "inter_residue_frac": float(len(involved) / max(len(ch), 1)),
            "n_pairs": float(n_pairs)}


def interchain_pae(pae: np.ndarray, token_chain: np.ndarray) -> float:
    """链间平均 PAE（Å）：衡量相对取向的不确定度。"""
    if pae is None or token_chain is None or len(token_chain) != pae.shape[0]:
        return float("nan")
    ch = np.asarray(token_chain)
    diff = ch[:, None] != ch[None, :]
    if not diff.any():
        return float("nan")
    return float(pae[diff].mean())
