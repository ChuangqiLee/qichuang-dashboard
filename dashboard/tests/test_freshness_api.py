"""Freshness / auto phase progress / hidden runs API tests (dashboard/README.md §19).  Synthetic data only.

    cd <kit>/dashboard && OMP_NUM_THREADS=1 ../.venv/bin/python -m pytest tests/test_freshness_api.py -q -x

Expected values are hand-computed from the tables in tests/make_freshness_fixture.py (ages relative to NOW):
  stale: runs (T5_R2 silent 300 s > 180 s), briefing (3 h > 2 h periodic), paper (13 h > 12 h, phase paper running)
  fresh: events (sporadic), system, session (heartbeat 5 s), results_summary / experiments / run_eval (event),
         session_status (30 min < 2 h, mtime fallback), workflow (1 h < 12 h), literature (no running dependant),
         routing (manual, never), cases (manual, never); leaderboard_events missing (not stale)
  auto progress: train_base 1/3, train_novel 3/4, vjepa 1/2, r2 0/2, evaluate 4/6
"""
from __future__ import annotations

import importlib
import importlib.util
import json
import os
import sys
import time
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
DASH = HERE.parent
# the real project the tests must never write into: $AN_REAL_ROOT, else $AN_ROOT, else the directory that holds
# dashboard/ (read at import, before any fixture sets AN_ROOT)
REAL_ROOT = Path(os.environ.get("AN_REAL_ROOT") or os.environ.get("AN_ROOT") or DASH.parent).resolve()
H = 3600.0

for _v in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS"):
    os.environ.setdefault(_v, "1")


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


mff = _load("make_freshness_fixture", HERE / "make_freshness_fixture.py")
STALE = {"runs", "briefing", "paper"}
ALL_IDS = ["runs", "events", "system", "session", "results_summary", "experiments", "leaderboard_events", "run_eval",
           "briefing", "session_status", "workflow", "paper", "literature", "routing", "cases"]
CADENCE = {"runs": "live", "events": "live", "system": "live", "session": "live", "results_summary": "event",
           "experiments": "event", "leaderboard_events": "event", "run_eval": "event", "briefing": "periodic",
           "session_status": "periodic", "workflow": "manual", "paper": "manual", "literature": "manual",
           "routing": "manual", "cases": "manual"}


@pytest.fixture(scope="module")
def server(tmp_path_factory):
    boot = tmp_path_factory.mktemp("an_fr_boot")
    mff.build(boot)
    saved = {k: os.environ.get(k) for k in ("AN_ROOT", "AN_LEADERBOARD_READONLY", "AN_TRANSCRIPTS", "AN_RAW", "AN_DEMO")}
    os.environ["AN_ROOT"] = str(boot)
    os.environ["AN_TRANSCRIPTS"] = str(boot / "transcripts")   # never scan real Claude Code transcripts
    os.environ.pop("AN_RAW", None)                              # no `du` over a real data directory
    os.environ.pop("AN_DEMO", None)
    os.environ["AN_LEADERBOARD_READONLY"] = "1"
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
    srv._exp_cfg_cache.clear()
    for rm in list(srv._runs.values()):
        rm.last_check = 0.0


@pytest.fixture
def fr(server, tmp_path, monkeypatch):
    """a fresh fixture tree per test (ages relative to NOW); the server module globals are pointed at it"""
    now = time.time()
    root = mff.build(tmp_path / "proj", now=now)
    for name, sub in (("ROOT", ""), ("STATE", "state"), ("RUNS", "runs"), ("RESULTS", "results"), ("CASES", "results/cases")):
        monkeypatch.setattr(server, name, root / sub if sub else root)
    monkeypatch.setenv("AN_LEADERBOARD_READONLY", "1")
    monkeypatch.setattr(server, "main_session", lambda: (None, None))   # no real transcript in these tests
    monkeypatch.setattr(server, "gpu_info", lambda: {"source": "nvml", "gpus": [], "pid_gpu": {}})
    server._runs.clear()
    server.LB_TL.reset()
    clear(server)
    assert REAL_ROOT not in (server.STATE / "x").resolve().parents
    from fastapi.testclient import TestClient

    with TestClient(server.app, base_url="http://127.0.0.1:17100") as client:
        yield {"srv": server, "root": root, "client": client, "state": root / "state", "now": now}
    server._runs.clear()
    server.LB_TL.reset()
    clear(server)


