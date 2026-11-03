"""Leaderboard API tests (rules: dashboard/README.md §18).  Synthetic data only; never touches the real project.

    cd <kit>/dashboard && OMP_NUM_THREADS=1 ../.venv/bin/python -m pytest tests/test_leaderboard_api.py -q -x

Expected numbers are hand-computed from the table in tests/make_leaderboard_fixture.py.

live val_dice (best so far), tol 0.003: best baseline B = LB_B1_done .900 (done -> not provisional)
  rank 1 LB_T1_cross  .910  Δ +.010  #1 and ahead      -> sota   trend up    (best at the last point)
  rank 2 LB_A1_abl    .909  Δ +.009                    -> ahead  trend final
  rank 3 LB_B1_done   .900  best baseline
  rank 4 LB_B2_run    .890  running baseline -> provisional
  rank 5 LB_T2_behind .880  Δ -.020                    -> behind trend final
  rank 6 LB_T3_flat   .750  Δ -.150                    -> behind trend flat  (best @4, last @20, not in last 3 points)
  rank - LB_T4_queued  —    (status.json only)
  crossings of LB_T1_cross (best-so-far .85 .89 .898 .899 .904 .9065 .9065 .910 at ep 2..16):
    tol .003: tie @6 (.898, Δ -.002), ahead @10 (.904, Δ +.004), sota @16 (.910 > A1 .909)
    tol 0   : tie @10, ahead @10, sota @16
    tol .01 : tie @4 (.89, Δ -.010), never ahead -> final verdict tie (still rank 1, no SOTA)
live val_hd95, tol 0.3: B = LB_B2_run 2.5 (running -> provisional); LB_T1_cross 2.1 Δ +0.4 -> sota (provisional)
  crossings: tie @10 (2.7, Δ -0.2), ahead @16, sota @16;  tol 0.5 -> tie
timeline back-fill (default tol): T1 dice behind->tie @6, tie->ahead @10, improved @12 (.904 -> .9065 >= .002),
  ahead->sota @16; T1 hd95 behind->tie @10, tie->sota @16  => 6 events, 3 events.jsonl milestones (to ahead/sota).
final inhouse_val dice mean: B = LB_B9_final .884; LB_T2_behind .886 Δ +.002 -> tie (rank 1, not sota);
  median: B = LB_B1_done .900; LB_T2_behind .905 -> sota, LB_A1_abl .902 -> tie.
"""
from __future__ import annotations

import importlib
import importlib.util
import json
import os
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
DASH = HERE.parent
# the real project the tests must never write into: $AN_REAL_ROOT, else $AN_ROOT, else the directory that holds
# dashboard/ (read at import, before any fixture sets AN_ROOT)
REAL_ROOT = Path(os.environ.get("AN_REAL_ROOT") or os.environ.get("AN_ROOT") or DASH.parent).resolve()

for _v in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS"):
    os.environ.setdefault(_v, "1")


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


mlf = _load("make_leaderboard_fixture", HERE / "make_leaderboard_fixture.py")
APPROX = dict(abs=1e-9)


@pytest.fixture(scope="module")
def server(tmp_path_factory):
    boot = tmp_path_factory.mktemp("an_lb_boot")
    mlf.build(boot)
    saved = {k: os.environ.get(k) for k in ("AN_ROOT", "AN_LEADERBOARD_READONLY", "AN_TRANSCRIPTS", "AN_RAW", "AN_DEMO")}
    os.environ["AN_ROOT"] = str(boot)
    os.environ["AN_TRANSCRIPTS"] = str(boot / "transcripts")   # never scan real Claude Code transcripts
    os.environ.pop("AN_RAW", None)                              # no `du` over a real data directory
    os.environ.pop("AN_DEMO", None)
    os.environ.pop("AN_LEADERBOARD_READONLY", None)
    if str(DASH) not in sys.path:
        sys.path.insert(0, str(DASH))
    srv = importlib.reload(sys.modules["server"]) if "server" in sys.modules else importlib.import_module("server")
    assert srv.STATE.resolve() == (boot / "state").resolve()
    yield srv
    for k, v in saved.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v


def clear(srv) -> None:
    srv.CACHE._d.clear()
    srv._lb_cache.clear()
    srv._json_cache.clear()
    for rm in list(srv._runs.values()):
        rm.last_check = 0.0


@pytest.fixture
def lb(server, tmp_path, monkeypatch):
    """a fresh fixture tree per test; the server module globals are pointed at it"""
    root = mlf.build(tmp_path / "proj")
    for name, sub in (("ROOT", ""), ("STATE", "state"), ("RUNS", "runs"), ("RESULTS", "results"), ("CASES", "results/cases")):
        monkeypatch.setattr(server, name, root / sub if sub else root)
    monkeypatch.delenv("AN_LEADERBOARD_READONLY", raising=False)
    server._runs.clear()
    server.LB_TL.reset()
    clear(server)
    # hard guard: nothing below may write into the real project
    assert REAL_ROOT not in server.lb_state_path().resolve().parents
    from fastapi.testclient import TestClient

    with TestClient(server.app, base_url="http://127.0.0.1:17100") as client:
        yield {"srv": server, "root": root, "client": client, "state": root / "state"}
    server._runs.clear()
    server.LB_TL.reset()
    clear(server)


