"""AN Research Monitor -- read-only FastAPI backend for the bilingual dashboard.

Run:  AN_ROOT=/path/to/project python -I dashboard/server.py   (binds 127.0.0.1:17100; see README.md for the AN_* variables)

Every /api/* endpoint is read-only, tolerant of missing / partial files and never
returns HTTP 500 for bad data: failures come back as {"ok": false, "error": ...}
with HTTP 200.  See README.md next to this file for the data contracts.
"""
from __future__ import annotations

import os

# keep this service lean on threads (the box has a tight pids limit)
for _v in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
    os.environ.setdefault(_v, "1")

import collections
import datetime as _dt
import fcntl
import functools
import hashlib
import json
import math
import re
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any, Callable

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool

# ----------------------------------------------------------------------------
# paths / constants
# ----------------------------------------------------------------------------
# the project root: $AN_ROOT, else the directory that holds dashboard/ (a dashboard copied into <project>/dashboard)
ROOT = Path(os.environ.get("AN_ROOT", "").strip() or Path(__file__).resolve().parent.parent)
STATE = ROOT / "state"
RUNS = ROOT / "runs"
RESULTS = ROOT / "results"
CASES = RESULTS / "cases"
PAPER = ROOT / "paper"
FIGS = PAPER / "figures"
STATIC = Path(__file__).resolve().parent / "static"
# Optional features are opt-in, so a new project never shows another project's transcripts or data:
#   AN_TRANSCRIPTS  Claude Code transcript directory (Agents / Session views); unset = no transcripts
#   AN_RAW          directory whose size the System view measures with `du -sb` (dataset extraction progress),
#   AN_RAW_TOTAL    against this many bytes; unset = no measurement
_TRANSCRIPTS_ENV = os.environ.get("AN_TRANSCRIPTS", "").strip()
TRANSCRIPTS = Path(_TRANSCRIPTS_ENV or "/nonexistent/an-transcripts-not-set")
_RAW_ENV = os.environ.get("AN_RAW", "").strip()
RAW = Path(_RAW_ENV or "/nonexistent/an-raw-not-set")
try:
    RAW_TOTAL = int(os.environ.get("AN_RAW_TOTAL", "").strip() or 0) or None
except ValueError:
    RAW_TOTAL = None
# disk shown on the System view and checked by the low-disk alert: $AN_DISK_PATH, else the project root
DISK_PATH = os.environ.get("AN_DISK_PATH", "").strip() or str(ROOT)
# AN_DEMO=1 (set by demo/run_demo.sh): the data is synthetic, so the System view does not list this machine's
# processes or supervisor programs (they belong to whatever else runs here)
DEMO = os.environ.get("AN_DEMO", "").strip().lower() in ("1", "true", "yes", "on")
HOST = os.environ.get("AN_DASH_HOST", "127.0.0.1")
PORT = int(os.environ.get("AN_DASH_PORT", "17100"))

IMG_EXT = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg"}
MAX_POINTS = 2000          # display points per series
MAX_AGENT_MSGS = 3000      # bounded memory per agent
ACTIVE_WINDOW_S = 120
BOOT_TS = time.time()


def now_iso() -> str:
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_ts(s: Any) -> float | None:
    if not s or not isinstance(s, str):
        return None
    try:
        t = s.strip().replace("Z", "+00:00")
        d = _dt.datetime.fromisoformat(t)
        if d.tzinfo is None:
            d = d.replace(tzinfo=_dt.timezone.utc)
        return d.timestamp()
    except Exception:
        return None


def fnum(x: Any) -> float | None:
    try:
        v = float(x)
        return v if math.isfinite(v) else None
    except Exception:
        return None


# ----------------------------------------------------------------------------
# small caches
# ----------------------------------------------------------------------------
class TTL:
    def __init__(self) -> None:
        self._d: dict[str, tuple[float, Any]] = {}
        self._locks: dict[str, threading.Lock] = collections.defaultdict(threading.Lock)
        self._g = threading.Lock()

    def get(self, key: str, ttl: float, fn: Callable[[], Any]) -> Any:
        hit = self._d.get(key)
        if hit and time.time() - hit[0] < ttl:
            return hit[1]
        with self._g:
            lk = self._locks[key]
        with lk:
            hit = self._d.get(key)
            if hit and time.time() - hit[0] < ttl:
                return hit[1]
            val = fn()
            self._d[key] = (time.time(), val)
            return val

    def stamp(self, key: str) -> float | None:
        """time the cached value of `key` was computed (None when never)"""
        hit = self._d.get(key)
        return hit[0] if hit else None


CACHE = TTL()
_json_cache: dict[str, tuple[tuple[float, int], Any]] = {}
_json_lock = threading.Lock()


def read_json(path: Path) -> tuple[Any, str | None]:
    """Return (data, error). Cached on (mtime, size). Missing file -> (None, 'missing')."""
    try:
        st = path.stat()
    except FileNotFoundError:
        return None, "missing"
    except Exception as e:  # pragma: no cover
        return None, f"stat failed: {e}"
    key = str(path)
    sig = (st.st_mtime, st.st_size)
    with _json_lock:
        hit = _json_cache.get(key)
        if hit and hit[0] == sig:
            return hit[1]
    try:
        if st.st_size == 0:
            res: tuple[Any, str | None] = (None, "empty")
        else:
            with open(path, "rb") as fh:
                res = (json.loads(fh.read().decode("utf-8", "replace")), None)
    except Exception as e:
        res = (None, f"invalid json: {e.__class__.__name__}: {str(e)[:200]}")
    with _json_lock:
        _json_cache[key] = (sig, res)
    return res


def safe_child(base: Path, name: str) -> Path | None:
    """Resolve base/name and make sure it stays inside base."""
    try:
        if not name or "\x00" in name:
            return None
        p = (base / name).resolve()
        b = base.resolve()
        if p == b or b not in p.parents:
            return None
        return p
    except Exception:
        return None


