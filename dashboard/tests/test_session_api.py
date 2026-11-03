"""Session-view API tests (contracts: dashboard/README.md §17).  Synthetic data only; never touches the real project.

    cd <kit>/dashboard && OMP_NUM_THREADS=1 ../.venv/bin/python -m pytest tests/test_session_api.py -q -x

Expected numbers are hand-computed from the layout documented in tests/make_session_fixture.py:
  turns              = 40 user text lines + 1 user line with a text block                      = 41
  assistant_messages = 2 API messages per turn (msg a is split over 3 lines, counted once)      = 80
  output_tokens      = sum_{i=1..40} (50+i) + 40*30 = 2000 + 820 + 1200                         = 4020
  thinking_tokens    = sum_{i=1..40} (20+i) = 800 + 820                                          = 1620
  cache_read         = sum 1000*i + sum (1000*i+500) = 820000 + 840000                           = 1660000
  cache_creation     = 40*100 + 40*10                                                            = 4400
  input_tokens       = 40*2 + 40*1                                                               = 120
  last_context       = msg 40b: 1 + 40500 + 10                                                   = 40511
  records (seq)      = 40 turns * 6 (user, 3 x msg a, tool_result, msg b) + text + image + synthetic = 243
"""
from __future__ import annotations

import collections
import datetime as dt
import importlib
import importlib.util
import json
import os
import shutil
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
DASH = HERE.parent
# the real project the tests must never write into: $AN_REAL_ROOT, else $AN_ROOT, else the directory that holds
# dashboard/ (read at import, before any fixture sets AN_ROOT)
REAL_ROOT = Path(os.environ.get("AN_REAL_ROOT") or os.environ.get("AN_ROOT") or DASH.parent).resolve()

os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("MKL_NUM_THREADS", "1")
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


msf = _load("make_session_fixture", HERE / "make_session_fixture.py")
SID, OLD_SID = msf.SID, msf.OLD_SID

T_TURNS, T_ASSIST, T_OUT, T_THINK = 41, 80, 4020, 1620
T_CREAD, T_CCREATE, T_IN, T_LASTCTX = 1_660_000, 4400, 120, 40511
N_RECORDS, N_TOOLS = 243, 40


class Clock:
    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t


@pytest.fixture(scope="module")
def env(tmp_path_factory):
    root = tmp_path_factory.mktemp("an_session_fixture")
    msf.build(root, base=True)
    saved = {k: os.environ.get(k) for k in ("AN_ROOT", "AN_TRANSCRIPTS", "AN_SESSION_FILE", "AN_RAW", "AN_DEMO")}
    os.environ["AN_ROOT"] = str(root)
    os.environ["AN_TRANSCRIPTS"] = str(root / "transcripts")
    os.environ.pop("AN_SESSION_FILE", None)
    os.environ.pop("AN_RAW", None)                              # no `du` over a real data directory
    os.environ.pop("AN_DEMO", None)
    if str(DASH) not in sys.path:
        sys.path.insert(0, str(DASH))
    if "server" in sys.modules:
        server = importlib.reload(sys.modules["server"])
    else:
        server = importlib.import_module("server")
    # hard guard: everything below writes only into the fixture
    assert server.STATE.resolve() == (root / "state").resolve()
    assert REAL_ROOT not in server.SESSION_INBOX.resolve().parents
    server.SESSION_MIN_INTERVAL = 0.0
    from fastapi.testclient import TestClient

    with TestClient(server.app, base_url="http://127.0.0.1:17100") as client:   # an allowed Host (send guard)
        yield {"root": root, "server": server, "client": client, "state": root / "state",
               "main": root / "transcripts" / f"{SID}.jsonl"}
    for k, v in saved.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v


_mt = [0]


def touch_write(p: Path, text: str) -> None:
    """Write a state file and give it a unique mtime (read_json caches on (mtime, size))."""
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, p)
    _mt[0] += 1
    ns = (1_900_000_000 + _mt[0]) * 1_000_000_000
    os.utime(p, ns=(ns, ns))


def iso(d: dt.datetime) -> str:
    return d.strftime("%Y-%m-%dT%H:%M:%SZ")