def get(env, url: str) -> dict:
    clear(env["srv"])
    r = env["client"].get(url)
    assert r.status_code == 200
    return r.json()


def rows_by_id(p: dict) -> dict:
    return {r["run_id"]: r for r in p["rows"]}


def lb_events(env) -> list[dict]:
    p = env["state"] / "leaderboard_events.jsonl"
    return [json.loads(x) for x in p.read_text().splitlines() if x.strip()] if p.exists() else []


def milestones(env) -> list[dict]:
    p = env["state"] / "events.jsonl"
    return [o for o in (json.loads(x) for x in p.read_text().splitlines() if x.strip()) if o.get("actor") == "leaderboard"]


# ----------------------------------------------------------------------------- live table
def test_live_dice_default_tol(lb):
    p = get(lb, "/api/leaderboard?scope=live&metric=val_dice")
    assert p["ok"] and p["scope"] == "live" and p["metric"] == "val_dice" and p["hib"] is True
    assert p["tol"] == pytest.approx(0.003) and p["tol_default"] == pytest.approx(0.003)
    assert p["best_baseline"]["id"] == "LB_B1_done" and p["best_baseline"]["value"] == pytest.approx(0.900)
    assert p["best_baseline"]["provisional"] is False
    assert p["sota"]["id"] == "LB_T1_cross" and p["sota"]["verdict"] == "sota" and p["sota"]["is_ours"] is True
    ids = [r["run_id"] for r in p["rows"]]
    assert ids == ["LB_T1_cross", "LB_A1_abl", "LB_B1_done", "LB_B2_run", "LB_T2_behind", "LB_T3_flat", "LB_T4_queued"]
    R = rows_by_id(p)
    assert [R[i]["rank"] for i in ids] == [1, 2, 3, 4, 5, 6, None]
    t1 = R["LB_T1_cross"]
    assert t1["value"] == pytest.approx(0.910) and t1["current"] == pytest.approx(0.910) and t1["best_epoch"] == 16
    assert t1["verdict"] == "sota" and t1["trend"] == "up" and t1["provisional"] is False
    assert t1["delta"] == pytest.approx(0.010, **APPROX) and t1["delta_sota"] == pytest.approx(0.0, **APPROX)
    assert t1["family"] == "ours" and t1["family_raw"] == "novel" and t1["status"] == "running"
    assert t1["epoch"] == 16 and t1["total_epochs"] == 20 and t1["n_points"] == 8   # malformed + partial lines skipped
    assert t1["sparkline"][0] == [2, pytest.approx(0.85)] and len(t1["sparkline"]) == 8
    assert [v for _e, v in t1["sparkline_best"]][-3:] == [pytest.approx(0.9065), pytest.approx(0.9065), pytest.approx(0.910)]
    a1 = R["LB_A1_abl"]
    assert a1["family"] == "ablation" and a1["verdict"] == "ahead" and a1["trend"] == "final"
    assert a1["delta"] == pytest.approx(0.009, **APPROX) and a1["delta_sota"] == pytest.approx(-0.001, **APPROX)
    b1, b2 = R["LB_B1_done"], R["LB_B2_run"]
    assert b1["is_best_baseline"] and b1["verdict"] is None and b1["provisional"] is False
    assert b2["verdict"] is None and b2["provisional"] is True and b2["trend"] == "up"
    assert b2["delta"] == pytest.approx(-0.010, **APPROX)
    t2, t3, t4 = R["LB_T2_behind"], R["LB_T3_flat"], R["LB_T4_queued"]
    assert t2["verdict"] == "behind" and t2["delta"] == pytest.approx(-0.020, **APPROX) and t2["trend"] == "final"
    assert t2["current"] == pytest.approx(0.87) and t2["best_epoch"] == 8
    assert t3["verdict"] == "behind" and t3["trend"] == "flat" and t3["best_epoch"] == 4
    assert t4["value"] is None and t4["verdict"] is None and t4["rank"] is None and t4["sparkline"] == []
    # exclusions: smoke, unregistered, _discarded
    assert not {"LB_T1_cross_smoke", "LB_X_unreg", "_discarded", "LB_T1_old", "LB_P_planned"} & set(ids)
    # crossings only for our runs, against the current best baseline
    assert set(p["crossings"]) == {"LB_T1_cross", "LB_T2_behind", "LB_T3_flat", "LB_T4_queued"}
    assert p["crossings"]["LB_T1_cross"] == {"tie": 6, "ahead": 10, "sota": 16}
    assert p["crossings"]["LB_T2_behind"] == {"tie": None, "ahead": None, "sota": None}
    assert {m["id"] for m in p["metrics"]} == {"val_dice", "val_hd95", "val_dice_aux", "val_dice_mean"}
    assert {m["id"]: m["available"] for m in p["metrics"]}["val_dice_aux"] is False


