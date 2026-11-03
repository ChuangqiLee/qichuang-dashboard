"""SYNTHETIC leaderboard fixture (rules: dashboard/README.md §18).  All numbers are hand-designed test data, NOT results.

Usage (OUT must be new, empty or an earlier fixture / demo directory; see _fixture_guard.py):
    python -I dashboard/tests/make_leaderboard_fixture.py /tmp/an_lb_fixture            # leaderboard-only tree
    python -I dashboard/tests/make_fixture.py /tmp/an_fixture && \
    python -I dashboard/tests/make_leaderboard_fixture.py /tmp/an_fixture --merge       # on top of the base fixture
    AN_ROOT=/tmp/an_lb_fixture AN_DASH_PORT=17199 python -I dashboard/server.py

Layout (validation every 2 epochs; ts = 2026-10-01T00:00Z + run offset + 60 s * epoch):

  run            family    state    val dice (ep 2, 4, …)                                   val hd95
  LB_B1_done     baseline  done     .80 .85 .88 .900 .895                       best .900@8  6 4 3.2 3.0 3.1      best 3.0
  LB_B2_run      baseline  running  .70 .86 .890                                best .890@6  5 3.5 2.5            best 2.5 (provisional)
  LB_T1_cross    novel     running  .85 .89 .898 .899 .904 .9065 .905 .910      best .910@16 8 5 3.0 2.9 2.7 2.6 2.65 2.1
  LB_T2_behind   novel     done     .80 .84 .86 .88 .87                         best .880@8  7 6 5 4.5 4.6        best 4.5
  LB_T3_flat     novel     running  .70 .75 .74 .73 .72 .71 .70 .70 .70 .70 (ep 2..20, best .75@4; no hd95 series)
  LB_T4_queued   novel     queued   (status.json only, no metrics)
  LB_A1_abl      ablation  done     .85 .90 .909 .905                           best .909@6  5 3.6 3.3 3.4        best 3.3
Excluded: LB_T1_cross_smoke (registered, *_smoke), LB_X_unreg (not in experiments.json), _discarded/LB_T1_old.
LB_T1_cross/metrics.jsonl also holds one malformed line and a partially written last line.

results/summary.json (dataset inhouse_val + inhouse_test_site01; metrics dice, hd95, rve):
  inhouse_val dice  mean / median:  LB_B1_done .880/.900  LB_B9_final .884/.890  LB_T2_behind .886/.905  LB_A1_abl .870/.902
  inhouse_val hd95  mean / median:  LB_B1_done 3.0/2.9    LB_B9_final 2.8/—      LB_T2_behind 2.6/2.5   LB_A1_abl 3.5/3.4
"""
from __future__ import annotations

import datetime as dt
import json
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
# fixed past clock: the tests treat these points as old history (back-fill) and compare their timestamps;
# demo/demo_extras.py shifts them to "now" for the demo
T0 = dt.datetime(2026, 10, 1, tzinfo=dt.timezone.utc)

RUNS = {
    #  id: (family, state, total_epochs, offset_min, dice list, hd95 list)
    "LB_B1_done": ("baseline", "done", 10, 0, [0.80, 0.85, 0.88, 0.900, 0.895], [6.0, 4.0, 3.2, 3.0, 3.1]),
    "LB_B2_run": ("baseline", "running", 20, 600, [0.70, 0.86, 0.890], [5.0, 3.5, 2.5]),
    "LB_T1_cross": ("novel", "running", 20, 120, [0.85, 0.89, 0.898, 0.899, 0.904, 0.9065, 0.905, 0.910],
                    [8.0, 5.0, 3.0, 2.9, 2.7, 2.6, 2.65, 2.1]),
    "LB_T2_behind": ("novel", "done", 10, 60, [0.80, 0.84, 0.86, 0.88, 0.87], [7.0, 6.0, 5.0, 4.5, 4.6]),
    "LB_T3_flat": ("novel", "running", 30, 180, [0.70, 0.75, 0.74, 0.73, 0.72, 0.71, 0.70, 0.70, 0.70, 0.70], None),
    "LB_A1_abl": ("ablation", "done", 8, 30, [0.85, 0.90, 0.909, 0.905], [5.0, 3.6, 3.3, 3.4]),
    "LB_T1_cross_smoke": ("novel", "done", 2, 100, [0.99], [0.5]),
}
UNREGISTERED = {"LB_X_unreg": [0.99, 0.995]}
NAMES = {
    "LB_B1_done": "Baseline one (done)", "LB_B2_run": "Baseline two (running)", "LB_T1_cross": "Ours crossing",
    "LB_T2_behind": "Ours behind", "LB_T3_flat": "Ours flat", "LB_T4_queued": "Ours queued",
    "LB_A1_abl": "Ours ablation", "LB_T1_cross_smoke": "Ours smoke", "LB_P_planned": "Ours planned",
    "LB_B9_final": "Baseline nine (final only)",
}


def iso(d: dt.datetime) -> str:
    return d.strftime("%Y-%m-%dT%H:%M:%SZ")