def get(env, url: str, keep_cache: bool = False) -> dict:
    if not keep_cache:
        clear(env["srv"])
    r = env["client"].get(url)
    assert r.status_code == 200
    return r.json()


def fresh(env, now: float | None = None) -> dict:
    clear(env["srv"])
    out = env["srv"].build_freshness(now=env["now"] if now is None else now)
    return {s["id"]: s for s in out["sources"]} | {"_": out}


def set_json(env, rel: str, obj, age: float) -> None:
    p = env["root"] / rel
    p.write_text(json.dumps(obj))
    os.utime(p, (env["now"] - age, env["now"] - age))


def phases_by_id(p: dict) -> dict:
    return {x["id"]: x for x in p["phases"]}


# ----------------------------------------------------------------------------- freshness rules
def test_freshness_endpoint_shape_and_stale_set(fr):
    p = get(fr, "/api/freshness")
    assert p["ok"] is True and isinstance(p["now"], str)
    ids = [s["id"] for s in p["sources"]]
    assert ids == ALL_IDS
    for s in p["sources"]:
        for k in ("id", "label_zh", "label_en", "path", "updated", "age_s", "cadence", "expected_max_age_s", "stale", "used_by"):
            assert k in s, (s["id"], k)
        assert s["cadence"] == CADENCE[s["id"]]
        assert isinstance(s["used_by"], list) and s["used_by"]
        assert s["label_zh"] and s["label_en"] and s["hint_zh"] and s["hint_en"]
    assert set(p["stale_ids"]) == STALE and p["n_stale"] == 3
    for s in p["sources"]:                                # bilingual reason only on stale rows
        assert bool(s["reason_zh"]) == bool(s["reason_en"]) == s["stale"], s["id"]
    by = {s["id"]: s for s in p["sources"]}
    assert "overview.kpi_best_dice" in by["results_summary"]["used_by"]


def test_live_rules(fr):
    f = fresh(fr)
    r = f["runs"]
    assert r["expected_max_age_s"] == 180                              # FR-3: run-silence limit
    assert r["age_s"] == pytest.approx(10.0, abs=0.01)             # newest activity = FB2 (10 s); hidden smoke ignored
    assert r["stale"] is True and r["stale_reason"] == "running_run_silent"
    assert sorted(r["detail"]["running"]) == ["FB2", "T5_R2"]
    assert r["detail"]["stale_runs"] == ["T5_R2"]                     # 300 s > 180 s; FB1_smoke (2 h) is hidden
    assert r["detail"]["oldest_running_age_s"] == pytest.approx(300.0, abs=0.01)
    assert r["reason_en"] == "Running T5_R2 silent for 5 min (live data expected within 3 min)"
    assert r["reason_zh"] == "运行中的 T5_R2 已 5 分钟 没有写入（实时数据预期 ≤ 3 分钟）"
    ev = f["events"]
    assert ev["cadence"] == "live" and ev["age_s"] == pytest.approx(900.0, abs=0.01)
    assert ev["stale"] is False and ev["stale_rule"] == "sporadic"     # sporadic log: never stale by age
    se = f["session"]
    assert se["age_s"] == pytest.approx(5.0, abs=1.01) and se["stale"] is False
    # fix the silent run -> runs fresh
    d = fr["root"] / "runs" / "T5_R2" / "metrics.jsonl"
    os.utime(d, (fr["now"] - 30, fr["now"] - 30))
    f = fresh(fr)
    assert f["runs"]["stale"] is False and f["runs"]["detail"]["stale_runs"] == []
    # nothing running -> producer idle, never stale however old
    for rid in ("FB2", "T5_R2"):
        set_json(fr, f"runs/{rid}/status.json", {"state": "done"}, 5 * H)
        for n in ("metrics.jsonl", "config.yaml"):
            os.utime(fr["root"] / "runs" / rid / n, (fr["now"] - 5 * H, fr["now"] - 5 * H))
    f = fresh(fr)
    assert f["runs"]["stale"] is False and f["runs"]["detail"]["running"] == []
    assert f["runs"]["age_s"] == pytest.approx(2 * H, abs=0.01)       # V1 (2 h) is now the newest visible run
    # heartbeat 120 s old and no transcript -> session stale
    set_json(fr, "state/session_watch.json", {"ts": mff.iso(fr["now"] - 120)}, 120)
    f = fresh(fr)
    assert f["session"]["stale"] is True and f["session"]["age_s"] == pytest.approx(120.0, abs=1.01)