def test_live_strict_and_wide_tolerance(lb):
    p = get(lb, "/api/leaderboard?scope=live&metric=val_dice&tol=0")
    assert p["tol"] == 0.0
    R = rows_by_id(p)
    assert R["LB_T1_cross"]["verdict"] == "sota" and R["LB_A1_abl"]["verdict"] == "ahead"
    assert p["crossings"]["LB_T1_cross"] == {"tie": 10, "ahead": 10, "sota": 16}
    p = get(lb, "/api/leaderboard?scope=live&metric=val_dice&tol=0.01")
    R = rows_by_id(p)
    assert p["tol"] == pytest.approx(0.01)
    assert R["LB_T1_cross"]["verdict"] == "tie" and R["LB_T1_cross"]["rank"] == 1   # #1 but not ahead -> no SOTA
    assert R["LB_A1_abl"]["verdict"] == "tie" and p["sota"]["verdict"] == "tie"
    assert p["crossings"]["LB_T1_cross"] == {"tie": 4, "ahead": None, "sota": None}


def test_tolerance_clamp_and_bad_values(lb):
    assert get(lb, "/api/leaderboard?metric=val_dice&tol=0.5")["tol"] == pytest.approx(0.05)
    assert get(lb, "/api/leaderboard?metric=val_dice&tol=-1")["tol"] == 0.0
    assert get(lb, "/api/leaderboard?metric=val_dice&tol=abc")["tol"] == pytest.approx(0.003)
    assert get(lb, "/api/leaderboard?metric=val_dice&tol=nan")["tol"] == pytest.approx(0.003)
    assert get(lb, "/api/leaderboard?metric=val_hd95&tol=9")["tol"] == pytest.approx(5.0)
    assert get(lb, "/api/leaderboard?metric=val_hd95")["tol"] == pytest.approx(0.3)
    bad = get(lb, "/api/leaderboard?metric=val_nope")
    assert bad["ok"] is False and "unknown" in bad["error"]
    assert get(lb, "/api/leaderboard?scope=weird")["ok"] is False


def test_hd95_direction_and_provisional(lb):
    p = get(lb, "/api/leaderboard?scope=live&metric=val_hd95")
    assert p["hib"] is False and p["kind"] == "dist"
    assert p["best_baseline"] == {"id": "LB_B2_run", "name": "Baseline two (running)", "value": pytest.approx(2.5),
                                  "status": "running", "provisional": True}
    ids = [r["run_id"] for r in p["rows"] if r["rank"] is not None]
    assert ids == ["LB_T1_cross", "LB_B2_run", "LB_B1_done", "LB_A1_abl", "LB_T2_behind"]
    R = rows_by_id(p)
    t1 = R["LB_T1_cross"]
    assert t1["value"] == pytest.approx(2.1) and t1["delta"] == pytest.approx(0.4, **APPROX)   # positive = better
    assert t1["verdict"] == "sota" and t1["provisional"] is True and t1["current"] == pytest.approx(2.1)
    assert R["LB_A1_abl"]["delta"] == pytest.approx(-0.8, **APPROX) and R["LB_A1_abl"]["verdict"] == "behind"
    assert R["LB_A1_abl"]["provisional"] is True
    assert R["LB_T3_flat"]["value"] is None and R["LB_T3_flat"]["rank"] is None   # no hd95 series, no status fallback
    assert p["crossings"]["LB_T1_cross"] == {"tie": 10, "ahead": 16, "sota": 16}
    p = get(lb, "/api/leaderboard?scope=live&metric=val_hd95&tol=0.5")
    assert rows_by_id(p)["LB_T1_cross"]["verdict"] == "tie"


def test_trend_window_helper(lb):
    s = lb["srv"]
    pts = [(e, v, None) for e, v in [(2, .5), (4, .6), (6, .7), (20, .69), (40, .68)]]
    assert s.lb_trend(pts, 2, "running") == "up"        # best is one of the last 3 points (34 epochs ago)
    pts2 = [(e, v, None) for e, v in [(2, .5), (4, .6), (6, .7), (8, .69), (10, .68), (12, .67), (14, .66)]]
    assert s.lb_trend(pts2, 2, "running") == "flat"     # best @6, last @14 (8 >= 6), 4 points after the best
    pts3 = [(e, v, None) for e, v in [(1, .5), (2, .7), (3, .6), (4, .6), (5, .6), (6, .6)]]
    assert s.lb_trend(pts3, 1, "running") == "up"       # 6 - 2 = 4 < 6 epochs
    assert s.lb_trend(pts3, 1, "done") == "final"
    assert s.lb_trend([], None, "running") == "flat"


