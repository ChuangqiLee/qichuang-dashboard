"""Demo-only finishing touches, run by demo/run_demo.sh after the fixture generators.

  * state/briefing.json: a synthetic progress briefing for the Overview.
  * Leaderboard runs (runs/LB_*): tests/make_leaderboard_fixture.py stamps them from a fixed 2026-10-01 clock (its
    tests need that); here their timestamps are shifted so the newest point is 5 minutes old and the running ones
    were just updated. Otherwise the alert strip shows "not updated for 48 000 min" warnings and the leaderboard
    milestones the server appends make the demo project look a month old.

    python -I demo/demo_extras.py <demo root>

The root must be a directory built by the generators (it carries their .qichuang-demo-root marker).
Everything written here is demo data, not a research result.
"""
from __future__ import annotations

import json
import os
import sys
import time
import types
from datetime import datetime, timezone
from pathlib import Path

H = 3600.0
TESTS = Path(__file__).resolve().parents[1] / "dashboard" / "tests"


def _load(name: str) -> types.ModuleType:
    """load dashboard/tests/<name>.py by path (python -I keeps it off sys.path; no __pycache__ is written)"""
    p = TESTS / f"{name}.py"
    m = types.ModuleType(name)
    m.__file__ = str(p)
    exec(compile(p.read_text(encoding="utf-8"), str(p), "exec"), m.__dict__)
    return m


def iso(t: float) -> str:
    return datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def wjson(p: Path, obj) -> None:
    """atomic write, as the data contract asks of every producer (tmp file + os.replace)"""
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, p)


def briefing(now: float) -> dict:
    zh = ("## 进展简报（演示数据）\n"
          "**已完成**：环境搭建、数据质控、文献调研（6 篇演示文献）。\n\n"
          "**进行中**：基线与新方法训练；`run_n2` 正在 GPU 0 上训练，排行榜实时对比最佳基线。\n\n"
          "**下一步**：训练结束后做正式评估，并更新 `results/summary.json`。\n\n"
          "> 本页所有数字均为合成测试数据，不是研究结果。")
    en = ("## Progress briefing (demo data)\n"
          "**Done**: environment, data QA, literature review (6 demo papers).\n\n"
          "**Running**: baseline and novel-method training; `run_n2` trains on GPU 0 and the leaderboard compares it "
          "with the best baseline live.\n\n"
          "**Next**: formal evaluation once training ends, then refresh `results/summary.json`.\n\n"
          "> Every number on this page is synthetic test data, not a research result.")
    return {"updated": iso(now - 1 * H), "author": "orchestrator (demo)", "zh": zh, "en": en}


def _ts(v) -> float | None:
    try:
        return datetime.fromisoformat(str(v).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def rebase_lb_runs(root: Path, now: float) -> None:
    """Shift the timestamps of runs/LB_* so that their newest metrics point is 5 min old; running runs get
    status `updated` = 1 min ago. Malformed and half-written metrics lines stay byte-for-byte (they are part of
    the demo)."""
    runs = [d for d in sorted((root / "runs").glob("LB_*")) if d.is_dir()]
    pts = []
    for d in runs:
        m = d / "metrics.jsonl"
        for line in m.read_text(encoding="utf-8").split("\n") if m.is_file() else []:
            try:
                pts.append(_ts(json.loads(line)["ts"]))
            except Exception:
                pass
    pts = [t for t in pts if t is not None]
    if not pts:
        return
    delta = now - 300 - max(pts)
    for d in runs:
        m = d / "metrics.jsonl"
        if m.is_file():
            out = []
            for line in m.read_text(encoding="utf-8").split("\n"):
                try:
                    o = json.loads(line)
                    o["ts"] = iso(_ts(o["ts"]) + delta)
                    line = json.dumps(o)
                except Exception:
                    pass  # malformed / half-written / ts-less lines stay as they are
                out.append(line)
            tmp = m.with_name(m.name + ".tmp")
            tmp.write_text("\n".join(out), encoding="utf-8")
            os.replace(tmp, m)
        s = d / "status.json"
        if s.is_file():
            st = json.loads(s.read_text(encoding="utf-8"))
            for k in ("started", "updated"):
                if _ts(st.get(k)) is not None:
                    st[k] = iso(_ts(st[k]) + delta)
            if st.get("state") == "running":
                st["updated"] = iso(now - 60)
            wjson(s, st)


def main() -> None:
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    guard = _load("_fixture_guard")
    root = guard.check(sys.argv[1])   # same refusals as the generators
    if not (root / guard.MARKER).is_file() or not (root / "state").is_dir():
        sys.exit(f"{root} is not a demo root built by the fixture generators (no {guard.MARKER} marker or no state/)")
    now = time.time()
    rebase_lb_runs(root, now)
    wjson(root / "state" / "briefing.json", briefing(now))
    print("demo extras written to", root / "state")


if __name__ == "__main__":
    main()
