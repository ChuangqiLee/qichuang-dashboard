"""SYNTHETIC freshness / auto-progress fixture (rules: dashboard/README.md §19).  All numbers are hand-designed test data.

Usage (OUT must be new, empty or an earlier fixture / demo directory; see _fixture_guard.py):
    python -I dashboard/tests/make_freshness_fixture.py /tmp/an_fr_fixture            # freshness-only tree
    python -I dashboard/tests/make_fixture.py /tmp/an_fixture && \
    python -I dashboard/tests/make_freshness_fixture.py /tmp/an_fixture --merge       # on top of the base fixture
    AN_ROOT=/tmp/an_fr_fixture AN_LEADERBOARD_READONLY=1 AN_DASH_PORT=17199 python -I dashboard/server.py

Every timestamp is relative to NOW (the build time): `updated` fields and file mtimes are set to NOW - age.

Source files (age = NOW - updated):                               expected (README §19 rules)
  state/workflow.json        updated 1 h, phases below            manual; paper (manual phase) running -> 12 h, fresh
  state/experiments.json     updated 2 h (registry below)          event, never stale
  state/events.jsonl         mtime 15 min                          live but sporadic: never stale by age
  state/briefing.json        updated 3 h                           periodic 2 h -> STALE
  state/session_status.json  updated "not-a-date", mtime 30 min    periodic, falls back to mtime -> fresh
  state/session_watch.json   heartbeat ts 5 s                      live 60 s -> fresh
  state/paper.json           updated 13 h, phase paper running     manual dependent 12 h -> STALE
  state/literature.json      updated 30 h, phase literature done   manual, no running dependant -> fresh
  state/routing.json         half-written JSON, mtime 100 h        manual, never stale; error + mtime
  state/leaderboard_events.jsonl  absent                           missing, not stale
  results/summary.json       updated 90 min, mtime 1 min           event; `updated` field wins (age 5400 s)
  results/cases/index.json   JSON list, mtime 10 min               manual; list -> mtime, no error
  runs/FB2 (running)         activity 10 s                         fresh
  runs/T5_R2 (running)       activity 5 min                        live 60 s -> runs STALE (stale_runs [T5_R2])
  runs/FB1_smoke (running)   activity 2 h, hidden                  ignored (hidden)
  runs/_discarded/old        directory only, hidden
  runs/FB1/eval/inhouse_val_summary.json  mtime 30 min             run_eval updated 30 min

Registry (state/experiments.json) and auto phase progress = done / (done + running + queued):
  id        family    status   config (cohorts / split)                 phase        eval_status.aggregate
  FB1       baseline  done     inhouse / inhouse_v1 (run config)        train_base   ok
  FB2       baseline  running  inhouse / inhouse_v1 (run config)        train_base   -
  FB3       baseline  queued   inhouse (configs/exp)                    train_base   -
  FB4       baseline  planned  inhouse (configs/exp)                    (not counted)
  FB5_pool  baseline  queued   inhouse+VS-SEG / public_v2 (configs/exp) r2 (public cohorts)
  T1        novel     done     inhouse (run config)                     train_novel  ok
  T2        novel     done     inhouse (run config)                     train_novel  failed
  T3        novel     queued   (no config at all -> in-house default)   train_novel
  T4        novel     pruned                                            (not counted)
  T5_R2     novel     running  inhouse+UCSD / public_v3 (run config)    r2
  A1        ablation  done     (no eval_status)                         train_novel  -
  A2        ablation  failed                                            (not counted)
  V1        novel     done                                              vjepa        ok
  V2        novel     queued                                            vjepa
  V3        novel     planned                                           (not counted)
  X1        other     done                                              (none)       ok
  => train_base 1/3 = .3333   train_novel 3/4 = .75   vjepa 1/2 = .5   r2 0/2 = 0.0
     evaluate = ok among done {FB1, T1, T2, A1, V1, X1} = {FB1, T1, V1, X1} = 4/6 = .6667

results/summary.json dice (Overview best-Dice tile uses inhouse_val, never the test split listed first):
  inhouse_test_site01: FT1(ours, primary) .95, FB1 .97        inhouse_val: FT1 .88, FB1 .87, FB9 .89 -> ours .88 vs .89
Live val dice (metrics.jsonl): FB1 .80 .85 (done, best baseline .85), FB2 .82 (running), T1 .84 .86 -> T1 sota, Δ +.01
"""
from __future__ import annotations

import datetime as dt
import json
import os
import shutil
import sys
import time
import types
from pathlib import Path

H = 3600.0


def _sibling(name: str) -> types.ModuleType:
    """load tests/<name>.py by path (python -I keeps this directory off sys.path; no __pycache__ is written)"""
    p = Path(__file__).resolve().parent / f"{name}.py"
    m = types.ModuleType(name)
    m.__file__ = str(p)
    exec(compile(p.read_text(encoding="utf-8"), str(p), "exec"), m.__dict__)
    return m