def test_cache_key_includes_tol(lb):
    s, c = lb["srv"], lb["client"]
    clear(s)
    a = c.get("/api/leaderboard?metric=val_dice&tol=0.003").json()
    b = c.get("/api/leaderboard?metric=val_dice&tol=0.01").json()      # no cache clear in between
    assert rows_by_id(a)["LB_T1_cross"]["verdict"] == "sota" and rows_by_id(b)["LB_T1_cross"]["verdict"] == "tie"
    assert {k[4] for k in s._lb_cache} >= {0.003, 0.01}


# ----------------------------------------------------------------------------- final scope
def test_final_scope(lb):
    p = get(lb, "/api/leaderboard?scope=final")
    assert p["ok"] and p["dataset"] == "inhouse_val" and p["metric"] == "dice" and p["stat"] == "mean"
    assert p["best_baseline"]["id"] == "LB_B9_final" and p["best_baseline"]["value"] == pytest.approx(0.884)
    R = rows_by_id(p)
    assert [r["run_id"] for r in p["rows"]] == ["LB_T2_behind", "LB_B9_final", "LB_B1_done", "LB_A1_abl"]
    t2 = R["LB_T2_behind"]
    assert t2["verdict"] == "tie" and t2["rank"] == 1 and t2["delta"] == pytest.approx(0.002, **APPROX)
    assert t2["ci_low"] == pytest.approx(0.876) and t2["ci_high"] == pytest.approx(0.896) and t2["n"] == 10
    assert t2["trend"] == "final" and t2["provisional"] is False and t2["sparkline"] == []
    assert R["LB_B1_done"]["value"] == pytest.approx(0.880)            # duplicate cell ignored
    assert R["LB_A1_abl"]["verdict"] == "behind" and p["sota"]["id"] == "LB_T2_behind" and p["sota"]["verdict"] == "tie"
    assert p["crossings"] == {} and {d["id"] for d in p["datasets"]} == {"inhouse_val", "inhouse_test_site01"}
    p = get(lb, "/api/leaderboard?scope=final&dataset=inhouse_val&metric=dice&stat=median")
    R = rows_by_id(p)
    assert p["best_baseline"]["id"] == "LB_B1_done" and R["LB_T2_behind"]["verdict"] == "sota"
    assert R["LB_A1_abl"]["verdict"] == "tie" and R["LB_T2_behind"]["delta"] == pytest.approx(0.005, **APPROX)
    # live metric ids map onto the final metric
    assert get(lb, "/api/leaderboard?scope=final&metric=val_dice")["metric"] == "dice"


def test_final_scope_hd95_and_median_fallback(lb):
    p = get(lb, "/api/leaderboard?scope=final&metric=hd95")
    assert p["hib"] is False and p["kind"] == "dist" and p["tol"] == pytest.approx(0.3)
    R = rows_by_id(p)
    assert p["best_baseline"]["id"] == "LB_B9_final" and R["LB_T2_behind"]["delta"] == pytest.approx(0.2, **APPROX)
    assert R["LB_T2_behind"]["verdict"] == "tie"
    p = get(lb, "/api/leaderboard?scope=final&metric=hd95&tol=0.1")
    assert rows_by_id(p)["LB_T2_behind"]["verdict"] == "sota"
    p = get(lb, "/api/leaderboard?scope=final&metric=hd95&stat=median")
    R = rows_by_id(p)
    assert R["LB_B9_final"]["median_fallback"] is True and R["LB_B9_final"]["value"] == pytest.approx(2.8)
    assert p["best_baseline"]["id"] == "LB_B9_final" and R["LB_T2_behind"]["verdict"] == "tie"   # Δ 0.3 <= tol 0.3
    p = get(lb, "/api/leaderboard?scope=final&metric=rve")
    assert p["hib"] is False and p["kind"] == "ratio" and p["best_baseline"]["id"] == "LB_B1_done"
    assert rows_by_id(p)["LB_T2_behind"]["verdict"] == "tie"
    assert get(lb, "/api/leaderboard?scope=final&dataset=nope")["ok"] is False
    assert get(lb, "/api/leaderboard?scope=final&metric=nope")["ok"] is False


