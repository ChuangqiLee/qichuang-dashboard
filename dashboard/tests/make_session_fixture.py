"""Build the SYNTHETIC Session-view fixture (contracts: dashboard/README.md §17) under a given directory.

Usage (writes only under DIR, which must be new, empty or an earlier fixture / demo directory; see _fixture_guard.py;
never touches the real project state or the real transcripts):
    python -I dashboard/tests/make_session_fixture.py /tmp/an_fixture            # base fixture + session files
    python -I dashboard/tests/make_session_fixture.py /tmp/an_fixture --no-base  # session files only
    AN_ROOT=/tmp/an_fixture AN_TRANSCRIPTS=/tmp/an_fixture/transcripts AN_DASH_PORT=17199 python -I dashboard/server.py

Without --no-base it first runs tests/make_fixture.py (which wipes DIR) for every other view.
Then it writes
  DIR/transcripts/<SID>.jsonl                      main session, exactly 300 lines (layout below)
  DIR/transcripts/<OLD>.jsonl                      an older top-level transcript (mtime 1 day ago)
  DIR/transcripts/<SID>/subagents/agent-afx1.jsonl a subagent transcript (newest mtime, not main)
  DIR/state/session_status.json, session_inbox.jsonl, session_inbox_ack.json, session_watch.json

Main transcript layout (line index k, 0-based; every line with a timestamp has T0 + 10*k seconds):
  k=0 custom-title, k=1 agent-name, k=2..15 ignored filler lines (queue-operation / system / attachment),
  then for turn i = 1..40 (7 lines): user text | assistant msg a: thinking | msg a: text | msg a: tool_use (Bash) |
  user tool_result | assistant msg b: text | attachment filler; after turn 10 one user line with a text block
  (a turn), after turn 20 one image-only user line (not a turn), after turn 30 one malformed line;
  k=299 one assistant "<synthetic>" line.
  usage of msg a (repeated on its 3 lines): input 2, cache_read 1000*i, cache_creation 100, output 50+i,
  thinking 20+i; msg b: input 1, cache_read 1000*i+500, cache_creation 10, output 30 (no thinking);
  model claude-fable-5-1 except msg 40b = claude-opus-5-5.
All content is test data.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import runpy
import sys
import time
import types
from pathlib import Path

HERE = Path(__file__).resolve().parent


def _sibling(name: str) -> types.ModuleType:
    """load tests/<name>.py by path (python -I keeps this directory off sys.path; no __pycache__ is written)"""
    p = HERE / f"{name}.py"
    m = types.ModuleType(name)
    m.__file__ = str(p)
    exec(compile(p.read_text(encoding="utf-8"), str(p), "exec"), m.__dict__)
    return m


guard = _sibling("_fixture_guard")
SID = "5e55a0b1-0000-4000-8000-000000000001"
OLD_SID = "0ld5e55a-0000-4000-8000-000000000000"
T0 = dt.datetime(2026, 10, 29, 10, 0, 0, tzinfo=dt.timezone.utc)
N_TURNS = 40


def iso(d: dt.datetime) -> str:
    return d.strftime("%Y-%m-%dT%H:%M:%SZ")


def wjson(p: Path, obj) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, p)


def transcript_lines() -> list[str]:
    out: list[str] = []

    def ts() -> str:
        return iso(T0 + dt.timedelta(seconds=10 * len(out)))

    def add(o: dict) -> None:
        out.append(json.dumps(o, ensure_ascii=False))

    def user(content, **kw) -> None:
        add({"parentUuid": None, "isSidechain": False, "type": "user", "message": {"role": "user", "content": content},
             "uuid": f"u{len(out)}", "timestamp": ts(), "sessionId": SID, **kw})

    def assistant(mid: str, model: str, block: dict, usage: dict) -> None:
        add({"parentUuid": None, "isSidechain": False, "type": "assistant",
             "message": {"id": mid, "type": "message", "role": "assistant", "model": model, "content": [block],
                         "usage": usage}, "requestId": "req_" + mid, "uuid": f"a{len(out)}", "timestamp": ts(),
             "sessionId": SID})

    def filler(kind: str) -> None:
        if kind == "queue-operation":
            add({"type": "queue-operation", "operation": "enqueue", "timestamp": ts(), "sessionId": SID})
        elif kind == "system":
            add({"parentUuid": None, "type": "system", "subtype": "info", "content": "test", "timestamp": ts()})
        else:
            add({"parentUuid": None, "type": "attachment", "attachment": {"type": "test"}, "timestamp": ts()})

    add({"type": "custom-title", "customTitle": "测试会话 · fixture session", "sessionId": SID})
    add({"type": "agent-name", "agentName": "orchestrator-fixture", "sessionId": SID})
    for j in range(14):
        filler(("queue-operation", "system", "attachment")[j % 3])
    for i in range(1, N_TURNS + 1):
        user(f"第 {i} 轮 · turn {i}: 汇报进度 / report progress")
        ua = {"input_tokens": 2, "cache_creation_input_tokens": 100, "cache_read_input_tokens": 1000 * i,
              "output_tokens": 50 + i, "output_tokens_details": {"thinking_tokens": 20 + i}, "service_tier": "standard"}
        ma = f"msg_fx_{i:03d}a"
        assistant(ma, "claude-fable-5-1", {"type": "thinking", "thinking": f"(test) thinking about turn {i}", "signature": "x"}, ua)
        assistant(ma, "claude-fable-5-1", {"type": "text", "text": f"**Turn {i}** — reply part 1 (test data)"}, ua)
        assistant(ma, "claude-fable-5-1", {"type": "tool_use", "id": f"toolu_{i:03d}", "name": "Bash",
                                           "input": {"command": f"echo {i}", "description": f"Echo turn {i}"}}, ua)
        user([{"type": "tool_result", "tool_use_id": f"toolu_{i:03d}", "content": f"ok {i}", "is_error": i == 7}],
             toolUseResult={"stdout": f"ok {i}"})
        ub = {"input_tokens": 1, "cache_creation_input_tokens": 10, "cache_read_input_tokens": 1000 * i + 500,
              "output_tokens": 30}
        assistant(f"msg_fx_{i:03d}b", "claude-opus-5-5" if i == N_TURNS else "claude-fable-5-1",
                  {"type": "text", "text": f"Done with turn {i}. 第 {i} 轮完成。"}, ub)
        filler("attachment")
        if i == 10:
            user([{"type": "text", "text": "补充说明 · extra note (a text block)"}])
        elif i == 20:
            user([{"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": "iVBORw0KGgo="}}])
        elif i == 30:
            out.append('{"parentUuid":null,"type":"user","message":{"role":"user","content": BROKEN')
    add({"parentUuid": None, "isSidechain": False, "type": "assistant",
         "message": {"id": "msg_synth", "role": "assistant", "model": "<synthetic>",
                     "content": [{"type": "text", "text": "No response requested."}],
                     "usage": {"input_tokens": 0, "output_tokens": 0, "cache_read_input_tokens": 0,
                               "cache_creation_input_tokens": 0}},
         "uuid": "synth", "timestamp": ts(), "sessionId": SID})
    assert len(out) == 300, len(out)
    return out


def session_state(state: Path, now: dt.datetime) -> None:
    wjson(state / "session_status.json", {
        "updated": iso(now - dt.timedelta(minutes=3)), "author": "orchestrator(fable-5.1) [test fixture]",
        "ccd_session_id": "local_00000000-test-0000-0000-fixture00000", "transcript_session_id": SID,
        "title": "测试会话 · fixture session", "model": "claude-fable-5-1", "effort": "max", "permission_mode": "auto",
        "fast_mode": {"state": "off", "disabled_reason": "sdk_opt_in_required"}, "remote_control": "off",
        "context": {"tokens_used": 244940, "window": 1000000, "percent_used": 24, "autocompact_at_percent": 97,
                    "categories": [{"name": "Messages", "tokens": 172150}, {"name": "System tools", "tokens": 34229},
                                   {"name": "System prompt", "tokens": 11525}]},
        "plan": {"name": "Max", "windows": [
            {"label": "5-hour limit", "percent_used": 7, "resets_at": iso(now + dt.timedelta(hours=3))},
            {"label": "Weekly · all models", "percent_used": 74, "resets_at": iso(now + dt.timedelta(days=5))},
            {"label": "Weekly · Fable", "percent_used": 93, "resets_at": iso(now + dt.timedelta(days=5))}]},
        "turn_budget_left": 14978247,
        "notes_zh": "（测试数据）会话不能自行切换模型/努力度；请在 Code 标签的模型菜单操作。",
        "notes_en": "(test data) A session cannot switch its own model/effort; use the Code tab's model menu."})
    inbox = [
        {"id": 1, "ts": "2026-10-29T10:40:00Z", "kind": "message", "text": "汇报一下 T0c 的进度", "model": "fable-5.1",
         "effort": "max", "source": "dashboard", "client": "fixture"},
        {"id": 2, "ts": "2026-10-29T10:45:00Z", "kind": "message", "text": "Pause the GPU1 queue <b>not html</b>",
         "model": "opus-5.5", "effort": "high", "source": "dashboard", "client": "fixture"},
        {"id": 3, "ts": "2026-10-29T10:48:00Z", "kind": "control", "control": "remote_control", "value": True, "text": "",
         "model": "fable-5.1", "effort": "max", "source": "dashboard", "client": "fixture"},
    ]
    (state / "session_inbox.jsonl").write_text("".join(json.dumps(m, ensure_ascii=False) + "\n" for m in inbox), encoding="utf-8")
    wjson(state / "session_inbox_ack.json", {"updated": "2026-10-29T10:46:00Z", "last_read_id": 2,
                                             "read": {"1": "2026-10-29T10:41:00Z", "2": "2026-10-29T10:46:00Z"},
                                             "replied": {"1": "2026-10-29T10:43:00Z"}})
    wjson(state / "session_watch.json", {"pid": 4242, "ts": iso(now), "since_id": 2,
                                         "started": int(now.timestamp()) - 600})


def build(out: Path, base: bool = True) -> Path:
    out = Path(out)
    guard.check(out)   # refuses /, $HOME, real projects and any non-empty directory without the fixture marker
    if base:
        argv = sys.argv
        try:
            sys.argv = [str(HERE / "make_fixture.py"), str(out)]
            runpy.run_path(str(HERE / "make_fixture.py"), run_name="__main__")
        finally:
            sys.argv = argv
    tr = out / "transcripts"
    tr.mkdir(parents=True, exist_ok=True)
    main = tr / f"{SID}.jsonl"
    main.write_text("\n".join(transcript_lines()) + "\n", encoding="utf-8")
    old = tr / f"{OLD_SID}.jsonl"
    old.write_text(json.dumps({"parentUuid": None, "type": "user", "message": {"role": "user", "content": "old session (test)"},
                               "timestamp": "2026-10-28T08:00:00Z", "sessionId": OLD_SID}) + "\n", encoding="utf-8")
    sub = tr / SID / "subagents" / "agent-afx1.jsonl"
    sub.parent.mkdir(parents=True, exist_ok=True)
    sub.write_text(json.dumps({"parentUuid": None, "isSidechain": True, "type": "assistant",
                               "message": {"id": "msg_sub", "role": "assistant", "model": "claude-opus-5-5",
                                           "content": [{"type": "text", "text": "subagent (test)"}],
                                           "usage": {"input_tokens": 5, "output_tokens": 999}},
                               "timestamp": "2026-10-29T10:30:00Z"}) + "\n", encoding="utf-8")
    t = time.time()
    os.utime(old, (t - 86400, t - 86400))
    os.utime(main, (t - 30, t - 30))
    os.utime(sub, (t, t))
    (out / "state").mkdir(parents=True, exist_ok=True)
    session_state(out / "state", dt.datetime.now(dt.timezone.utc))
    guard.mark(out)
    return out


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    dest = Path(args[0] if args else "/tmp/an_fixture")
    build(dest, base="--no-base" not in sys.argv)   # build() runs the shared target guard
    print("session fixture written to", dest, "(set AN_TRANSCRIPTS to", dest / "transcripts", ")")
