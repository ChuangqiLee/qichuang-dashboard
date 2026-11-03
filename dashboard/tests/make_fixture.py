"""Generate a SYNTHETIC fixture project tree that exercises every dashboard view.

Usage (OUT is wiped first, so it must be new, empty or an earlier fixture / demo directory; see _fixture_guard.py):
    python -I dashboard/tests/make_fixture.py /tmp/an_fixture
    AN_ROOT=/tmp/an_fixture AN_DASH_PORT=17199 python -I dashboard/server.py

Everything is generated here (state/{workflow.json, events.jsonl, routing.json, literature.json} come from
_synthetic_state.py); nothing is read or copied from a real project.
All numbers produced here are random test data, NOT research results.
The files follow the data contracts documented in dashboard/README.md.
"""
from __future__ import annotations

import datetime as dt
import json
import math
import random
import shutil
import sys
import types
from pathlib import Path


def _sibling(name: str) -> types.ModuleType:
    """load tests/<name>.py by path (python -I keeps this directory off sys.path; no __pycache__ is written)"""
    p = Path(__file__).resolve().parent / f"{name}.py"
    m = types.ModuleType(name)
    m.__file__ = str(p)
    exec(compile(p.read_text(encoding="utf-8"), str(p), "exec"), m.__dict__)
    return m


guard = _sibling("_fixture_guard")
synthetic = _sibling("_synthetic_state")
OUT = Path(sys.argv[1] if len(sys.argv) > 1 else "/tmp/an_fixture")
rng = random.Random(7)
NOW = dt.datetime.now(dt.timezone.utc)


def iso(d: dt.datetime) -> str:
    return d.strftime("%Y-%m-%dT%H:%M:%SZ")


def wjson(p: Path, obj) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj, ensure_ascii=False, indent=1))


def png(p: Path, seed: int) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np

    r = np.random.default_rng(seed)
    yy, xx = np.mgrid[0:96, 0:96]
    img = r.normal(0.3, 0.08, (96, 96)) + 0.5 * np.exp(-((xx - 50) ** 2 + (yy - 44) ** 2) / 300)
    m = ((xx - 50) ** 2 + (yy - 44) ** 2) < 120
    fig, ax = plt.subplots(figsize=(2.4, 2.4), dpi=80)
    ax.imshow(img, cmap="gray")
    ax.contour(m, colors=["#22d3ee"], linewidths=1)
    ax.axis("off")
    p.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(p, bbox_inches="tight", facecolor="black")
    plt.close(fig)