@pytest.fixture(autouse=True)
def fresh(env, monkeypatch):
    server = env["server"]
    msf.session_state(env["state"], dt.datetime.now(dt.timezone.utc))
    for name in ("session_status.json", "session_inbox_ack.json", "session_watch.json"):
        p = env["state"] / name
        touch_write(p, p.read_text(encoding="utf-8"))
    server._send_times.clear()
    server._send_last_id = 0
    server._session_extra.clear()
    server.CACHE._d.clear()
    clock = Clock()
    monkeypatch.setattr(server, "_send_clock", clock)
    monkeypatch.delenv("AN_SESSION_FILE", raising=False)
    env["clock"] = clock
    yield env
    server.CACHE._d.clear()


def get(env, url: str, **kw) -> dict:
    env["server"].CACHE._d.clear()
    r = env["client"].get(url, **kw)
    assert r.status_code == 200, r.text
    return r.json()


def send(env, body, headers=None, raw: bytes | None = None, ctype: str | None = "application/json"):
    h = {"X-AN-Session": "1"} if headers is None else dict(headers)
    if ctype is not None:
        h["Content-Type"] = ctype
    content = raw if raw is not None else json.dumps(body).encode("utf-8")
    r = env["client"].post("/api/session/send", content=content, headers=h)
    assert r.status_code == 200, r.text
    return r.json()


def inbox_lines(env) -> list[dict]:
    p = env["state"] / "session_inbox.jsonl"
    if not p.exists():
        return []
    out = []
    for line in p.read_text(encoding="utf-8").split("\n"):
        if line.strip():
            try:
                out.append(json.loads(line))
            except Exception:
                out.append({"_bad": line})
    return out


# ---------------------------------------------------------------------------------------------------------------
# /api/session
# ---------------------------------------------------------------------------------------------------------------
def test_session_fields_and_usage(env):
    d = get(env, "/api/session")
    assert d["ok"] is True
    for k in ("session", "status", "status_age_s", "listening", "heartbeat_age_s", "watcher", "ack", "usage",
              "inbox_pending", "now"):
        assert k in d, k
    s = d["session"]
    assert s["id"] == SID and s["file"] == f"{SID}.jsonl"           # newest top-level file, not the subagent
    assert s["title"] == "测试会话 · fixture session"
    assert s["first_ts"] == "2026-10-29T10:02:40Z"                  # k=16 -> T0 + 160 s
    assert s["last_ts"] == "2026-10-29T10:49:50Z"                   # k=299 (synthetic) -> T0 + 2990 s
    assert s["n_messages"] == N_RECORDS and s["n_tool_calls"] == N_TOOLS
    assert s["model_seen"] == "claude-opus-5-5"
    assert s["active"] is True                                      # mtime = now - 30 s < 120 s
    assert s["bad_lines"] == 1
    u = d["usage"]
    assert u["turns"] == T_TURNS
    assert u["assistant_messages"] == T_ASSIST
    assert u["output_tokens_total"] == T_OUT
    assert u["thinking_tokens_total"] == T_THINK
    assert u["cache_read_total"] == T_CREAD
    assert u["cache_creation_total"] == T_CCREATE
    assert u["input_tokens_total"] == T_IN
    assert u["last_context_tokens"] == T_LASTCTX
    assert u["last_model"] == "claude-opus-5-5"                     # <synthetic> line ignored
    assert u["last_ts"] == "2026-10-29T10:49:30Z"                   # msg 40b at k=297
    st = d["status"]
    assert st["model"] == "claude-fable-5-1" and st["context"]["window"] == 1000000
    assert 150 <= d["status_age_s"] <= 260                          # updated = now - 3 min
    assert d["listening"] is True and 0 <= d["heartbeat_age_s"] < 15
    assert d["watcher"]["pid"] == 4242 and d["watcher"]["since_id"] == 2
    assert d["ack"]["last_read_id"] == 2
    assert d["inbox_pending"] == 1                                  # only id 3 is "delivered"


def test_session_selection_env_override_and_fallback(env, monkeypatch):
    old = env["root"] / "transcripts" / f"{OLD_SID}.jsonl"
    monkeypatch.setenv("AN_SESSION_FILE", str(old))
    d = get(env, "/api/session")
    assert d["session"]["id"] == OLD_SID and d["usage"]["turns"] == 1 and d["usage"]["assistant_messages"] == 0
    assert d["usage"]["last_context_tokens"] is None
    monkeypatch.setenv("AN_SESSION_FILE", "relative/not-absolute.jsonl")
    d = get(env, "/api/session")
    assert d["session"]["id"] == SID and "session_note" in d
    monkeypatch.setenv("AN_SESSION_FILE", str(env["root"] / "transcripts" / "missing.jsonl"))
    d = get(env, "/api/session")
    assert d["session"]["id"] == SID and "session_note" in d


