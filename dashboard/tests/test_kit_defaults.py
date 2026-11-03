"""Kit safety and default-configuration tests (使用指南.md §5 / §8).  Synthetic data only.

    cd <kit>/dashboard && OMP_NUM_THREADS=1 ../.venv/bin/python -m pytest tests/test_kit_defaults.py -q

  * the fixture generators refuse targets whose wiping could destroy real data (_fixture_guard.py);
  * make_fixture.py writes only synthetic state and relative run_dir values;
  * with no AN_* variables the server shows its own project only: no transcripts, no raw-data `du`,
    no supervisor alerts, the disk of the project root;
  * secrets are masked in process command lines; AN_DEMO hides host processes;
  * the Overview best-Dice tile accepts both family spellings (novel / ours) like the leaderboard.
"""
from __future__ import annotations

import importlib
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
DASH = HERE.parent

for _v in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS"):
    os.environ.setdefault(_v, "1")

ENV_KEYS = ("AN_ROOT", "AN_TRANSCRIPTS", "AN_RAW", "AN_RAW_TOTAL", "AN_DISK_PATH", "AN_ALERT_SERVICES", "AN_DEMO",
            "AN_SESSION_FILE", "AN_LEADERBOARD_READONLY")


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


guard = _load("_fixture_guard", HERE / "_fixture_guard.py")


@pytest.fixture(scope="module")
def srv():
    """server.py imported with no AN_* variable at all (the defaults a new project gets)"""
    saved = {k: os.environ.get(k) for k in ENV_KEYS}
    for k in ENV_KEYS:
        os.environ.pop(k, None)
    os.environ["AN_LEADERBOARD_READONLY"] = "1"   # the default root is the kit itself: never write into it
    if str(DASH) not in sys.path:
        sys.path.insert(0, str(DASH))
    s = importlib.reload(sys.modules["server"]) if "server" in sys.modules else importlib.import_module("server")
    yield s
    for k, v in saved.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v


# ------------------------------------------------------------------------------------------- fixture guard
def test_guard_refuses_dangerous_targets(tmp_path, monkeypatch):
    proj = tmp_path / "realproj"
    (proj / "state").mkdir(parents=True)
    monkeypatch.setenv("AN_ROOT", str(proj))
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    (tmp_path / "home").mkdir()
    busy = tmp_path / "busy"
    busy.mkdir()
    (busy / "precious.txt").write_text("keep me")
    a_file = tmp_path / "a_file"
    a_file.write_text("x")
    for bad in ("/", tmp_path / "home", tmp_path, proj, proj / "sub", guard.BASE, guard.BASE / "dashboard",
                guard.BASE / "new_dir", busy, a_file):
        with pytest.raises(SystemExit):
            guard.check(bad)
    assert (busy / "precious.txt").read_text() == "keep me"


def test_guard_accepts_new_empty_and_marked(tmp_path, monkeypatch):
    monkeypatch.delenv("AN_ROOT", raising=False)
    monkeypatch.delenv("AN_REAL_ROOT", raising=False)
    (tmp_path / "empty").mkdir()
    marked = tmp_path / "marked"
    marked.mkdir()
    (marked / "old.json").write_text("{}")
    guard.mark(marked)
    for ok in (tmp_path / "new" / "deeper", tmp_path / "empty", marked):
        assert guard.check(ok) == Path(os.path.realpath(ok))


def test_make_fixture_cli_refuses_a_real_directory(tmp_path):
    proj = tmp_path / "newproj"
    (proj / "state").mkdir(parents=True)
    (proj / "state" / "experiments.json").write_text('{"experiments": []}')
    r = subprocess.run([sys.executable, "-I", str(HERE / "make_fixture.py"), str(proj)], capture_output=True,
                       timeout=120, env={**os.environ, "MPLBACKEND": "Agg"})
    assert r.returncode != 0 and b"refusing" in r.stderr
    assert (proj / "state" / "experiments.json").read_text() == '{"experiments": []}'   # nothing was deleted


def test_make_fixture_is_fully_synthetic(tmp_path):
    pytest.importorskip("matplotlib")
    out = tmp_path / "fx"
    r = subprocess.run([sys.executable, "-I", str(HERE / "make_fixture.py"), str(out)], capture_output=True,
                       timeout=300, env={**os.environ, "MPLBACKEND": "Agg"})
    assert r.returncode == 0, r.stderr.decode()[-500:]
    assert (out / guard.MARKER).is_file()
    wf = json.loads((out / "state" / "workflow.json").read_text(encoding="utf-8"))
    assert wf["project"]["en"].startswith("Demo project")
    ev = [json.loads(x) for x in (out / "state" / "events.jsonl").read_text(encoding="utf-8").splitlines()]
    assert ev[0]["msg_en"] == "Project started (demo data)" and all(e["msg_zh"] and e["msg_en"] for e in ev)
    lit = json.loads((out / "state" / "literature.json").read_text(encoding="utf-8"))
    assert all(p["url"].startswith("https://example.org/") for p in lit["papers"])
    exps = json.loads((out / "state" / "experiments.json").read_text(encoding="utf-8"))["experiments"]
    assert all(not str(e.get("run_dir") or "").startswith("/") for e in exps)
    # rebuilding a marked fixture works (the guard accepts its own output)
    r2 = subprocess.run([sys.executable, "-I", str(HERE / "make_fixture.py"), str(out)], capture_output=True,
                        timeout=300, env={**os.environ, "MPLBACKEND": "Agg"})
    assert r2.returncode == 0, r2.stderr.decode()[-500:]


