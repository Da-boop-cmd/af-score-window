"""对称感知的界面评估（B1）。

问题：20–21 聚体是"自由组装"预测，整体链间 PAE 常到 30 Å（等于没有取向信息），
拿它当界面分等于给所有设计打同一个分。真正有信息量的是**局部链对**：
某两条链到底贴不贴得上、取向是否确定。

做法：枚举所有链对，用 Cα 接触数 + 该链对的 PAE 子矩阵给每一对打分，
再取"接触最多的一对"作为这个模型的界面质量代表（最优局部界面）。
这样既绕开整体排布的任意性，又能回答"这个衣壳蛋白能不能成核"。
"""
from __future__ import annotations

from typing import Dict, List, Optional, Tuple

import numpy as np

from .struct3d import Structure


def _chain_ca(struct: Structure) -> Dict[str, np.ndarray]:
    idx = struct.ca_idx()
    keep = idx >= 0
    ch = np.asarray(struct.res_chains)[keep]
    xyz = struct.xyz[idx[keep]]
    return {c: xyz[ch == c] for c in struct.chain_list()}


def _token_index(token_chain) -> Dict[str, np.ndarray]:
    ch = np.asarray(token_chain)
    return {c: np.where(ch == c)[0] for c in sorted(set(ch.tolist()))}


def analyse(struct: Structure, pae: Optional[np.ndarray] = None,
            token_chain=None, cutoff: float = 8.0) -> Dict[str, float]:
    """逐链对统计，返回最优局部界面的指标。单体返回空 dict。"""
    chains = struct.chain_list()
    if len(chains) < 2:
        return {}

    ca = _chain_ca(struct)
    tidx = _token_index(token_chain) if (pae is not None and token_chain is not None) else {}

    pairs: List[Tuple[int, float, str]] = []      # (接触数, 链对 PAE, 名字)
    for i in range(len(chains)):
        for j in range(i + 1, len(chains)):
            a, b = chains[i], chains[j]
            if a not in ca or b not in ca or len(ca[a]) == 0 or len(ca[b]) == 0:
                continue
            d = np.linalg.norm(ca[a][:, None, :] - ca[b][None, :, :], axis=-1)
            n = int((d < cutoff).sum())
            if n == 0:
                continue
            p = float("nan")
            if tidx and a in tidx and b in tidx:
                sub = pae[np.ix_(tidx[a], tidx[b])]
                p = float(np.nanmean(sub))
            pairs.append((n, p, a + "-" + b))

    if not pairs:
        return {"iface_n_pairs": 0.0, "iface_best_contacts": 0.0,
                "iface_best_pae": float("nan"), "iface_contacts_median": 0.0,
                "iface_score": 0.0, "iface_best_pair": ""}

    pairs.sort(key=lambda x: x[0], reverse=True)
    best_n, best_p, best_name = pairs[0]
    med = float(np.median([x[0] for x in pairs]))

    # 局部界面得分：接触数（60 满标）+ 该链对 PAE（20 Å 衰减）
    contact_term = min(best_n / 60.0, 1.0)
    if np.isfinite(best_p):
        score = 0.5 * float(np.exp(-best_p / 20.0)) + 0.5 * contact_term
    else:
        score = contact_term

    return {"iface_n_pairs": float(len(pairs)),
            "iface_best_contacts": float(best_n),
            "iface_best_pae": best_p,
            "iface_contacts_median": med,
            "iface_score": round(float(score), 6),
            "iface_best_pair": best_name}
