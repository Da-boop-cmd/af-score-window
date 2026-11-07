"""共进化分析：从 AF3 自带的 a3m 里算互信息接触，检验结构是否"有进化支持"。

AlphaFold 并不显式算互信息：MSA 进 Evoformer（AF2）或被大幅弱化（AF3 只保留
一个轻量 MSA 模块 + Pairformer），模型在训练中用 masked MSA 学会"补偿突变"，
再由 outer-product mean 压成 pair representation，交给结构模块出坐标。

本模块反其道而行，用经典 DCA-lite 把共进化显式算出来：
  1. a3m 去插入列 → 与 query 等长的比对
  2. θ=0.8 序列重加权（近重复序列不重复计票，同时抑制系统发育噪声）
  3. 精确互信息 MI = Σ f_ab ln(f_ab / f_a f_b) + 伪计数（χ² 近似会在稀有态上爆表）
  4. APC（average product correction）去系统偏差
  5. 取 top-L 残基对当接触预测，与结构 Cα<8 Å 的真接触比对得 precision
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import numpy as np

AA = "ACDEFGHIKLMNPQRSTVWY"
CODE = {a: i for i, a in enumerate(AA)}
GAP = 20
N_AA = 20


@dataclass
class CoevResult:
    n_seqs: int = 0
    n_eff: float = 0.0
    L: int = 0
    precision: float = float("nan")
    coverage: float = float("nan")
    support: float = float("nan")
    conservation: Optional[np.ndarray] = None
    mi: Optional[np.ndarray] = None

    def summary(self) -> Dict[str, float]:
        return {"coev_n_seqs": self.n_seqs, "coev_n_eff": self.n_eff,
                "coev_precision": self.precision, "coev_coverage": self.coverage,
                "coev_support": self.support}


def parse_a3m(raw: bytes, max_seqs: int = 1500) -> Tuple[str, List[str]]:
    text = raw.decode("utf-8", "replace")
    seqs: List[str] = []
    buf: List[str] = []
    for line in text.splitlines():
        if line.startswith(">"):
            if buf:
                seqs.append("".join(buf)); buf = []
            continue
        buf.append(line)
    if buf:
        seqs.append("".join(buf))
    if not seqs:
        return "", []
    query = "".join(c for c in seqs[0].upper() if c.isalpha())
    clean: List[str] = []
    for s in seqs:
        up = "".join(c for c in s if not c.islower())
        up = "".join(c if c.isalpha() else "-" for c in up).upper()
        if len(up) == len(query):
            clean.append(up)
        if len(clean) >= max_seqs:
            break
    return query, clean


def encode(seqs: List[str]) -> np.ndarray:
    L = len(seqs[0])
    arr = np.full((len(seqs), L), GAP, dtype=np.uint8)
    for r, s in enumerate(seqs):
        arr[r] = [CODE.get(c, GAP) for c in s]
    return arr


def sequence_weights(codes: np.ndarray, identity: float = 0.8) -> Tuple[np.ndarray, float]:
    n = codes.shape[0]
    if n == 0:
        return np.zeros(0), 0.0
    centers: List[np.ndarray] = []
    assign = np.zeros(n, dtype=np.int64)
    for i in range(n):
        row = codes[i]
        if not centers:
            centers.append(row); continue
        ident = (np.stack(centers) == row).mean(axis=1)
        j = int(np.argmax(ident))
        if ident[j] >= identity:
            assign[i] = j
        else:
            centers.append(row); assign[i] = len(centers) - 1
    n_clusters = len(centers)
    counts = np.bincount(assign, minlength=n_clusters).astype(np.float64)
    return 1.0 / counts[assign], float(n_clusters)


def mi_apc(codes: np.ndarray, weights: np.ndarray, beta: float = 1.0,
           block: int = 8) -> np.ndarray:
    n, L = codes.shape
    X = np.zeros((n, L, N_AA), dtype=np.float32)
    rows, cols = np.meshgrid(np.arange(n), np.arange(L), indexing="ij")
    ok = codes != GAP
    X[rows[ok], cols[ok], codes[ok]] = 1.0

    neff = float(weights.sum())
    total = neff + beta
    cnt = (X * weights[:, None, None]).reshape(n, L * N_AA)
    na = (X.reshape(n, L * N_AA).T @ weights).reshape(L, N_AA)
    fa = (na + beta / N_AA) / total

    D = np.zeros((L, L), dtype=np.float32)
    for s in range(0, L, block):
        e = min(s + block, L)
        A = (cnt[:, s * N_AA:e * N_AA].T @ cnt).reshape(e - s, N_AA, L, N_AA)
        A = (A + beta / (N_AA * N_AA)) / total
        den = fa[s:e, :, None, None] * fa[None, None, :, :]
        D[s:e] = (A * np.log(A / den)).sum(axis=(1, 3))
    D = np.maximum(D, 0.0)
    D = 0.5 * (D + D.T)
    np.fill_diagonal(D, 0.0)
    r, c = D.mean(axis=1), D.mean(axis=0)
    D = np.maximum(D - np.outer(r, c) / (r.mean() + 1e-12), 0.0)
    np.fill_diagonal(D, 0.0)
    return D


def conservation(codes: np.ndarray) -> np.ndarray:
    n, L = codes.shape
    out = np.zeros(L)
    for i in range(L):
        col = codes[:, i]
        col = col[col != GAP]
        if len(col) < 2:
            continue
        p = np.bincount(col, minlength=N_AA + 1)[:N_AA].astype(float)
        p /= p.sum()
        p = p[p > 0]
        out[i] = max(0.0, 1.0 - float(-(p * np.log(p)).sum()) / np.log(N_AA))
    return out


def analyse(raw_a3m: bytes, ca: np.ndarray, max_seqs: int = 1200,
            min_sep: int = 5, contact_cutoff: float = 8.0,
            seg_len: Optional[int] = None) -> CoevResult:
    """对一条链的 a3m 与其 Cα 坐标做共进化分析。

    seg_len：多聚体任务的 a3m 是各链 MSA 的列拼接（query 长 = Σ链长），
    只取前 seg_len 列即第一条链的比对。
    """
    query, seqs = parse_a3m(raw_a3m, max_seqs=max_seqs)
    if seg_len and query and len(query) > seg_len:
        query = query[:seg_len]
        seqs = [s[:seg_len] for s in seqs]
    if len(seqs) < 5:
        return CoevResult(n_seqs=len(seqs), L=len(query))
    codes = encode(seqs)
    w, neff = sequence_weights(codes)
    mi = mi_apc(codes, w)
    cons = conservation(codes)

    L = min(len(query), len(ca), mi.shape[0])
    mi_sq = mi[:L, :L]
    d = np.linalg.norm(ca[:L, None, :] - ca[None, :L, :], axis=-1)
    true = d < contact_cutoff
    iu = np.triu_indices(L, k=min_sep)
    scores, truth = mi_sq[iu], true[iu]
    k = min(L, len(scores))
    top = np.argsort(scores)[::-1][:k]
    precision = float(truth[top].mean())
    order = np.argsort(scores)[::-1]
    coverage = float(truth[order[:2 * k]].sum() / max(truth.sum(), 1))
    pos = scores[truth]
    support = float(np.mean([(scores < v).mean() for v in pos])) if len(pos) else float("nan")
    return CoevResult(n_seqs=len(seqs), n_eff=neff, L=L, precision=precision,
                      coverage=coverage, support=support, conservation=cons, mi=mi_sq)
