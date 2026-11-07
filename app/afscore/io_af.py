"""AlphaFold 3 Server 结果读取。

一个任务包（zip）里通常有：
    fold_<job>_job_request.json          输入序列与 copies 数
    fold_<job>_model_0..4.cif            5 个采样模型（pLDDT 在 B-factor 列）
    fold_<job>_summary_confidences_*.json  ptm / iptm / chain_pair_pae_min ...
    fold_<job>_full_data_*.json          token 级 PAE、atom_plddts
    msas/*.a3m                           预测所用的配对/非配对 MSA
    templates/*.cif                      检索到的模板

本模块只负责"把文件变成 numpy 数组"，不做任何科学判断。
"""
from __future__ import annotations

import io
import json
import os
import re
import zipfile
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import numpy as np

from .struct3d import Structure, VDW_RADII, THREE_TO_ONE, build_structure

MODEL_RE = re.compile(r"model_(\d+)\.cif$")


@dataclass
class Model:
    """单个采样模型。"""

    index: int
    struct: Structure
    plddt: np.ndarray                     # 每残基 pLDDT（原子 B-factor 均值）
    pae: Optional[np.ndarray] = None      # token 级 (N,N) 预测对齐误差
    token_chain: Optional[np.ndarray] = None
    token_res: Optional[np.ndarray] = None
    ptm: float = float("nan")
    iptm: float = float("nan")
    fraction_disordered: float = float("nan")
    has_clash: float = float("nan")
    chain_pair_pae_min: Optional[np.ndarray] = None

    @property
    def n_residues(self) -> int:
        return self.struct.n_residues


@dataclass
class Job:
    """一个 AlphaFold Server 任务。"""

    name: str
    path: str
    sequences: List[Tuple[str, int]] = field(default_factory=list)   # (序列, copies)
    models: List[Model] = field(default_factory=list)
    msa_files: List[str] = field(default_factory=list)
    msa_bytes: Dict[str, bytes] = field(default_factory=dict)
    design: Dict[str, str] = field(default_factory=dict)             # 解析出的设计变量


# ---------------------------------------------------------------- cif 解析
def parse_cif_atoms(text: str) -> Structure:
    """解析 mmCIF 的 _atom_site 循环（AF3 输出列固定且无引号，可走快速路径）。"""
    cols: Optional[List[str]] = None
    rows: List[List[str]] = []
    in_atom_loop = False
    for line in text.splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        if s.startswith("_atom_site."):
            if cols is None:
                cols = []
            cols.append(s.split(".", 1)[1])
            in_atom_loop = True
            continue
        if in_atom_loop:
            if s.startswith(("loop_", "_", "data_")):
                break
            if s.startswith(("ATOM", "HETATM")):
                rows.append(s.split())
    if cols is None or not rows:
        raise ValueError("未找到 _atom_site 记录")

    ci = {c: i for i, c in enumerate(cols)}
    need = ["type_symbol", "label_atom_id", "label_comp_id", "label_asym_id", "Cartn_x", "Cartn_y", "Cartn_z"]
    if any(k not in ci for k in need):
        raise ValueError(f"缺少必要列: {[k for k in need if k not in ci]}")

    n = len(rows)
    xyz = np.empty((n, 3), dtype=np.float64)
    element = np.empty(n, dtype="<U2")
    atom_name = np.empty(n, dtype="<U4")
    res_name = np.empty(n, dtype="<U3")
    chain = np.empty(n, dtype="<U2")
    res_seq = np.empty(n, dtype=np.int32)
    bfactor = np.empty(n, dtype=np.float64)
    hetero = np.zeros(n, dtype=bool)

    ix, iy, iz = ci["Cartn_x"], ci["Cartn_y"], ci["Cartn_z"]
    ia, ic, ir = ci["label_atom_id"], ci["label_comp_id"], ci["label_asym_id"]
    iel = ci["type_symbol"]
    ib = ci.get("B_iso_or_equiv")
    iseq = ci.get("label_seq_id")
    ig = ci.get("group_PDB")

    for i, r in enumerate(rows):
        xyz[i] = (float(r[ix]), float(r[iy]), float(r[iz]))
        element[i] = r[iel][:2]
        atom_name[i] = r[ia][:4]
        res_name[i] = r[ic][:3]
        chain[i] = r[ir][:2]
        res_seq[i] = int(r[iseq]) if iseq is not None and r[iseq] not in ("?", ".") else i
        bfactor[i] = float(r[ib]) if ib is not None and r[ib] not in ("?", ".") else 0.0
        hetero[i] = (ig is not None and r[ig] == "HETATM")

    st = build_structure(xyz, element, atom_name, res_name, chain, res_seq, bfactor, hetero)
    return st