def ts_of(run_id: str, epoch: int) -> str:
    off = RUNS[run_id][3] if run_id in RUNS else 0
    return iso(T0 + dt.timedelta(minutes=off, seconds=60 * epoch))


def wjson(p: Path, obj) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj, ensure_ascii=False, indent=1))


def val_lines(run_id: str, epoch: int, dice=None, hd95=None) -> list[str]:
    out = []
    ts = ts_of(run_id, epoch)
    out.append(json.dumps({"ts": ts, "epoch": epoch, "step": epoch * 10, "split": "train", "name": "loss", "value": 1.0 / epoch}))
    if dice is not None:
        out.append(json.dumps({"ts": ts, "epoch": epoch, "step": epoch * 10, "split": "val", "name": "dice", "value": dice}))
        out.append(json.dumps({"ts": ts, "epoch": epoch, "step": epoch * 10, "split": "val", "name": "dice_mean", "value": dice - 0.01}))
    if hd95 is not None:
        out.append(json.dumps({"ts": ts, "epoch": epoch, "step": epoch * 10, "split": "val", "name": "hd95", "value": hd95}))
    return out


def append_val(root: Path, run_id: str, epoch: int, dice=None, hd95=None) -> None:
    """append validation points (completes a partially written last line first)"""
    p = Path(root) / "runs" / run_id / "metrics.jsonl"
    body = p.read_bytes() if p.exists() else b""
    if body and not body.endswith(b"\n"):
        body = body[: body.rfind(b"\n") + 1]   # drop the partial line (as a writer finishing it would rewrite it)
    p.write_bytes(body + ("\n".join(val_lines(run_id, epoch, dice, hd95)) + "\n").encode())


def status(run_id: str, state: str, epoch, total, best: dict) -> dict:
    return {"state": state, "epoch": epoch, "total_epochs": total, "eta_s": 0.0 if state == "done" else 600.0, "gpu": 0,
            "best": best, "config": {"exp_id": run_id}, "started": iso(T0), "updated": ts_of(run_id, epoch or 0),
            "exp_id": run_id, "name": NAMES.get(run_id, run_id)}