def test_event_rules(fr):
    f = fresh(fr)
    rs = f["results_summary"]
    assert rs["cadence"] == "event" and rs["expected_max_age_s"] is None and rs["stale"] is False
    assert rs["updated_from"] == "field" and rs["age_s"] == pytest.approx(1.5 * H, abs=1.01)   # field, not mtime (60 s)
    assert f["experiments"]["age_s"] == pytest.approx(2 * H, abs=1.01) and f["experiments"]["stale"] is False
    assert f["run_eval"]["age_s"] == pytest.approx(1800.0, abs=0.01)
    lb = f["leaderboard_events"]
    assert lb["missing"] is True and lb["updated"] is None and lb["age_s"] is None and lb["stale"] is False
    # very old event source stays not stale
    f = fresh(fr, now=fr["now"] + 30 * 24 * H)
    assert f["results_summary"]["stale"] is False and f["experiments"]["stale"] is False


def test_periodic_rules(fr):
    f = fresh(fr)
    b = f["briefing"]
    assert b["expected_max_age_s"] == 7200 and b["stale"] is True and b["stale_reason"] == "age"
    assert b["age_s"] == pytest.approx(3 * H, abs=1.01)
    ss = f["session_status"]
    assert ss["updated_from"] == "mtime" and ss["age_s"] == pytest.approx(1800.0, abs=0.01) and ss["stale"] is False
    # boundary (ISO timestamps carry whole seconds): age exactly 7200 s is not stale (> rule), 7201 s is
    t0 = float(int(fr["now"]))
    set_json(fr, "state/briefing.json", {"updated": mff.iso(t0 - 7200)}, 7200)
    assert fr["srv"].build_freshness(now=t0)["sources"][8]["age_s"] == 7200.0
    assert fresh(fr, now=t0)["briefing"]["stale"] is False
    set_json(fr, "state/briefing.json", {"updated": mff.iso(t0 - 7201)}, 7201)
    assert fresh(fr, now=t0)["briefing"]["stale"] is True
    (fr["state"] / "briefing.json").unlink()
    b = fresh(fr)["briefing"]
    assert b["missing"] is True and b["stale"] is False