# ----------------------------------------------------------------------------- timeline
def test_backfill_events_and_milestones(lb):
    p = get(lb, "/api/leaderboard")
    ev = lb_events(lb)
    got = [(e["metric"], e["kind"], e["from"], e["to"], e["epoch"]) for e in ev]
    assert got == [("val_dice", "verdict", "behind", "tie", 6), ("val_dice", "verdict", "tie", "ahead", 10),
                   ("val_dice", "improved", "ahead", "ahead", 12), ("val_dice", "verdict", "ahead", "sota", 16),
                   ("val_hd95", "verdict", "behind", "tie", 10), ("val_hd95", "verdict", "tie", "sota", 16)]
    assert all(e["run_id"] == "LB_T1_cross" for e in ev)
    e = ev[1]
    assert e["ts"] == mlf.ts_of("LB_T1_cross", 10) and e["backfill"] is True     # historical ts of the crossing
    assert e["baseline_id"] == "LB_B1_done" and e["baseline"] == pytest.approx(0.9) and e["tol"] == pytest.approx(0.003)
    assert e["value"] == pytest.approx(0.904) and "超越最佳基线 LB_B1_done" in e["msg_zh"] and "ahead" in e["msg_en"]
    assert ev[2]["prev"] == pytest.approx(0.904) and ev[2]["value"] == pytest.approx(0.9065)
    assert ev[5]["provisional"] is True and ev[5]["baseline_id"] == "LB_B2_run"
    # API: newest first, ≤ 50
    # (equal ts: verdict changes before `improved`, val_dice before val_hd95)
    order = sorted(range(len(ev)), key=lambda i: (ev[i]["ts"], ev[i]["kind"] == "verdict", ev[i]["metric"] == "val_dice", i),
                   reverse=True)
    assert [x["id"] for x in p["events"]] == [ev[i]["id"] for i in order]
    ms = milestones(lb)
    assert len(ms) == 3 and all(m["type"] == "milestone" and m["level"] == "info" for m in ms)
    assert {m["msg_en"] for m in ms} == {ev[1]["msg_en"], ev[3]["msg_en"], ev[5]["msg_en"]}   # ahead / sota only
    st = json.loads((lb["state"] / "leaderboard_state.json").read_text())
    assert st["keys"]["LB_T1_cross|val_dice"]["n"] == 8 and st["keys"]["LB_T1_cross|val_dice"]["verdict"] == "sota"
    assert st["keys"]["LB_T2_behind|val_dice"]["verdict"] == "behind"
    q = get(lb, "/api/leaderboard/events?limit=2")
    assert q["ok"] and q["count"] == 2 and q["total"] == 6 and q["events"][0]["id"] == p["events"][0]["id"]
    assert get(lb, "/api/leaderboard/events?limit=99999")["count"] == 6
    assert get(lb, "/api/leaderboard/events?run_id=LB_T2_behind")["count"] == 0


def test_backfill_is_idempotent(lb):
    s = lb["srv"]
    get(lb, "/api/leaderboard")
    n_ev, n_ms = len(lb_events(lb)), len(milestones(lb))
    assert (n_ev, n_ms) == (6, 3)
    for _ in range(3):                                           # same data -> nothing new
        get(lb, "/api/leaderboard")
    assert (len(lb_events(lb)), len(milestones(lb))) == (6, 3)
    s.LB_TL.reset()                                              # process restart
    get(lb, "/api/leaderboard")
    assert (len(lb_events(lb)), len(milestones(lb))) == (6, 3)
    (lb["state"] / "leaderboard_state.json").unlink()            # state lost: event ids still dedupe
    s.LB_TL.reset()
    get(lb, "/api/leaderboard")
    assert (len(lb_events(lb)), len(milestones(lb))) == (6, 3)
    (lb["state"] / "leaderboard_state.json").write_text("{broken")   # malformed state tolerated
    s.LB_TL.reset()
    p = get(lb, "/api/leaderboard")
    assert p["ok"] and p["timeline_error"] is None and len(lb_events(lb)) == 6


def test_incremental_improvement_and_baseline_change(lb):
    get(lb, "/api/leaderboard")
    mlf.append_val(lb["root"], "LB_T1_cross", 18, dice=0.9125, hd95=2.05)   # +.0025 over .910 while sota
    p = get(lb, "/api/leaderboard")
    ev = lb_events(lb)
    assert len(ev) == 7 and ev[-1]["kind"] == "improved" and ev[-1]["epoch"] == 18 and ev[-1]["to"] == "sota"
    assert ev[-1]["prev"] == pytest.approx(0.910) and len(milestones(lb)) == 3   # improvements are not milestones
    assert rows_by_id(p)["LB_T1_cross"]["value"] == pytest.approx(0.9125)
    # the running baseline overtakes: B = .915 (provisional); T1 .9125 -> Δ -.0025 -> tie (no new T1 point)
    mlf.append_val(lb["root"], "LB_B2_run", 8, dice=0.915, hd95=2.6)
    p = get(lb, "/api/leaderboard")
    assert p["best_baseline"]["id"] == "LB_B2_run" and p["best_baseline"]["provisional"] is True
    t1 = rows_by_id(p)["LB_T1_cross"]
    assert t1["verdict"] == "tie" and t1["provisional"] is True and t1["delta"] == pytest.approx(-0.0025, **APPROX)
    ev = lb_events(lb)
    assert len(ev) == 8
    last = ev[-1]
    assert (last["from"], last["to"], last["baseline_id"], last["backfill"]) == ("sota", "tie", "LB_B2_run", False)
    assert "失去 ★ SOTA" in last["msg_zh"] and len(milestones(lb)) == 3
    get(lb, "/api/leaderboard")
    assert len(lb_events(lb)) == 8