def _parse_confidence(payload) -> Dict:
    if isinstance(payload, list):
        payload = payload[0] if payload else {}
    if not isinstance(payload, dict):
        return {}
    out: Dict = {}
    for k in ("plddt", "pLDDT"):
        if isinstance(payload.get(k), list):
            out["plddt"] = np.asarray(payload[k], dtype=np.float64)
    for k in ("pae", "predicted_aligned_error"):
        if k in payload:
            arr = np.asarray(payload[k], dtype=np.float64)
            if arr.ndim == 2 and arr.shape[0] == arr.shape[1]:
                out["pae"] = arr
    for k, key in (("ptm", "ptm"), ("iptm", "iptm"),
                   ("fraction_disordered", "fraction_disordered"),
                   ("has_clash", "has_clash")):
        if isinstance(payload.get(k), (int, float)):
            out[key] = float(payload[k])
    for k in ("chain_pair_pae_min", "token_chain_ids", "token_res_ids", "atom_plddts"):
        if isinstance(payload.get(k), list):
            out[k] = np.asarray(payload[k], dtype=np.float64 if k == "atom_plddts" else object)
    return out


def _design_from_name(name: str) -> Dict[str, str]:
    """从任务名解析设计变量，例如 ggssgg_biaowei4_20_a。"""
    low = name.lower()
    key = low.replace("_", "")          # 统一去下划线，兼容 biaowei_4 / biaowei4
    linker = ("ggssgg" if "ggssgg" in key else
              "gpgpg" if "gpgpg" in key else
              "none" if "nonelinker" in key else
              "linker_only" if "linkeronly" in key else "—")
    if "biaowei1234" in key:
        epitope = "E1-E2-E3-E4"
    elif "biaowei4" in key:
        epitope = "E4"
    elif "biaowei12" in key:
        epitope = "E1+E2"
    elif "biaowei3" in key:
        epitope = "E3"
    elif "kongde" in key:
        epitope = "空载对照"
    else:
        epitope = "—"
    if "danti" in key:
        assembly = "单体"
    elif re.search(r"20(_|$)", low) or "20a" in key or "20b" in key:
        assembly = "20 聚体"
    elif "wt9" in key:
        assembly = "9 聚体"
    elif "kongde1" in key:
        assembly = "21 聚体"
    else:
        assembly = "—"
    return {"linker": linker, "epitope": epitope, "assembly": assembly}


# ---------------------------------------------------------------- 任务加载
def _parse_pae_stream(text: str, chunk_rows: int = 256) -> Optional[np.ndarray]:
    """分块解析 PAE 矩阵，避免把 4892×4892 的数字一次性建成 Python 列表。

    直接把整份 JSON 交给 json.loads 时，20 聚体的 full_data（约 215 MB 文本、
    两个 2400 万元素的矩阵）会瞬间吃掉 700 MB 以上内存并触发换页。
    这里先定位 "pae" 数组的文本边界，再按行切块解析，峰值内存降到几十 MB。
    """
    i = text.find('"pae"')
    if i < 0:
        return None
    j = text.find("[[", i)
    if j < 0:
        return None
    k = text.find("]]", j)
    if k < 0:
        return None
    body = text[j + 2:k]
    cuts = [0]
    p = body.find("],[")
    while p >= 0:
        cuts.append(p + 3)                 # 下一行起点
        p = body.find("],[", p + 3)
    n = len(cuts)
    out = np.empty((n, n), dtype=np.float32)
    for s in range(0, n, chunk_rows):
        e = min(s + chunk_rows, n)
        start = cuts[s]
        end = cuts[e] - 3 if e < n else len(body)
        part = "[[" + body[start:end] + "]]"
        out[s:e] = np.asarray(json.loads(part), dtype=np.float32)
    return out