def test_session_cached_for_two_seconds(env):
    server = env["server"]
    server.CACHE._d.clear()
    a = env["client"].get("/api/session").json()
    touch_write(env["state"] / "session_status.json", json.dumps({"updated": iso(dt.datetime.now(dt.timezone.utc)), "model": "x"}))
    b = env["client"].get("/api/session").json()
    assert a["now"] == b["now"] and b["status"]["model"] == "claude-fable-5-1"   # served from the ≤2 s cache
    c = get(env, "/api/session")
    assert c["status"] == {"updated": c["status"]["updated"], "model": "x"}


def test_listening_by_heartbeat_age(env):
    now = dt.datetime.now(dt.timezone.utc)
    hb = env["state"] / "session_watch.json"
    touch_write(hb, json.dumps({"pid": 1, "ts": iso(now - dt.timedelta(seconds=5)), "since_id": 0, "started": 0}))
    d = get(env, "/api/session")
    assert d["listening"] is True and 4 <= d["heartbeat_age_s"] <= 8
    touch_write(hb, json.dumps({"pid": 1, "ts": iso(now - dt.timedelta(seconds=20)), "since_id": 0, "started": 0}))
    d = get(env, "/api/session")
    assert d["listening"] is False and 19 <= d["heartbeat_age_s"] <= 23
    assert get(env, "/api/session/inbox")["listening"] is False
    assert get(env, "/api/session/stream?after=243")["listening"] is False
    touch_write(hb, json.dumps({"pid": 1, "ts": "not a time"}))
    d = get(env, "/api/session")
    assert d["listening"] is False and d["heartbeat_age_s"] is None
    hb.unlink()
    d = get(env, "/api/session")
    assert d["listening"] is False and d["heartbeat_age_s"] is None and d["watcher"] is None


def test_partial_status_tolerated(env):
    p = env["state"] / "session_status.json"
    touch_write(p, json.dumps({"model": "claude-fable-5-1"}))           # no "updated", no context / plan
    d = get(env, "/api/session")
    assert d["ok"] and d["status"] == {"model": "claude-fable-5-1"} and d["status_age_s"] is None
    touch_write(p, '{"updated": "2026-10-29T13:00:00Z", "model": "claude-fa')   # half-written
    d = get(env, "/api/session")
    assert d["ok"] and d["status"] == {} and d["status_error"].startswith("invalid json")
    touch_write(p, "")
    d = get(env, "/api/session")
    assert d["ok"] and d["status"] == {} and d["status_error"] == "empty"
    touch_write(p, json.dumps({"updated": "2026-10-29T13:00:00Z", "context": {"tokens_used": float("nan")}}))
    d = get(env, "/api/session")                                         # NaN -> null, strict JSON
    assert d["ok"] and d["status"]["context"]["tokens_used"] is None


def test_missing_state_files_tolerated(env):
    for name in ("session_status.json", "session_inbox_ack.json", "session_watch.json", "session_inbox.jsonl"):
        (env["state"] / name).unlink()
    d = get(env, "/api/session")
    assert d["ok"] and d["status"] == {} and d["ack"] == {} and d["watcher"] is None
    assert d["listening"] is False and d["inbox_pending"] == 0 and "status_error" not in d
    assert d["usage"]["turns"] == T_TURNS
    i = get(env, "/api/session/inbox")
    assert i["ok"] and i["messages"] == [] and i["ack"] == {} and i["listening"] is False
    s = get(env, "/api/session/stream?after=240")
    assert s["ok"] and s["inbox"] == [] and [m["seq"] for m in s["messages"]] == [241, 242, 243]
    # sending still works with no inbox / ack: the file is created
    r = send(env, {"text": "hello"})
    assert r["ok"] and r["id"] == 1
    assert (env["state"] / "session_inbox.jsonl.lock").exists()


def test_no_transcript_tolerated(env, monkeypatch, tmp_path):
    server = env["server"]
    monkeypatch.setattr(server, "AGENTS", server.AgentRegistry(tmp_path / "nothing-here"))
    d = get(env, "/api/session")
    assert d["ok"] and d["session"] is None and d["usage"] is None and d["session_error"]
    s = get(env, "/api/session/stream")
    assert s["ok"] and s["messages"] == [] and s["latest_seq"] == 0 and len(s["inbox"]) == 3