def test_manual_rules(fr):
    f = fresh(fr)
    pa = f["paper"]
    assert pa["depends_running"] == ["paper"] and pa["expected_max_age_s"] == 12 * H
    assert pa["stale"] is True and pa["stale_reason"] == "dependent_phase_running"
    assert pa["reason_en"] == "Not updated for 13.0 h while phase paper depends on it (expected within 12.0 h)"
    li = f["literature"]
    assert li["age_s"] == pytest.approx(30 * H, abs=1.01) and li["depends_running"] == []
    assert li["expected_max_age_s"] is None and li["stale"] is False
    ro = f["routing"]                                    # half-written JSON -> mtime + error, never stale
    assert ro["updated_from"] == "mtime" and ro["age_s"] == pytest.approx(100 * H, abs=0.01)
    assert "invalid json" in ro["error"] and ro["stale"] is False
    ca = f["cases"]                                      # index.json is a JSON list -> mtime, no error
    assert ca["updated_from"] == "mtime" and "error" not in ca and ca["age_s"] == pytest.approx(600.0, abs=0.01)
    wf = f["workflow"]                                   # running manual phase: paper -> 12 h window, 1 h old
    assert wf["depends_running"] == ["paper"] and wf["expected_max_age_s"] == 12 * H and wf["stale"] is False
    # workflow 13 h old while a manual phase runs -> stale; once only auto phases run -> never stale
    wfd = json.loads((fr["state"] / "workflow.json").read_text())
    wfd["updated"] = mff.iso(fr["now"] - 13 * H)
    set_json(fr, "state/workflow.json", wfd, 13 * H)
    assert fresh(fr)["workflow"]["stale"] is True
    for ph in wfd["phases"]:
        if ph["id"] == "paper":
            ph["status"] = "done"
    set_json(fr, "state/workflow.json", wfd, 13 * H)
    f = fresh(fr)
    assert f["workflow"]["depends_running"] == [] and f["workflow"]["stale"] is False   # train_* / evaluate are auto
    assert f["paper"]["stale"] is False and f["paper"]["expected_max_age_s"] is None    # paper phase no longer runs


def test_freshness_cached_5s(fr):
    p1 = get(fr, "/api/freshness")
    assert "briefing" in p1["stale_ids"]
    set_json(fr, "state/briefing.json", {"updated": mff.iso(time.time())}, 0)
    p2 = get(fr, "/api/freshness", keep_cache=True)       # within the 5 s TTL: same payload
    assert p2["now"] == p1["now"] and "briefing" in p2["stale_ids"]
    p3 = get(fr, "/api/freshness")                        # cache cleared -> re-read
    assert "briefing" not in p3["stale_ids"]


def test_overview_freshness_and_tile_timestamps(fr):
    o = get(fr, "/api/overview")
    assert o["ok"] is True
    fz = o["freshness"]
    assert set(fz["stale_ids"]) == STALE
    assert fz["tiles"]["kpi_best_dice"] == "results_summary"
    assert fz["by_id"]["results_summary"]["cadence"] == "event" and fz["by_id"]["briefing"]["stale"] is True
    assert o["workflow_updated"] and o["experiments"]["updated"] and o["literature"]["updated"] and o["paper"]["updated"]
    assert o["routing_updated"] is None                   # routing.json is half-written
    assert {p["id"]: p["progress_source"] for p in o["phases"]}["train_novel"] == "auto"


# ----------------------------------------------------------------------------- best-Dice tile
def test_best_dice_inhouse_val_with_live_line(fr):
    bd = get(fr, "/api/overview")["best_dice"]
    assert bd["source"] == "results" and bd["dataset"] == "inhouse_val"   # not the test split listed first
    assert bd["ours"] == pytest.approx(0.88) and bd["ours_id"] == "FT1"
    assert bd["baseline"] == pytest.approx(0.89) and bd["baseline_id"] == "FB9"
    assert bd["updated"] == mff.iso(fr["now"] - 1.5 * H) and bd["freshness_id"] == "results_summary"
    lv = bd["live"]
    assert lv["metric"] == "val_dice" and lv["link"] == "#/leaderboard"
    assert lv["ours_id"] == "T1" and lv["ours_short"] == "T1" and lv["ours"] == pytest.approx(0.86)
    assert lv["baseline_id"] == "FB1" and lv["baseline_short"] == "FB1" and lv["baseline"] == pytest.approx(0.85)
    assert lv["delta"] == pytest.approx(0.01) and lv["verdict"] == "sota" and lv["provisional"] is False