def build(root: Path, merge: bool = False) -> Path:
    root = Path(root)
    guard.check(root)   # refuses /, $HOME, real projects and any non-empty directory without the fixture marker
    if not merge and root.exists():
        shutil.rmtree(root)
    (root / "state").mkdir(parents=True, exist_ok=True)
    exps = []
    for rid, (fam, state, total, _off, _d, _h) in RUNS.items():
        exps.append({"id": rid, "name": NAMES[rid], "family": fam, "status": state, "parent_id": None,
                     "run_dir": f"runs/{rid}"})   # the dashboard uses the last path component
    exps.append({"id": "LB_T4_queued", "name": NAMES["LB_T4_queued"], "family": "novel", "status": "queued",
                 "run_dir": "runs/LB_T4_queued"})
    exps.append({"id": "LB_P_planned", "name": NAMES["LB_P_planned"], "family": "novel", "status": "planned", "run_dir": None})
    ep_path = root / "state" / "experiments.json"
    if merge and ep_path.exists():
        old = json.loads(ep_path.read_text())
        have = {e.get("id") for e in old.get("experiments", [])}
        old["experiments"] = old.get("experiments", []) + [e for e in exps if e["id"] not in have]
        wjson(ep_path, old)
    else:
        wjson(ep_path, {"updated": iso(T0), "experiments": exps})
    if not (root / "state" / "events.jsonl").exists():
        (root / "state" / "events.jsonl").write_text(json.dumps({"ts": iso(T0), "type": "info", "level": "info", "actor": "fixture",
                                                                  "msg_zh": "（测试）排行榜夹具", "msg_en": "(test) leaderboard fixture"}) + "\n")
    for rid, (fam, state, total, _off, dice, hd) in RUNS.items():
        d = root / "runs" / rid
        if d.exists():
            shutil.rmtree(d)
        d.mkdir(parents=True)
        lines = []
        for i, v in enumerate(dice):
            ep = 2 * (i + 1)
            lines += val_lines(rid, ep, v, hd[i] if hd else None)
        body = "\n".join(lines) + "\n"
        if rid == "LB_T1_cross":
            body = body.replace(lines[2] + "\n", lines[2] + "\n" + "{not json\n" + '{"split": "val", "name": "dice", "value": "NaN"}\n', 1)
            body += '{"ts": "2026-10-01T09:00:00Z", "epoch": 18, "split": "val", "name": "dice", "val'   # partially written
        (d / "metrics.jsonl").write_text(body)
        eps = [2 * (i + 1) for i in range(len(dice))]
        bi = max(range(len(dice)), key=lambda i: dice[i])
        best = {"val_dice": dice[bi], "epoch": eps[bi]}
        if hd:
            best["val_hd95"] = min(hd)
        wjson(d / "status.json", status(rid, state, eps[-1], total, best))
    d = root / "runs" / "LB_T4_queued"
    d.mkdir(parents=True, exist_ok=True)
    wjson(d / "status.json", {"state": "queued", "epoch": 0, "total_epochs": 20, "exp_id": "LB_T4_queued", "name": NAMES["LB_T4_queued"]})
    for rid, dice in UNREGISTERED.items():
        d = root / "runs" / rid
        d.mkdir(parents=True, exist_ok=True)
        (d / "metrics.jsonl").write_text("\n".join(json.dumps({"ts": iso(T0), "epoch": 2 * (i + 1), "split": "val", "name": "dice", "value": v})
                                                   for i, v in enumerate(dice)) + "\n")
        wjson(d / "status.json", status(rid, "done", 4, 4, {"val_dice": max(dice)}))
    d = root / "runs" / "_discarded" / "LB_T1_old"
    d.mkdir(parents=True, exist_ok=True)
    (d / "metrics.jsonl").write_text(json.dumps({"ts": iso(T0), "epoch": 2, "split": "val", "name": "dice", "value": 0.999}) + "\n")
    # final evaluation
    datasets = [{"id": "inhouse_test_site01", "name_zh": "院内 test_site01", "name_en": "In-house test_site01", "n": 20, "postprocess": "none"},
                {"id": "inhouse_val", "name_zh": "院内 val", "name_en": "In-house val", "n": 10, "postprocess": "none"}]
    metrics = [{"id": "dice", "name_zh": "Dice", "name_en": "Dice", "higher_is_better": True, "unit": ""},
               {"id": "hd95", "name_zh": "HD95", "name_en": "HD95", "higher_is_better": False, "unit": "mm"},
               {"id": "rve", "name_zh": "相对体积误差", "name_en": "Relative volume error", "higher_is_better": False, "unit": ""}]
    methods = [{"id": "LB_B1_done", "name": NAMES["LB_B1_done"], "family": "baseline", "is_primary": False},
               {"id": "LB_B9_final", "name": NAMES["LB_B9_final"], "family": "baseline", "is_primary": False},
               {"id": "LB_T2_behind", "name": NAMES["LB_T2_behind"], "family": "ours", "is_primary": True},
               {"id": "LB_A1_abl", "name": NAMES["LB_A1_abl"], "family": "ablation", "is_primary": False}]
    table = {  # (dataset, metric): {method: (mean, median)}
        ("inhouse_val", "dice"): {"LB_B1_done": (0.880, 0.900), "LB_B9_final": (0.884, 0.890), "LB_T2_behind": (0.886, 0.905), "LB_A1_abl": (0.870, 0.902)},
        ("inhouse_val", "hd95"): {"LB_B1_done": (3.0, 2.9), "LB_B9_final": (2.8, None), "LB_T2_behind": (2.6, 2.5), "LB_A1_abl": (3.5, 3.4)},
        ("inhouse_val", "rve"): {"LB_B1_done": (0.10, 0.08), "LB_B9_final": (0.12, 0.09), "LB_T2_behind": (0.098, 0.07), "LB_A1_abl": (0.2, 0.15)},
        ("inhouse_test_site01", "dice"): {"LB_B1_done": (0.86, 0.88), "LB_B9_final": (0.87, 0.89), "LB_T2_behind": (0.85, 0.87), "LB_A1_abl": (0.84, 0.86)},
    }
    cells = []
    for (ds, met), vals in table.items():
        for mth, (mean, med) in vals.items():
            c = {"method": mth, "dataset": ds, "metric": met, "mean": mean, "std": 0.05, "ci_low": mean - 0.01,
                 "ci_high": mean + 0.01, "n": 10 if ds == "inhouse_val" else 20}
            if med is not None:
                c.update(median=med, q1=med - 0.02, q3=med + 0.02)
            cells.append(c)
    cells.append({"method": "LB_B1_done", "dataset": "inhouse_val", "metric": "dice", "mean": 0.5, "n": 1})  # duplicate: ignored
    cells.append({"method": "LB_A1_abl", "dataset": "inhouse_val", "metric": "assd", "mean": None})          # unusable
    sp = root / "results" / "summary.json"
    if merge and sp.exists():
        old = json.loads(sp.read_text())
        for k, new in (("datasets", datasets), ("metrics", metrics), ("methods", methods)):
            have = {x.get("id") for x in old.get(k, [])}
            old[k] = old.get(k, []) + [x for x in new if x["id"] not in have]
        old["cells"] = old.get("cells", []) + cells
        wjson(sp, old)
    else:
        wjson(sp, {"updated": iso(T0), "datasets": datasets, "metrics": metrics, "methods": methods, "cells": cells,
                   "per_case": [], "pvalues": []})
    guard.mark(root)
    return root


if __name__ == "__main__":
    out = Path(sys.argv[1] if len(sys.argv) > 1 and not sys.argv[1].startswith("-") else "/tmp/an_lb_fixture")
    build(out, merge="--merge" in sys.argv)   # build() runs the shared target guard
    print(f"leaderboard fixture written to {out}")