# ---------------------------------------------------------------------------------------------------------------
# /api/session/stream
# ---------------------------------------------------------------------------------------------------------------
def test_stream_tail_and_records(env):
    d = get(env, "/api/session/stream?limit=150")
    seqs = [m["seq"] for m in d["messages"]]
    assert seqs == list(range(94, 244))
    assert d["cursor"] == 243 and d["latest_seq"] == 243 and d["first_seq"] == 1
    assert d["more"] is False and d["gap"] is False and d["more_before"] is True
    d = get(env, "/api/session/stream?after=0&limit=10")
    m = {r["seq"]: r for r in d["messages"]}
    assert m[1]["role"] == "user" and m[1]["blocks"][0]["t"] == "text" and "turn 1" in m[1]["blocks"][0]["text"]
    assert m[2]["role"] == "assistant" and m[2]["blocks"][0]["t"] == "thinking"
    assert m[3]["blocks"][0]["t"] == "text"
    tu = m[4]["blocks"][0]
    assert tu["t"] == "tool_use" and tu["name"] == "Bash" and tu["input"]["main"] == "echo 1" and tu["input"]["desc"] == "Echo turn 1"
    assert m[5]["role"] == "tool" and m[5]["blocks"][0]["t"] == "tool_result" and m[5]["blocks"][0]["name"] == "Bash"
    assert m[5]["blocks"][0]["is_error"] is False and m[5]["blocks"][0]["text"] == "ok 1"
    d = get(env, "/api/session/stream?after=40&limit=1")             # turn 7 = seq 37..42, tool_result = 41
    assert d["messages"][0]["seq"] == 41 and d["messages"][0]["blocks"][0]["is_error"] is True and d["more"] is True
    d = get(env, "/api/session/stream?after=60&limit=2")             # seq 61 = extra text user line after turn 10
    assert d["messages"][0]["blocks"][0]["text"].startswith("补充说明")


def test_stream_cursor_semantics(env):
    d = get(env, "/api/session/stream?after=0&limit=200")
    assert [m["seq"] for m in d["messages"]] == list(range(1, 201))
    assert d["more"] is True and d["cursor"] == 200 and d["gap"] is False
    d = get(env, f"/api/session/stream?after={d['cursor']}&limit=200")
    assert [m["seq"] for m in d["messages"]] == list(range(201, 244))
    assert d["more"] is False and d["cursor"] == 243
    d = get(env, "/api/session/stream?after=243")
    assert d["messages"] == [] and d["cursor"] == 243 and d["more"] is False
    d = get(env, "/api/session/stream?after=0&limit=9999")           # clamped to 500
    assert len(d["messages"]) == 243 and d["more"] is False
    d = get(env, "/api/session/stream?before=94&limit=150")           # "load earlier"
    assert [m["seq"] for m in d["messages"]] == list(range(1, 94)) and d["more_before"] is False
    d = get(env, "/api/session/stream?after=abc")
    assert d["ok"] is False


def test_stream_gap_with_bounded_window(env, monkeypatch, tmp_path):
    server = env["server"]
    copy = tmp_path / "bounded-session.jsonl"
    shutil.copy(env["main"], copy)
    monkeypatch.setattr(server, "MAX_AGENT_MSGS", 100)
    monkeypatch.setenv("AN_SESSION_FILE", str(copy))
    d = get(env, "/api/session/stream?after=10&limit=200")
    assert d["first_seq"] == 144 and d["latest_seq"] == 243 and d["gap"] is True
    assert [m["seq"] for m in d["messages"]] == list(range(144, 244)) and d["more"] is False
    d = get(env, "/api/session/stream?after=143")
    assert d["gap"] is False and len(d["messages"]) == 100
    s = get(env, "/api/session")
    assert s["session"]["id"] == "bounded-session" and s["usage"]["output_tokens_total"] == T_OUT


def test_stream_inbox_states(env):
    d = get(env, "/api/session/stream?after=243")
    assert [(m["id"], m["state"]) for m in d["inbox"]] == [(1, "replied"), (2, "read"), (3, "delivered")]
    assert d["inbox"][2]["kind"] == "control" and d["inbox"][2]["value"] is True