def test_readonly_flag_writes_nothing(lb, monkeypatch):
    monkeypatch.setenv("AN_LEADERBOARD_READONLY", "1")
    before = (lb["state"] / "events.jsonl").read_bytes()
    p = get(lb, "/api/leaderboard")
    assert p["readonly"] is True and len(p["events"]) == 6          # computed in memory
    assert not (lb["state"] / "leaderboard_state.json").exists()
    assert not (lb["state"] / "leaderboard_events.jsonl").exists()
    assert (lb["state"] / "events.jsonl").read_bytes() == before
    get(lb, "/api/leaderboard")
    assert len(get(lb, "/api/leaderboard/events")["events"]) == 6   # no in-memory duplicates either


def test_overview_card(lb):
    o = get(lb, "/api/overview")
    L = o["leaderboard"]
    assert L["best_baseline"]["id"] == "LB_B1_done" and L["top_ours"]["run_id"] == "LB_T1_cross"
    assert L["top_ours"]["verdict"] == "sota" and L["top_ours"]["delta"] == pytest.approx(0.01, **APPROX)
    assert [r["run_id"] for r in L["ours"]] == ["LB_T1_cross", "LB_T2_behind", "LB_T3_flat"]
    assert L["latest_event"]["to"] == "sota" and L["latest_event"]["epoch"] == 16
    # val_dice and val_hd95 both reach SOTA at the same point ts: the Dice event wins the tie, and the client gets
    # the recent list too (so a same-ts HD95 / improved event cannot hide a SOTA event from the toast check)
    assert L["latest_event"]["metric"] == "val_dice"
    assert len(L["recent_events"]) == 6 and L["recent_events"][0]["id"] == L["latest_event"]["id"]
    assert {(e["metric"], e["to"]) for e in L["recent_events"]} >= {("val_dice", "sota"), ("val_hd95", "sota")}


def test_malformed_and_missing_files(lb):
    s = lb["srv"]
    (lb["root"] / "runs" / "LB_T2_behind" / "status.json").write_text("{not json")
    (lb["root"] / "results" / "summary.json").unlink()
    p = get(lb, "/api/leaderboard")
    assert p["ok"]
    t2 = rows_by_id(p)["LB_T2_behind"]
    assert t2["value"] == pytest.approx(0.88) and t2["status"] == "done"     # falls back to experiments.json status
    f = get(lb, "/api/leaderboard?scope=final")
    assert f["ok"] and f["missing"] is True and f["rows"] == []
    (lb["root"] / "results" / "summary.json").write_text("[1, 2")
    assert get(lb, "/api/leaderboard?scope=final")["missing"] is True
    (lb["state"] / "experiments.json").write_text("garbage")
    p = get(lb, "/api/leaderboard")
    assert p["ok"] and p["rows"] == [] and p["best_baseline"] is None
    (lb["state"] / "leaderboard_events.jsonl").write_text("garbage\n")
    s.LB_TL.reset()
    assert get(lb, "/api/leaderboard/events")["bad_lines"] == 1


def test_routes_registered_before_fallback(lb):
    paths = [getattr(r, "path", "") for r in lb["srv"].app.routes]
    assert paths.index("/api/leaderboard") < paths.index("/api/{rest:path}")
    assert paths.index("/api/leaderboard/events") < paths.index("/api/{rest:path}")


def test_merge_on_base_fixture(server, tmp_path, monkeypatch):
    """the builder layers onto tests/make_fixture.py output without breaking it (other runs just join the table)"""
    pytest.importorskip("matplotlib")
    import subprocess

    root = tmp_path / "base"
    r = subprocess.run([sys.executable, "-I", str(HERE / "make_fixture.py"), str(root)], capture_output=True, timeout=300,
                       env={**os.environ, "MPLBACKEND": "Agg"})
    assert r.returncode == 0, r.stderr.decode()[-500:]
    mlf.build(root, merge=True)
    for name, sub in (("ROOT", ""), ("STATE", "state"), ("RUNS", "runs"), ("RESULTS", "results")):
        monkeypatch.setattr(server, name, root / sub if sub else root)
    monkeypatch.setenv("AN_LEADERBOARD_READONLY", "1")
    server._runs.clear()
    server.LB_TL.reset()
    clear(server)
    try:
        from fastapi.testclient import TestClient

        with TestClient(server.app, base_url="http://127.0.0.1:17100") as c:
            p = c.get("/api/leaderboard").json()
            ids = {x["run_id"] for x in p["rows"]}
            assert p["ok"] and {"LB_T1_cross", "run_b1", "run_n2"} <= ids
            f = c.get("/api/leaderboard?scope=final&dataset=inhouse").json()
            assert f["ok"] and "ours" in {x["run_id"] for x in f["rows"]}
            assert c.get("/api/results").json()["ok"]
    finally:
        server._runs.clear()
        server.LB_TL.reset()
        clear(server)