def load_job_meta(path: str) -> Job:
    """只读任务元信息（序列、设计变量、MSA），不解析任何结构。"""
    name = os.path.splitext(os.path.basename(path))[0]
    job = Job(name=name, path=path, design=_design_from_name(name))
    with zipfile.ZipFile(path) as zf:
        names = zf.namelist()
        req_name = next((n for n in names if n.endswith("job_request.json")), None)
        if req_name:
            req = json.loads(zf.read(req_name))
            if isinstance(req, list):
                req = req[0]
            for ent in req.get("sequences", []):
                pc = ent.get("proteinChain") or ent.get("protein")
                if pc:
                    job.sequences.append((pc.get("sequence", ""), int(pc.get("count", 1))))
        job.msa_files = [n for n in names if n.endswith(".a3m")]
        for n in job.msa_files:
            job.msa_bytes[n] = zf.read(n)
    return job


def iter_models(path: str, want_pae: bool = True):
    """逐个产出 Model，调用方用完即丢，峰值只占一个 PAE 矩阵。"""
    with zipfile.ZipFile(path) as zf:
        names = zf.namelist()
        mfiles = sorted((int(MODEL_RE.search(n).group(1)), n) for n in names if MODEL_RE.search(n))
        for idx, mname in mfiles:
            st = parse_cif_atoms(zf.read(mname).decode("utf-8", "replace"))
            plddt_res = st.plddt_per_residue()

            summary: Dict = {}
            sname = next((n for n in names if n.endswith(f"summary_confidences_{idx}.json")), None)
            if sname:
                summary = _parse_confidence(json.loads(zf.read(sname)))

            full: Dict = {}
            if want_pae:
                fname = next((n for n in names if n.endswith(f"full_data_{idx}.json")), None)
                if fname:
                    txt = zf.read(fname).decode("utf-8", "replace")
                    pae = _parse_pae_stream(txt)
                    if pae is not None:
                        full["pae"] = pae
                    tci = txt.find('"token_chain_ids"')
                    if tci > 0:
                        b = txt.find("[", tci)
                        e = txt.find("]", b)
                        if b > 0 and e > b:
                            full["token_chain_ids"] = json.loads(txt[b:e + 1])
                    del txt

            yield Model(
                index=idx, struct=st,
                plddt=summary.get("plddt") if summary.get("plddt") is not None
                and len(summary["plddt"]) == st.n_residues else plddt_res,
                pae=full.get("pae"),
                token_chain=full.get("token_chain_ids"),
                ptm=summary.get("ptm", float("nan")),
                iptm=summary.get("iptm", float("nan")),
                fraction_disordered=summary.get("fraction_disordered", float("nan")),
                has_clash=summary.get("has_clash", float("nan")),
                chain_pair_pae_min=summary.get("chain_pair_pae_min"),
            )


def load_job(path: str, want_pae: bool = True) -> Job:
    """一次性读入全部模型（小任务方便，大任务建议用 iter_models）。"""
    job = load_job_meta(path)
    job.models = list(iter_models(path, want_pae=want_pae))
    return job


def iter_job_paths(root: str) -> List[str]:
    return sorted(os.path.join(root, f) for f in os.listdir(root) if f.lower().endswith(".zip"))