# ---------------------------------------------------------------------------------------------------------------
# /api/session/inbox
# ---------------------------------------------------------------------------------------------------------------
def test_inbox_state_computation(env):
    d = get(env, "/api/session/inbox")
    assert d["ok"] and [(m["id"], m["state"]) for m in d["messages"]] == [(1, "replied"), (2, "read"), (3, "delivered")]
    assert d["messages"][0]["replied_at"] == "2026-10-29T10:43:00Z" and d["messages"][1]["read_at"] == "2026-10-29T10:46:00Z"
    assert d["messages"][2]["read_at"] is None and d["pending"] == 1 and d["ack"]["last_read_id"] == 2
    assert d["messages"][1]["text"] == "Pause the GPU1 queue <b>not html</b>"   # stored and returned verbatim
    ack = env["state"] / "session_inbox_ack.json"
    touch_write(ack, json.dumps({"last_read_id": 3, "read": {"1": "t", "2": "t"}, "replied": {"1": "t", "3": "t"}}))
    d = get(env, "/api/session/inbox")
    assert [m["state"] for m in d["messages"]] == ["replied", "read", "replied"] and d["pending"] == 0
    touch_write(ack, json.dumps({"last_read_id": 3}))                      # read via last_read_id only
    d = get(env, "/api/session/inbox")
    assert [m["state"] for m in d["messages"]] == ["read", "read", "read"]
    touch_write(ack, "[1, 2")                                             # broken ack -> everything delivered
    d = get(env, "/api/session/inbox")
    assert [m["state"] for m in d["messages"]] == ["delivered"] * 3 and d["ack"] == {}
    assert get(env, "/api/session/inbox?limit=2")["messages"][0]["id"] == 2


def test_inbox_bad_and_partial_lines(env):
    p = env["state"] / "session_inbox.jsonl"
    with open(p, "a", encoding="utf-8") as fh:
        fh.write("not json\n")
        fh.write('{"id": "seven", "text": "string id"}\n')
        fh.write('{"id": 4, "ts": "2026-10-29T10:49:00Z", "kind": "message", "te')   # partial, no newline
    d = get(env, "/api/session")
    assert d["inbox_total"] == 3 and d["inbox_bad_lines"] == 2
    r = send(env, {"text": "after a partial line"})
    assert r["ok"] and r["id"] == 4
    lines = inbox_lines(env)
    assert lines[-1]["id"] == 4 and lines[-1]["text"] == "after a partial line"
    assert "_bad" in lines[-2]                                             # the partial line was not glued on
    i = get(env, "/api/session/inbox")
    assert [m["id"] for m in i["messages"]] == [1, 2, 3, 4] and i["messages"][-1]["state"] == "delivered"


# ---------------------------------------------------------------------------------------------------------------
# POST /api/session/send
# ---------------------------------------------------------------------------------------------------------------
def test_send_rejections(env):
    before = (env["state"] / "session_inbox.jsonl").read_bytes()
    ok = {"text": "汇报进度", "model": "fable-5.1", "effort": "max"}
    assert send(env, ok, headers={})["code"] == "no_header"
    assert send(env, ok, headers={"X-AN-Session": "0"})["code"] == "no_header"
    assert send(env, ok, ctype="text/plain")["code"] == "bad_content_type"
    assert send(env, ok, ctype="application/x-www-form-urlencoded")["code"] == "bad_content_type"
    assert send(env, ok, ctype=None)["code"] == "bad_content_type"
    assert send(env, None, raw=b"{not json")["code"] == "bad_json"
    assert send(env, None, raw=b"\xff\xfe")["code"] == "bad_json"
    assert send(env, ["a"])["code"] == "bad_json"
    assert send(env, {**ok, "kind": "exec"})["code"] == "bad_kind"
    assert send(env, {**ok, "model": "gpt-5"})["code"] == "bad_model"
    assert send(env, {**ok, "model": "claude-fable-5-1"})["code"] == "bad_model"
    assert send(env, {**ok, "effort": "ultra"})["code"] == "bad_effort"
    assert send(env, {**ok, "text": "   \n "})["code"] == "empty_text"
    assert send(env, {**ok, "text": 42})["code"] == "bad_text"
    assert send(env, {**ok, "text": "x" * 20001})["code"] == "text_too_long"
    assert send(env, {**ok, "text": "x" * 33000})["code"] == "too_large"          # body > 32 KB
    assert send(env, {"kind": "control", "control": "shell", "value": True})["code"] == "bad_control"
    assert send(env, {"kind": "control", "control": "remote_control", "value": "yes"})["code"] == "bad_value"
    assert send(env, {"kind": "control", "control": "remote_control", "value": 1})["code"] == "bad_value"
    for r in [send(env, ok, headers={})]:
        assert r["ok"] is False and r["error"]
    assert (env["state"] / "session_inbox.jsonl").read_bytes() == before        # nothing appended
    assert env["server"]._send_times == collections.deque()                      # rejections do not count