def main() -> None:
    guard.check(OUT)   # refuses /, $HOME, real projects and any non-empty directory without the fixture marker
    if OUT.exists():
        shutil.rmtree(OUT)
    (OUT / "state").mkdir(parents=True)
    synthetic.write_state(OUT / "state", NOW.timestamp())   # workflow, events, routing, literature (all synthetic)
    # experiments with lineage
    exps = [
        {"id": "B1", "name": "nnU-Net 3d_fullres", "family": "baseline", "status": "done", "parent_id": None},
        {"id": "B2", "name": "SwinUNETR", "family": "baseline", "status": "done", "parent_id": None},
        {"id": "N1", "name": "Novel-A", "family": "novel", "status": "done", "parent_id": "B1"},
        {"id": "N2", "name": "Novel-A + aniso", "family": "novel", "status": "running", "parent_id": "N1", "gpu": 0},
        {"id": "N3", "name": "Novel-B", "family": "novel", "status": "pruned", "parent_id": "B1"},
        {"id": "A1", "name": "Novel-A w/o module X", "family": "ablation", "status": "queued", "parent_id": "N1"},
    ]
    for e in exps:
        e.update(hypothesis_zh="（测试数据）假设描述", hypothesis_en="(test data) hypothesis text",
                 verdict_zh="（测试）结论" if e["status"] in ("done", "pruned") else "", verdict_en="(test) verdict" if e["status"] in ("done", "pruned") else "",
                 metrics_summary={"val_dice": round(0.8 + rng.random() * 0.1, 4)} if e["status"] != "queued" else {},
                 run_dir=f"runs/run_{e['id'].lower()}")   # the dashboard uses the last path component
    wjson(OUT / "state" / "experiments.json", {"updated": iso(NOW), "experiments": exps})
    # runs
    for i, (rid, state) in enumerate([("run_b1", "done"), ("run_n1", "done"), ("run_n2", "running")]):
        d = OUT / "runs" / rid
        d.mkdir(parents=True)
        lines = []
        start = NOW - dt.timedelta(hours=3 - i)
        epochs = 40 if state == "done" else 23
        step = 0
        for ep in range(epochs):
            for _ in range(50):
                step += 1
                loss = 1.2 * math.exp(-step / (600 + 150 * i)) + 0.08 + rng.gauss(0, 0.03)
                lines.append({"ts": iso(start + dt.timedelta(seconds=step * 3)), "epoch": ep, "step": step, "split": "train", "name": "loss", "value": loss})
            dice = 0.86 + 0.03 * i - 0.5 * math.exp(-ep / 6) + rng.gauss(0, 0.01)
            lines.append({"ts": iso(start + dt.timedelta(seconds=step * 3)), "epoch": ep, "step": step, "split": "val", "name": "dice", "value": dice})
            lines.append({"ts": iso(start + dt.timedelta(seconds=step * 3)), "epoch": ep, "step": step, "split": "val", "name": "hd95", "value": 9 * math.exp(-ep / 8) + 1.5 + rng.random()})
        body = "\n".join(json.dumps(x) for x in lines) + "\n"
        if state == "running":
            body += '{"ts": "2026-10-28T00:00:00Z", "epoch": 23, "step": 99'  # partially written line
        (d / "metrics.jsonl").write_text(body)
        wjson(d / "status.json", {"state": state, "epoch": epochs, "total_epochs": 40, "eta_s": 0 if state == "done" else 1700.0, "gpu": i % 2,
                                   "best": {"val_dice": round(0.86 + 0.03 * i, 4), "val_hd95": 2.1}, "config": {"lr": 1e-3}, "started": iso(start),
                                   "updated": iso(NOW), "exp_id": rid.split("_")[1].upper(), "name": rid.replace("run_", "").upper() + " test"})
        (d / "log.txt").write_text("\n".join(f"[{iso(start)}] epoch {e} loss {0.5 / (e + 1):.4f}" for e in range(epochs)) + "\n")
        for k in range(3):
            png(d / "samples" / f"ep{k:03d}_case{k}.png", 10 * i + k)
    # results summary
    datasets = [{"id": "inhouse", "name_zh": "院内测试集", "name_en": "In-house test", "n": 120}, {"id": "vsseg", "name_zh": "VS-SEG 外部", "name_en": "VS-SEG external", "n": 48}]
    metrics = [{"id": "dice", "name_zh": "Dice", "name_en": "Dice", "higher_is_better": True, "unit": ""},
               {"id": "hd95", "name_zh": "HD95", "name_en": "HD95", "higher_is_better": False, "unit": "mm"},
               {"id": "assd", "name_zh": "ASSD", "name_en": "ASSD", "higher_is_better": False, "unit": "mm"},
               {"id": "rve", "name_zh": "相对体积误差", "name_en": "Rel. volume error", "higher_is_better": False, "unit": "%"}]
    methods = [{"id": "nnunet", "name": "nnU-Net", "family": "baseline", "is_primary": False},
               {"id": "swin", "name": "SwinUNETR", "family": "baseline", "is_primary": False},
               {"id": "ours", "name": "Ours", "family": "ours", "is_primary": True},
               {"id": "ours_abl", "name": "Ours w/o X", "family": "ablation", "is_primary": False}]
    base = {"nnunet": 0.86, "swin": 0.84, "ours": 0.89, "ours_abl": 0.87}
    cells, per_case, pv = [], [], []
    for ds in datasets:
        shift = 0 if ds["id"] == "inhouse" else -0.04
        for m in methods:
            vals = [min(0.99, max(0.3, rng.gauss(base[m["id"]] + shift, 0.06))) for _ in range(ds["n"])]
            mean = sum(vals) / len(vals)
            sd = (sum((v - mean) ** 2 for v in vals) / (len(vals) - 1)) ** 0.5
            cells.append({"method": m["id"], "dataset": ds["id"], "metric": "dice", "mean": mean, "std": sd, "ci_low": mean - 1.96 * sd / len(vals) ** 0.5, "ci_high": mean + 1.96 * sd / len(vals) ** 0.5, "n": len(vals)})
            for met, mu in (("hd95", 4 - 10 * (base[m["id"]] - 0.84)), ("assd", 1.2 - 3 * (base[m["id"]] - 0.84)), ("rve", 12 - 100 * (base[m["id"]] - 0.84))):
                cells.append({"method": m["id"], "dataset": ds["id"], "metric": met, "mean": mu, "std": mu * 0.3, "ci_low": mu * 0.9, "ci_high": mu * 1.1, "n": ds["n"]})
            for k, v in enumerate(vals):
                per_case.append({"method": m["id"], "dataset": ds["id"], "case_id": f"{ds['id']}_{k:03d}", "metric": "dice", "value": v})
        for k in range(ds["n"]):
            gt = rng.lognormvariate(0.3, 0.9)
            per_case.append({"method": "ground_truth", "dataset": ds["id"], "case_id": f"{ds['id']}_{k:03d}", "metric": "volume_ml", "value": gt})
            for m in methods:
                per_case.append({"method": m["id"], "dataset": ds["id"], "case_id": f"{ds['id']}_{k:03d}", "metric": "volume_ml", "value": max(0.01, gt * rng.gauss(1.0, 0.08 if m["id"] == "ours" else 0.14))})
        for met in ("dice", "hd95"):
            pv.append({"method_a": "ours", "method_b": "nnunet", "dataset": ds["id"], "metric": met, "p": 0.0004 if ds["id"] == "inhouse" else 0.03})
            pv.append({"method_a": "ours_abl", "method_b": "nnunet", "dataset": ds["id"], "metric": met, "p": 0.2})
    wjson(OUT / "results" / "summary.json", {"updated": iso(NOW), "datasets": datasets, "metrics": metrics, "methods": methods, "cells": cells, "per_case": per_case, "pvalues": pv})
    idx = []
    for k in range(4):
        f = f"case_{k}.png"
        png(OUT / "results" / "cases" / f, 100 + k)
        idx.append({"file": f, "case_id": f"inhouse_{k:03d}", "dataset": "inhouse", "caption_zh": "（测试）定性病例", "caption_en": "(test) qualitative case"})
    wjson(OUT / "results" / "cases" / "index.json", idx)
    # paper
    png(OUT / "paper" / "figures" / "fig1_cohort.png", 200)
    wjson(OUT / "state" / "paper.json", {"updated": iso(NOW), "target_journal": "Meta-Radiology (test)",
                                          "sections": [{"name": "Abstract", "status": "done", "words": 240}, {"name": "Introduction", "status": "draft", "words": 900}, {"name": "Methods", "status": "pending", "words": 0}],
                                          "figures": [{"file": "fig1_cohort.png", "caption_zh": "队列示意图（测试）", "caption_en": "Cohort schematic (test)", "status": "draft"},
                                                      {"file": "fig2_missing.png", "caption_zh": "缺失图", "caption_en": "missing figure", "status": "pending"}],
                                          "references": {"total": 40, "verified_1x": 40, "verified_2x": 31, "verified_3x": 22}})
    (OUT / "paper" / "main.pdf").write_bytes(b"%PDF-1.4\n%test\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n")
    guard.mark(OUT)
    print("fixture written to", OUT)


if __name__ == "__main__":
    main()