# ----------------------------------------------------------------------------- review fixes (LB-DE-1..4, RC-1/2, UX1)
def add_run(env, rid: str, fam: str, state: str, lines: list[dict], total: int = 20) -> None:
    """register a run in experiments.json and write its metrics.jsonl / status.json"""
    ep = env["state"] / "experiments.json"
    d = json.loads(ep.read_text())
    d["experiments"].append({"id": rid, "name": rid, "family": fam, "status": state, "run_dir": f"/x/runs/{rid}"})
    ep.write_text(json.dumps(d))
    rd = env["root"] / "runs" / rid
    rd.mkdir(parents=True, exist_ok=True)
    (rd / "metrics.jsonl").write_text("".join(json.dumps({"split": "val", **o}) + "\n" for o in lines))
    last = [o.get("epoch") for o in lines if o.get("epoch") is not None]
    (rd / "status.json").write_text(json.dumps({"state": state, "epoch": last[-1] if last else 3, "total_epochs": total,
                                                "name": rid, "best": {}}))


def test_failed_runs_are_shown_but_not_counted(lb):
    add_run(lb, "LB_B0_failed", "baseline", "failed",
            [{"epoch": 2, "ts": mlf.ts_of("x", 2), "name": "dice", "value": 0.80},
             {"epoch": 4, "ts": mlf.ts_of("x", 4), "name": "dice", "value": 0.95},
             {"epoch": 4, "ts": mlf.ts_of("x", 4), "name": "hd95", "value": 1.0}])
    add_run(lb, "LB_T9_failed", "novel", "failed", [{"epoch": 2, "ts": mlf.ts_of("x", 2), "name": "dice", "value": 0.99}])
    p = get(lb, "/api/leaderboard")
    R = rows_by_id(p)
    assert p["best_baseline"]["id"] == "LB_B1_done" and p["sota"]["id"] == "LB_T1_cross"
    for rid in ("LB_B0_failed", "LB_T9_failed"):
        assert R[rid]["not_counted"] is True and R[rid]["rank"] is None and R[rid]["verdict"] is None
        assert R[rid]["is_best_baseline"] is False
    assert R["LB_T1_cross"]["verdict"] == "sota" and R["LB_T1_cross"]["not_counted"] is False
    assert [r["run_id"] for r in p["rows"]].index("LB_B0_failed") > [r["run_id"] for r in p["rows"]].index("LB_A1_abl")
    h = get(lb, "/api/leaderboard?metric=val_hd95")
    assert h["best_baseline"]["id"] != "LB_B0_failed"
    assert all(e["run_id"] == "LB_T1_cross" for e in lb_events(lb)) and len(lb_events(lb)) == 6
    o = get(lb, "/api/overview")["leaderboard"]
    assert o["top_ours"]["run_id"] == "LB_T1_cross" and "LB_T9_failed" not in [r["run_id"] for r in o["ours"]]


def _rewrite(env, rid: str, pts: list[tuple]) -> None:
    lines = []
    for ep, dice, hd in pts:
        lines += mlf.val_lines(rid, ep, dice, hd)
    (env["root"] / "runs" / rid / "metrics.jsonl").write_text("\n".join(lines) + "\n")


T1_PTS = list(zip(range(2, 17, 2), [0.85, 0.89, 0.898, 0.899, 0.904, 0.9065, 0.905, 0.910],
                  [8, 5, 3.0, 2.9, 2.7, 2.6, 2.65, 2.1]))


def test_truncated_series_emits_one_reset_event_now(lb):
    get(lb, "/api/leaderboard")
    assert len(lb_events(lb)) == 6
    _rewrite(lb, "LB_T1_cross", T1_PTS[:6])                       # restarted run: epochs <= 12 only
    p = get(lb, "/api/leaderboard")
    t1 = rows_by_id(p)["LB_T1_cross"]
    assert t1["verdict"] == "ahead" and t1["value"] == pytest.approx(0.9065)
    new = lb_events(lb)[6:]
    got = sorted((e["metric"], e["from"], e["to"], e["epoch"], e.get("reset"), e["backfill"]) for e in new)
    assert got == [("val_dice", "sota", "ahead", 12, True, False), ("val_hd95", "sota", "tie", 12, True, False)]
    assert all(e["ts"] > mlf.ts_of("LB_T1_cross", 16) for e in new)   # ts = now, not a historical epoch
    assert p["events"][0]["id"] in {e["id"] for e in new}           # the newest entry matches the table
    assert len(milestones(lb)) == 3                                  # downgrades are not milestones
    get(lb, "/api/leaderboard")
    assert len(lb_events(lb)) == 8                                   # and the new state is stable