def test_best_dice_dataset_choice(fr):
    srv = fr["srv"]
    cells = [{"dataset": d} for d in ("x_test", "y_val_lcc", "y_val")]
    data = {"datasets": [{"id": "x_test", "split": "test"}, {"id": "y_val_lcc", "postprocess": "lcc"},
                         {"id": "y_val", "postprocess": "none"}]}
    assert srv.best_dice_dataset(data, cells) == "y_val"           # primary validation dataset first
    assert srv.best_dice_dataset({"datasets": [{"id": "a_test"}]}, [{"dataset": "a_test"}]) is None
    assert srv.best_dice_dataset({"datasets": [{"id": "site1", "split": "val"}]}, [{"dataset": "site1"}]) == "site1"
    # summary with only a test split -> falls back to the registry (metrics_summary), never a test split
    sm = json.loads((fr["root"] / "results" / "summary.json").read_text())
    sm["cells"] = [c for c in sm["cells"] if c["dataset"] != "inhouse_val"]
    set_json(fr, "results/summary.json", sm, 60)
    bd = get(fr, "/api/overview")["best_dice"]
    assert bd["source"] != "results" and bd.get("dataset") is None


# ----------------------------------------------------------------------------- auto phase progress
def test_workflow_auto_progress(fr):
    before = (fr["state"] / "workflow.json").read_bytes()
    p = get(fr, "/api/workflow")
    ph = phases_by_id(p)
    assert p["current_phase"] == "train_novel"                       # header phase stays from the file
    exp = {"train_base": (1, 1, 1, 3), "train_novel": (3, 0, 1, 4), "vjepa": (1, 0, 1, 2), "r2": (0, 1, 1, 2)}
    for pid, (d, r, q, t) in exp.items():
        a = ph[pid]["progress_auto"]
        assert ph[pid]["progress_source"] == "auto", pid
        assert (a["done"], a["running"], a["queued"], a["total"]) == (d, r, q, t), pid
        assert ph[pid]["progress"] == pytest.approx(round(d / t, 4)), pid
    assert ph["train_base"]["progress"] == pytest.approx(0.3333)
    assert ph["train_novel"]["progress"] == pytest.approx(0.75)
    assert ph["vjepa"]["progress"] == pytest.approx(0.5)
    assert ph["r2"]["progress"] == 0.0 and ph["r2"]["progress_manual"] == pytest.approx(0.3)
    assert sorted(ph["r2"]["progress_auto"]["members"]["queued"]) == ["FB5_pool"]
    assert ph["r2"]["progress_auto"]["members"]["running"] == ["T5_R2"]
    assert sorted(ph["train_novel"]["progress_auto"]["members"]["done"]) == ["A1", "T1", "T2"]
    ev = ph["evaluate"]
    assert ev["progress_source"] == "auto" and ev["progress_auto"]["done"] == 6 and ev["progress_auto"]["ok"] == 4
    assert ev["progress"] == pytest.approx(0.6667)
    assert sorted(ev["progress_auto"]["members"]["pending"]) == ["A1", "T2"]
    for pid, v in (("env", 1.0), ("paper", 0.4), ("refs", 0.0), ("literature", 1.0)):
        assert ph[pid]["progress_source"] == "manual" and ph[pid]["progress"] == pytest.approx(v)
    assert ph["train_novel"]["progress_manual"] == pytest.approx(0.1)
    assert (fr["state"] / "workflow.json").read_bytes() == before     # the file is never written
    h = get(fr, "/api/health")
    assert h["phase"]["id"] == "train_novel" and h["phase"]["progress"] == pytest.approx(0.75)