guard = _sibling("_fixture_guard")


def iso(t: float) -> str:
    return dt.datetime.fromtimestamp(t, dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


REGISTRY = [
    # id, family, status, run dir?, eval aggregate
    ("FB1", "baseline", "done", True, "ok"),
    ("FB2", "baseline", "running", True, None),
    ("FB3", "baseline", "queued", False, None),
    ("FB4", "baseline", "planned", False, None),
    ("FB5_pool", "baseline", "queued", False, None),
    ("T1", "novel", "done", True, "ok"),
    ("T2", "novel", "done", True, "failed"),
    ("T3", "novel", "queued", False, None),
    ("T4", "novel", "pruned", False, None),
    ("T5_R2", "novel", "running", True, None),
    ("A1", "ablation", "done", False, None),
    ("A2", "ablation", "failed", False, None),
    ("V1", "novel", "done", True, "ok"),
    ("V2", "novel", "queued", False, None),
    ("V3", "novel", "planned", False, None),
    ("X1", "other", "done", False, "ok"),
]
RUN_CFG = {  # run dir config.yaml: data.cohorts / data.split
    "FB1": (["inhouse"], "inhouse_v1"), "FB2": (["inhouse"], "inhouse_v1"), "T1": (["inhouse"], "inhouse_v1"),
    "T2": (["inhouse"], "inhouse_v1"), "T5_R2": (["inhouse", "UCSD"], "public_v3"), "V1": (["inhouse"], "inhouse_v1"),
}
EXP_CFG = {  # configs/exp/<id>.yaml for experiments without a run dir
    "FB3": (["inhouse"], "inhouse_v1"), "FB4": (["inhouse"], "inhouse_v1"), "FB5_pool": (["inhouse", "VS-SEG"], "public_v2"),
}
RUN_STATE = {"FB1": "done", "FB2": "running", "T1": "done", "T2": "done", "T5_R2": "running", "V1": "done"}
RUN_AGE = {"FB1": 3 * H, "FB2": 10.0, "T1": 4 * H, "T2": 5 * H, "T5_R2": 300.0, "V1": 2 * H}
VAL_DICE = {"FB1": [0.80, 0.85], "FB2": [0.82], "T1": [0.84, 0.86], "V1": [0.83]}
PHASES = [
    # id, status, manual progress
    ("env", "done", 1.0), ("literature", "done", 1.0), ("train_base", "running", 0.2), ("train_novel", "running", 0.1),
    ("vjepa", "pending", 0.0), ("evaluate", "running", 0.5), ("r2", "pending", 0.3), ("paper", "running", 0.4),
    ("refs", "pending", 0.0),
]


def _write(p: Path, text: str, age: float | None, now: float) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    if age is not None:
        os.utime(p, (now - age, now - age))


def _wj(p: Path, obj, age: float | None, now: float) -> None:
    _write(p, json.dumps(obj, ensure_ascii=False, indent=1), age, now)


def _cfg(cohorts: list[str], split: str, eid: str, fam: str) -> str:
    return (f"exp_id: {eid}\nfamily: {fam}\nmodel:\n  name: dummy\ndata:\n  cohorts: [{', '.join(cohorts)}]\n"
            f"  split: {split}\n  train_split: train\n  val_split: val\n")


def build(out: Path | str, now: float | None = None, merge: bool = False) -> Path:
    out = Path(out)
    guard.check(out)   # refuses /, $HOME, real projects and any non-empty directory without the fixture marker
    now = time.time() if now is None else now
    if out.exists() and not merge:
        shutil.rmtree(out)
    st, runs, res = out / "state", out / "runs", out / "results"
    fam = {r[0]: r[1] for r in REGISTRY}

    _wj(st / "workflow.json", {
        "project": {"zh": "新鲜度测试", "en": "Freshness fixture"}, "updated": iso(now - H), "current_phase": "train_novel",
        "phases": [{"id": i, "name_zh": i, "name_en": i, "status": s, "progress": p,
                    "started": iso(now - 20 * H) if s != "pending" else None, "ended": iso(now - 10 * H) if s == "done" else None}
                   for i, s, p in PHASES]}, 60.0, now)
    exps = []
    for eid, f, s, has_run, agg in REGISTRY:
        e = {"id": eid, "name": f"{eid} synthetic", "family": f, "status": s, "parent_id": None,
             "run_dir": str(runs / eid) if has_run else None}
        if agg:
            e["eval_status"] = {"inhouse_val": agg, "aggregate": agg}
        exps.append(e)
    _wj(st / "experiments.json", {"updated": iso(now - 2 * H), "experiments": exps}, 2 * H, now)
    _write(st / "events.jsonl", json.dumps({"ts": iso(now - 900), "type": "info", "level": "info", "actor": "fixture",
                                            "msg_zh": "测试事件", "msg_en": "fixture event"}) + "\n", 900.0, now)
    _wj(st / "briefing.json", {"updated": iso(now - 3 * H), "author": "fixture", "zh": "## 简报", "en": "## Briefing"}, 3 * H, now)
    _wj(st / "session_status.json", {"updated": "not-a-date", "model": "claude-fable-5-1"}, 1800.0, now)
    _wj(st / "session_watch.json", {"pid": 1, "ts": iso(now - 5), "since_id": 0, "started": iso(now - H)}, 5.0, now)
    _wj(st / "paper.json", {"updated": iso(now - 13 * H), "sections": [{"name": "Intro", "status": "draft", "words": 100}],
                            "figures": [], "references": {"total": 4, "verified_1x": 4, "verified_2x": 2, "verified_3x": 1}},
        13 * H, now)
    _wj(st / "literature.json", {"updated": iso(now - 30 * H), "papers": []}, 30 * H, now)
    _write(st / "routing.json", '{"updated": "2026-10-01T00:00:00Z", "rout', 100 * H, now)  # half-written
    lb = st / "leaderboard_events.jsonl"
    if lb.exists():
        lb.unlink()

    for eid, (coh, split) in RUN_CFG.items():
        d = runs / eid
        _write(d / "config.yaml", _cfg(coh, split, eid, fam[eid]), RUN_AGE[eid], now)
        _wj(d / "status.json", {"state": RUN_STATE[eid], "epoch": 2, "total_epochs": 10, "exp_id": eid, "name": f"{eid} synthetic",
                                "started": iso(now - 6 * H), "updated": iso(now - RUN_AGE[eid])}, RUN_AGE[eid], now)
        lines = []
        for k, v in enumerate(VAL_DICE.get(eid, [])):
            lines.append(json.dumps({"ts": iso(now - 6 * H + 600 * (k + 1)), "epoch": 2 * (k + 1), "step": 100 * (k + 1),
                                     "split": "val", "name": "dice", "value": v}))
        _write(d / "metrics.jsonl", "".join(x + "\n" for x in lines), RUN_AGE[eid], now)
    _wj(runs / "FB1" / "eval" / "inhouse_val_summary.json", {"dice": 0.87}, 1800.0, now)
    sm = runs / "FB1_smoke"
    _wj(sm / "status.json", {"state": "running", "updated": iso(now - 2 * H)}, 2 * H, now)
    _write(sm / "metrics.jsonl", "", 2 * H, now)
    (runs / "_discarded" / "old").mkdir(parents=True, exist_ok=True)

    for eid, (coh, split) in EXP_CFG.items():
        _write(out / "configs" / "exp" / f"{eid}.yaml", _cfg(coh, split, eid, fam[eid]), 5 * H, now)

    cells = []
    for ds, vals in (("inhouse_test_site01", {"FT1": 0.95, "FB1": 0.97}), ("inhouse_val", {"FT1": 0.88, "FB1": 0.87, "FB9": 0.89})):
        for m, v in vals.items():
            cells.append({"method": m, "dataset": ds, "metric": "dice", "mean": v, "std": 0.01, "n": 10})
    _wj(res / "summary.json", {
        "updated": iso(now - 1.5 * H),
        "datasets": [{"id": "inhouse_test_site01", "name_zh": "院内测试", "name_en": "In-house test", "split": "test_site01",
                      "postprocess": "none"},
                     {"id": "inhouse_val", "name_zh": "院内验证", "name_en": "In-house val", "split": "val", "postprocess": "none"}],
        "metrics": [{"id": "dice", "name_zh": "Dice", "name_en": "Dice", "higher_is_better": True}],
        "methods": [{"id": "FT1", "name": "FT1 ours", "family": "ours", "is_primary": True},
                    {"id": "FB1", "name": "FB1 base", "family": "baseline"}, {"id": "FB9", "name": "FB9 base", "family": "baseline"}],
        "cells": cells, "per_case": [], "pvalues": []}, 60.0, now)
    idx = []                                             # --merge keeps the base fixture's gallery (Results screenshots)
    if merge:
        try:
            idx = json.loads((res / "cases" / "index.json").read_text())
            idx = idx if isinstance(idx, list) else []
        except (OSError, ValueError):
            idx = []
        for k, e in enumerate(x for x in idx if isinstance(x, dict)):   # design-shaped keys too (dashboard/README.md §7)
            e.setdefault("id", e.get("case_id"))
            e.setdefault("title_zh", f"（测试）病例 {k + 1}")
            e.setdefault("title_en", f"(test) case {k + 1}")
            e.setdefault("dice", {"FT1": round(0.86 + 0.02 * k, 4), "FB1": round(0.88 - 0.01 * k, 4)})
            e.setdefault("note", "synthetic")
    _wj(res / "cases" / "index.json", idx, 600.0, now)
    guard.mark(out)
    return out


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if not args:
        print(__doc__)
        sys.exit(2)
    print(build(args[0], merge="--merge" in sys.argv[1:]))