def test_send_valid_appends_with_increasing_ids(env):
    lock = env["state"] / "session_inbox.jsonl.lock"
    if lock.exists():
        lock.unlink()
    r = send(env, {"text": "  汇报一下 T0c 的进度\n", "model": "opus-5.5", "effort": "high"})
    assert r["ok"] is True and r["id"] == 4 and r["ts"].endswith("Z")
    assert lock.exists()
    lines = inbox_lines(env)
    assert len(lines) == 4
    last = lines[-1]
    assert last == {"id": 4, "ts": r["ts"], "kind": "message", "text": "汇报一下 T0c 的进度", "model": "opus-5.5",
                    "effort": "high", "source": "dashboard", "client": "testclient"}
    env["clock"].t += 1.5
    r2 = send(env, {"kind": "control", "control": "remote_control", "value": False, "text": "ignored"})
    assert r2["ok"] and r2["id"] == 5
    c = inbox_lines(env)[-1]
    assert c["kind"] == "control" and c["control"] == "remote_control" and c["value"] is False and c["text"] == ""
    assert c["model"] == "fable-5.1" and c["effort"] == "max"                    # defaults
    env["clock"].t += 1.5
    r3 = send(env, {"text": "x" * 20000}, ctype="application/json; charset=utf-8")   # exactly at the limit
    assert r3["ok"] and r3["id"] == 6
    # the ack may be ahead of the file (e.g. inbox rotated): ids never go backwards
    touch_write(env["state"] / "session_inbox_ack.json", json.dumps({"last_read_id": 50, "read": {"77": "t"}}))
    env["clock"].t += 1.5
    assert send(env, {"text": "after ack"})["id"] == 78
    (env["state"] / "session_inbox.jsonl").unlink()
    (env["state"] / "session_inbox_ack.json").unlink()
    env["clock"].t += 1.5
    assert send(env, {"text": "after rotation"})["id"] == 79                     # in-memory high-water mark
    # newly sent message is visible to the GETs with state "delivered"
    d = get(env, "/api/session/inbox")
    assert d["messages"][-1]["id"] == 79 and d["messages"][-1]["state"] == "delivered"
    assert get(env, "/api/session")["inbox_pending"] == 1


def test_send_surrogates_are_sanitised(env):
    r = send(env, None, raw=b'{"text": "a\\ud800b"}')
    assert r["ok"]
    raw = (env["state"] / "session_inbox.jsonl").read_bytes().split(b"\n")[-2]
    assert json.loads(raw.decode("utf-8"))["text"] == "a?b"


def test_send_rate_limits(env):
    clock = env["clock"]
    assert send(env, {"text": "one"})["ok"]
    r = send(env, {"text": "too fast"})
    assert r["ok"] is False and r["code"] == "rate_limited"
    clock.t += 0.9
    assert send(env, {"text": "still too fast"})["code"] == "rate_limited"
    clock.t += 0.2                                                               # 1.1 s after the first
    assert send(env, {"text": "two"})["ok"]
    for k in range(58):                                                          # 60 accepted in ~65 s
        clock.t += 1.1
        assert send(env, {"text": f"n{k}"})["ok"], k
    clock.t += 1.1
    r = send(env, {"text": "61st within 10 min"})
    assert r["ok"] is False and r["code"] == "rate_limited" and "60" in r["error"]
    clock.t += 600                                                               # window has passed
    assert send(env, {"text": "later"})["ok"]
    ids = [m["id"] for m in inbox_lines(env)]
    assert ids == list(range(1, 3 + 61 + 1)) and ids == sorted(set(ids))


