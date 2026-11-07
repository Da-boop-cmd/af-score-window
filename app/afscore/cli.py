"""命令行入口。

    python -m afscore.cli run --data <结果目录> --out out        # 批量评分 + 出图
    python -m afscore.cli score --input <单个 zip> --out out_one  # 单个任务包评分
    python -m afscore.cli figures --scores out/scores.csv --data <结果目录> --out out/figures

只负责"算分"和"画图"两件事，不生成任何报告文本。
"""
from __future__ import annotations

import argparse
import os
from typing import Optional

import pandas as pd

from .io_af import iter_job_paths, load_job
from .pipeline import run as run_pipeline
from .report import make_figures
from .scoring import add_scores


def _figures(df: pd.DataFrame, data_dir: str, out_dir: str) -> dict:
    """画 5 张图：柱状图、分项热图、Pareto 散点、残基轨迹、PAE。"""
    lookup = {os.path.splitext(os.path.basename(p))[0]: p for p in iter_job_paths(data_dir)}
    return make_figures(df, out_dir, lookup)


def main(argv: Optional[list] = None) -> None:
    ap = argparse.ArgumentParser("afscore", description="AlphaFold3 预测结果评分")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_run = sub.add_parser("run", help="批量评分 + 出图")
    p_run.add_argument("--data", required=True)
    p_run.add_argument("--out", default="out")
    p_run.add_argument("--no-cache", action="store_true")

    p_one = sub.add_parser("score", help="单个任务包评分")
    p_one.add_argument("--input", required=True)
    p_one.add_argument("--out", default="out_one")

    p_fig = sub.add_parser("figures", help="从已有 scores.csv 出图")
    p_fig.add_argument("--scores", required=True)
    p_fig.add_argument("--data", required=True)
    p_fig.add_argument("--out", default="out/figures")

    p_val = sub.add_parser("validate", help="用实验数据校链（ELISA OD 等）")
    p_val.add_argument("--scores", required=True)
    p_val.add_argument("--assay", required=True)
    p_val.add_argument("--out", default="out/validation")

    args = ap.parse_args(argv)

    if args.cmd == "run":
        if not os.path.isdir(args.data):
            raise SystemExit("数据目录不存在: %s\n（在 af-score 目录下运行，或传绝对路径）" % args.data)
        df = run_pipeline(args.data, args.out, use_cache=not args.no_cache)
        figs = _figures(df, args.data, os.path.join(args.out, "figures"))
        print(f"结果表: {os.path.join(args.out, 'scores.csv')}")
        print(f"图:     {os.path.join(args.out, 'figures')}")
    elif args.cmd == "score":
        from .metrics import model_features
        job = load_job(args.input)
        df = add_scores(pd.DataFrame([model_features(job, m) for m in job.models]))
        os.makedirs(args.out, exist_ok=True)
        df.to_csv(os.path.join(args.out, "scores.csv"), index=False)
        print(df[["job", "model", "composite", "grade"]].to_string(index=False))
    elif args.cmd == "figures":
        df = pd.read_csv(args.scores)
        figs = _figures(df, args.data, args.out)
        print("\n".join(f"{k}: {v}" for k, v in figs.items()))
    elif args.cmd == "validate":
        from .validation import validate
        rep = validate(args.scores, args.assay, args.out)
        print(f"匹配 {rep['n_matched']} / {rep['n_assay']} 条实验记录")
        if rep.get("unmatched"):
            print("未匹配的设计:", ", ".join(rep["unmatched"][:8]))
        if "spearman" in rep:
            print(f"Spearman ρ = {rep['spearman']:.3f} | Pearson r = {rep['pearson']:.3f}")
        if rep.get("figure"):
            print("图:", rep["figure"])


if __name__ == "__main__":
    main()