# ----------------------------------------------------------------------------
# app + error policy
# ----------------------------------------------------------------------------
def _finite(o: Any) -> Any:
    """Replace NaN/Infinity (valid in Python's json.loads, invalid in strict JSON) by None."""
    if isinstance(o, float):
        return o if math.isfinite(o) else None
    if isinstance(o, dict):
        return {k: _finite(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_finite(v) for v in o]
    return o


class SafeJSON(JSONResponse):
    """Strict-JSON response that never fails on NaN/Infinity coming from user-written state files."""

    def render(self, content: Any) -> bytes:
        try:
            return json.dumps(content, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode("utf-8")
        except ValueError:
            return json.dumps(_finite(content), ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode("utf-8")


app = FastAPI(title="AN Research Monitor", docs_url=None, redoc_url=None, openapi_url=None,
              default_response_class=SafeJSON)


_limiter_set = False


def _limit_threads() -> None:
    """Cap the sync-endpoint thread pool (default 40) -- must run inside the event loop."""
    global _limiter_set
    if _limiter_set:
        return
    _limiter_set = True
    try:
        import anyio.to_thread

        anyio.to_thread.current_default_thread_limiter().total_tokens = 6
    except Exception:
        pass


@app.exception_handler(Exception)
async def _all_errors(request: Request, exc: Exception):  # never 500 on bad data
    return SafeJSON({"ok": False, "error": f"{exc.__class__.__name__}: {str(exc)[:300]}"}, status_code=200)


@app.exception_handler(RequestValidationError)
async def _bad_params(request: Request, exc: RequestValidationError):  # e.g. ?limit=abc -> ok:false, HTTP 200
    try:
        msg = "; ".join(f"{'.'.join(str(x) for x in e.get('loc', []))}: {e.get('msg')}" for e in exc.errors())[:300]
    except Exception:
        msg = "invalid request parameters"
    return SafeJSON({"ok": False, "error": f"bad request: {msg}"}, status_code=200)


@app.middleware("http")
async def _no_cache(request: Request, call_next):
    _limit_threads()
    resp = await call_next(request)
    p = request.url.path
    if p.startswith("/api/") and "/samples/" not in p and "/figures/" not in p and "/cases/" not in p:
        resp.headers["Cache-Control"] = "no-store"
    elif not p.startswith("/api/"):
        resp.headers["Cache-Control"] = "no-cache"
    return resp


def safe(fn: Callable) -> Callable:
    @functools.wraps(fn)
    def wrapper(*a, **kw):
        try:
            out = fn(*a, **kw)
            if isinstance(out, dict) and "ok" not in out:
                out = {"ok": True, **out}
            return out
        except Exception as e:
            return {"ok": False, "error": f"{e.__class__.__name__}: {str(e)[:300]}"}

    return wrapper


@app.get("/api/health")
@safe
def api_health():
    wf = api_workflow()  # progress of the auto phases is derived (README §19)
    phase = None
    if isinstance(wf, dict) and wf.get("ok") and not wf.get("missing"):
        cur = wf.get("current_phase")
        for ph in wf.get("phases") or []:
            if isinstance(ph, dict) and ph.get("id") == cur:
                phase = {"id": cur, "name_zh": ph.get("name_zh"), "name_en": ph.get("name_en"),
                         "status": ph.get("status"), "progress": ph.get("progress")}
        if phase is None and cur:
            phase = {"id": cur, "name_zh": cur, "name_en": cur}
    return {"ok": True, "ts": now_iso(), "uptime_s": round(time.time() - BOOT_TS, 1), "phase": phase}


# ----------------------------------------------------------------------------
# events
# ----------------------------------------------------------------------------
_events = {"sig": None, "items": [], "bad": 0}
_events_lock = threading.Lock()


def load_events() -> tuple[list[dict], int]:
    path = STATE / "events.jsonl"
    try:
        st = path.stat()
    except FileNotFoundError:
        return [], 0
    sig = (st.st_mtime, st.st_size)
    with _events_lock:
        if _events["sig"] == sig:
            return _events["items"], _events["bad"]
        items, bad = [], 0
        with open(path, "rb") as fh:
            data = fh.read()
        for i, line in enumerate(data.split(b"\n")):
            line = line.strip()
            if not line:
                continue
            try:
                o = json.loads(line)
                if not isinstance(o, dict):
                    raise ValueError
            except Exception:
                bad += 1
                continue
            items.append({
                "i": i,
                "ts": o.get("ts"),
                "t": parse_ts(o.get("ts")),
                "type": str(o.get("type") or "info"),
                "level": str(o.get("level") or "info"),
                "actor": str(o.get("actor") or "?"),
                "msg_zh": o.get("msg_zh") or o.get("msg_en") or o.get("msg") or "",
                "msg_en": o.get("msg_en") or o.get("msg_zh") or o.get("msg") or "",
            })
        _events.update(sig=sig, items=items, bad=bad)
        return items, bad


def events_newest(items: list[dict]) -> list[dict]:
    return sorted(items, key=lambda e: ((e["t"] or 0), e["i"]), reverse=True)


@app.get("/api/events")
@safe
def api_events(limit: int = 500, level: str = "", actor: str = "", type: str = ""):
    items, bad = load_events()
    ev = events_newest(items)
    actors = sorted({e["actor"] for e in items})
    types = sorted({e["type"] for e in items})
    if level:
        ev = [e for e in ev if e["level"] == level]
    if actor:
        ev = [e for e in ev if e["actor"] == actor]
    if type:
        ev = [e for e in ev if e["type"] == type]
    limit = max(1, min(int(limit), 5000))
    return {"total": len(items), "bad_lines": bad, "actors": actors, "types": types,
            "count": len(ev), "events": ev[:limit]}


# ----------------------------------------------------------------------------
# state files
# ----------------------------------------------------------------------------
def state_payload(name: str, key: str) -> dict:
    data, err = read_json(STATE / name)
    if err:
        return {"ok": err in ("missing", "empty"), "missing": True, "error": err, key: [] if key != "data" else None}
    return {"ok": True, "data": data}


@app.get("/api/workflow")
@safe
def api_workflow():
    data, err = read_json(STATE / "workflow.json")
    if err:
        return {"ok": err in ("missing", "empty"), "error": err, "phases": [], "missing": True}
    phases = [p for p in (data.get("phases") or []) if isinstance(p, dict)] if isinstance(data, dict) else []
    auto, auto_err = {}, None
    try:
        auto = CACHE.get("phase_auto", 3, phase_progress_auto)
    except Exception as e:  # noqa: BLE001 -- a broken registry never hides the workflow file
        auto_err = f"{e.__class__.__name__}: {str(e)[:200]}"
    phases = apply_phase_auto(phases, auto)
    exps_upd = auto.get("_updated") if isinstance(auto, dict) else None
    out = {"ok": True, "project": data.get("project") if isinstance(data, dict) else None,
           "updated": data.get("updated") if isinstance(data, dict) else None,
           "current_phase": data.get("current_phase") if isinstance(data, dict) else None,
           "phases": phases, "progress_updated": exps_upd, "now": now_iso()}
    if auto_err:
        out["progress_error"] = auto_err
    return out


@app.get("/api/experiments")
@safe
def api_experiments():
    data, err = read_json(STATE / "experiments.json")
    if err:
        return {"ok": err in ("missing", "empty"), "error": err, "experiments": [], "missing": True}
    exps = data.get("experiments") if isinstance(data, dict) else data
    exps = [e for e in (exps or []) if isinstance(e, dict)]
    return {"ok": True, "updated": data.get("updated") if isinstance(data, dict) else None, "experiments": exps}


@app.get("/api/routing")
@safe
def api_routing():
    data, err = read_json(STATE / "routing.json")
    if err:
        return {"ok": err in ("missing", "empty"), "error": err, "routing": None, "missing": True}
    return {"ok": True, "updated": data.get("updated") if isinstance(data, dict) else None,
            "routing": data.get("routing", data) if isinstance(data, dict) else data}


@app.get("/api/literature")
@safe
def api_literature():
    data, err = read_json(STATE / "literature.json")
    if err:
        return {"ok": err in ("missing", "empty"), "error": err, "papers": [], "missing": True}
    papers = data.get("papers") if isinstance(data, dict) else data
    papers = [p for p in (papers or []) if isinstance(p, dict)]
    return {"ok": True, "updated": data.get("updated") if isinstance(data, dict) else None, "papers": papers}


@app.get("/api/paper")
@safe
def api_paper():
    data, err = read_json(STATE / "paper.json")
    pdf = PAPER / "main.pdf"
    pdf_info = None
    if pdf.is_file():
        st = pdf.stat()
        pdf_info = {"size": st.st_size, "mtime": _dt.datetime.fromtimestamp(st.st_mtime, _dt.timezone.utc).isoformat()}
    if err:
        return {"ok": err in ("missing", "empty"), "error": err, "missing": True, "sections": [], "figures": [],
                "references": None, "pdf": pdf_info}
    d = data if isinstance(data, dict) else {}
    figs = []
    for f in d.get("figures") or []:
        if not isinstance(f, dict):
            continue
        g = dict(f)
        p = safe_child(FIGS, str(f.get("file") or ""))
        g["exists"] = bool(p and p.is_file())
        g["is_image"] = bool(p and p.suffix.lower() in IMG_EXT)
        figs.append(g)
    return {"ok": True, "updated": d.get("updated"), "target_journal": d.get("target_journal"),
            "sections": [s for s in d.get("sections") or [] if isinstance(s, dict)], "figures": figs,
            "references": d.get("references") if isinstance(d.get("references"), dict) else None,
            "pdf": pdf_info}


@app.get("/api/paper/figures/{name:path}")
def api_paper_figure(name: str):
    p = safe_child(FIGS, name)
    if not p or not p.is_file():
        return JSONResponse({"ok": False, "error": "not found"}, status_code=404)
    return FileResponse(p, headers={"Cache-Control": "max-age=30"})


@app.get("/api/paper/pdf")
def api_paper_pdf():
    p = PAPER / "main.pdf"
    if not p.is_file():
        return JSONResponse({"ok": False, "error": "not found"}, status_code=404)
    return FileResponse(p, media_type="application/pdf", headers={"Cache-Control": "no-cache",
                                                                     "Content-Disposition": "inline; filename=main.pdf"})


# ----------------------------------------------------------------------------
# results
# ----------------------------------------------------------------------------
@app.get("/api/results")
@safe
def api_results():
    data, err = read_json(RESULTS / "summary.json")
    idx, ierr = read_json(CASES / "index.json")
    cases = []
    if isinstance(idx, list):
        for c in idx:
            if isinstance(c, dict) and c.get("file"):
                p = safe_child(CASES, str(c["file"]))
                if p and p.is_file():
                    cases.append(c)
    out: dict[str, Any] = {"ok": True, "cases": cases, "cases_error": ierr,
                           "updated": data.get("updated") if isinstance(data, dict) else None,
                           "cases_updated": file_updated(CASES / "index.json")[0]}
    if err or not isinstance(data, dict):
        out.update(missing=True, error=err or "not an object", summary=None)
        return out
    s = {k: data.get(k) for k in ("updated", "datasets", "metrics", "methods", "cells", "per_case", "pvalues")}
    for k in ("datasets", "metrics", "methods", "cells", "per_case", "pvalues"):
        s[k] = [x for x in (s.get(k) or []) if isinstance(x, dict)]
    out["summary"] = s
    out["missing"] = not s["cells"]
    return out


@app.get("/api/results/cases/{name:path}")
def api_case_image(name: str):
    p = safe_child(CASES, name)
    if not p or not p.is_file() or p.suffix.lower() not in IMG_EXT:
        return JSONResponse({"ok": False, "error": "not found"}, status_code=404)
    return FileResponse(p, headers={"Cache-Control": "max-age=30"})


# ----------------------------------------------------------------------------
# runs (training)
# ----------------------------------------------------------------------------
class RunMetrics:
    """Incremental reader for runs/<id>/metrics.jsonl."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.offset = 0
        self.ino = None
        self.series: dict[tuple[str, str], list[tuple]] = collections.defaultdict(list)
        self.bad = 0
        self.lines = 0
        self.lock = threading.Lock()
        self.last_check = 0.0

    def reset(self) -> None:
        self.offset = 0
        self.series = collections.defaultdict(list)
        self.bad = 0
        self.lines = 0

    def update(self) -> None:
        with self.lock:
            if time.time() - self.last_check < 1.5:
                return
            self.last_check = time.time()
            try:
                st = self.path.stat()
            except FileNotFoundError:
                self.reset()
                return
            if self.ino != st.st_ino or st.st_size < self.offset:
                self.ino = st.st_ino
                self.reset()
            if st.st_size == self.offset:
                return
            with open(self.path, "rb") as fh:
                fh.seek(self.offset)
                chunk = fh.read(min(st.st_size - self.offset, 64 * 1024 * 1024))
            end = chunk.rfind(b"\n")
            if end < 0:
                return  # partially written line; wait for newline
            body = chunk[: end + 1]
            self.offset += len(body)
            for line in body.split(b"\n"):
                line = line.strip()
                if not line:
                    continue
                self.lines += 1
                try:
                    o = json.loads(line)
                    name = str(o.get("name"))
                    split = str(o.get("split") or "train")
                    v = fnum(o.get("value"))
                    if v is None or not o.get("name"):
                        raise ValueError
                except Exception:
                    self.bad += 1
                    continue
                step = fnum(o.get("step"))
                ep = fnum(o.get("epoch"))
                arr = self.series[(split, name)]
                arr.append((step, ep, v, o.get("ts")))
                if len(arr) > 400000:  # memory bound: decimate oldest half
                    self.series[(split, name)] = arr[: len(arr) // 2: 2] + arr[len(arr) // 2:]

    def keys(self) -> list[dict]:
        return [{"split": k[0], "name": k[1], "n": len(v)} for k, v in sorted(self.series.items())]


_runs: dict[str, RunMetrics] = {}
_runs_lock = threading.Lock()


def run_dirs() -> list[Path]:
    if not RUNS.is_dir():
        return []
    out = []
    for p in RUNS.iterdir():
        if p.is_dir() and not p.name.startswith("."):
            out.append(p)
    return out


def get_run_metrics(run_id: str) -> RunMetrics | None:
    d = safe_child(RUNS, run_id)
    if not d or not d.is_dir():
        return None
    with _runs_lock:
        rm = _runs.get(run_id)
        if rm is None:
            rm = _runs[run_id] = RunMetrics(d / "metrics.jsonl")
    rm.update()
    return rm


def downsample(points: list[tuple], limit: int = MAX_POINTS) -> list[tuple]:
    n = len(points)
    if n <= limit:
        return points
    buckets = max(1, (limit - 2) // 2)  # min+max per bucket, plus first/last -> never more than `limit`
    size = n / buckets
    out = []
    for b in range(buckets):
        lo, hi = int(b * size), int((b + 1) * size)
        seg = points[lo:hi] or points[lo:lo + 1]
        imin = min(range(len(seg)), key=lambda i: seg[i][2])
        imax = max(range(len(seg)), key=lambda i: seg[i][2])
        for i in sorted({imin, imax}):
            out.append(seg[i])
    if out[0] is not points[0]:
        out.insert(0, points[0])
    if out[-1] is not points[-1]:
        out.append(points[-1])
    return out


def run_status(d: Path) -> dict:
    st, err = read_json(d / "status.json")
    st = st if isinstance(st, dict) else {}
    out = {"run_id": d.name, "status": st, "status_error": err}
    try:
        mt = max((f.stat().st_mtime for f in d.iterdir() if f.is_file()), default=d.stat().st_mtime)
    except Exception:
        mt = None
    out["mtime"] = mt
    samples = d / "samples"
    out["n_samples"] = sum(1 for f in samples.iterdir() if f.suffix.lower() in IMG_EXT) if samples.is_dir() else 0
    out["has_log"] = (d / "log.txt").is_file()
    return out


_FAMILY_RE = re.compile(r"^family:\s*['\"]?([A-Za-z0-9_-]+)", re.M)
_cfg_family: dict[str, tuple] = {}


def experiment_families() -> dict[str, str]:
    """experiment id (and run_dir basename) -> family, from state/experiments.json"""
    data, err = read_json(STATE / "experiments.json")
    if err or not data:
        return {}
    exps = data.get("experiments") if isinstance(data, dict) else data
    out: dict[str, str] = {}
    for e in exps or []:
        if not isinstance(e, dict) or not isinstance(e.get("family"), str):
            continue
        if e.get("id") is not None:
            out.setdefault(str(e["id"]), e["family"])
        rd = e.get("run_dir")
        if isinstance(rd, str) and rd.strip():
            out.setdefault(Path(rd.rstrip("/")).name, e["family"])
    return out


def config_family(d: Path) -> str | None:
    """top-level `family:` of runs/<id>/config.yaml (cached by mtime/size)"""
    f = d / "config.yaml"
    try:
        stt = f.stat()
    except OSError:
        return None
    sig = (stt.st_mtime_ns, stt.st_size)
    hit = _cfg_family.get(str(f))
    if hit and hit[0] == sig:
        return hit[1]
    fam = None
    try:
        with open(f, "r", encoding="utf-8", errors="replace") as fh:
            m = _FAMILY_RE.search(fh.read(65536))
        fam = m.group(1) if m else None
    except OSError:
        fam = None
    _cfg_family[str(f)] = (sig, fam)
    return fam


def run_family(d: Path, status: dict, fams: dict[str, str]) -> str | None:
    """family of a run: experiments.json (run id, run_dir basename or status exp_id), else config.yaml, else None"""
    exp_id = status.get("exp_id") if isinstance(status, dict) else None
    fam = fams.get(d.name) or (fams.get(str(exp_id)) if exp_id is not None else None) or config_family(d)
    return fam if isinstance(fam, str) and fam else None


def run_hidden(name: str) -> bool:
    """run dirs the Training list hides by default: `_discarded`, `*_smoke` and other `_*` dirs (same rule as the leaderboard)"""
    return lb_excluded(name)


@app.get("/api/runs")
@safe
def api_runs(hidden: str = ""):
    runs = []
    dirs = run_dirs()
    fams = experiment_families()
    show_hidden = str(hidden).strip().lower() in ("1", "true", "yes", "on")
    with _runs_lock:  # free the in-memory series of runs whose directory was deleted
        for rid in [k for k in _runs if k not in {d.name for d in dirs}]:
            _runs.pop(rid, None)
    n_hidden = 0
    for d in dirs:
        hid = run_hidden(d.name)
        n_hidden += hid
        if hid and not show_hidden:
            continue
        r = run_status(d)
        r["hidden"] = hid
        rm = get_run_metrics(d.name)
        r["series"] = rm.keys() if rm else []
        r["bad_lines"] = rm.bad if rm else 0
        r["family"] = run_family(d, r["status"], fams)
        runs.append(r)
    order = {"running": 0, "queued": 1, "done": 2, "failed": 3}
    runs.sort(key=lambda r: (order.get(str(r["status"].get("state")), 4), -(r["mtime"] or 0)))
    upd = max((r["mtime"] for r in runs if r.get("mtime")), default=None)
    return {"runs": runs, "n_hidden": n_hidden, "show_hidden": show_hidden, "updated": _iso(upd),
            "now": time.time()}


@app.get("/api/runs/{run_id}/metrics")
@safe
def api_run_metrics(run_id: str, name: str = "", split: str = "", max_points: int = MAX_POINTS):
    rm = get_run_metrics(run_id)
    if rm is None:
        return {"ok": False, "error": "run not found", "series": []}
    max_points = max(50, min(int(max_points), MAX_POINTS))
    out = []
    for (sp, nm), pts in sorted(rm.series.items()):
        if name and nm != name:
            continue
        if split and sp != split:
            continue
        ds = downsample(pts, max_points)
        out.append({"split": sp, "name": nm, "n": len(pts),
                    "step": [p[0] for p in ds], "epoch": [p[1] for p in ds], "value": [p[2] for p in ds],
                    "last_ts": pts[-1][3] if pts else None})
    return {"run_id": run_id, "series": out, "bad_lines": rm.bad}


def tail_lines(path: Path, n: int = 200, max_bytes: int = 512 * 1024) -> list[str]:
    try:
        size = path.stat().st_size
    except FileNotFoundError:
        return []
    with open(path, "rb") as fh:
        fh.seek(max(0, size - max_bytes))
        data = fh.read()
    lines = data.decode("utf-8", "replace").splitlines()
    if size > max_bytes and lines:
        lines = lines[1:]
    return [ln[:2000] for ln in lines[-n:]]


@app.get("/api/runs/{run_id}/log")
@safe
def api_run_log(run_id: str, lines: int = 200):
    d = safe_child(RUNS, run_id)
    if not d or not d.is_dir():
        return {"ok": False, "error": "run not found", "lines": []}
    return {"run_id": run_id, "lines": tail_lines(d / "log.txt", max(1, min(int(lines), 1000)))}


@app.get("/api/runs/{run_id}/samples")
@safe
def api_run_samples(run_id: str):
    d = safe_child(RUNS, run_id)
    if not d or not d.is_dir():
        return {"ok": False, "error": "run not found", "samples": []}
    sd = d / "samples"
    items = []
    if sd.is_dir():
        for f in sd.iterdir():
            if f.is_file() and f.suffix.lower() in IMG_EXT:
                items.append({"file": f.name, "mtime": f.stat().st_mtime, "size": f.stat().st_size})
    items.sort(key=lambda x: x["mtime"], reverse=True)
    return {"run_id": run_id, "samples": items[:200]}


@app.get("/api/runs/{run_id}/samples/{file}")
def api_run_sample(run_id: str, file: str):
    d = safe_child(RUNS, run_id)
    p = safe_child(d / "samples", file) if d else None
    if not p or not p.is_file() or p.suffix.lower() not in IMG_EXT:
        return JSONResponse({"ok": False, "error": "not found"}, status_code=404)
    return FileResponse(p, headers={"Cache-Control": "max-age=10"})


# ----------------------------------------------------------------------------
# system
# ----------------------------------------------------------------------------
_nvml_ok = None
_nvml_lock = threading.Lock()


def _nvml():
    global _nvml_ok
    with _nvml_lock:
        if _nvml_ok is None:
            try:
                import warnings

                with warnings.catch_warnings():
                    warnings.simplefilter("ignore")
                    import pynvml  # noqa: F401
                pynvml.nvmlInit()
                _nvml_ok = pynvml
            except Exception:
                _nvml_ok = False
        return _nvml_ok or None


def gpu_info() -> dict:
    nv = _nvml()
    gpus, pid_gpu = [], {}
    if nv:
        try:
            for i in range(nv.nvmlDeviceGetCount()):
                h = nv.nvmlDeviceGetHandleByIndex(i)
                g = {"index": i}
                try:
                    name = nv.nvmlDeviceGetName(h)
                    g["name"] = name.decode() if isinstance(name, bytes) else name
                except Exception:
                    g["name"] = "GPU"
                try:
                    u = nv.nvmlDeviceGetUtilizationRates(h)
                    g["util"] = u.gpu
                    g["mem_util"] = u.memory
                except Exception:
                    g["util"] = None
                try:
                    m = nv.nvmlDeviceGetMemoryInfo(h)
                    g["mem_used"] = m.used
                    g["mem_total"] = m.total
                except Exception:
                    pass
                try:
                    g["temp"] = nv.nvmlDeviceGetTemperature(h, 0)
                except Exception:
                    g["temp"] = None
                try:
                    g["power_w"] = nv.nvmlDeviceGetPowerUsage(h) / 1000.0
                    g["power_limit_w"] = nv.nvmlDeviceGetEnforcedPowerLimit(h) / 1000.0
                except Exception:
                    pass
                try:
                    for pr in nv.nvmlDeviceGetComputeRunningProcesses(h):
                        pid_gpu.setdefault(pr.pid, []).append(i)
                except Exception:
                    pass
                gpus.append(g)
            return {"source": "nvml", "gpus": gpus, "pid_gpu": pid_gpu}
        except Exception:
            gpus = []
    # fallback: nvidia-smi
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=index,name,utilization.gpu,memory.used,memory.total,temperature.gpu,power.draw,power.limit",
             "--format=csv,noheader,nounits"], capture_output=True, text=True, timeout=5).stdout
        for line in out.strip().splitlines():
            p = [x.strip() for x in line.split(",")]
            if len(p) < 8:
                continue
            gpus.append({"index": int(p[0]), "name": p[1], "util": fnum(p[2]),
                         "mem_used": (fnum(p[3]) or 0) * 1048576, "mem_total": (fnum(p[4]) or 0) * 1048576,
                         "temp": fnum(p[5]), "power_w": fnum(p[6]), "power_limit_w": fnum(p[7])})
        return {"source": "nvidia-smi", "gpus": gpus, "pid_gpu": {}}
    except Exception as e:
        return {"source": "none", "gpus": [], "pid_gpu": {}, "error": str(e)[:200]}


# secrets in command lines: `--hf-token X`, `--api-key=X`, `PASSWORD=X`, `--wandb-key X`, `https://user:pass@host`,
# `unzip -P X`. The option / variable name must END with the keyword, so `--max-tokens 512` stays readable.
_SECRET_ARG_RE = re.compile(
    r"(?i)((?<![\w-])[\w.-]*?(?:token|secret(?:[_-]?key)?|passw(?:or)?d|passphrase|pwd|api[_-]?key|access[_-]?key"
    r"|private[_-]?key|(?<=\w[_.-])key|auth|credentials?|cookie)(?:=|\s+))(?!-)\S+")
_URL_CRED_RE = re.compile(r"(?i)(\b[a-z][a-z0-9+.-]*://)[^/\s@]+@")
_UNZIP_PW_RE = re.compile(r"(\s-P\s*)\S+")


def redact_cmd(cs: str, unzip: bool = False) -> str:
    """mask secrets in a process command line before it is shown on the dashboard"""
    cs = _URL_CRED_RE.sub(r"\1***@", cs)
    cs = _SECRET_ARG_RE.sub(r"\1***", cs)
    return _UNZIP_PW_RE.sub(r"\1***", cs) if unzip else cs


def procs_info(pid_gpu: dict) -> dict:
    import psutil

    train, unzip = [], []
    if DEMO:   # synthetic demo data: do not show this machine's processes
        return {"train": train, "unzip": unzip, "hidden": True}
    for p in psutil.process_iter(["pid", "name", "cmdline", "create_time"]):
        try:
            cmd = p.info.get("cmdline") or []
            cs = " ".join(cmd)
            nm = p.info.get("name") or ""
            if nm == "unzip" or (cmd and os.path.basename(cmd[0]) == "unzip"):
                unzip.append({"pid": p.info["pid"], "cmd": redact_cmd(cs, unzip=True)[:300]})
                continue
            if "python" in (nm + " " + (cmd[0] if cmd else "")).lower() and "train" in cs.lower() \
                    and "an_dashboard" not in cs and "dashboard/server.py" not in cs:
                gpu = pid_gpu.get(p.info["pid"])
                if gpu is None:
                    try:
                        cvd = p.environ().get("CUDA_VISIBLE_DEVICES")
                        gpu = cvd if cvd not in (None, "") else None
                    except Exception:
                        gpu = None
                train.append({"pid": p.info["pid"], "gpu": gpu,
                              "elapsed_s": round(time.time() - (p.info.get("create_time") or time.time())),
                              "cmd": redact_cmd(cs)[:240]})
        except Exception:
            continue
    return {"train": train, "unzip": unzip}


_du = {"bytes": None, "files": None, "ts": 0.0, "running": False, "secs": None}
_du_lock = threading.Lock()


def _du_worker() -> None:
    t0 = time.time()
    total = files = 0
    try:
        out = subprocess.run(["du", "-sb", str(RAW)], capture_output=True, text=True, timeout=600).stdout
        total = int(out.split()[0]) if out.strip() else 0
    except Exception:
        total = None
    with _du_lock:
        _du.update(bytes=total, ts=time.time(), running=False, secs=round(time.time() - t0, 1))


def extraction_info(unzip_running: bool) -> dict:
    ttl = 30 if unzip_running else 600
    with _du_lock:
        stale = time.time() - _du["ts"] > ttl
        if _RAW_ENV and stale and not _du["running"] and RAW.exists():
            _du["running"] = True
            threading.Thread(target=_du_worker, daemon=True).start()
        b = _du["bytes"]
        return {"configured": bool(_RAW_ENV), "bytes": b, "total": RAW_TOTAL,
                "frac": (b / RAW_TOTAL) if b and RAW_TOTAL else None,
                "measured_at": _du["ts"] or None, "measuring": _du["running"], "du_secs": _du["secs"],
                "unzip_running": unzip_running}


def supervisor_info() -> list[dict]:
    if DEMO:   # synthetic demo data: do not show this machine's supervisor programs
        return []
    try:
        out = subprocess.run(["supervisorctl", "status"], capture_output=True, text=True, timeout=8).stdout
    except Exception as e:
        return [{"name": "supervisorctl", "state": "ERROR", "info": str(e)[:200]}]
    rows = []
    for line in out.splitlines():
        parts = line.split(None, 2)
        if len(parts) >= 2:
            rows.append({"name": parts[0], "state": parts[1], "info": parts[2] if len(parts) > 2 else ""})
    return rows


def _disk_target() -> Path:
    """DISK_PATH, or its nearest existing parent (a project root that does not exist yet still has a disk)"""
    p = Path(DISK_PATH)
    while not p.exists() and p != p.parent:
        p = p.parent
    return p


def host_info() -> dict:
    import psutil

    vm = psutil.virtual_memory()
    try:
        du = shutil.disk_usage(_disk_target())
        disk = {"total": du.total, "used": du.used, "free": du.free, "path": DISK_PATH}
    except Exception:
        disk = None
    try:
        la = os.getloadavg()
    except Exception:
        la = None
    pids = None
    try:
        pids = {"current": int(open("/sys/fs/cgroup/pids.current").read()),
                "max": open("/sys/fs/cgroup/pids.max").read().strip()}
    except Exception:
        pass
    return {"cpu_percent": psutil.cpu_percent(interval=None), "cpu_count": psutil.cpu_count(),
            "load": la, "ram": {"total": vm.total, "used": vm.total - vm.available, "percent": vm.percent},
            "disk_workspace": disk, "pids": pids}


@app.get("/api/system")
@safe
def api_system():
    g = CACHE.get("gpu", 3, gpu_info)
    pr = CACHE.get("procs", 5, lambda: procs_info(g.get("pid_gpu", {})))
    h = CACHE.get("host", 3, host_info)
    sv = CACHE.get("supervisor", 10, supervisor_info)
    ex = extraction_info(bool(pr["unzip"]))
    return {"ts": now_iso(), "gpu_source": g.get("source"), "gpus": g.get("gpus", []), "host": h,
            "train_procs": pr["train"], "unzip_procs": pr["unzip"], "extraction": ex, "supervisor": sv,
            "disk_path": DISK_PATH, "demo": DEMO}


# ----------------------------------------------------------------------------
# agents (Claude Code transcripts)
# ----------------------------------------------------------------------------
WANTED_TYPES = {"user", "assistant", "agent-name", "custom-title"}
_prefix_re = re.compile(rb'^\{"type":"([^"]+)"')


def _clip(s: Any, n: int) -> str:
    if s is None:
        return ""
    if not isinstance(s, str):
        try:
            s = json.dumps(s, ensure_ascii=False)
        except Exception:
            s = str(s)
    return s if len(s) <= n else s[:n] + f"… [+{len(s) - n} chars]"


def tool_summary(name: str, inp: Any) -> dict:
    inp = inp if isinstance(inp, dict) else {"input": inp}
    n = (name or "").lower()
    out: dict[str, Any] = {}
    if n == "bash":
        out["main"] = _clip(inp.get("command"), 1200)
        if inp.get("description"):
            out["desc"] = _clip(inp.get("description"), 200)
        if inp.get("run_in_background"):
            out["flags"] = "background"
    elif n in ("read", "write", "edit", "multiedit", "notebookedit"):
        out["main"] = _clip(inp.get("file_path") or inp.get("notebook_path"), 400)
        if n == "edit":
            out["old"] = _clip(inp.get("old_string"), 300)
            out["new"] = _clip(inp.get("new_string"), 300)
        elif n == "write":
            out["new"] = _clip(inp.get("content"), 300)
        elif n == "read" and (inp.get("offset") or inp.get("limit")):
            out["desc"] = f"offset={inp.get('offset')} limit={inp.get('limit')}"
    elif n in ("agent", "task", "workflow") or "agent" in n or "workflow" in n:
        out["main"] = _clip(inp.get("prompt") or inp.get("task") or inp.get("script") or inp.get("description"), 400)
        d = inp.get("description") or inp.get("subagent_type") or inp.get("name")
        if d:
            out["desc"] = _clip(d, 200)
    elif n in ("grep", "glob"):
        out["main"] = _clip(inp.get("pattern"), 300)
        if inp.get("path"):
            out["desc"] = _clip(inp.get("path"), 300)
    elif n == "webfetch":
        out["main"] = _clip(inp.get("url"), 400)
        if inp.get("prompt"):
            out["desc"] = _clip(inp.get("prompt"), 200)
    elif n == "websearch":
        out["main"] = _clip(inp.get("query"), 300)
    elif n == "structuredoutput":
        out["main"] = _clip(inp, 400)
    elif n == "skill":
        out["main"] = _clip(inp.get("skill"), 200)
        if inp.get("args"):
            out["desc"] = _clip(inp.get("args"), 200)
    else:
        for k in ("command", "file_path", "path", "url", "query", "prompt", "pattern"):
            if inp.get(k):
                out["main"] = _clip(inp.get(k), 400)
                break
        else:
            out["main"] = _clip(inp, 400)
    return out


def result_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for b in content:
            if isinstance(b, dict):
                if b.get("type") == "text":
                    parts.append(str(b.get("text") or ""))
                elif b.get("type") == "image":
                    parts.append("[image]")
                else:
                    parts.append(f"[{b.get('type')}]")
            else:
                parts.append(str(b))
        return "\n".join(parts)
    if content is None:
        return ""
    return _clip(content, 4000)


class AgentFile:
    def __init__(self, path: Path, rel: str, aid: str, is_main: bool) -> None:
        self.path = path
        self.rel = rel
        self.id = aid
        self.is_main = is_main
        self.offset = 0
        self.ino = None
        self.msgs: collections.deque = collections.deque(maxlen=MAX_AGENT_MSGS)
        self.seq = 0
        self.n_messages = 0
        self.n_tool_calls = 0
        self.first_ts = None
        self.last_ts = None
        self.last_tool = None
        self.last_text = None
        self.title = None      # custom-title
        self.agent_name = None  # agent-name
        self.model = None
        self.is_sidechain = not is_main
        self.mtime = 0.0
        self.size = 0
        self.lock = threading.Lock()
        self.last_check = 0.0
        self.bad = 0
        self.tool_names: dict[str, str] = {}
        self._usage_reset()

    def _reset(self) -> None:
        self.offset = 0
        self.msgs.clear()
        self.seq = 0
        self.n_messages = self.n_tool_calls = 0
        self.first_ts = self.last_ts = self.last_tool = self.last_text = None
        self.tool_names = {}
        self._usage_reset()

    # -- token usage counters (Session view); filled incrementally by _line ------------------------
    _USAGE_KEYS = ("output_tokens_total", "thinking_tokens_total", "cache_read_total",
                   "cache_creation_total", "input_tokens_total")

    def _usage_reset(self) -> None:
        self.usage = {"turns": 0, "assistant_messages": 0, "output_tokens_total": 0, "thinking_tokens_total": 0,
                      "cache_read_total": 0, "cache_creation_total": 0, "input_tokens_total": 0,
                      "last_context_tokens": None, "last_model": None, "last_ts": None}
        # Claude Code writes one transcript line per content block and repeats the API message's usage on
        # each of them -> count every message.id once (the newest copy wins); bounded memory.
        self._usage_recent: collections.OrderedDict = collections.OrderedDict()

    @staticmethod
    def _tok(d: Any, k: str) -> int:
        v = d.get(k) if isinstance(d, dict) else None
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            return 0
        return int(v) if math.isfinite(v) and v > 0 else 0

    def _count_usage(self, o: dict, msg: dict) -> None:
        model = msg.get("model")
        if model == "<synthetic>":
            return
        us = msg.get("usage")
        if not isinstance(us, dict):
            return
        vals = (self._tok(us, "output_tokens"), self._tok(us.get("output_tokens_details"), "thinking_tokens"),
                self._tok(us, "cache_read_input_tokens"), self._tok(us, "cache_creation_input_tokens"),
                self._tok(us, "input_tokens"))
        mid = msg.get("id") or o.get("requestId") or o.get("uuid")
        u = self.usage
        old = self._usage_recent.pop(mid, None) if mid else None
        if old is None:
            u["assistant_messages"] += 1
        else:
            for k, v in zip(self._USAGE_KEYS, old):
                u[k] -= v
        for k, v in zip(self._USAGE_KEYS, vals):
            u[k] += v
        if mid:
            self._usage_recent[mid] = vals
            while len(self._usage_recent) > 256:
                self._usage_recent.popitem(last=False)
        u["last_context_tokens"] = vals[4] + vals[2] + vals[3]
        if isinstance(model, str) and model:
            u["last_model"] = model
        if o.get("timestamp"):
            u["last_ts"] = o.get("timestamp")

    _NOT_A_TURN_RE = re.compile(r"\s*<task-notification\b")

    def _count_turn(self, msg: dict, meta: str | None = None) -> None:
        """A turn is a user line with text that is not a tool_result, not harness-injected (`isMeta`, the
        auto-compaction summary) and not a background-task notification (README §17)."""
        if meta:
            return
        c = msg.get("content")
        first = None
        if isinstance(c, str):
            ok, first = bool(c.strip()), c
        elif isinstance(c, list):
            types = {b.get("type") for b in c if isinstance(b, dict)}
            ok = "text" in types and "tool_result" not in types
            first = next((str(b.get("text") or "") for b in c if isinstance(b, dict) and b.get("type") == "text"), None)
        else:
            ok = False
        if ok and first is not None and self._NOT_A_TURN_RE.match(first):
            ok = False
        if ok:
            self.usage["turns"] += 1

    def usage_snapshot(self) -> dict:
        with self.lock:
            return dict(self.usage)

    def update(self, min_interval: float = 2.0) -> None:
        with self.lock:
            if time.time() - self.last_check < min_interval:
                return
            self.last_check = time.time()
            try:
                st = self.path.stat()
            except FileNotFoundError:
                return
            self.mtime, self.size = st.st_mtime, st.st_size
            if self.ino is not None and (self.ino != st.st_ino or st.st_size < self.offset):
                self._reset()
            self.ino = st.st_ino
            budget = 48 * 1024 * 1024
            while self.offset < st.st_size and budget > 0:
                with open(self.path, "rb") as fh:
                    fh.seek(self.offset)
                    chunk = fh.read(min(st.st_size - self.offset, 8 * 1024 * 1024))
                if not chunk:
                    break
                end = chunk.rfind(b"\n")
                if end < 0:
                    if len(chunk) >= 8 * 1024 * 1024:  # one gigantic line: read it whole
                        with open(self.path, "rb") as fh:
                            fh.seek(self.offset)
                            line = fh.readline()
                        if line.endswith(b"\n"):
                            self.offset += len(line)
                            self._line(line)
                            budget -= len(line)
                            continue
                    break  # truncated last line; wait for the rest
                body = chunk[: end + 1]
                self.offset += len(body)
                budget -= len(body)
                for line in body.split(b"\n"):
                    if line:
                        self._line(line)

    def _line(self, line: bytes) -> None:
        m = _prefix_re.match(line)
        if m and m.group(1).decode("ascii", "replace") not in WANTED_TYPES:
            return
        try:
            o = json.loads(line)
        except Exception:
            self.bad += 1
            return
        if not isinstance(o, dict):
            return
        t = o.get("type")
        if t == "agent-name":
            self.agent_name = o.get("agentName") or o.get("name") or self.agent_name
            return
        if t == "custom-title":
            self.title = o.get("customTitle") or o.get("title") or self.title
            return
        if t not in ("user", "assistant"):
            return
        if o.get("isSidechain") is True:
            self.is_sidechain = True
        msg = o.get("message") if isinstance(o.get("message"), dict) else {}
        ts = o.get("timestamp")
        role = msg.get("role") or t
        if t == "assistant" and msg.get("model") and msg.get("model") != "<synthetic>":
            self.model = msg.get("model")
        meta = None
        if t == "user":
            if o.get("isCompactSummary") is True:
                meta = "compact"
            elif o.get("isMeta") is True:
                meta = "meta"
        if t == "assistant":
            self._count_usage(o, msg)
        elif o.get("isSidechain") is not True:
            self._count_turn(msg, meta)
        content = msg.get("content")
        blocks = []
        if isinstance(content, str):
            if content.strip():
                blocks.append({"t": "text", "text": _clip(content, 16000)})
        elif isinstance(content, list):
            for b in content:
                if not isinstance(b, dict):
                    continue
                bt = b.get("type")
                if bt == "text":
                    tx = str(b.get("text") or "")
                    if tx.strip():
                        blocks.append({"t": "text", "text": _clip(tx, 16000)})
                elif bt == "tool_use":
                    nm = str(b.get("name") or "?")
                    self.tool_names[str(b.get("id"))] = nm
                    if len(self.tool_names) > 5000:
                        self.tool_names = dict(list(self.tool_names.items())[-2500:])
                    blocks.append({"t": "tool_use", "id": b.get("id"), "name": nm, "input": tool_summary(nm, b.get("input"))})
                elif bt == "tool_result":
                    tx = result_text(b.get("content"))
                    tid = str(b.get("tool_use_id"))
                    blocks.append({"t": "tool_result", "tool_use_id": tid, "name": self.tool_names.get(tid),
                                   "is_error": bool(b.get("is_error")), "len": len(tx), "text": _clip(tx, 4000)})
                elif bt == "thinking":
                    tx = str(b.get("thinking") or "")
                    if tx.strip():
                        blocks.append({"t": "thinking", "text": _clip(tx, 8000)})
                elif bt == "image":
                    blocks.append({"t": "text", "text": "[image]"})
        if not blocks:
            return
        if t == "user" and all(b["t"] == "tool_result" for b in blocks):
            role = "tool"
        self.seq += 1
        self.n_messages += 1
        rec = {"seq": self.seq, "ts": ts, "role": role, "blocks": blocks}
        if meta:
            rec["meta"] = meta   # harness-injected user line (isMeta / isCompactSummary): not the user's own words
        self.msgs.append(rec)
        if ts:
            if not self.first_ts:
                self.first_ts = ts
            self.last_ts = ts
        for b in blocks:
            if b["t"] == "tool_use":
                self.n_tool_calls += 1
                self.last_tool = {"name": b["name"], "main": _clip(b["input"].get("main"), 240),
                                  "desc": b["input"].get("desc"), "ts": ts}
            elif b["t"] == "text" and role == "assistant":
                self.last_text = _clip(b["text"], 280)

    def label(self, meta: dict) -> str:
        if self.is_main:
            return self.title or self.agent_name or "orchestrator"
        return meta.get("label") or self.agent_name or self.title or meta.get("description") or self.id

    def summary(self, meta: dict) -> dict:
        active = (time.time() - self.mtime) < ACTIVE_WINDOW_S if self.mtime else False
        return {"id": self.id, "file": self.rel, "label": self.label(meta), "phase": meta.get("phase"),
                "is_main": self.is_main, "is_sidechain": self.is_sidechain, "model": self.model or meta.get("model"),
                "first_ts": self.first_ts, "last_ts": self.last_ts, "n_messages": self.n_messages,
                "n_tool_calls": self.n_tool_calls, "active": active, "mtime": self.mtime, "size": self.size,
                "last_tool": self.last_tool, "last_text_snippet": self.last_text, "done": meta.get("done", False)}


class AgentRegistry:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.files: dict[str, AgentFile] = {}
        self.meta: dict[str, dict] = {}
        self.lock = threading.Lock()
        self.last_scan = 0.0
        self.journals: dict[str, tuple[float, int]] = {}

    def _scan(self) -> None:
        if time.time() - self.last_scan < 5:
            return
        self.last_scan = time.time()
        if not self.root.is_dir():
            return
        seen_ids: set[str] = set(f.id for f in self.files.values())
        for p in self.root.rglob("*.jsonl"):
            try:
                rel = str(p.relative_to(self.root))
            except Exception:
                continue
            if rel.split("/")[0] == "memory":
                continue
            if p.name == "journal.jsonl":
                self._journal(p)
                continue
            if rel in {f.rel for f in self.files.values()}:
                continue
            is_main = "/" not in rel
            stem = p.stem
            aid = stem[6:] if stem.startswith("agent-") else stem
            aid = re.sub(r"[^A-Za-z0-9_.-]", "_", aid)
            if aid in seen_ids:
                aid = aid + "-" + hashlib.sha1(rel.encode()).hexdigest()[:6]
            seen_ids.add(aid)
            self.files[rel] = AgentFile(p, rel, aid, is_main)
            mp = p.with_name(stem + ".meta.json")
            if mp.is_file():
                mj, _ = read_json(mp)
                if isinstance(mj, dict):
                    m = self.meta.setdefault(aid, {})
                    m.setdefault("description", mj.get("description"))
                    m.setdefault("model", mj.get("model"))
                    if mj.get("workflowPhase"):
                        m.setdefault("phase", mj.get("workflowPhase"))

    def _journal(self, p: Path) -> None:
        try:
            st = p.stat()
        except Exception:
            return
        sig = (st.st_mtime, st.st_size)
        if self.journals.get(str(p)) == sig:
            return
        self.journals[str(p)] = sig
        try:
            with open(p, "rb") as fh:
                for line in fh:
                    try:
                        o = json.loads(line)
                    except Exception:
                        continue
                    aid = o.get("agentId")
                    if not aid:
                        continue
                    m = self.meta.setdefault(aid, {})
                    if o.get("type") == "started":
                        if o.get("label"):
                            m["label"] = o["label"]
                        if o.get("phase"):
                            m["phase"] = o["phase"]
                    elif o.get("type") == "result":
                        m["done"] = True
        except Exception:
            pass

    def refresh(self) -> None:
        with self.lock:
            self._scan()
            files = list(self.files.values())
        for f in files:
            try:
                f.update()
            except Exception:
                pass

    def get(self, aid: str) -> AgentFile | None:
        with self.lock:
            for f in self.files.values():
                if f.id == aid:
                    return f
        return None

    def list(self) -> list[dict]:
        self.refresh()
        out = [f.summary(self.meta.get(f.id, {})) for f in list(self.files.values())]
        out.sort(key=lambda a: (not a["is_main"], not a["active"], -(a["mtime"] or 0)))
        return out


AGENTS = AgentRegistry(TRANSCRIPTS)


@app.get("/api/agents")
@safe
def api_agents():
    lst = CACHE.get("agents", 2, AGENTS.list)
    activity = [{"id": a["id"], "label": a["label"], "tool": a["last_tool"], "is_main": a["is_main"]}
                for a in lst if a["active"] and a["last_tool"]]
    activity.sort(key=lambda x: str((x["tool"] or {}).get("ts") or ""), reverse=True)
    upd = max((a["mtime"] for a in lst if a.get("mtime")), default=None)
    return {"agents": lst, "activity": activity, "n_active": sum(1 for a in lst if a["active"]),
            "root": str(TRANSCRIPTS) if _TRANSCRIPTS_ENV else None, "updated": _iso(upd), "now": time.time()}


@app.get("/api/agents/{aid}/messages")
@safe
def api_agent_messages(aid: str, since: int = -1, limit: int = 200):
    f = AGENTS.get(aid)
    if f is None:
        AGENTS.refresh()
        f = AGENTS.get(aid)
    if f is None:
        return {"ok": False, "error": "agent not found", "messages": []}
    f.update(min_interval=1.0)
    limit = max(1, min(int(limit), 500))
    with f.lock:
        msgs = list(f.msgs)
    first_seq = msgs[0]["seq"] if msgs else 0
    if since is None or since < 0:
        sel = msgs[-limit:]
        more = False
    else:
        sel = [m for m in msgs if m["seq"] > since]
        more = len(sel) > limit
        sel = sel[:limit]
    cursor = sel[-1]["seq"] if sel else (since if since is not None and since >= 0 else f.seq)
    return {"id": aid, "messages": sel, "cursor": cursor, "more": more, "latest_seq": f.seq,
            "first_seq": first_seq, "gap": bool(since is not None and since >= 0 and msgs and since < first_seq - 1),
            "summary": f.summary(AGENTS.meta.get(aid, {}))}


# ----------------------------------------------------------------------------
# session view: mirror of the main Claude Code session + dashboard -> orchestrator inbox
# (contracts: README §17; the server never acts on inbox messages)
# ----------------------------------------------------------------------------
SESSION_INBOX = STATE / "session_inbox.jsonl"
SESSION_INBOX_LOCK = STATE / "session_inbox.jsonl.lock"
SESSION_ACK = STATE / "session_inbox_ack.json"
SESSION_WATCH = STATE / "session_watch.json"
SESSION_STATUS = STATE / "session_status.json"
LISTEN_WINDOW_S = 15.0
SESSION_MODELS = ("fable-5.1", "opus-5.5", "sonnet-5.5", "haiku-5.5")
SESSION_EFFORTS = ("low", "medium", "high", "xhigh", "max")
SESSION_CONTROLS = ("remote_control",)
SEND_MAX_BYTES = 32 * 1024
SEND_MAX_CHARS = 20000
SEND_MIN_GAP_S = 1.0
SEND_WINDOW_S = 600.0
SEND_WINDOW_MAX = 60
SESSION_MIN_INTERVAL = 1.0   # transcript re-read throttle for the session endpoints (s)
INBOX_KEEP = 5000            # inbox messages kept in memory
INBOX_LIST_MAX = 200

_send_clock: Callable[[], float] = time.monotonic   # tests replace it
_send_times: collections.deque = collections.deque()
_send_lock = threading.Lock()
_send_last_id = 0
_session_extra: dict[str, AgentFile] = {}
_inbox_cache: dict[str, Any] = {"sig": None, "items": [], "bad": 0}
_inbox_lock = threading.Lock()


def main_session() -> tuple[AgentFile | None, str | None]:
    """The transcript of the main session: $AN_SESSION_FILE (absolute path) if usable, else the top-level
    (is_main) transcript with the newest mtime.  Returns (file, note)."""
    with AGENTS.lock:
        AGENTS._scan()
        files = list(AGENTS.files.values())
    note = None
    env = os.environ.get("AN_SESSION_FILE", "").strip()
    if env:
        p = Path(env)
        try:
            rp = p.resolve() if p.is_absolute() else None
        except Exception:
            rp = None
        if rp is not None and rp.suffix == ".jsonl" and rp.is_file():
            for f in files:
                if str(f.path) == env or (f.is_main and f.path.resolve() == rp):
                    return f, None
            with AGENTS.lock:
                f = _session_extra.get(str(rp))
                if f is None:
                    _session_extra.clear()
                    f = AgentFile(rp, rp.name, re.sub(r"[^A-Za-z0-9_.-]", "_", rp.stem), True)
                    _session_extra[str(rp)] = f
            return f, None
        note = "AN_SESSION_FILE is not an existing absolute .jsonl path; using the newest main transcript"
    best, best_m = None, -1.0
    for f in files:
        if not f.is_main:
            continue
        try:
            m = f.path.stat().st_mtime
        except Exception:
            continue
        if m > best_m:
            best, best_m = f, m
    return best, note


def _inbox_item(o: dict) -> dict | None:
    i = o.get("id")
    if isinstance(i, bool) or not isinstance(i, int) or i <= 0:
        return None
    s = lambda k, n=64: (_clip(o.get(k), n) if o.get(k) is not None else None)  # noqa: E731
    it = {"id": i, "ts": s("ts"), "kind": s("kind") or "message", "text": _clip(o.get("text") or "", SEND_MAX_CHARS),
          "model": s("model"), "effort": s("effort"), "source": s("source"), "client": s("client", 120)}
    if it["kind"] == "control":
        it["control"] = s("control")
        it["value"] = o.get("value") if isinstance(o.get("value"), (bool, int, float, str)) else None
    return it


def read_inbox() -> tuple[list[dict], int]:
    """Parsed inbox (oldest first).  Cached on (mtime_ns, size, inode); a trailing partial line is ignored."""
    try:
        st = SESSION_INBOX.stat()
    except FileNotFoundError:
        return [], 0
    sig = (st.st_mtime_ns, st.st_size, st.st_ino)
    with _inbox_lock:
        if _inbox_cache["sig"] == sig:
            return _inbox_cache["items"], _inbox_cache["bad"]
        with open(SESSION_INBOX, "rb") as fh:
            data = fh.read()
        end = data.rfind(b"\n")
        items, bad = [], 0
        for line in data[: end + 1].split(b"\n") if end >= 0 else []:
            line = line.strip()
            if not line:
                continue
            try:
                o = json.loads(line)
                it = _inbox_item(o) if isinstance(o, dict) else None
            except Exception:
                it = None
            if it is None:
                bad += 1
                continue
            items.append(it)
        items = items[-INBOX_KEEP:]
        _inbox_cache.update(sig=sig, items=items, bad=bad)
        return items, bad


def read_ack() -> dict:
    d, _ = read_json(SESSION_ACK)
    return d if isinstance(d, dict) else {}


def inbox_with_state(items: list[dict], ack: dict) -> list[dict]:
    read = ack.get("read") if isinstance(ack.get("read"), dict) else {}
    replied = ack.get("replied") if isinstance(ack.get("replied"), dict) else {}
    lr = ack.get("last_read_id")
    lr = lr if isinstance(lr, int) and not isinstance(lr, bool) else 0
    out = []
    for m in items:
        k = str(m["id"])
        if k in replied:
            st = "replied"
        elif k in read or m["id"] <= lr:
            st = "read"
        else:
            st = "delivered"
        out.append({**m, "state": st, "read_at": read.get(k) if isinstance(read.get(k), str) else None,
                    "replied_at": replied.get(k) if isinstance(replied.get(k), str) else None})
    return out


def watch_info(now: float) -> tuple[bool, float | None, dict | None]:
    w, _ = read_json(SESSION_WATCH)
    if not isinstance(w, dict):
        return False, None, None
    t = parse_ts(w.get("ts"))
    age = round(now - t, 1) if t is not None else None
    listening = age is not None and -LISTEN_WINDOW_S < age < LISTEN_WINDOW_S
    watcher = {k: w.get(k) for k in ("pid", "ts", "since_id", "started") if k in w}
    return listening, age, watcher


def _session_summary(f: AgentFile) -> dict:
    with f.lock:
        mtime = f.mtime
        out = {"file": f.rel, "id": f.id, "title": f.title or f.agent_name, "first_ts": f.first_ts,
               "last_ts": f.last_ts, "n_messages": f.n_messages, "n_tool_calls": f.n_tool_calls,
               "model_seen": f.model, "latest_seq": f.seq, "bad_lines": f.bad, "size": f.size}
    out["active"] = bool(mtime) and (time.time() - mtime) < ACTIVE_WINDOW_S
    out["mtime"] = mtime
    return out


def build_session() -> dict:
    now = time.time()
    f, note = main_session()
    session = usage = None
    if f is not None:
        f.update(min_interval=SESSION_MIN_INTERVAL)
        session = _session_summary(f)
        usage = f.usage_snapshot()
    status, serr = read_json(SESSION_STATUS)
    if not isinstance(status, dict):
        status = {}
    st_t = parse_ts(status.get("updated"))
    listening, hb_age, watcher = watch_info(now)
    ack = read_ack()
    items, bad = read_inbox()
    pending = sum(1 for m in inbox_with_state(items, ack) if m["state"] == "delivered")
    out = {"ok": True, "session": session, "status": status, "status_age_s": round(now - st_t, 1) if st_t else None,
           "listening": listening, "heartbeat_age_s": hb_age, "watcher": watcher, "ack": ack, "usage": usage,
           "inbox_pending": pending, "inbox_total": len(items), "inbox_bad_lines": bad,
           "transcripts_set": bool(_TRANSCRIPTS_ENV or os.environ.get("AN_SESSION_FILE", "").strip()),
           "now": now, "now_iso": now_iso()}
    if serr and serr != "missing":
        out["status_error"] = serr
    if f is None:
        out["session_error"] = "no main session transcript found" + ("" if out["transcripts_set"] else " (AN_TRANSCRIPTS is not set)")
    if note:
        out["session_note"] = note
    return out


@app.get("/api/session")
@safe
def api_session():
    return CACHE.get("session", 2, build_session)


def _inbox_tail(limit: int) -> tuple[list[dict], dict]:
    items, _ = read_inbox()
    ack = read_ack()
    return inbox_with_state(items[-limit:], ack), ack


@app.get("/api/session/stream")
@safe
def api_session_stream(after: int = -1, limit: int = 200, before: int = 0):
    f, _ = main_session()
    now = time.time()
    listening, hb_age, _w = watch_info(now)
    inbox, _ack = _inbox_tail(INBOX_LIST_MAX)
    base = {"inbox": inbox, "listening": listening, "heartbeat_age_s": hb_age, "now": now}
    if f is None:
        return {**base, "ok": True, "messages": [], "cursor": max(after, 0), "latest_seq": 0, "first_seq": 0,
                "gap": False, "more": False, "more_before": False, "session_error": "no main session transcript found"}
    f.update(min_interval=SESSION_MIN_INTERVAL)
    limit = max(1, min(int(limit), 500))
    with f.lock:
        msgs = list(f.msgs)
        latest = f.seq
    first_seq = msgs[0]["seq"] if msgs else 0
    gap = reset = False
    if before and before > 0:          # "load earlier": the `limit` records just before seq `before`
        older = [m for m in msgs if m["seq"] < before]
        sel = older[-limit:]
        more = False
        cursor = after if after is not None and after >= 0 else latest
    elif after is None or after < 0:
        sel = msgs[-limit:]
        more = False
        cursor = sel[-1]["seq"] if sel else latest
    else:
        newer = [m for m in msgs if m["seq"] > after]
        more = len(newer) > limit
        sel = newer[:limit]
        cursor = sel[-1]["seq"] if sel else after
        gap = bool(msgs) and after < first_seq - 1
        if after > latest:                 # cursor from another (or a rewritten) transcript: the client must restart
            reset = True
            gap, cursor = True, latest
    more_before = bool(sel) and sel[0]["seq"] > first_seq
    return {**base, "id": f.id, "messages": sel, "cursor": cursor, "latest_seq": latest, "first_seq": first_seq,
            "gap": gap, "more": more, "more_before": more_before, "reset": reset}


@app.get("/api/session/inbox")
@safe
def api_session_inbox(limit: int = INBOX_LIST_MAX):
    limit = max(1, min(int(limit), 1000))
    msgs, ack = _inbox_tail(limit)
    listening, hb_age, watcher = watch_info(time.time())
    return {"messages": msgs, "ack": ack, "listening": listening, "heartbeat_age_s": hb_age, "watcher": watcher,
            "pending": sum(1 for m in msgs if m["state"] == "delivered")}


def _fail(error: str, code: str) -> dict:
    return {"ok": False, "error": error, "code": code}


def _clean_text(s: str) -> str:
    # lone surrogates ("\ud800" escapes) cannot be written as UTF-8 and would break the watcher's reader
    return s.encode("utf-8", "replace").decode("utf-8", "replace")


def validate_send(data: Any, client: str) -> tuple[dict | None, dict | None]:
    if not isinstance(data, dict):
        return None, _fail("body must be a JSON object", "bad_json")
    kind = data.get("kind")
    kind = "message" if kind is None else kind
    if kind not in ("message", "control"):
        return None, _fail("kind must be 'message' or 'control'", "bad_kind")
    model = data.get("model")
    model = "fable-5.1" if model is None else model
    if model not in SESSION_MODELS:
        return None, _fail(f"model must be one of {', '.join(SESSION_MODELS)}", "bad_model")
    effort = data.get("effort")
    effort = "max" if effort is None else effort
    if effort not in SESSION_EFFORTS:
        return None, _fail(f"effort must be one of {', '.join(SESSION_EFFORTS)}", "bad_effort")
    rec: dict[str, Any] = {"kind": kind}
    if kind == "message":
        text = data.get("text")
        if not isinstance(text, str):
            return None, _fail("text must be a string", "bad_text")
        text = _clean_text(text).strip()
        if not text:
            return None, _fail("text is empty", "empty_text")
        if len(text) > SEND_MAX_CHARS:
            return None, _fail(f"text longer than {SEND_MAX_CHARS} characters", "text_too_long")
        rec["text"] = text
    else:
        control = data.get("control")
        if control not in SESSION_CONTROLS:
            return None, _fail(f"control must be one of {', '.join(SESSION_CONTROLS)}", "bad_control")
        value = data.get("value")
        if not isinstance(value, bool):
            return None, _fail("value must be true or false", "bad_value")
        rec.update(control=control, value=value, text="")
    rec.update(model=model, effort=effort, source="dashboard", client=_clean_text(client)[:120])
    return rec, None


def _inbox_max_id() -> int:
    """Highest id in the inbox file and in the ack file (fresh read; caller holds the lock)."""
    best = 0
    try:
        with open(SESSION_INBOX, "rb") as fh:
            for line in fh:
                try:
                    o = json.loads(line)
                except Exception:
                    continue
                i = o.get("id") if isinstance(o, dict) else None
                if isinstance(i, int) and not isinstance(i, bool) and i > best:
                    best = i
    except FileNotFoundError:
        pass
    ack = read_ack()
    lr = ack.get("last_read_id")
    if isinstance(lr, int) and not isinstance(lr, bool):
        best = max(best, lr)
    for k in ("read", "replied"):
        d = ack.get(k)
        if isinstance(d, dict):
            for key in d:
                if isinstance(key, str) and key.isdigit():
                    best = max(best, int(key))
    return best


def append_inbox(rec: dict) -> dict:
    global _send_last_id
    with _send_lock:
        t = _send_clock()
        while _send_times and t - _send_times[0] >= SEND_WINDOW_S:
            _send_times.popleft()
        if _send_times and t - _send_times[-1] < SEND_MIN_GAP_S:
            return _fail("rate limited: at most one message per second", "rate_limited")
        if len(_send_times) >= SEND_WINDOW_MAX:
            return _fail(f"rate limited: at most {SEND_WINDOW_MAX} messages per {int(SEND_WINDOW_S / 60)} minutes",
                         "rate_limited")
        STATE.mkdir(parents=True, exist_ok=True)
        fd = os.open(SESSION_INBOX_LOCK, os.O_RDWR | os.O_CREAT, 0o664)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            nid = max(_inbox_max_id(), _send_last_id) + 1
            ts = now_iso()
            full = {"id": nid, "ts": ts, **rec}
            line = json.dumps(full, ensure_ascii=False).encode("utf-8") + b"\n"
            try:
                size = SESSION_INBOX.stat().st_size
            except FileNotFoundError:
                size = 0
            if size > 0:
                with open(SESSION_INBOX, "rb") as fh:
                    fh.seek(size - 1)
                    if fh.read(1) != b"\n":   # never glue onto a half-written line
                        line = b"\n" + line
            with open(SESSION_INBOX, "ab") as fh:
                fh.write(line)
                fh.flush()
                os.fsync(fh.fileno())
        finally:
            try:
                fcntl.flock(fd, fcntl.LOCK_UN)
            finally:
                os.close(fd)
        _send_times.append(t)
        _send_last_id = nid
    CACHE._d.pop("session", None)
    return {"ok": True, "id": nid, "ts": ts}


def _host_name(v: str | None) -> str | None:
    """Hostname (lower-case, no port, IPv6 without brackets) of a Host header or an Origin URL; None if unusable."""
    v = (v or "").strip().lower()
    if "://" in v:
        v = v.split("://", 1)[1]
    v = v.split("/", 1)[0].split("@")[-1]
    if not v:
        return None
    if v.startswith("["):
        end = v.find("]")
        return v[1:end] if end > 1 else None
    if v.count(":") == 1:
        v = v.split(":", 1)[0]
    elif v.count(":") > 1:          # bare IPv6 without brackets
        return v
    return v.rstrip(".") or None


def send_allowed_hosts() -> tuple[set[str], tuple[str, ...]]:
    """Exact host names and domain suffixes the send endpoint accepts (DNS-rebinding guard, README §17)."""
    exact = {"127.0.0.1", "localhost", "::1"}
    suffixes = [".trycloudflare.com"]
    extra = [os.environ.get("PUBLIC_IPADDR", "")] + os.environ.get("AN_DASH_ALLOWED_HOSTS", "").split(",")
    for h in extra:
        h = h.strip().lower()
        if not h:
            continue
        if h.startswith("*."):
            suffixes.append(h[1:])
        elif h.startswith("."):
            suffixes.append(h)
        else:
            n = _host_name(h)
            if n:
                exact.add(n)
    return exact, tuple(suffixes)


def host_allowed(name: str | None) -> bool:
    if not name:
        return False
    exact, suffixes = send_allowed_hosts()
    return name in exact or any(name.endswith(s) and len(name) > len(s) for s in suffixes)


@app.post("/api/session/send")
async def api_session_send(request: Request):
    try:
        # DNS rebinding: a rebound page is same-origin and may set any header, but its Host stays the attacker's name.
        # (Caddy rewrites Host to localhost:17100, so Origin is checked against the allowlist, not against Host.)
        if not host_allowed(_host_name(request.headers.get("host"))):
            return _fail("Host header is not an allowed dashboard host (set AN_DASH_ALLOWED_HOSTS)", "bad_host")
        origin = request.headers.get("origin")
        if origin is not None and origin.strip().lower() != "null" and not host_allowed(_host_name(origin)):
            return _fail("Origin is not an allowed dashboard host (set AN_DASH_ALLOWED_HOSTS)", "bad_host")
        if origin is not None and origin.strip().lower() == "null":
            return _fail("opaque Origin rejected", "bad_host")
        if request.headers.get("x-an-session") != "1":
            return _fail("missing X-AN-Session: 1 header", "no_header")
        ctype = (request.headers.get("content-type") or "").split(";")[0].strip().lower()
        if ctype != "application/json":
            return _fail("Content-Type must be application/json", "bad_content_type")
        try:
            declared = int(request.headers.get("content-length") or 0)
        except ValueError:
            declared = 0
        if declared > SEND_MAX_BYTES:
            return _fail(f"body larger than {SEND_MAX_BYTES} bytes", "too_large")
        body = bytearray()
        async for chunk in request.stream():
            body += chunk
            if len(body) > SEND_MAX_BYTES:
                return _fail(f"body larger than {SEND_MAX_BYTES} bytes", "too_large")
        try:
            data = json.loads(bytes(body).decode("utf-8"))
        except Exception:
            return _fail("body is not valid JSON", "bad_json")
        rec, err = validate_send(data, request.headers.get("user-agent") or "")
        if err:
            return err
        return await run_in_threadpool(append_inbox, rec)
    except Exception as e:
        return {"ok": False, "error": f"{e.__class__.__name__}: {str(e)[:300]}", "code": "error"}


# ----------------------------------------------------------------------------
# overview
# ----------------------------------------------------------------------------
DICE_RE = re.compile(r"dice|dsc", re.I)
BEST_DICE_DATASET = "inhouse_val"   # daily monitoring uses the validation split, never a test split
_TEST_RE = re.compile(r"test", re.I)
_VAL_RE = re.compile(r"(^|[_\-.])val($|[_\-.])", re.I)


def _exp_val_dice(ms: dict) -> float | None:
    """validation Dice of one experiments.json metrics_summary: the exact `val_dice` when present, else the max
    over other val Dice keys; never a test-split key, never the aux / mean variants (another grid)"""
    if fnum(ms.get("val_dice")) is not None:
        return fnum(ms.get("val_dice"))
    vals = [fnum(v) for k, v in ms.items()
            if DICE_RE.search(str(k)) and not _TEST_RE.search(str(k)) and re.search(r"val", str(k), re.I)
            and not re.search(r"aux|mean", str(k), re.I) and fnum(v) is not None]
    return max(vals) if vals else None


def best_dice_dataset(data: dict, cells: list[dict]) -> str | None:
    """inhouse_val when it has cells; else the first validation dataset (id contains a `val` token, no `test`,
    primary datasets (postprocess none) first); never a test split"""
    have = {c.get("dataset") for c in cells}
    if BEST_DICE_DATASET in have:
        return BEST_DICE_DATASET
    dsets = [d for d in data.get("datasets") or [] if isinstance(d, dict)]
    ids = [str(d.get("id")) for d in sorted(dsets, key=lambda d: str(d.get("postprocess") or "none") != "none")]
    ids += sorted(str(x) for x in have if x is not None and str(x) not in ids)
    for i in ids:
        split = str(next((d.get("split") for d in dsets if str(d.get("id")) == i), "") or "")
        if i in have and not _TEST_RE.search(i) and (_VAL_RE.search(i) or split.lower() == "val"):
            return i
    return None


def _short_id(rid: Any) -> str | None:
    """`N2_aniso_dropout` -> `N2` (the compact name of the Overview live line)"""
    return str(rid).split("_")[0] if rid else None


def best_dice_live(lb: dict | None) -> dict | None:
    """one line from the leaderboard field of /api/overview: our top run vs the best baseline (live val Dice)"""
    if not isinstance(lb, dict) or lb.get("error"):
        return None
    top, bb = lb.get("top_ours") or {}, lb.get("best_baseline") or {}
    if not top and not bb:
        return None
    return {"metric": lb.get("metric"), "tol": lb.get("tol"),
            "ours_id": top.get("run_id"), "ours_short": _short_id(top.get("run_id")), "ours_name": top.get("name"),
            "ours": fnum(top.get("value")), "ours_status": top.get("status"),
            "baseline_id": bb.get("id"), "baseline_short": _short_id(bb.get("id")), "baseline_name": bb.get("name"),
            "baseline": fnum(bb.get("value")), "verdict": top.get("verdict"), "delta": fnum(top.get("delta")),
            "provisional": bool(top.get("provisional") or bb.get("provisional")), "link": "#/leaderboard"}


def best_dice(lb: dict | None = None) -> dict:
    out = _best_dice_core()
    out["live"] = best_dice_live(lb)
    return out


def _best_dice_core() -> dict:
    data, err = read_json(RESULTS / "summary.json")
    if isinstance(data, dict) and data.get("cells"):
        metrics = [m for m in data.get("metrics") or [] if isinstance(m, dict)]
        mids = [m.get("id") for m in metrics if DICE_RE.search(str(m.get("id")))] or ["dice"]
        mid = mids[0]
        fam = {m.get("id"): m for m in data.get("methods") or [] if isinstance(m, dict)}
        cells = [c for c in data["cells"] if isinstance(c, dict) and c.get("metric") == mid and fnum(c.get("mean")) is not None]
        ds = best_dice_dataset(data, cells)
        cells = [c for c in cells if ds is not None and c.get("dataset") == ds]
        # families as everywhere else (lb_family): novel | ours = ours, case-insensitive
        ours = [c for c in cells if lb_family((fam.get(c.get("method")) or {}).get("family")) == "ours"]
        prim = [c for c in ours if (fam.get(c.get("method")) or {}).get("is_primary")]
        base = [c for c in cells if lb_family((fam.get(c.get("method")) or {}).get("family")) == "baseline"]
        o = max(prim or ours, key=lambda c: fnum(c["mean"]), default=None)
        b = max(base, key=lambda c: fnum(c["mean"]), default=None)
        if o or b:
            def mname(c):
                return ((fam.get(c.get("method")) or {}).get("name") or c.get("method")) if c else None
            dsx = next((d for d in data.get("datasets") or [] if isinstance(d, dict) and d.get("id") == ds), {})
            return {"source": "results", "metric": mid, "dataset": ds,
                    "dataset_name_zh": dsx.get("name_zh"), "dataset_name_en": dsx.get("name_en"),
                    "ours": fnum(o["mean"]) if o else None, "ours_method": mname(o),
                    "ours_id": o.get("method") if o else None,
                    "baseline": fnum(b["mean"]) if b else None, "baseline_method": mname(b),
                    "baseline_id": b.get("method") if b else None,
                    "updated": data.get("updated") or file_updated(RESULTS / "summary.json")[0],
                    "freshness_id": "results_summary"}
    exps, _ = read_json(STATE / "experiments.json")
    exps = exps.get("experiments") if isinstance(exps, dict) else []
    best = {"novel": None, "baseline": None}
    names = {"novel": None, "baseline": None}
    for e in exps or []:
        if not isinstance(e, dict):
            continue
        fam = lb_family(e.get("family"))   # novel | ours -> ours (as on the leaderboard)
        if fam == "ablation":
            continue
        ms = e.get("metrics_summary") if isinstance(e.get("metrics_summary"), dict) else {}
        v = _exp_val_dice(ms)
        key = {"ours": "novel", "baseline": "baseline"}.get(fam)
        if key and v is not None and (best[key] is None or v > best[key]):
            best[key], names[key] = v, e.get("name") or e.get("id")
    if best["novel"] is not None or best["baseline"] is not None:
        return {"source": "experiments", "metric": "dice", "ours": best["novel"], "ours_method": names["novel"],
                "baseline": best["baseline"], "baseline_method": names["baseline"],
                "updated": file_updated(STATE / "experiments.json")[0], "freshness_id": "experiments"}
    return {"source": None, "updated": None}


def queue_summary() -> dict | None:
    q = CACHE.get("queue", 3, build_queue)
    return {k: q.get(k) for k in ("eta_end", "eta_s", "counts")} if isinstance(q, dict) else None


def _part(fn, default):
    """Overview sub-payloads must degrade on their own: a failing part never empties the whole Overview."""
    try:
        return fn()
    except Exception as e:  # noqa: BLE001
        print(f"[overview] part {getattr(fn, '__name__', 'lambda')} failed: {e!r}", file=sys.stderr, flush=True)
        return default


@app.get("/api/overview")
@safe
def api_overview():
    items, _ = load_events()
    first_t = min((e["t"] for e in items if e["t"]), default=None)
    wf = api_workflow()
    phases = wf.get("phases") or []
    cur = wf.get("current_phase")
    exps = api_experiments().get("experiments") or []
    ecount = collections.Counter(str(e.get("status") or "queued") for e in exps)
    runs, n_hidden = [], 0
    for d in run_dirs():
        if run_hidden(d.name):  # same rule as the Training list (FR-5): `_discarded`, `*_smoke` ...
            n_hidden += 1
            continue
        st, _ = read_json(d / "status.json")
        runs.append({"run_id": d.name, "status": st if isinstance(st, dict) else {}})
    rcount = collections.Counter(str(r["status"].get("state") or "unknown") for r in runs)
    # mini curves for running runs
    curves = []
    fams = experiment_families()
    for r in [r for r in runs if r["status"].get("state") == "running"][:6]:
        rm = get_run_metrics(r["run_id"])
        if not rm:
            continue
        pick = None
        for key in (("val", "dice"), ("val", "loss"), ("train", "loss")):
            if key in rm.series:
                pick = key
                break
        if pick is None and rm.series:
            pick = sorted(rm.series.keys())[0]
        if pick:
            ds = downsample(rm.series[pick], 200)
            curves.append({"run_id": r["run_id"], "name": r["status"].get("name") or r["run_id"],
                           "family": run_family(RUNS / r["run_id"], r["status"], fams),
                           "split": pick[0], "metric": pick[1],
                           "x": [p[0] if p[0] is not None else p[1] for p in ds], "y": [p[2] for p in ds]})
    litp = api_literature()
    lit = litp.get("papers") or []
    paper = api_paper()
    secs = paper.get("sections") or []
    sys_ = CACHE.get("gpu", 3, gpu_info)
    lb = _part(lb_overview, {})
    exp_p = api_experiments()
    return {
        "now": now_iso(),
        "project": wf.get("project"),
        "first_event_ts": _dt.datetime.fromtimestamp(first_t, _dt.timezone.utc).isoformat() if first_t else None,
        "elapsed_s": round(time.time() - first_t) if first_t else None,
        "current_phase": cur,
        "phases": [{k: p.get(k) for k in ("id", "name_zh", "name_en", "status", "progress", "progress_source",
                                           "started", "ended")} for p in phases],
        "workflow_updated": wf.get("updated"),
        "experiments": {"total": len(exps), "by_status": dict(ecount), "updated": exp_p.get("updated")},
        "runs": {"total": len(runs), "by_state": dict(rcount), "n_hidden": n_hidden},
        "best_dice": _part(lambda: best_dice(lb), {"source": None, "updated": None, "live": None}),
        "gpus": [{k: g.get(k) for k in ("index", "name", "util", "mem_used", "mem_total", "temp")} for g in sys_.get("gpus", [])],
        "gpus_ts": _iso(CACHE.stamp("gpu")),
        "literature": {"found": len(lit), "updated": litp.get("updated"),
                       "verified_1x": sum(1 for p in lit if (fnum(p.get("verified_count")) or 0) >= 1),
                       "verified_3x": sum(1 for p in lit if (fnum(p.get("verified_count")) or 0) >= 3)},
        "paper": {"sections_total": len(secs),
                  "sections_done": sum(1 for s in secs if str(s.get("status")).lower() in ("done", "final", "complete", "completed")),
                  "words": sum(int(fnum(s.get("words")) or 0) for s in secs),
                  "references": paper.get("references"), "pdf": paper.get("pdf"), "updated": paper.get("updated")},
        "curves": curves,
        "events": events_newest(items)[:15],
        "milestones": [e for e in events_newest(items) if e["type"] == "milestone"][:12],
        "routing": api_routing().get("routing"),
        "routing_updated": api_routing().get("updated"),
        "briefing": _part(briefing_payload, {"missing": True, "error": "briefing failed"}),
        "alerts": _part(lambda: (CACHE.get("alerts", 3, build_alerts) or {}).get("alerts", []), []),
        "queue": _part(queue_summary, {}),
        "leaderboard": lb,
        "freshness": _part(freshness_overview, {"stale_ids": [], "error": "freshness failed"}),
    }


# ----------------------------------------------------------------------------
# briefing / alerts / experiment queue
# ----------------------------------------------------------------------------
def _iso(t: float | None) -> str | None:
    return _dt.datetime.fromtimestamp(t, _dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ") if t else None


def briefing_payload() -> dict:
    data, err = read_json(STATE / "briefing.json")
    if err or not isinstance(data, dict):
        return {"ok": err in ("missing", "empty", None), "missing": True, "error": err or "not an object"}
    return {"ok": True, "missing": False, "updated": data.get("updated"), "author": data.get("author"),
            "zh": data.get("zh") if isinstance(data.get("zh"), str) else "",
            "en": data.get("en") if isinstance(data.get("en"), str) else ""}


@app.get("/api/briefing")
@safe
def api_briefing():
    return briefing_payload()


STALE_S = 600
# supervisor programs that must be RUNNING (else a warning), e.g. AN_ALERT_SERVICES=my_jobrunner,my_diskguard
ALERT_SV = tuple(s.strip() for s in os.environ.get("AN_ALERT_SERVICES", "").split(",") if s.strip())
DISK_WARN_GB, DISK_ERR_GB = 60, 40
MILESTONE_WINDOW_S = 15 * 60


def build_alerts() -> dict:
    now = time.time()
    alerts: list[dict] = []
    exps = api_experiments().get("experiments") or []
    for e in exps:
        if str(e.get("status")) == "failed":
            nm = e.get("name") or e.get("id")
            alerts.append({"id": f"failed:{e.get('id')}", "level": "error", "view": "training",
                           "ts": e.get("ended") or e.get("started") or e.get("created"),
                           "msg_zh": f"实验失败：{e.get('id')}（{nm}）", "msg_en": f"Experiment failed: {e.get('id')} ({nm})"})
    n_running = 0
    for d in run_dirs():
        st, _ = read_json(d / "status.json")
        if not isinstance(st, dict) or st.get("state") != "running":
            continue
        n_running += 1
        upd = parse_ts(st.get("updated"))
        if upd and now - upd > STALE_S:
            mins = int((now - upd) // 60)
            alerts.append({"id": f"stale:{d.name}", "level": "warn", "view": "training", "ts": st.get("updated"),
                           "msg_zh": f"训练 {d.name} 已 {mins} 分钟无更新（stale）",
                           "msg_en": f"Run {d.name} has not updated for {mins} min (stale)"})
    pause = STATE / "jobrunner.pause"
    if pause.exists():
        try:
            pts = _iso(pause.stat().st_mtime)
        except Exception:
            pts = None
        alerts.append({"id": "jobrunner_paused", "level": "warn", "view": "workflow", "ts": pts,
                       "msg_zh": "任务调度器已暂停（state/jobrunner.pause）", "msg_en": "Job runner paused (state/jobrunner.pause)"})
    try:
        h = CACHE.get("host", 3, host_info)
        dk = h.get("disk_workspace") or {}
        free = dk.get("free")
        if isinstance(free, (int, float)):
            gb = free / 1e9
            if gb < DISK_WARN_GB:
                lvl = "error" if gb < DISK_ERR_GB else "warn"
                alerts.append({"id": "disk_low", "level": lvl, "view": "system", "ts": now_iso(),
                               "msg_zh": f"{DISK_PATH} 可用空间仅 {gb:.0f} GB",
                               "msg_en": f"{DISK_PATH} free space is only {gb:.0f} GB"})
    except Exception:
        pass
    try:
        sv = {r["name"]: r for r in CACHE.get("supervisor", 10, supervisor_info)}
        for name in ALERT_SV:
            r = sv.get(name)
            if r is None or r.get("state") != "RUNNING":
                stt = r.get("state") if r else "MISSING"
                alerts.append({"id": f"sv:{name}", "level": "warn", "view": "system", "ts": now_iso(),
                               "msg_zh": f"服务 {name} 未运行（{stt}）", "msg_en": f"Service {name} is not running ({stt})"})
    except Exception:
        pass
    items, _ = load_events()
    for ev in events_newest(items):
        if not ev["t"] or now - ev["t"] > MILESTONE_WINDOW_S:
            break
        if ev["type"] == "milestone":
            alerts.append({"id": f"ms:{ev['i']}", "level": "info", "view": "events", "ts": ev["ts"],
                           "msg_zh": ev["msg_zh"], "msg_en": ev["msg_en"]})
    rank = {"error": 0, "warn": 1, "info": 2}
    alerts.sort(key=lambda a: (rank.get(a["level"], 3), -(parse_ts(a.get("ts")) or 0)))
    counts = collections.Counter(a["level"] for a in alerts)
    return {"alerts": alerts, "counts": dict(counts), "n_running": n_running, "now": now_iso()}


@app.get("/api/alerts")
@safe
def api_alerts():
    return CACHE.get("alerts", 3, build_alerts)


QUEUE_DEFAULT_S = 2 * 3600
QUEUE_SKIP = ("planned", "pruned")


def _median(xs: list[float]) -> float | None:
    xs = sorted(xs)
    n = len(xs)
    if not n:
        return None
    return xs[n // 2] if n % 2 else (xs[n // 2 - 1] + xs[n // 2]) / 2


def _lane(g: Any) -> str | None:
    v = fnum(g)
    return str(int(v)) if v is not None else None


def build_queue() -> dict:
    now = time.time()
    exps = api_experiments().get("experiments") or []
    status_by_run: dict[str, dict] = {}
    for d in run_dirs():
        st, _ = read_json(d / "status.json")
        if isinstance(st, dict):
            status_by_run[d.name] = st
            if st.get("exp_id"):
                status_by_run.setdefault("exp:" + str(st.get("exp_id")), st)

    def status_of(e: dict) -> dict:
        rd = e.get("run_dir")
        rid = str(rd).rstrip("/").split("/")[-1] if rd else None
        return status_by_run.get(rid or "", {}) or status_by_run.get("exp:" + str(e.get("id")), {}) or {}

    def val_dice(e: dict, st: dict):
        b = st.get("best") if isinstance(st.get("best"), dict) else {}
        v = fnum(b.get("val_dice"))
        if v is None:
            ms = e.get("metrics_summary") if isinstance(e.get("metrics_summary"), dict) else {}
            v = fnum(ms.get("val_dice"))
        return v

    counts: collections.Counter = collections.Counter()
    actual, running, queued = [], [], []
    durs: dict[str, list[float]] = collections.defaultdict(list)
    for e in exps:
        stt = str(e.get("status") or "queued")
        notes = str(e.get("notes") or "")
        if stt in QUEUE_SKIP:
            counts["skipped_" + stt] += 1
            continue
        if notes.lower().startswith("evaluation-only") and stt not in ("running", "done", "failed"):
            counts["skipped_eval_only"] += 1
            continue
        st = status_of(e)
        item = {"id": e.get("id"), "name": e.get("name") or e.get("id"), "family": e.get("family"),
                "status": stt, "priority": fnum(e.get("priority")) or 0, "val_dice": val_dice(e, st),
                "eta_s": None, "estimated": False, "gpu": _lane(e.get("gpu"))}
        if stt in ("done", "failed"):
            s = parse_ts(st.get("started")) or parse_ts(e.get("started"))
            en = parse_ts(st.get("updated")) or parse_ts(e.get("ended"))
            if not s or not en or en < s:
                counts["no_times"] += 1
                continue
            item.update(start=s, end=en, lane=_lane(st.get("gpu")) or item["gpu"] or "any")
            if stt == "done":
                durs[str(e.get("family"))].append(en - s)
            actual.append(item)
        elif stt == "running":
            s = parse_ts(st.get("started")) or parse_ts(e.get("started")) or now
            eta = fnum(st.get("eta_s"))
            item.update(start=s, end=now + (eta if eta is not None and eta >= 0 else 0), eta_s=eta, estimated=True,
                        lane=_lane(st.get("gpu")) or item["gpu"] or "any", epoch=st.get("epoch"),
                        total_epochs=st.get("total_epochs"))
            running.append(item)
        else:
            queued.append(item)
        counts[stt] += 1
    all_d = [x for v in durs.values() for x in v]
    med_all = _median(all_d)
    med_fam = {f: _median(v) for f, v in durs.items() if len(v) >= 2}

    def proj(fam: Any) -> tuple[float, str]:
        f = str(fam)
        if f in med_fam:
            return med_fam[f], "family"
        if med_all is not None:
            return med_all, "all"
        return QUEUE_DEFAULT_S, "default"

    lanes_free: dict[str, float] = {}
    for r in running:
        if r["lane"] != "any":
            lanes_free[r["lane"]] = max(lanes_free.get(r["lane"], now), r["end"])
    for q in queued:
        if q["gpu"] is not None:
            lanes_free.setdefault(q["gpu"], now)
    for a in actual:
        if a["lane"] != "any":
            lanes_free.setdefault(a["lane"], now)
    if not lanes_free:
        lanes_free = {"0": now}
    queued.sort(key=lambda q: (-q["priority"], str(q["id"])))
    for q in queued:
        lane = q["gpu"] if q["gpu"] is not None else min(lanes_free, key=lambda k: (lanes_free[k], k))
        lanes_free.setdefault(lane, now)
        d, src = proj(q.get("family"))
        q.update(lane=lane, start=lanes_free[lane], end=lanes_free[lane] + d, estimated=True, duration_src=src,
                 any_lane=q["gpu"] is None)
        lanes_free[lane] = q["end"]
    items = actual + running + queued
    by_lane: dict[str, list] = collections.defaultdict(list)
    for it in items:
        it.pop("gpu", None)
        by_lane[it["lane"]].append(it)
    order = sorted(by_lane, key=lambda k: (k == "any", k))
    lanes = []
    for k in order:
        lst = sorted(by_lane[k], key=lambda x: x["start"])
        for it in lst:
            it["duration_s"] = round(it["end"] - it["start"], 1)
            it["start"], it["end"] = _iso(it["start"]), _iso(it["end"])
            it.pop("lane", None)
        lanes.append({"lane": k, "items": lst})
    pending = running + queued
    eta_end = max((parse_ts(x["end"]) or 0 for x in pending), default=None) if pending else None
    return {"now": _iso(now), "lanes": lanes,
            "durations": {"median_s_by_family": {f: round(v, 1) for f, v in med_fam.items()},
                          "median_s_all": round(med_all, 1) if med_all is not None else None,
                          "default_s": QUEUE_DEFAULT_S},
            "counts": dict(counts), "eta_end": _iso(eta_end) if eta_end else None,
            "eta_s": round(eta_end - now) if eta_end else None}


@app.get("/api/queue")
@safe
def api_queue():
    return CACHE.get("queue", 3, build_queue)


# ----------------------------------------------------------------------------
# live leaderboard (README §18)
# ----------------------------------------------------------------------------
LB_LIVE_METRICS: dict[str, tuple[str, bool]] = {   # api id -> (val series name in metrics.jsonl, higher is better)
    "val_dice": ("dice", True),
    "val_hd95": ("hd95", False),
    "val_dice_aux": ("dice_aux", True),
    "val_dice_mean": ("dice_mean", True),
}
LB_HEADLINE = ("val_dice", "val_hd95")              # metrics the change timeline follows
LB_TOL_DEFAULT = {"ratio": 0.003, "dist": 0.3}      # Dice-type / distance (mm) metrics
LB_TOL_MAX = {"ratio": 0.05, "dist": 5.0}
LB_IMPROVE_MIN = {"ratio": 0.002, "dist": 0.2}      # "improved" event threshold (already tie/ahead/sota)
LB_TREND_EPOCHS = 6
LB_TREND_POINTS = 3
LB_SPARK_POINTS = 80
LB_TABLE_EVENTS = 50
LB_OVERVIEW_EVENTS = 20
LB_EVENTS_KEEP = 5000                               # leaderboard events kept in memory
LB_EVENTS_LIMIT_MAX = 2000
LB_CACHE_S = 3.0
LB_TIMELINE_S = 5.0
LB_EPS = 1e-9
LB_LEVEL = {"behind": 0, "tie": 1, "ahead": 2, "sota": 3}
# run states that are shown but never counted (best baseline, rank, verdict, SOTA, timeline)
LB_NOT_COUNTED = frozenset({"failed", "pruned", "crashed", "killed", "error", "aborted", "cancelled"})
LB_BACKFILL_GRACE_S = 60.0
LB_VD_ZH = {"behind": "落后", "tie": "持平", "ahead": "超越", "sota": "★ SOTA"}
LB_VD_EN = {"behind": "behind", "tie": "tie", "ahead": "ahead", "sota": "★ SOTA"}
LB_MET_LABEL = {"val_dice": "val Dice", "val_hd95": "val HD95", "val_dice_aux": "val Dice (aux)",
                "val_dice_mean": "val Dice (mean)"}
_LB_DIST_RE = re.compile(r"hd|assd|asd|dist", re.I)
_lb_cache: dict[tuple, tuple[float, Any]] = {}
_lb_cache_lock = threading.Lock()
LB_CACHE_MAX = 64


def lb_readonly() -> bool:
    """AN_LEADERBOARD_READONLY=1: never write state/leaderboard_* or state/events.jsonl (test instances on real data)"""
    return str(os.environ.get("AN_LEADERBOARD_READONLY", "")).strip().lower() in ("1", "true", "yes", "on")


def lb_state_path() -> Path:
    return STATE / "leaderboard_state.json"


def lb_events_path() -> Path:
    return STATE / "leaderboard_events.jsonl"


def lb_kind(metric_id: Any, unit: Any = None) -> str:
    """'dist' (HD95-type, mm) or 'ratio' (Dice-type) -> default / max tolerance"""
    return "dist" if (str(unit or "").strip().lower() == "mm" or _LB_DIST_RE.search(str(metric_id))) else "ratio"


def lb_tol(tol: Any, kind: str) -> float:
    v = fnum(tol) if not (isinstance(tol, str) and not tol.strip()) else None
    if v is None:
        return LB_TOL_DEFAULT[kind]
    return round(max(0.0, min(v, LB_TOL_MAX[kind])), 6)


def lb_family(f: Any) -> str:
    f = str(f or "").strip().lower()
    if f in ("novel", "ours"):
        return "ours"
    return f if f in ("baseline", "ablation") else "other"


def lb_excluded(name: str) -> bool:
    return name.startswith(("_", ".")) or name.endswith("_smoke") or "_discarded" in name


def lb_better(a: float, b: float, hib: bool) -> bool:
    return a > b if hib else a < b


def lb_gain(v: float | None, ref: float | None, hib: bool) -> float | None:
    """signed difference, positive = v is better than ref"""
    if v is None or ref is None:
        return None
    return (v - ref) if hib else (ref - v)


def lb_verdict(d: float | None, tol: float) -> str | None:
    """d = gain vs the best baseline (positive = better)"""
    if d is None:
        return None
    if d > tol + LB_EPS:
        return "ahead"
    if d >= -tol - LB_EPS:
        return "tie"
    return "behind"


def lb_rank_key(value: float, rid: str, hib: bool) -> tuple:
    return ((-value if hib else value), rid)


def lb_point_verdict(best: float, rid: str, B: float, hib: bool, tol: float, rival: tuple | None) -> str | None:
    """verdict of a value against the best baseline B; `sota` when ahead and ranked above the best other run"""
    vd = lb_verdict(lb_gain(best, B, hib), tol)
    if vd == "ahead" and (rival is None or lb_rank_key(best, rid, hib) < lb_rank_key(rival[0], rival[1], hib)):
        return "sota"
    return vd


def lb_best(pts: list[tuple], hib: bool) -> tuple[float | None, int | None]:
    best, bi = None, None
    for i, p in enumerate(pts):
        if best is None or lb_better(p[1], best, hib):
            best, bi = p[1], i
    return best, bi


def lb_trend(pts: list[tuple], bi: int | None, state: str, x_unit: str = "epoch") -> str:
    """up = best improved within the last K epochs or the last 3 validation points; final for finished runs"""
    if state not in ("running", "queued", "unknown"):
        return "final"
    if bi is None or not pts:
        return "flat"
    if len(pts) - 1 - bi < LB_TREND_POINTS:
        return "up"
    last_x, best_x = pts[-1][0], pts[bi][0]
    if x_unit == "epoch" and last_x is not None and best_x is not None and last_x - best_x < LB_TREND_EPOCHS:
        return "up"
    return "flat"


def lb_sparkline(pts: list[tuple], bi: int | None, hib: bool) -> tuple[list, list]:
    n = len(pts)
    if not n:
        return [], []
    run_best, b = [], None
    for p in pts:
        b = p[1] if b is None or lb_better(p[1], b, hib) else b
        run_best.append(b)
    if n <= LB_SPARK_POINTS:
        idx = list(range(n))
    else:
        L = LB_SPARK_POINTS - 1
        idx = {round(i * (n - 1) / (L - 1)) for i in range(L)}
        if bi is not None:
            idx.add(bi)
        idx = sorted(idx)
    return [[pts[i][0], pts[i][1]] for i in idx], [[pts[i][0], run_best[i]] for i in idx]


def lb_registry() -> dict[str, dict]:
    """registered experiments by id and run_dir basename (state/experiments.json)"""
    data, _ = read_json(STATE / "experiments.json")
    exps = data.get("experiments") if isinstance(data, dict) else data
    reg: dict[str, dict] = {}
    for e in exps if isinstance(exps, list) else []:
        if not isinstance(e, dict) or e.get("id") is None:
            continue
        reg.setdefault(str(e["id"]), e)
        rd = e.get("run_dir")
        if isinstance(rd, str) and rd.strip():
            reg.setdefault(Path(rd.rstrip("/")).name, e)
    return reg


def _lb_num(x: Any) -> Any:
    v = fnum(x)
    return (int(v) if v is not None and float(v).is_integer() else v) if v is not None else None


def lb_series(raw: list[tuple]) -> tuple[list[tuple], str]:
    """RunMetrics points (step, epoch, value, ts) -> sorted [(x, value, ts)], one point per x, and the x unit.

    x is the epoch; the global step is used only when no point of the series carries an epoch (unit "step"),
    otherwise points without an epoch are dropped. A resumed run re-logs earlier epochs (metrics.jsonl is opened
    in append mode), so the last point written for an epoch wins.
    """
    has_ep = any(p[1] is not None for p in raw)
    by_x: dict[Any, tuple] = {}
    for p in raw:
        x = _lb_num(p[1] if has_ep else p[0])
        v = fnum(p[2])
        if x is None or v is None:
            continue
        by_x.pop(x, None)
        by_x[x] = (x, v, p[3])
    return sorted(by_x.values(), key=lambda t: t[0]), ("epoch" if has_ep or not raw else "step")


def lb_live_runs() -> list[dict]:
    """registered, non-smoke run dirs with their validation series (reuses RunMetrics / get_run_metrics)"""
    reg = lb_registry()
    out = []
    for d in sorted(run_dirs(), key=lambda p: p.name):
        rid = d.name
        if lb_excluded(rid) or rid not in reg:
            continue
        e = reg[rid]
        st, _ = read_json(d / "status.json")
        st = st if isinstance(st, dict) else {}
        rm = get_run_metrics(rid)
        fam_raw = e.get("family") if isinstance(e.get("family"), str) else run_family(d, st, {})
        best = st.get("best") if isinstance(st.get("best"), dict) else {}
        series, x_unit = {}, {}
        for mid, (nm, _hib) in LB_LIVE_METRICS.items():
            series[mid], x_unit[mid] = lb_series(list(rm.series.get(("val", nm)) or []) if rm else [])
        reg_st = str(e.get("status") or "").strip().lower()
        status = str(st.get("state") or e.get("status") or "unknown")
        out.append({"run_id": rid, "name": str(e.get("name") or st.get("name") or rid), "family": lb_family(fam_raw),
                    "family_raw": fam_raw, "status": status,
                    "counted": status.strip().lower() not in LB_NOT_COUNTED and reg_st not in LB_NOT_COUNTED,
                    "epoch": _lb_num(st.get("epoch")), "total_epochs": _lb_num(st.get("total_epochs")),
                    "eta_s": fnum(st.get("eta_s")), "gpu": st.get("gpu"), "updated": st.get("updated"),
                    "status_best": best, "series": series, "x_unit": x_unit, "bad_lines": rm.bad if rm else 0})
    return out


def lb_rank(rows: list[dict], hib: bool, tol: float) -> tuple[dict | None, dict | None, list[dict]]:
    """rank (all runs with a value), best baseline, Δ, Δ_sota, verdict, provisional. Returns (best baseline, top, sorted rows)."""
    def cnt(r: dict) -> bool:
        return r.get("counted", True) is not False

    key = lambda r: lb_rank_key(r["value"], r["run_id"], hib)  # noqa: E731
    have = sorted([r for r in rows if r.get("value") is not None and cnt(r)], key=key)
    off = sorted([r for r in rows if r.get("value") is not None and not cnt(r)], key=key)
    rest = sorted([r for r in rows if r.get("value") is None], key=lambda r: (r["family"] != "ours", r["run_id"]))
    for i, r in enumerate(have):
        r["rank"] = i + 1
    for r in off + rest:
        r["rank"] = None
    bb = next((r for r in have if r["family"] == "baseline"), None)
    top = have[0] if have else None
    B = bb["value"] if bb else None
    for r in have + off + rest:
        v = r.get("value")
        r["delta"] = lb_gain(v, B, hib)
        r["delta_sota"] = lb_gain(v, top["value"], hib) if top else None
        r["is_best_baseline"] = r is bb
        r["not_counted"] = not cnt(r)
        if r["family"] == "baseline":
            r["verdict"] = None
            r["provisional"] = r.get("status") == "running"
        elif r["not_counted"]:
            r["verdict"], r["provisional"] = None, False
        else:
            vd = lb_verdict(r["delta"], tol)
            r["verdict"] = "sota" if vd == "ahead" and r is top else vd
            r["provisional"] = bool(bb is not None and bb.get("status") == "running" and vd is not None)
    return bb, top, have + off + rest


def lb_live_rows(runs: list[dict], mid: str) -> list[dict]:
    _nm, hib = LB_LIVE_METRICS[mid]
    rows = []
    for r in runs:
        pts = r["series"].get(mid) or []
        best, bi = lb_best(pts, hib)
        if best is not None:
            value, best_epoch, current, src = best, pts[bi][0], pts[-1][1], "metrics"
        else:   # no validation points yet: fall back to status.json best (best.epoch belongs to val_dice)
            value = fnum(r["status_best"].get(mid))
            best_epoch = _lb_num(r["status_best"].get("epoch")) if (value is not None and mid == "val_dice") else None
            current, src = None, ("status" if value is not None else None)
        spark, spark_best = lb_sparkline(pts, bi, hib)
        xu = (r.get("x_unit") or {}).get(mid, "epoch")
        rows.append({"run_id": r["run_id"], "name": r["name"], "family": r["family"], "family_raw": r["family_raw"],
                     "counted": r.get("counted", True), "x_unit": xu,
                     "status": r["status"], "epoch": r["epoch"], "total_epochs": r["total_epochs"], "eta_s": r["eta_s"],
                     "gpu": r["gpu"], "updated": r["updated"], "value": value, "current": current,
                     "best_epoch": best_epoch, "last_epoch": pts[-1][0] if pts else None, "n_points": len(pts),
                     "source": src, "trend": lb_trend(pts, bi, r["status"], xu), "sparkline": spark,
                     "sparkline_best": spark_best})
    return rows


def lb_crossings(pts: list[tuple], rid: str, B: float | None, hib: bool, tol: float, rival: tuple | None) -> dict:
    """first epoch at which the run's best-so-far reached tie / ahead / sota against the CURRENT best baseline"""
    res: dict[str, Any] = {"tie": None, "ahead": None, "sota": None}
    if B is None:
        return res
    best = None
    for x, v, _ts in pts:
        if best is not None and not lb_better(v, best, hib):
            continue
        best = v
        lvl = LB_LEVEL.get(lb_point_verdict(best, rid, B, hib, tol, rival) or "", -1)
        for name in ("tie", "ahead", "sota"):
            if res[name] is None and lvl >= LB_LEVEL[name]:
                res[name] = x
        if res["sota"] is not None:
            break
    return res


def _lb_rival(have: list[dict], rid: str) -> tuple | None:
    o = next((r for r in have if r["run_id"] != rid and r.get("value") is not None and not r.get("not_counted")), None)
    return (o["value"], o["run_id"]) if o else None


def _lb_fmt(v: Any, kind: str) -> str:
    v = fnum(v)
    if v is None:
        return "—"
    return f"{v:.2f} mm" if kind == "dist" else f"{v:.4f}"


def _lb_ep(x: Any) -> str:
    v = fnum(x)
    if v is None:
        return "?"
    return str(int(v)) if v.is_integer() else f"{v:g}"


def lb_event_text(ev: dict) -> tuple[str, str]:
    kind = lb_kind(ev["metric"])
    rid, lbl, ep = ev["run_id"], LB_MET_LABEL.get(ev["metric"], ev["metric"]), _lb_ep(ev.get("epoch"))
    if ev.get("x_unit") == "step":   # series without epochs: x is the global step
        return tuple(s.replace(f"第 {ep} 轮", f"第 {ep} 步").replace(f"epoch {ep}", f"step {ep}")
                     for s in lb_event_text({**ev, "x_unit": "epoch"}))
    val, base, bid = _lb_fmt(ev.get("value"), kind), _lb_fmt(ev.get("baseline"), kind), ev.get("baseline_id") or "?"
    tol = f"{ev.get('tol'):g}" + (" mm" if kind == "dist" else "")
    prov_zh = "（最佳基线仍在训练，暂定）" if ev.get("provisional") else ""
    prov_en = " (best baseline still training: provisional)" if ev.get("provisional") else ""
    fr, to = ev.get("from"), ev.get("to")
    if ev.get("kind") == "improved":
        prev = _lb_fmt(ev.get("prev"), kind)
        return (f"{rid} 再进步：{lbl} 最佳 {prev} → {val}（第 {ep} 轮，{LB_VD_ZH.get(to, to)}；最佳基线 {bid} {base}）{prov_zh}",
                f"{rid} improved again: best {lbl} {prev} → {val} (epoch {ep}, {LB_VD_EN.get(to, to)}; best baseline {bid} {base}){prov_en}")
    if to == "sota":
        return (f"{rid} 在第 {ep} 轮登顶 ★ SOTA：{lbl} {val}，所有模型第一，且超越最佳基线 {bid}（{base}，容差 {tol}）{prov_zh}",
                f"{rid} took ★ SOTA at epoch {ep}: {lbl} {val}, #1 of all models and ahead of the best baseline {bid} ({base}, tolerance {tol}){prov_en}")
    if fr == "sota":
        return (f"{rid} 在第 {ep} 轮失去 ★ SOTA：{lbl} {val}，现为「{LB_VD_ZH.get(to, to)}」（最佳基线 {bid} {base}）{prov_zh}",
                f"{rid} lost ★ SOTA at epoch {ep}: {lbl} {val}, now {LB_VD_EN.get(to, to)} (best baseline {bid} {base}){prov_en}")
    if to == "ahead":
        return (f"{rid} 在第 {ep} 轮超越最佳基线 {bid}（{lbl} {val} vs {base}，容差 {tol}）{prov_zh}",
                f"{rid} moved ahead of the best baseline {bid} at epoch {ep} ({lbl} {val} vs {base}, tolerance {tol}){prov_en}")
    if to == "tie":
        return (f"{rid} 在第 {ep} 轮与最佳基线 {bid} 持平（{lbl} {val} vs {base}，容差 ±{tol}）{prov_zh}",
                f"{rid} tied with the best baseline {bid} at epoch {ep} ({lbl} {val} vs {base}, tolerance ±{tol}){prov_en}")
    return (f"{rid} 在第 {ep} 轮落后于最佳基线 {bid}（{lbl} {val} vs {base}，容差 {tol}）{prov_zh}",
            f"{rid} fell behind the best baseline {bid} at epoch {ep} ({lbl} {val} vs {base}, tolerance {tol}){prov_en}")


def _lb_r6(v: Any) -> Any:
    v = fnum(v)
    return round(v, 6) if v is not None else None


class LeaderboardTimeline:
    """Verdict-change timeline for our runs (val_dice, val_hd95, default tolerance).

    State per run+metric (`state/leaderboard_state.json`) records the number of validation points already
    processed plus a fingerprint of that prefix, so a re-run never re-emits events; events also carry a
    deterministic `id` that is checked against `state/leaderboard_events.jsonl`. When the fingerprint no longer
    matches (metrics.jsonl replaced, truncated or rewritten) or the state is lost after events were recorded, the
    series is rebuilt silently and at most one reconciling event (ts = now, `reset: true`) is emitted, from the
    verdict the timeline last showed to the current one; no transition is attributed to historical epochs.
    With AN_LEADERBOARD_READONLY=1 everything is computed in memory and nothing is written.
    """

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.reset()

    def reset(self) -> None:
        self.loaded = False
        self.keys: dict[str, dict] = {}
        self.events: list[dict] = []
        self.ids: set[str] = set()
        self.sig: tuple | None = None
        self.bad = 0
        self.error: str | None = None
        self.n_updates = 0
        self.last_poll: float | None = None   # time of the previous update (back-fill flag)

    @staticmethod
    def _sig() -> tuple:
        out = []
        for p in (lb_state_path(), lb_events_path()):
            try:
                st = p.stat()
                out.append((st.st_mtime_ns, st.st_size, st.st_ino))
            except OSError:
                out.append(None)
        return tuple(out)

    def _load(self) -> None:
        keys: dict[str, dict] = {}
        try:
            with open(lb_state_path(), "rb") as fh:
                st = json.loads(fh.read().decode("utf-8", "replace") or "null")
            if isinstance(st, dict) and isinstance(st.get("keys"), dict):
                keys = {str(k): v for k, v in st["keys"].items() if isinstance(v, dict)}
                if self.last_poll is None:
                    self.last_poll = parse_ts(st.get("polled") or st.get("updated"))
        except FileNotFoundError:
            pass
        except Exception:  # malformed state: start over (event ids prevent duplicates)
            keys = {}
        events, bad = [], 0
        try:
            with open(lb_events_path(), "rb") as fh:
                data = fh.read()
            for line in data.split(b"\n"):
                line = line.strip()
                if not line:
                    continue
                try:
                    o = json.loads(line)
                    if not isinstance(o, dict) or not o.get("run_id"):
                        raise ValueError
                except Exception:
                    bad += 1
                    continue
                events.append(o)
        except FileNotFoundError:
            pass
        self.keys, self.events, self.bad = keys, events[-LB_EVENTS_KEEP:], bad
        self.ids = {str(e.get("id")) for e in events if e.get("id")}
        self.sig = self._sig()
        self.loaded = True

    def _persist(self, new_events: list[dict], milestones: list[dict]) -> None:
        STATE.mkdir(parents=True, exist_ok=True)
        tmp = lb_state_path().with_name(lb_state_path().name + ".tmp")
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump({"version": 2, "updated": now_iso(), "polled": now_iso(), "tol": {m: LB_TOL_DEFAULT[lb_kind(m)] for m in LB_HEADLINE},
                       "keys": self.keys}, fh, ensure_ascii=False, indent=1)
        os.replace(tmp, lb_state_path())
        for path, items in ((lb_events_path(), new_events), (STATE / "events.jsonl", milestones)):
            if not items:
                continue
            body = "".join(json.dumps(x, ensure_ascii=False) + "\n" for x in items).encode("utf-8")
            fd = os.open(str(path), os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
            try:
                fcntl.flock(fd, fcntl.LOCK_EX)
                os.write(fd, body)
            finally:
                try:
                    fcntl.flock(fd, fcntl.LOCK_UN)
                finally:
                    os.close(fd)

    @staticmethod
    def _fp(pts: list[tuple], n: int) -> list | None:
        """fingerprint of the first n points: (x, value, ts) of the first and of the n-th point"""
        if n <= 0 or n > len(pts):
            return None
        a, b = pts[0], pts[n - 1]
        return [a[0], _lb_r6(a[1]), a[2], b[0], _lb_r6(b[1]), b[2]]

    def _last_verdicts(self) -> dict[str, dict]:
        """last recorded verdict event per run|metric (events file order), used when the state is missing"""
        out: dict[str, dict] = {}
        for e in self.events:
            if e.get("kind", "verdict") == "verdict" and e.get("to") in LB_LEVEL:
                out[f"{e.get('run_id')}|{e.get('metric')}"] = e
        return out

    def update(self, runs: list[dict]) -> dict:
        with self.lock:
            if not self.loaded or self._sig() != self.sig:
                self._load()
            self.n_updates += 1
            by_id = {r["run_id"]: r for r in runs}
            now = now_iso()
            now_t = parse_ts(now) or time.time()
            prev_poll = self.last_poll
            new_events: list[dict] = []
            changed = False
            last_vd: dict[str, dict] | None = None
            for mid in LB_HEADLINE:
                _nm, hib = LB_LIVE_METRICS[mid]
                kind = lb_kind(mid)
                tol, thr = LB_TOL_DEFAULT[kind], LB_IMPROVE_MIN[kind]
                bb, _top, rows = lb_rank(lb_live_rows(runs, mid), hib, tol)
                if bb is None:
                    continue   # nothing to compare with yet: keep history for a later back-fill
                B, bid, prov = bb["value"], bb["run_id"], bb.get("status") == "running"
                have = [r for r in rows if r.get("value") is not None and not r.get("not_counted")]
                for r in rows:
                    if r["family"] != "ours" or r.get("not_counted"):
                        continue   # failed / pruned runs keep their past events but produce no new ones
                    rid = r["run_id"]
                    pts = by_id[rid]["series"].get(mid) or []
                    xu = r.get("x_unit") or "epoch"
                    rival = _lb_rival(have, rid)
                    key = f"{rid}|{mid}"
                    s = self.keys.get(key)
                    # `known` = the verdict the timeline last showed; `silent` = rebuild the series state from scratch
                    # without emitting per-point events (the series was replaced/truncated/rewritten, or the state
                    # file was lost after events were recorded): a single reconciling event (ts = now) follows.
                    first = False
                    if s is not None:
                        n0 = int(fnum(s.get("n")) or 0)
                        known = s.get("verdict") if s.get("verdict") in LB_LEVEL else None
                        fp = s.get("fp")
                        silent = n0 > len(pts) or (n0 > 0 and fp is not None and fp != self._fp(pts, n0))
                    else:
                        if last_vd is None:
                            last_vd = self._last_verdicts()
                        le = last_vd.get(key)
                        known, n0, silent, first = (le.get("to") if le else None), 0, le is not None, le is None
                    if silent:
                        n0, verdict, best, best_x, ref = 0, None, None, None, None
                    else:
                        verdict = known
                        best = fnum(s.get("best")) if (s and n0) else None
                        best_x = s.get("best_epoch") if (s and n0) else None
                        ref = fnum(s.get("ref")) if s else None

                    def emit(evkind: str, fr: Any, to: str, x: Any, ts: Any, value: float, prev: Any = None,
                             reset: bool = False) -> None:
                        pt = parse_ts(ts) if ts else None
                        ev = {"ts": ts if pt else now, "kind": evkind, "run_id": rid, "name": r["name"],
                              "family": r["family"], "metric": mid, "epoch": x, "x_unit": xu, "from": fr, "to": to,
                              "value": value, "prev": prev, "baseline": B, "baseline_id": bid,
                              "provisional": prov, "tol": tol,
                              # back-filled = reconstructed history: the first replay of a series, or a point
                              # older than the previous timeline update (not a live change seen while polling)
                              "backfill": bool(pt) and (first or (prev_poll is not None
                                                                  and pt < prev_poll - LB_BACKFILL_GRACE_S))}
                        if reset:
                            ev["reset"] = True
                        ev["id"] = "|".join(str(p) for p in (rid, mid, evkind, x, fr, to, _lb_r6(value), _lb_r6(B)))
                        ev["msg_zh"], ev["msg_en"] = lb_event_text(ev)
                        if ev["id"] not in self.ids:
                            self.ids.add(ev["id"])
                            new_events.append(ev)

                    for x, v, ts in pts[n0:]:
                        improved = best is None or lb_better(v, best, hib)
                        if not improved and verdict is not None:
                            continue
                        if improved:
                            best, best_x = v, x
                        vd = lb_point_verdict(best, rid, B, hib, tol, rival)
                        if vd != verdict:
                            if not silent and (verdict is not None or vd != "behind"):
                                emit("verdict", verdict, vd, x, ts, best)
                            verdict, ref = vd, best
                        elif improved and vd in ("tie", "ahead", "sota") and ref is not None \
                                and (lb_gain(best, ref, hib) or 0) >= thr - LB_EPS:
                            if not silent:
                                emit("improved", vd, vd, x, ts, best, ref)
                            ref = best
                    # the best baseline or the #1 rival can change without new points of this run
                    cur = r.get("value")
                    if cur is not None:
                        vd = lb_point_verdict(cur, rid, B, hib, tol, rival)
                        if vd != verdict:
                            if not silent and (verdict is not None or vd != "behind"):
                                emit("verdict", verdict, vd, r.get("epoch") if r.get("epoch") is not None else best_x,
                                     None, cur)
                            verdict, ref = vd, cur
                    if silent and verdict is not None and verdict != known and (known is not None or verdict != "behind"):
                        emit("verdict", known, verdict, best_x, None, best if best is not None else cur, reset=True)
                    ns = {"n": len(pts), "fp": self._fp(pts, len(pts)), "verdict": verdict, "best": best,
                          "best_epoch": best_x, "ref": ref, "baseline_id": bid, "baseline": B}
                    if s is None or any(s.get(k) != ns[k] for k in ns):
                        ns["updated"] = now
                        self.keys[key] = ns
                        changed = True
            milestones = [{"ts": e["ts"], "type": "milestone", "level": "info", "actor": "leaderboard",
                           "msg_zh": e["msg_zh"], "msg_en": e["msg_en"]}
                          for e in new_events if e["kind"] == "verdict" and e["to"] in ("ahead", "sota")
                          and LB_LEVEL[e["to"]] > LB_LEVEL.get(e["from"] or "behind", 0)]
            self.events.extend(new_events)
            if len(self.events) > LB_EVENTS_KEEP:
                self.events = self.events[-LB_EVENTS_KEEP:]
            self.error = None
            self.last_poll = now_t
            if (changed or new_events) and not lb_readonly():
                try:
                    self._persist(new_events, milestones)
                except Exception as e:  # noqa: BLE001  (read-only volume etc.: keep working in memory)
                    self.error = f"persist failed: {e.__class__.__name__}: {str(e)[:200]}"
                self.sig = self._sig()
            return {"new": len(new_events), "milestones": len(milestones), "error": self.error}

    def newest(self, limit: int, run_id: str = "") -> list[dict]:
        """newest first; at equal ts verdict changes come before `improved` events and val_dice before val_hd95"""
        with self.lock:
            items = list(enumerate(self.events))
        if run_id:
            items = [(i, e) for i, e in items if e.get("run_id") == run_id]
        items.sort(key=lambda ie: (parse_ts(ie[1].get("ts")) or 0, ie[1].get("kind", "verdict") == "verdict",
                                   ie[1].get("metric") == "val_dice", ie[0]), reverse=True)
        return [e for _i, e in items[:limit]]

LB_TL = LeaderboardTimeline()


def lb_runs_cached() -> list[dict]:
    return CACHE.get("lb_live_runs", 2, lb_live_runs)


def lb_timeline() -> dict:
    """timeline refresh, at most every LB_TIMELINE_S; never raises"""
    def run() -> dict:
        try:
            return LB_TL.update(lb_runs_cached())
        except Exception as e:  # noqa: BLE001
            print(f"[leaderboard] timeline failed: {e!r}", file=sys.stderr, flush=True)
            return {"error": f"{e.__class__.__name__}: {str(e)[:200]}"}
    return CACHE.get("lb_timeline", LB_TIMELINE_S, run)


def _lb_summary_row(r: dict | None, keys: tuple) -> dict | None:
    return {k: r.get(k) for k in keys} if r else None


def lb_live_payload(metric: str, tol_q: Any) -> dict:
    mid = metric or "val_dice"
    if mid not in LB_LIVE_METRICS:
        return {"ok": False, "error": f"unknown live metric: {mid}", "metrics": list(LB_LIVE_METRICS)}
    _nm, hib = LB_LIVE_METRICS[mid]
    kind = lb_kind(mid)
    tol = lb_tol(tol_q, kind)
    runs = lb_runs_cached()
    bb, top, rows = lb_rank(lb_live_rows(runs, mid), hib, tol)
    B = bb["value"] if bb else None
    have = [r for r in rows if r.get("value") is not None and not r.get("not_counted")]
    by_id = {r["run_id"]: r for r in runs}
    crossings = {r["run_id"]: lb_crossings(by_id[r["run_id"]]["series"].get(mid) or [], r["run_id"], B, hib, tol,
                                           _lb_rival(have, r["run_id"]))
                 for r in rows if r["family"] == "ours"}
    ups = [parse_ts(r.get("updated")) for r in runs]
    ups = [u for u in ups if u]
    return {"ok": True, "scope": "live", "metric": mid, "dataset": "inhouse_val", "stat": None, "hib": hib,
            "kind": kind, "tol": tol, "tol_default": LB_TOL_DEFAULT[kind], "tol_max": LB_TOL_MAX[kind],
            "best_baseline": ({"id": bb["run_id"], "name": bb["name"], "value": bb["value"], "status": bb["status"],
                               "provisional": bb["status"] == "running"} if bb else None),
            "sota": ({"id": top["run_id"], "name": top["name"], "family": top["family"], "value": top["value"],
                      "verdict": top.get("verdict"), "is_ours": top["family"] == "ours"} if top else None),
            "rows": rows, "crossings": crossings,
            "metrics": [{"id": k, "hib": h, "kind": lb_kind(k),
                         "available": any(r["series"].get(k) or fnum(r["status_best"].get(k)) is not None for r in runs)}
                        for k, (_n, h) in LB_LIVE_METRICS.items()],
            "datasets": [], "updated": _iso(max(ups)) if ups else None,
            "bad_lines": sum(int(r.get("bad_lines") or 0) for r in runs)}


def _lb_final_metric(metric: str, ids: list[str]) -> str | None:
    m = metric or "dice"
    if m in ids:
        return m
    if m.startswith("val_"):
        m2 = m[4:]
        if m2 in ids:
            return m2
        head = m2.split("_")[0]
        if head in ids:
            return head
    return None


def lb_final_payload(metric: str, dataset: str, stat: str, tol_q: Any) -> dict:
    stat = stat if stat in ("mean", "median") else "mean"
    data, err = read_json(RESULTS / "summary.json")
    base = {"ok": True, "scope": "final", "stat": stat, "rows": [], "crossings": {}, "best_baseline": None,
            "sota": None, "metrics": [], "datasets": []}
    if err or not isinstance(data, dict):
        kind = lb_kind(metric or "dice")
        base.update(missing=True, error=err or "not an object", metric=metric or "dice", dataset=dataset or None,
                    hib=True, kind=kind, tol=lb_tol(tol_q, kind), tol_default=LB_TOL_DEFAULT[kind],
                    tol_max=LB_TOL_MAX[kind], updated=None)
        return base
    metrics = [m for m in data.get("metrics") or [] if isinstance(m, dict) and m.get("id") is not None]
    datasets = [d for d in data.get("datasets") or [] if isinstance(d, dict) and d.get("id") is not None]
    methods = {}
    for m in data.get("methods") or []:
        if isinstance(m, dict) and m.get("id") is not None:
            methods.setdefault(str(m["id"]), m)
    cells = [c for c in data.get("cells") or [] if isinstance(c, dict)]
    mids = [str(m["id"]) for m in metrics] or sorted({str(c.get("metric")) for c in cells})
    dids = [str(d["id"]) for d in datasets] or sorted({str(c.get("dataset")) for c in cells})
    base["metrics"] = [{"id": str(m["id"]), "name_zh": m.get("name_zh"), "name_en": m.get("name_en"), "unit": m.get("unit"),
                        "hib": bool(m.get("higher_is_better", True)), "kind": lb_kind(m["id"], m.get("unit"))} for m in metrics]
    base["datasets"] = [{k: d.get(k) for k in ("id", "name_zh", "name_en", "n", "cohort", "split", "output", "postprocess")}
                        for d in datasets]
    base["updated"] = data.get("updated")
    mid = _lb_final_metric(metric, mids)
    if mid is None:
        return {**base, "ok": False, "error": f"unknown metric: {metric}"}
    ds = dataset or ("inhouse_val" if "inhouse_val" in dids else (dids[0] if dids else None))
    if dataset and dataset not in dids:
        return {**base, "ok": False, "error": f"unknown dataset: {dataset}"}
    mdef = next((m for m in metrics if str(m["id"]) == mid), {})
    hib = bool(mdef.get("higher_is_better", not lowerish(mid))) if mdef else not lowerish(mid)
    kind = lb_kind(mid, mdef.get("unit"))
    tol = lb_tol(tol_q, kind)
    runs_by_id = {d.name: d for d in run_dirs()}
    rows, seen = [], set()
    for c in cells:
        mth = str(c.get("method"))
        if c.get("metric") != mid or c.get("dataset") != ds or mth in seen:
            continue
        mean, med = fnum(c.get("mean")), fnum(c.get("median"))
        val = med if (stat == "median" and med is not None) else mean
        if val is None:
            continue
        seen.add(mth)
        m = methods.get(mth, {})
        st: dict = {}
        if mth in runs_by_id:
            s, _ = read_json(runs_by_id[mth] / "status.json")
            st = s if isinstance(s, dict) else {}
        rows.append({"run_id": mth, "name": str(m.get("name") or mth), "family": lb_family(m.get("family")),
                     "family_raw": m.get("family"), "is_primary": bool(m.get("is_primary")),
                     "status": str(st.get("state") or "done"), "epoch": _lb_num(st.get("epoch")),
                     "total_epochs": _lb_num(st.get("total_epochs")), "eta_s": fnum(st.get("eta_s")),
                     "value": val, "current": val, "best_epoch": None, "n_points": 0, "source": "results",
                     "median_fallback": stat == "median" and med is None,
                     "mean": mean, "median": med, "std": fnum(c.get("std")), "ci_low": fnum(c.get("ci_low")),
                     "ci_high": fnum(c.get("ci_high")), "q1": fnum(c.get("q1")), "q3": fnum(c.get("q3")),
                     "n": _lb_num(c.get("n")), "trend": "final", "sparkline": [], "sparkline_best": []})
    bb, top, rows = lb_rank(rows, hib, tol)
    for r in rows:   # final evaluation numbers exist only for finished models: never provisional
        r["provisional"] = False
    base.update(metric=mid, dataset=ds, hib=hib, kind=kind, tol=tol, tol_default=LB_TOL_DEFAULT[kind],
                tol_max=LB_TOL_MAX[kind], rows=rows,
                best_baseline=({"id": bb["run_id"], "name": bb["name"], "value": bb["value"], "status": bb["status"],
                                "provisional": False} if bb else None),
                sota=({"id": top["run_id"], "name": top["name"], "family": top["family"], "value": top["value"],
                       "verdict": top.get("verdict"), "is_ours": top["family"] == "ours"} if top else None),
                missing=not rows)
    return base


_LOWER_RE = re.compile(r"loss|hd|asd|error|err|nll|ece|mae|mse|rmse|fpr|fnr|rve|vol|fp_", re.I)


def lowerish(metric_id: str) -> bool:
    return bool(_LOWER_RE.search(str(metric_id)))


def lb_payload(scope: str = "live", metric: str = "", dataset: str = "", stat: str = "mean", tol: Any = "") -> dict:
    scope = scope or "live"
    if scope not in ("live", "final"):
        return {"ok": False, "error": f"unknown scope: {scope}"}
    tl = lb_timeline()
    tol_key = _lb_r6(tol) if fnum(tol) is not None else ""
    key = (scope, metric or "", dataset or "", stat or "", tol_key)
    now = time.time()
    with _lb_cache_lock:
        hit = _lb_cache.get(key)
        if hit and now - hit[0] < LB_CACHE_S:
            return hit[1]
    out = lb_live_payload(metric, tol) if scope == "live" else lb_final_payload(metric, dataset, stat, tol)
    if out.get("ok"):
        out["events"] = LB_TL.newest(LB_TABLE_EVENTS)
        out["readonly"] = lb_readonly()
        out["timeline_error"] = (tl or {}).get("error")
        out["now"] = now_iso()
    with _lb_cache_lock:
        if len(_lb_cache) >= LB_CACHE_MAX:
            for k in sorted(_lb_cache, key=lambda k: _lb_cache[k][0])[: LB_CACHE_MAX // 2]:
                _lb_cache.pop(k, None)
        _lb_cache[key] = (now, out)
    return out


@app.get("/api/leaderboard")
@safe
def api_leaderboard(scope: str = "live", metric: str = "", dataset: str = "", stat: str = "mean", tol: str = ""):
    return lb_payload(scope[:16], metric[:64], dataset[:128], stat[:16], tol[:32])


@app.get("/api/leaderboard/events")
@safe
def api_leaderboard_events(limit: int = 200, run_id: str = ""):
    tl = lb_timeline()
    limit = max(1, min(int(limit), LB_EVENTS_LIMIT_MAX))
    ev = LB_TL.newest(limit, run_id[:128])
    return {"events": ev, "count": len(ev), "total": len(LB_TL.events), "bad_lines": LB_TL.bad,
            "readonly": lb_readonly(), "timeline_error": (tl or {}).get("error"), "now": now_iso()}


def lb_overview() -> dict:
    """compact race card for /api/overview (reuses the cached live computation at the default tolerance)"""
    p = lb_payload("live", "val_dice", "", "mean", "")
    if not p.get("ok"):
        return {"error": p.get("error")}
    keys = ("run_id", "name", "family", "status", "epoch", "total_epochs", "value", "verdict", "delta", "trend",
            "rank", "provisional")
    ours = [r for r in p["rows"] if r["family"] == "ours" and r.get("value") is not None and not r.get("not_counted")]
    top = ours[0] if ours else None
    evs = p.get("events") or []
    return {"metric": p["metric"], "tol": p["tol"], "best_baseline": p["best_baseline"], "sota": p["sota"],
            "top_ours": _lb_summary_row(top, keys), "ours": [_lb_summary_row(r, keys) for r in ours[:8]],
            "latest_event": evs[0] if evs else None,
            # the client checks these for new ahead / SOTA events (toasts), not only latest_event
            "recent_events": evs[:LB_OVERVIEW_EVENTS]}


# ----------------------------------------------------------------------------
# auto-derived phase progress (README §19) -- written into the /api/workflow payload, never the file
# ----------------------------------------------------------------------------
AUTO_PHASES = ("train_base", "train_novel", "vjepa", "evaluate", "r2")
R2_SPLIT = "public_v3"
_exp_cfg_cache: dict[str, tuple] = {}


def _exp_config(rid: str | None, eid: str) -> dict:
    """`data` facts (cohorts, split) of an experiment: runs/<run dir>/config.yaml, runs/<id>/config.yaml, else
    configs/exp/<id>.yaml (queued / planned experiments have no run dir yet). Cached by (mtime, size)."""
    cands = []
    for n in (rid, eid):
        if n and re.fullmatch(r"[A-Za-z0-9_.-]+", n):
            cands.append(RUNS / n / "config.yaml")
    if re.fullmatch(r"[A-Za-z0-9_.-]+", eid or ""):
        cands.append(ROOT / "configs" / "exp" / f"{eid}.yaml")
    for f in cands:
        try:
            stt = f.stat()
        except OSError:
            continue
        sig = (stt.st_mtime_ns, stt.st_size)
        hit = _exp_cfg_cache.get(str(f))
        if hit and hit[0] == sig:
            return hit[1]
        out: dict = {"file": str(f)}
        try:
            import yaml  # noqa: PLC0415

            with open(f, "r", encoding="utf-8", errors="replace") as fh:
                c = yaml.safe_load(fh.read(1 << 20))
            d = c.get("data") if isinstance(c, dict) and isinstance(c.get("data"), dict) else {}
            coh = d.get("cohorts")
            out["cohorts"] = [str(x) for x in coh] if isinstance(coh, list) else ([str(coh)] if coh else None)
            out["split"] = str(d["split"]) if d.get("split") is not None else None
        except Exception as e:  # noqa: BLE001 -- a broken config only loses its phase facts
            out["error"] = f"{e.__class__.__name__}: {str(e)[:120]}"
        _exp_cfg_cache[str(f)] = (sig, out)
        return out
    return {}


def experiment_phase(e: dict, cfg: dict) -> str | None:
    """training phase an experiment belongs to:
    r2 = config split public_v3, or a baseline whose data.cohorts contain a public (non in-house) cohort;
    train_base = other baselines; vjepa = novel V*; train_novel = other novel (T*) and ablations."""
    fam = str(e.get("family") or "").strip().lower()
    eid = str(e.get("id") or "")
    split = str(cfg.get("split") or "").strip().lower()
    cohorts = cfg.get("cohorts") or []
    public = any(not str(c).strip().lower().startswith("inhouse") for c in cohorts)
    if split == R2_SPLIT or (fam == "baseline" and public):
        return "r2"
    if fam == "baseline":
        return "train_base"
    if fam in ("novel", "ours"):
        return "vjepa" if eid[:1].upper() == "V" else "train_novel"
    if fam == "ablation":
        return "train_novel"
    return None


def phase_progress_auto() -> dict:
    """{phase id: {progress, done, running, queued, total, members, rule}} from state/experiments.json + configs.
    Training phases: done / (done + running + queued) of their runs (planned / pruned / failed are not counted).
    evaluate: done runs with eval_status.aggregate == ok / done runs. progress is None when nothing counts."""
    data, err = read_json(STATE / "experiments.json")
    exps = data.get("experiments") if isinstance(data, dict) else data
    exps = [e for e in exps if isinstance(e, dict) and e.get("id") is not None] if isinstance(exps, list) else []
    out: dict[str, Any] = {"_updated": data.get("updated") if isinstance(data, dict) else None, "_error": err}
    acc = {p: {"done": [], "running": [], "queued": []} for p in AUTO_PHASES if p != "evaluate"}
    ev_done, ev_ok = [], []
    for e in exps:
        eid = str(e["id"])
        st = str(e.get("status") or "").strip().lower()
        rd = e.get("run_dir")
        rid = Path(rd.rstrip("/")).name if isinstance(rd, str) and rd.strip() else None
        ph = experiment_phase(e, _exp_config(rid, eid))
        if ph in acc and st in acc[ph]:
            acc[ph][st].append(eid)
        if st == "done":
            ev_done.append(eid)
            es = e.get("eval_status")
            if isinstance(es, dict) and str(es.get("aggregate") or "").strip().lower() == "ok":
                ev_ok.append(eid)
    rules = {"train_base": "baseline, in-house cohorts", "train_novel": "novel T* + ablation",
             "vjepa": "novel V*", "r2": f"split {R2_SPLIT} or baseline with public cohorts"}
    for ph, a in acc.items():
        tot = len(a["done"]) + len(a["running"]) + len(a["queued"])
        out[ph] = {"progress": (len(a["done"]) / tot) if tot else None, "done": len(a["done"]),
                   "running": len(a["running"]), "queued": len(a["queued"]), "total": tot,
                   "members": {k: v[:60] for k, v in a.items()}, "rule": rules[ph]}
    out["evaluate"] = {"progress": (len(ev_ok) / len(ev_done)) if ev_done else None, "done": len(ev_done),
                       "ok": len(ev_ok), "total": len(ev_done),
                       "members": {"ok": ev_ok[:60], "pending": [x for x in ev_done if x not in ev_ok][:60]},
                       "rule": "done runs with eval_status.aggregate == ok"}
    return out


def apply_phase_auto(phases: list[dict], auto: dict) -> list[dict]:
    """copies of the workflow phases with the auto progress (progress_source auto); manual phases keep the file value"""
    out = []
    for p in phases:
        q = dict(p)
        a = auto.get(str(p.get("id"))) if isinstance(auto, dict) and str(p.get("id")) in AUTO_PHASES else None
        q["progress_manual"] = p.get("progress")
        if isinstance(a, dict) and a.get("progress") is not None:
            q["progress"] = round(a["progress"], 4)
            q["progress_source"] = "auto"
            q["progress_auto"] = a
        else:
            q["progress_source"] = "manual"
            if isinstance(a, dict):
                q["progress_auto"] = a  # nothing counted yet -> the file value stays
        out.append(q)
    return out


# ----------------------------------------------------------------------------
# data freshness (README §19)
# ----------------------------------------------------------------------------
FRESH_TTL_S = 5.0
FRESH_LIVE_S = 60
FRESH_RUN_SILENT_S = 180  # FR-3: V-JEPA-family validation passes write nothing for ~65 s
FRESH_PERIODIC_S = 2 * 3600
FRESH_MANUAL_DEP_S = 12 * 3600
FRESH_RUNNING = ("running",)
# manual sources that go stale only while a phase depending on them runs
FRESH_MANUAL_DEPS = {"paper": ("paper", "refs"), "literature": ("literature",), "routing": ()}
FRESH_TILES = {  # Overview tile / card -> freshness source id (one shared badge per source)
    "kpi_phase": "workflow", "phases": "workflow", "kpi_elapsed": "events", "kpi_experiments": "experiments",
    "kpi_queue_eta": "experiments", "kpi_best_dice": "results_summary", "kpi_best_dice_live": "runs",
    "kpi_gpu": "system", "kpi_papers": "literature", "kpi_sections": "paper", "kpi_refs": "paper",
    "routing": "routing", "briefing": "briefing", "events": "events", "milestones": "events", "curves": "runs",
    "race": "runs", "race_events": "leaderboard_events",
}


def file_updated(path: Path, field: bool = True) -> tuple[str | None, float | None, float | None, str | None, str | None]:
    """(updated ISO, updated epoch, mtime, from: field|mtime, error) of a state file: the JSON file's own
    `updated` field when present and parseable, else its mtime. Missing -> (None, None, None, None, 'missing')."""
    try:
        mt = path.stat().st_mtime
    except FileNotFoundError:
        return None, None, None, None, "missing"
    except OSError as e:
        return None, None, None, None, f"stat failed: {e.__class__.__name__}"
    err = None
    if field and path.suffix == ".json":
        data, err = read_json(path)
        if isinstance(data, dict):
            t = parse_ts(data.get("updated"))
            if t is not None:
                return _iso(t), t, mt, "field", None
        elif err in ("missing",):  # vanished between stat and read
            return None, None, None, None, "missing"
    return _iso(mt), mt, mt, "mtime", err


def _src(sid: str, zh: str, en: str, path: str, cadence: str, used_by: list[str], hint_zh: str, hint_en: str) -> dict:
    return {"id": sid, "label_zh": zh, "label_en": en, "path": path, "cadence": cadence, "used_by": used_by,
            "hint_zh": hint_zh, "hint_en": hint_en, "updated": None, "updated_from": None, "mtime": None,
            "age_s": None, "expected_max_age_s": None, "stale": False, "stale_reason": None, "missing": False}


def _fill(src: dict, upd: tuple, now: float) -> dict:
    iso, t, mt, frm, err = upd
    age = round(now - t, 1) if t is not None else None
    if age is not None and -5.0 < age <= 0:  # sampled a moment after `now` (not clock skew); also -0.0
        age = 0.0
    if age is not None and age <= -5.0:  # FR-6: a future `updated` field -> trust the mtime instead
        skew = round(-age, 1)
        if mt is not None and (now - mt) > -5.0:
            iso, t, frm = _iso(mt), mt, "mtime"
            age = max(0.0, round(now - mt, 1))
        else:
            age = 0.0
        src["clock_skew_s"] = skew
        err = err or f"clock skew: updated is {skew:.0f} s in the future"
    src.update(updated=iso, updated_from=frm, mtime=_iso(mt), age_s=age)
    if err == "missing":
        src["missing"] = True
    elif err:
        src["error"] = err
    return src


def _age_stale(src: dict, max_age: float | None, reason: str) -> None:
    src["expected_max_age_s"] = max_age
    if max_age is not None and src.get("age_s") is not None and src["age_s"] > max_age:
        src["stale"], src["stale_reason"] = True, reason


def _run_activity(d: Path) -> float | None:
    ts = []
    for n in ("metrics.jsonl", "status.json", "log.txt"):
        try:
            ts.append((d / n).stat().st_mtime)
        except OSError:
            pass
    return max(ts) if ts else None


def _fresh_dur(sec: Any) -> tuple[str, str]:
    v = fnum(sec)
    if v is None:
        return "?", "?"
    if v < 120:
        return f"{v:.0f} 秒", f"{v:.0f} s"
    if v < 2 * 3600:
        return f"{v / 60:.0f} 分钟", f"{v / 60:.0f} min"
    return f"{v / 3600:.1f} 小时", f"{v / 3600:.1f} h"


def _fresh_reason(x: dict) -> tuple[str, str]:
    """bilingual one-liner explaining why a source is flagged stale (shown in the badge tooltip)"""
    az, ae = _fresh_dur(x.get("age_s"))
    mz, me = _fresh_dur(x.get("expected_max_age_s"))
    r = x.get("stale_reason")
    if r == "running_run_silent":
        d = x.get("detail") or {}
        ids = ", ".join(d.get("stale_runs") or [])
        oz, oe = _fresh_dur(d.get("oldest_running_age_s"))
        return (f"运行中的 {ids} 已 {oz} 没有写入（实时数据预期 ≤ {mz}）",
                f"Running {ids} silent for {oe} (live data expected within {me})")
    if r == "dependent_phase_running":
        ph = ", ".join(x.get("depends_running") or [])
        return (f"{az} 未更新，而依赖它的阶段 {ph} 正在进行（预期 ≤ {mz}）",
                f"Not updated for {ae} while phase {ph} depends on it (expected within {me})")
    if r == "sample_failed":
        return "实时采样失败", "Live sampling failed"
    return f"{az} 未更新（预期 ≤ {mz}）", f"Not updated for {ae} (expected within {me})"


def build_freshness(now: float | None = None) -> dict:
    """one row per data source: when it last changed, its cadence class and whether it looks stale (README §19)"""
    now = time.time() if now is None else now
    rel = lambda p: os.path.relpath(p, ROOT) if str(p).startswith(str(ROOT)) else str(p)  # noqa: E731
    wf_data, _ = read_json(STATE / "workflow.json")
    wf_phases = [p for p in (wf_data.get("phases") or []) if isinstance(p, dict)] if isinstance(wf_data, dict) else []
    running_phases = {str(p.get("id")) for p in wf_phases if str(p.get("status") or "").lower() in FRESH_RUNNING}
    out: list[dict] = []

    # ---- live --------------------------------------------------------------------------------------------
    s = _src("runs", "训练运行（metrics.jsonl / status.json）", "Training runs (metrics.jsonl / status.json)",
             "runs/*/{metrics.jsonl,status.json,log.txt}", "live",
             ["overview.curves", "overview.race", "overview.kpi_best_dice_live", "training", "leaderboard.live", "alerts"],
             "训练中的运行每隔几秒写入指标（验证时可能静默约 1 分钟）；运行中的训练 3 分钟无写入才判定过期，没有运行中的训练时不判定",
             "Running runs append metrics every few seconds (validation can be silent for ~1 min); stale only after 3 min "
             "without a write, not judged while no run is running")
    newest, running, stale_runs, oldest = None, [], [], None
    for d in run_dirs():
        if run_hidden(d.name):
            continue
        t = _run_activity(d)
        if t is not None and (newest is None or t > newest):
            newest = t
        st, _ = read_json(d / "status.json")
        if isinstance(st, dict) and str(st.get("state") or "").lower() in FRESH_RUNNING:
            running.append(d.name)
            age = (now - t) if t is not None else None
            if age is None or age > FRESH_RUN_SILENT_S:
                stale_runs.append(d.name)
            if age is not None and (oldest is None or age > oldest):
                oldest = age
    _fill(s, (_iso(newest), newest, newest, "mtime", None) if newest is not None else (None, None, None, None, "missing"), now)
    s["expected_max_age_s"] = FRESH_RUN_SILENT_S
    s["detail"] = {"running": running, "stale_runs": stale_runs,
                   "oldest_running_age_s": round(oldest, 1) if oldest is not None else None}
    if stale_runs:
        s["stale"], s["stale_reason"] = True, "running_run_silent"
    out.append(s)

    s = _src("events", "事件日志", "Event log", "state/events.jsonl", "live",
             ["overview.events", "overview.milestones", "overview.kpi_elapsed", "events", "alerts"],
             "事件按发生追加（无固定节奏），只显示时间，不按时长判定过期",
             "Appended when something happens (no fixed rhythm): timestamp only, never stale by age")
    _fill(s, file_updated(STATE / "events.jsonl", field=False), now)
    s["expected_max_age_s"] = FRESH_LIVE_S
    s["stale_rule"] = "sporadic"
    out.append(s)

    s = _src("system", "系统指标（GPU / CPU / 内存）", "System metrics (GPU / CPU / RAM)", "NVML / psutil", "live",
             ["overview.kpi_gpu", "system"], "每次请求实时采样（缓存 3 秒）", "Sampled live on request (3 s cache)")
    try:
        g = CACHE.get("gpu", 3, gpu_info)
        t = CACHE.stamp("gpu")
        _fill(s, (_iso(t), t, None, "sample", None), now)
        if (g or {}).get("source") == "none":
            s["error"] = "no GPU source"
    except Exception as e:  # noqa: BLE001
        s["error"] = f"{e.__class__.__name__}: {str(e)[:120]}"
    _age_stale(s, FRESH_LIVE_S, "age")
    if s.get("error") and s["updated"] is None:
        s["stale"], s["stale_reason"] = True, "sample_failed"
    out.append(s)

    s = _src("session", "主会话（对话记录 / 监听心跳）", "Main session (transcript / listener heartbeat)",
             "transcript + state/session_watch.json", "live", ["session"],
             "编排器工作时写对话记录，等待时监听器每 3 秒写心跳；两者都超过 60 秒才算过期",
             "The orchestrator writes its transcript while working and the listener beats every 3 s while it waits; "
             "stale only when both are older than 60 s")
    ts = []
    w, _ = read_json(STATE / "session_watch.json")
    hb = parse_ts(w.get("ts")) if isinstance(w, dict) else None
    if hb is not None:
        ts.append(hb)
    try:
        f, _note = main_session()
        if f is not None:
            ts.append(f.path.stat().st_mtime)
    except Exception:  # noqa: BLE001
        pass
    t = max(ts) if ts else None
    _fill(s, (_iso(t), t, None, "field" if t == hb and hb is not None else "mtime", None) if t is not None
          else (None, None, None, None, "missing"), now)
    s["detail"] = {"heartbeat": _iso(hb)}
    _age_stale(s, FRESH_LIVE_S, "age")
    out.append(s)

    # ---- event -------------------------------------------------------------------------------------------
    for sid, zh, en, path, used, hz, he in (
        ("results_summary", "正式评估汇总", "Formal evaluation summary", RESULTS / "summary.json",
         ["overview.kpi_best_dice", "results", "leaderboard.final"],
         "结果汇总只在训练完成并评估后更新", "The results summary only updates after a run finishes and is evaluated"),
        ("experiments", "实验注册表（状态 / 结论）", "Experiment registry (status / verdicts)", STATE / "experiments.json",
         ["overview.kpi_experiments", "overview.kpi_queue_eta", "workflow.phases", "workflow.lineage", "workflow.queue",
          "leaderboard", "alerts"],
         "运行开始、结束或评估完成时由调度器更新", "Updated by the job runner when a run starts, finishes or is evaluated"),
        ("leaderboard_events", "排行榜变化记录", "Leaderboard change log", STATE / "leaderboard_events.jsonl",
         ["overview.race", "leaderboard.timeline"],
         "只在名次或结论变化时追加", "Appended only when a verdict or rank changes"),
    ):
        s = _src(sid, zh, en, rel(path), "event", used, hz, he)
        _fill(s, file_updated(path, field=path.suffix == ".json"), now)
        out.append(s)
    s = _src("run_eval", "运行评估输出", "Run evaluation outputs", "runs/*/eval/*_summary.json", "event",
             ["results", "workflow.phases"], "某个运行评估完成时写入", "Written when a run's evaluation finishes")
    newest = None
    for d in run_dirs():
        if run_hidden(d.name) or not (d / "eval").is_dir():
            continue
        try:
            for f in (d / "eval").iterdir():
                if f.name.endswith("_summary.json"):
                    m = f.stat().st_mtime
                    newest = m if newest is None or m > newest else newest
        except OSError:
            continue
    _fill(s, (_iso(newest), newest, newest, "mtime", None) if newest is not None else (None, None, None, None, "missing"), now)
    out.append(s)

    # ---- periodic ----------------------------------------------------------------------------------------
    for sid, zh, en, path, used, hz, he in (
        ("briefing", "进展简报", "Progress briefing", STATE / "briefing.json", ["overview.briefing"],
         "编排器约每 2 小时更新一次", "The orchestrator refreshes it about every 2 h"),
        ("session_status", "会话状态（令牌 / 上下文）", "Session status (tokens / context)", STATE / "session_status.json",
         ["session.status"], "编排器每次唤醒或收尾时写入，预期 2 小时内", "Written at every orchestrator wake-up / wrap-up; expected within 2 h"),
    ):
        s = _src(sid, zh, en, rel(path), "periodic", used, hz, he)
        _fill(s, file_updated(path), now)
        if not s["missing"]:
            _age_stale(s, FRESH_PERIODIC_S, "age")
        else:
            s["expected_max_age_s"] = FRESH_PERIODIC_S
        out.append(s)

    # ---- manual ------------------------------------------------------------------------------------------
    try:  # FR-4: an auto phase with nothing countable falls back to the file value -> it is hand-written too
        _auto = CACHE.get("phase_auto", 3, phase_progress_auto)
        manual_ids = {str(q.get("id")) for q in apply_phase_auto(wf_phases, _auto) if q.get("progress_source") == "manual"}
    except Exception:  # noqa: BLE001
        manual_ids = {str(q.get("id")) for q in wf_phases if str(q.get("id")) not in AUTO_PHASES}
    wf_dep = sorted(p for p in running_phases if p in manual_ids)  # running phases whose progress is hand-written
    for sid, zh, en, path, used, deps, hz, he in (
        ("workflow", "工作流阶段（手工备注）", "Workflow phases (manual notes)", STATE / "workflow.json",
         ["overview.kpi_phase", "overview.phases", "workflow.phases"], tuple(wf_dep),
         "阶段状态与备注为手工维护；训练/评估类阶段的进度已自动推算",
         "Phase status and notes are hand-maintained; training / evaluation progress is derived automatically"),
        ("paper", "论文状态", "Paper status", STATE / "paper.json", ["overview.kpi_sections", "overview.kpi_refs", "paper"],
         FRESH_MANUAL_DEPS["paper"], "手工更新；论文或参考文献阶段进行中时 12 小时未更新视为可能过期",
         "Updated by hand; may be stale after 12 h while the paper or references phase runs"),
        ("literature", "文献库", "Literature", STATE / "literature.json", ["overview.kpi_papers", "literature"],
         FRESH_MANUAL_DEPS["literature"], "手工更新；文献阶段进行中时 12 小时未更新视为可能过期",
         "Updated by hand; may be stale after 12 h while the literature phase runs"),
        ("routing", "模型路由", "Model routing", STATE / "routing.json", ["overview.routing", "agents"], (),
         "手工更新，不判定过期", "Updated by hand; never judged stale"),
        ("cases", "定性病例展示", "Qualitative case gallery", CASES / "index.json", ["results.gallery"], (),
         "由 scripts/make_case_gallery.py 生成，不判定过期", "Generated by scripts/make_case_gallery.py; never judged stale"),
    ):
        s = _src(sid, zh, en, rel(path), "manual", used, hz, he)
        _fill(s, file_updated(path, field=path.suffix == ".json"), now)
        act = [p for p in deps if p in running_phases]
        s["depends_on"] = list(deps)
        s["depends_running"] = act
        if act and not s["missing"]:
            _age_stale(s, FRESH_MANUAL_DEP_S, "dependent_phase_running")
        out.append(s)

    for x in out:
        x["reason_zh"], x["reason_en"] = _fresh_reason(x) if x["stale"] else (None, None)
    stale_ids = [x["id"] for x in out if x["stale"]]
    return {"ok": True, "sources": out, "stale_ids": stale_ids, "n_stale": len(stale_ids), "tiles": FRESH_TILES,
            "rules": {"live_s": FRESH_LIVE_S, "run_silent_s": FRESH_RUN_SILENT_S, "periodic_s": FRESH_PERIODIC_S, "manual_dependent_s": FRESH_MANUAL_DEP_S},
            "now": _iso(now)}


def freshness_cached() -> dict:
    return CACHE.get("freshness", FRESH_TTL_S, build_freshness)


def freshness_overview() -> dict:
    """compact form for /api/overview: stale ids, tile -> source map, and per-source timestamp / cadence / stale"""
    f = freshness_cached()
    keys = ("updated", "age_s", "cadence", "expected_max_age_s", "stale", "stale_reason", "missing")
    return {"stale_ids": f.get("stale_ids", []), "tiles": f.get("tiles", {}),
            "by_id": {x["id"]: {k: x.get(k) for k in keys} for x in f.get("sources", [])}, "now": f.get("now")}


@app.get("/api/freshness")
@safe
def api_freshness():
    return freshness_cached()


@app.get("/api/{rest:path}")
def api_unknown(rest: str):
    return JSONResponse({"ok": False, "error": f"unknown endpoint /api/{rest}"}, status_code=404)


# static SPA at /
app.mount("/", StaticFiles(directory=str(STATIC), html=True), name="static")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host=HOST, port=PORT, log_level="warning", access_log=False, workers=1)