# ------------------------------------------------------------------------------------------- server defaults
def test_defaults_are_project_local(srv):
    assert srv.ROOT.resolve() == DASH.parent.resolve()          # the directory that holds dashboard/
    assert not srv.TRANSCRIPTS.exists() and srv.RAW_TOTAL is None and srv.ALERT_SV == () and srv.DEMO is False
    assert srv.DISK_PATH == str(srv.ROOT)
    from fastapi.testclient import TestClient

    with TestClient(srv.app, base_url="http://127.0.0.1:17100") as c:
        ag = c.get("/api/agents").json()
        assert ag["ok"] and ag["agents"] == [] and ag["root"] is None
        se = c.get("/api/session").json()
        assert se["ok"] and se["session"] is None and se["transcripts_set"] is False
        assert "AN_TRANSCRIPTS" in se["session_error"]
        sy = c.get("/api/system").json()
        assert sy["ok"] and sy["extraction"]["configured"] is False and sy["extraction"]["measuring"] is False
        assert sy["disk_path"] == str(srv.ROOT) and sy["demo"] is False
        if sy["host"]["disk_workspace"] is not None:
            assert sy["host"]["disk_workspace"]["path"] == str(srv.ROOT)


def test_alert_services_from_env(srv, monkeypatch, tmp_path):
    for name, sub in (("ROOT", ""), ("STATE", "state"), ("RUNS", "runs"), ("RESULTS", "results")):
        monkeypatch.setattr(srv, name, tmp_path / sub if sub else tmp_path)
    monkeypatch.setattr(srv, "supervisor_info", lambda: [{"name": "my_jobrunner", "state": "RUNNING", "info": ""}])
    monkeypatch.setattr(srv, "host_info", lambda: {"disk_workspace": {"total": 100e9, "used": 99e9, "free": 1e9}})
    monkeypatch.setattr(srv, "DISK_PATH", "/data/myproj")
    srv.CACHE._d.clear()
    ids = {a["id"]: a for a in srv.build_alerts()["alerts"]}
    assert not any(i.startswith("sv:") for i in ids)              # nothing to watch by default
    assert ids["disk_low"]["msg_en"].startswith("/data/myproj ") and ids["disk_low"]["level"] == "error"
    monkeypatch.setenv("AN_ALERT_SERVICES", "my_jobrunner, my_diskguard ,")
    s2 = tuple(x.strip() for x in os.environ["AN_ALERT_SERVICES"].split(",") if x.strip())
    monkeypatch.setattr(srv, "ALERT_SV", s2)
    srv.CACHE._d.clear()
    ids = {a["id"]: a for a in srv.build_alerts()["alerts"]}
    assert "sv:my_jobrunner" not in ids and "MISSING" in ids["sv:my_diskguard"]["msg_en"]
    srv.CACHE._d.clear()


def test_redact_cmd(srv):
    r = srv.redact_cmd
    assert r("python train.py --hf-token hf_abc --epochs 10") == "python train.py --hf-token *** --epochs 10"
    assert r("env OPENAI_API_KEY=sk-1 python train.py --api-key=sk-2") == "env OPENAI_API_KEY=*** python train.py --api-key=***"
    assert r("python train.py --password=p1 --wandb-key k1 --secret-key s1") == \
        "python train.py --password=*** --wandb-key *** --secret-key ***"
    assert r("python train.py --data https://u:pw@host/x.zip") == "python train.py --data https://***@host/x.zip"
    assert r("unzip -o -P pw data.zip", unzip=True) == "unzip -o -P *** data.zip"
    keep = "python train.py --max-tokens 512 --tokenizer bert --key val_dice --use-auth --epochs 3"
    assert r(keep) == keep


def test_demo_hides_host_processes(srv, monkeypatch):
    monkeypatch.setattr(srv, "DEMO", True)
    assert srv.procs_info({}) == {"train": [], "unzip": [], "hidden": True}
    assert srv.supervisor_info() == []


@pytest.mark.parametrize("summary_fam,exp_fam", [("ours", "novel"), ("novel", "ours"), ("Ours", "Novel")])
def test_best_dice_accepts_both_family_spellings(srv, monkeypatch, tmp_path, summary_fam, exp_fam):
    for name, sub in (("ROOT", ""), ("STATE", "state"), ("RESULTS", "results")):
        monkeypatch.setattr(srv, name, tmp_path / sub if sub else tmp_path)
    (tmp_path / "state").mkdir()
    (tmp_path / "results").mkdir()
    exps = {"experiments": [{"id": "E1", "family": exp_fam, "metrics_summary": {"val_dice": 0.88}},
                            {"id": "B1", "family": "baseline", "metrics_summary": {"val_dice": 0.85}}]}
    (tmp_path / "state" / "experiments.json").write_text(json.dumps(exps))
    srv._json_cache.clear()
    d = srv._best_dice_core()                                      # no summary.json yet: experiments.json fallback
    assert d["source"] == "experiments" and d["ours"] == pytest.approx(0.88) and d["baseline"] == pytest.approx(0.85)
    summ = {"datasets": [{"id": "inhouse_val"}], "metrics": [{"id": "dice"}],
            "methods": [{"id": "m1", "family": summary_fam, "is_primary": True}, {"id": "b1", "family": "baseline"}],
            "cells": [{"method": "m1", "dataset": "inhouse_val", "metric": "dice", "mean": 0.9},
                      {"method": "b1", "dataset": "inhouse_val", "metric": "dice", "mean": 0.86}]}
    (tmp_path / "results" / "summary.json").write_text(json.dumps(summ))
    srv._json_cache.clear()
    d = srv._best_dice_core()
    assert d["source"] == "results" and d["ours"] == pytest.approx(0.9) and d["baseline"] == pytest.approx(0.86)
    srv._json_cache.clear()