def test_replaced_series_same_length_is_detected(lb):
    get(lb, "/api/leaderboard")
    _rewrite(lb, "LB_T1_cross", [(ep, d - 0.05, hd + 3) for ep, d, hd in T1_PTS])   # same n, other values
    p = get(lb, "/api/leaderboard")
    assert rows_by_id(p)["LB_T1_cross"]["verdict"] == "behind"
    new = lb_events(lb)[6:]
    assert sorted((e["metric"], e["from"], e["to"], e.get("reset")) for e in new) == \
        [("val_dice", "sota", "behind", True), ("val_hd95", "sota", "behind", True)]


def test_lost_state_after_baseline_change_adds_no_contradicting_event(lb):
    s = lb["srv"]
    get(lb, "/api/leaderboard")
    mlf.append_val(lb["root"], "LB_B2_run", 8, dice=0.915, hd95=2.6)    # running baseline overtakes T1 (.910)
    get(lb, "/api/leaderboard")
    ev = lb_events(lb)
    assert len(ev) == 7 and (ev[-1]["from"], ev[-1]["to"]) == ("sota", "behind")
    (lb["state"] / "leaderboard_state.json").unlink()
    s.LB_TL.reset()
    get(lb, "/api/leaderboard")
    assert len(lb_events(lb)) == 7 and len(milestones(lb)) == 3
    st = json.loads((lb["state"] / "leaderboard_state.json").read_text())
    assert st["keys"]["LB_T1_cross|val_dice"]["verdict"] == "behind"


def test_backfill_flag_only_for_history(lb):
    import datetime as dt
    get(lb, "/api/leaderboard")
    assert all(e["backfill"] is True for e in lb_events(lb))          # first replay = reconstructed history
    now = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    with open(lb["root"] / "runs" / "LB_T1_cross" / "metrics.jsonl", "a") as fh:
        fh.write("\n" + json.dumps({"ts": now, "epoch": 18, "step": 180, "split": "val", "name": "dice", "value": 0.915}) + "\n")
    get(lb, "/api/leaderboard")
    last = lb_events(lb)[-1]
    assert (last["kind"], last["epoch"], last["ts"], last["backfill"]) == ("improved", 18, now, False)


def test_resumed_run_duplicate_epochs_and_step_only_series(lb):
    ts = mlf.ts_of("x", 1)
    pts = [(e, 0.80 + 0.01 * e) for e in range(1, 7)] + [(e, 0.79 + 0.01 * e) for e in range(4, 9)]
    add_run(lb, "LB_T5_dup", "novel", "running", [{"epoch": e, "step": 10 * e, "ts": ts, "name": "dice", "value": v} for e, v in pts])
    add_run(lb, "LB_T6_noep", "novel", "running", [{"step": 100, "ts": ts, "name": "dice", "value": 0.81},
                                                     {"step": 200, "ts": ts, "name": "dice", "value": 0.82}], total=10)
    add_run(lb, "LB_T7_mixed", "novel", "running", [{"epoch": 1, "ts": ts, "name": "dice", "value": 0.70},
                                                      {"step": 999, "ts": ts, "name": "dice", "value": 0.99}])
    R = rows_by_id(get(lb, "/api/leaderboard"))
    d = R["LB_T5_dup"]
    xs = [x for x, _v in d["sparkline"]]
    assert xs == sorted(set(xs)) == list(range(1, 9)) and d["n_points"] == 8
    assert dict(map(tuple, d["sparkline"]))[4] == pytest.approx(0.83) and d["value"] == pytest.approx(0.87)
    assert [x for x, _ in d["sparkline_best"]] == list(range(1, 9)) and d["x_unit"] == "epoch"
    n = R["LB_T6_noep"]
    assert n["x_unit"] == "step" and n["best_epoch"] == 200 and n["epoch"] == 3 and n["trend"] == "up"
    m = R["LB_T7_mixed"]                       # a point without an epoch is dropped when others carry one
    assert m["x_unit"] == "epoch" and m["value"] == pytest.approx(0.70) and m["n_points"] == 1


def test_step_unit_event_text(lb):
    s = lb["srv"]
    zh, en = s.lb_event_text({"run_id": "R", "metric": "val_dice", "epoch": 200, "x_unit": "step", "from": "tie", "to": "ahead",
                              "value": 0.91, "baseline": 0.9, "baseline_id": "B", "tol": 0.003, "kind": "verdict"})
    assert "第 200 步" in zh and "step 200" in en and "轮" not in zh and "epoch" not in en