def test_send_csrf_preflight_and_methods(env):
    c = env["client"]
    r = c.options("/api/session/send", headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "POST",
                                                "Access-Control-Request-Headers": "x-an-session,content-type"})
    assert r.status_code >= 400 and "access-control-allow-origin" not in {k.lower() for k in r.headers}
    r = c.get("/api/session/send")
    assert r.status_code == 404 and r.json()["ok"] is False
    r = c.post("/api/session/send", data={"text": "form post"}, headers={"X-AN-Session": "1"})
    assert r.status_code == 200 and r.json()["code"] == "bad_content_type"


# ---------------------------------------------------------------------------------------------------------------
# existing endpoints unchanged + incremental parsing
# ---------------------------------------------------------------------------------------------------------------
def test_existing_endpoints_still_work(env):
    c = env["client"]
    assert c.get("/api/health").json()["ok"] is True
    a = get(env, "/api/agents")
    ids = {x["id"] for x in a["agents"]}
    assert {SID, OLD_SID, "afx1"} <= ids
    m = get(env, f"/api/agents/{SID}/messages?since=240")
    assert [x["seq"] for x in m["messages"]] == [241, 242, 243] and m["cursor"] == 243
    r = c.get("/api/definitely-not-a-route")
    assert r.status_code == 404 and r.json()["ok"] is False
    r = c.get("/api/session/nope")
    assert r.status_code == 404
    paths = [getattr(rt, "path", "") for rt in env["server"].app.routes]
    assert paths.index("/api/{rest:path}") > max(paths.index(p) for p in
                                                  ("/api/session", "/api/session/stream", "/api/session/inbox", "/api/session/send"))


def test_incremental_parse_and_partial_transcript_line(env):
    server = env["server"]
    f, _ = server.main_session()
    f.update(min_interval=0)
    off0 = f.offset
    line_user = json.dumps({"parentUuid": None, "type": "user", "message": {"role": "user", "content": "第 41 轮"},
                            "timestamp": "2026-10-29T11:00:00Z"})
    line_asst = json.dumps({"parentUuid": None, "type": "assistant", "timestamp": "2026-10-29T11:00:10Z",
                            "message": {"id": "msg_fx_041a", "role": "assistant", "model": "claude-fable-5-1",
                                        "content": [{"type": "text", "text": "turn 41"}],
                                        "usage": {"input_tokens": 3, "cache_read_input_tokens": 41000,
                                                  "cache_creation_input_tokens": 7, "output_tokens": 11,
                                                  "output_tokens_details": {"thinking_tokens": 5}}}})
    with open(env["main"], "a", encoding="utf-8") as fh:
        fh.write(line_user[:25])                                                 # half-written line
    d = get(env, "/api/session")
    assert d["usage"]["turns"] == T_TURNS and d["session"]["n_messages"] == N_RECORDS and f.offset == off0
    with open(env["main"], "a", encoding="utf-8") as fh:
        fh.write(line_user[25:] + "\n" + line_asst + "\n")
    d = get(env, "/api/session")
    u = d["usage"]
    assert u["turns"] == T_TURNS + 1 and u["assistant_messages"] == T_ASSIST + 1
    assert u["output_tokens_total"] == T_OUT + 11 and u["thinking_tokens_total"] == T_THINK + 5
    assert u["cache_read_total"] == T_CREAD + 41000 and u["cache_creation_total"] == T_CCREATE + 7
    assert u["input_tokens_total"] == T_IN + 3
    assert u["last_context_tokens"] == 3 + 41000 + 7 and u["last_model"] == "claude-fable-5-1"
    assert u["last_ts"] == "2026-10-29T11:00:10Z"
    assert d["session"]["n_messages"] == N_RECORDS + 2 and d["session"]["latest_seq"] == 245
    assert f.offset == env["main"].stat().st_size                                # nothing re-read
    # a repeated line of the same API message (Claude Code splits blocks) is not double counted
    with open(env["main"], "a", encoding="utf-8") as fh:
        fh.write(line_asst + "\n")
    u2 = get(env, "/api/session")["usage"]
    assert u2["assistant_messages"] == T_ASSIST + 1 and u2["output_tokens_total"] == T_OUT + 11
    s = get(env, "/api/session/stream?after=243")
    assert [m["seq"] for m in s["messages"]] == [244, 245, 246] and s["cursor"] == 246