def test_auto_progress_nothing_counted_keeps_manual(fr):
    set_json(fr, "state/experiments.json", {"updated": mff.iso(fr["now"]), "experiments": [
        {"id": "Z1", "family": "baseline", "status": "planned"}]}, 0)
    ph = phases_by_id(get(fr, "/api/workflow"))
    for pid, v in (("train_base", 0.2), ("train_novel", 0.1), ("vjepa", 0.0), ("evaluate", 0.5), ("r2", 0.3)):
        assert ph[pid]["progress_source"] == "manual" and ph[pid]["progress"] == pytest.approx(v), pid
        assert ph[pid]["progress_auto"]["total"] == 0


def test_missing_and_partial_files(fr):
    # half-written registry: workflow still served with the manual values, freshness reports the error
    (fr["state"] / "experiments.json").write_text('{"updated": "2026-10-29T00:00:00Z", "experiments": [{"id": "F')
    p = get(fr, "/api/workflow")
    assert p["ok"] is True
    ph = phases_by_id(p)
    assert ph["train_novel"]["progress_source"] == "manual" and ph["train_novel"]["progress"] == pytest.approx(0.1)
    f = fresh(fr)
    assert "invalid json" in f["experiments"]["error"] and f["experiments"]["updated_from"] == "mtime"
    # missing workflow.json
    (fr["state"] / "workflow.json").unlink()
    p = get(fr, "/api/workflow")
    assert p["ok"] is True and p["missing"] is True and p["phases"] == []
    f = fresh(fr)
    assert f["workflow"]["missing"] is True and f["workflow"]["stale"] is False
    assert f["paper"]["depends_running"] == [] and f["paper"]["stale"] is False   # no phase file -> nothing running
    # empty project root: every endpoint still answers
    empty = fr["root"].parent / "empty"
    empty.mkdir()
    srv = fr["srv"]
    for name, sub in (("ROOT", ""), ("STATE", "state"), ("RUNS", "runs"), ("RESULTS", "results"), ("CASES", "results/cases")):
        setattr(srv, name, empty / sub if sub else empty)
    p = get(fr, "/api/freshness")
    assert p["ok"] is True and [s["id"] for s in p["sources"]] == ALL_IDS
    by = {s["id"]: s for s in p["sources"]}
    for sid in ("runs", "events", "results_summary", "experiments", "briefing", "paper", "workflow", "cases"):
        assert by[sid]["missing"] is True and by[sid]["stale"] is False, sid
    o = get(fr, "/api/overview")
    assert o["ok"] is True and o["best_dice"]["source"] is None and isinstance(o["freshness"]["stale_ids"], list)
    assert get(fr, "/api/workflow")["missing"] is True
    assert get(fr, "/api/runs")["runs"] == []


# ----------------------------------------------------------------------------- training run list
def test_runs_hide_discarded_and_smoke(fr):
    p = get(fr, "/api/runs")
    ids = {r["run_id"] for r in p["runs"]}
    assert ids == {"FB1", "FB2", "T1", "T2", "T5_R2", "V1"}
    assert p["n_hidden"] == 2 and p["show_hidden"] is False and all(r["hidden"] is False for r in p["runs"])
    assert p["updated"] is not None
    p = get(fr, "/api/runs?hidden=1")
    hid = {r["run_id"] for r in p["runs"] if r["hidden"]}
    assert hid == {"FB1_smoke", "_discarded"} and len(p["runs"]) == 8 and p["show_hidden"] is True
    assert get(fr, "/api/runs?hidden=0")["n_hidden"] == 2 and len(get(fr, "/api/runs?hidden=0")["runs"]) == 6
    # a hidden run stays reachable directly
    assert get(fr, "/api/runs/FB1_smoke/metrics")["ok"] is True


def test_payload_timestamps(fr):
    r = get(fr, "/api/results")
    assert r["updated"] == mff.iso(fr["now"] - 1.5 * H) and r["cases_updated"] == mff.iso(fr["now"] - 600)
    assert get(fr, "/api/workflow")["updated"] == mff.iso(fr["now"] - H)
    assert get(fr, "/api/paper")["updated"] == mff.iso(fr["now"] - 13 * H)
    assert get(fr, "/api/literature")["updated"] == mff.iso(fr["now"] - 30 * H)
    assert "updated" in get(fr, "/api/agents")
    assert get(fr, "/api/leaderboard")["updated"] is not None