# ---------------------------------------------------------------------------------------------------------------
# review fixes: DNS-rebinding guard, stale cursors, harness-injected user lines
# ---------------------------------------------------------------------------------------------------------------
def test_send_host_and_origin_allowlist(env, monkeypatch):
    clock = env["clock"]
    before = (env["state"] / "session_inbox.jsonl").read_bytes()
    ok = {"text": "rebind probe"}
    monkeypatch.setenv("PUBLIC_IPADDR", "80.0.0.1")
    monkeypatch.delenv("AN_DASH_ALLOWED_HOSTS", raising=False)
    bad = [{"Host": "evil.example"}, {"Host": "attacker-rebind.example:17100", "Origin": "http://attacker-rebind.example:17100"},
           {"Host": "127.0.0.1.evil.example"}, {"Host": "localhost:8080", "Origin": "http://evil.example:8080"},
           {"Host": "localhost:8080", "Origin": "null"}, {"Host": "trycloudflare.com"}, {"Host": ""}]
    for h in bad:
        r = send(env, ok, headers={"X-AN-Session": "1", **h})
        assert r["ok"] is False and r["code"] == "bad_host", h
    assert (env["state"] / "session_inbox.jsonl").read_bytes() == before
    good = [{"Host": "localhost:8080", "Origin": "http://localhost:8080"},                       # SSH tunnel
            {"Host": "localhost:17100", "Origin": "http://80.0.0.1:40100"},                     # via Caddy (Host rewritten)
            {"Host": "localhost:17100", "Origin": "https://abc-def.trycloudflare.com"},         # quick tunnel
            {"Host": "[::1]:17100"}, {"Host": "127.0.0.1:17100"}]
    for h in good:
        clock.t += 1.5
        r = send(env, ok, headers={"X-AN-Session": "1", **h})
        assert r["ok"] is True, (h, r)
    clock.t += 1.5
    assert send(env, ok, headers={"X-AN-Session": "1", "Host": "dash.example.org"})["code"] == "bad_host"
    monkeypatch.setenv("AN_DASH_ALLOWED_HOSTS", "dash.example.org, *.corp.example")
    assert send(env, ok, headers={"X-AN-Session": "1", "Host": "dash.example.org"})["ok"] is True
    clock.t += 1.5
    assert send(env, ok, headers={"X-AN-Session": "1", "Host": "localhost", "Origin": "https://a.corp.example"})["ok"] is True
    assert env["server"]._host_name("http://[::1]:8080/x") == "::1" and env["server"]._host_name("Example.ORG.:80") == "example.org"


def test_stream_cursor_beyond_latest_resets(env):
    d = get(env, "/api/session/stream?after=99999")
    assert d["messages"] == [] and d["reset"] is True and d["gap"] is True and d["cursor"] == d["latest_seq"] >= N_RECORDS
    last = d["latest_seq"]
    d = get(env, f"/api/session/stream?after={last}")
    assert d["reset"] is False and d["gap"] is False and d["cursor"] == last


def test_meta_lines_flagged_and_not_turns(env, monkeypatch, tmp_path):
    p = tmp_path / "meta-session.jsonl"
    L = [{"type": "user", "timestamp": "2026-10-29T12:00:00Z", "message": {"role": "user", "content": "real prompt one"}},
         {"type": "user", "isMeta": True, "timestamp": "2026-10-29T12:00:10Z", "message": {"role": "user", "content": "meta injected"}},
         {"type": "user", "isMeta": True, "timestamp": "2026-10-29T12:00:11Z",
          "message": {"role": "user", "content": [{"type": "text", "text": "[Image: original 3186x1238, displayed at 1568x609]"}]}},
         {"type": "user", "timestamp": "2026-10-29T12:00:12Z",
          "message": {"role": "user", "content": "<task-notification>\n<task-id>x</task-id>\n</task-notification>"}},
         {"type": "user", "isCompactSummary": True, "timestamp": "2026-10-29T12:00:20Z",
          "message": {"role": "user", "content": "This session is being continued from a previous conversation..."}},
         {"type": "user", "timestamp": "2026-10-29T12:00:30Z", "message": {"role": "user", "content": [{"type": "text", "text": "real prompt two"}]}}]
    p.write_text("".join(json.dumps(o, ensure_ascii=False) + "\n" for o in L), encoding="utf-8")
    monkeypatch.setenv("AN_SESSION_FILE", str(p))
    s = get(env, "/api/session")
    assert s["session"]["id"] == "meta-session" and s["usage"]["turns"] == 2
    d = get(env, "/api/session/stream?after=0")
    assert [m.get("meta") for m in d["messages"]] == [None, "meta", "meta", None, "compact", None]