def test_route_registered_before_catch_all(fr):
    paths = [getattr(r, "path", "") for r in fr["srv"].app.routes]
    assert paths.index("/api/freshness") < paths.index("/api/{rest:path}")


# ----------------------------------------------------------------------------- review fixes (FR-2 .. FR-6)
def test_review_fixes_fr2_to_fr6(fr):
    srv, now = fr["srv"], fr["now"]
    # FR-3: a running run silent for 66 s (a V-JEPA validation pass) is not stale; 181 s is
    for n in ("metrics.jsonl", "status.json", "log.txt"):
        p = fr["root"] / "runs" / "T5_R2" / n
        if p.exists():
            os.utime(p, (now - 66, now - 66))
    assert fresh(fr)["runs"]["stale"] is False
    for n in ("metrics.jsonl", "status.json", "log.txt"):
        p = fr["root"] / "runs" / "T5_R2" / n
        if p.exists():
            os.utime(p, (now - 181, now - 181))
    assert fresh(fr)["runs"]["stale"] is True
    # FR-5: the Overview counts only the runs the Training list shows
    o = get(fr, "/api/overview")
    assert o["runs"]["total"] == 6 and o["runs"]["n_hidden"] == 2
    assert all(not srv.run_hidden(c["run_id"]) for c in o["curves"])
    # FR-6: an `updated` field 3 h in the future -> the mtime is used and the skew is reported
    set_json(fr, "state/briefing.json", {"updated": mff.iso(now + 3 * H)}, 3 * H)
    b = fresh(fr)["briefing"]
    assert b["updated_from"] == "mtime" and b["age_s"] == pytest.approx(3 * H, abs=1.01) and b["stale"] is True
    assert b["clock_skew_s"] == pytest.approx(3 * H, abs=1.01) and "clock skew" in b["error"]
    # FR-2: experiments.json fallback never takes a test-split key, and prefers the exact val_dice
    assert srv._exp_val_dice({"val_dice": 0.84, "test_dice": 0.97, "val_dice_aux": 0.99}) == 0.84
    assert srv._exp_val_dice({"test_dice_site01": 0.99, "val_dsc_lcc": 0.8, "val_dice_mean": 0.95}) == 0.8
    assert srv._exp_val_dice({"test_dice": 0.97}) is None
    (fr["root"] / "results" / "summary.json").unlink()
    set_json(fr, "state/experiments.json", {"updated": mff.iso(now), "experiments": [
        {"id": "T1", "family": "novel", "status": "done", "metrics_summary": {"val_dice": 0.84, "test_dice": 0.97}},
        {"id": "FB1", "family": "baseline", "status": "done",
         "metrics_summary": {"val_dice": 0.85, "test_dice_site01": 0.99}}]}, 0)
    bd = get(fr, "/api/overview")["best_dice"]
    assert bd["source"] == "experiments" and bd["ours"] == 0.84 and bd["baseline"] == 0.85
    # FR-4: a running auto phase with nothing countable keeps the manual value -> workflow.json depends on it
    wfd = json.loads((fr["state"] / "workflow.json").read_text())
    for ph in wfd["phases"]:
        if ph["id"] == "r2":
            ph["status"] = "running"
        elif ph["id"] == "paper":
            ph["status"] = "done"
    wfd["updated"] = mff.iso(now - 20 * H)
    set_json(fr, "state/workflow.json", wfd, 20 * H)
    ph = phases_by_id(get(fr, "/api/workflow"))
    assert ph["r2"]["progress_source"] == "manual"
    wf = fresh(fr)["workflow"]
    assert "r2" in wf["depends_running"] and wf["stale"] is True
