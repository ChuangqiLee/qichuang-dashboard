"""SYNTHETIC orchestrator state files for the fixtures and the demo: state/{workflow.json, events.jsonl,
routing.json, literature.json}. Written by tests/make_fixture.py (so a fixture never depends on, or copies, a real
project's state). Every value is demo data: no research result, no real paper (links point at example.org).
All times are relative to `now` (epoch seconds), so the demo always looks current.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

H = 3600.0


def iso(t: float) -> str:
    return datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def wjson(p: Path, obj) -> None:
    """atomic write, as the data contract asks of every producer (tmp file + os.replace)"""
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, p)


def workflow(now: float) -> dict:
    # (id, zh, en, status, manual progress, started h ago, ended h ago, notes_zh, notes_en)
    # train_base / train_novel / evaluate are auto phases: the server derives their progress from experiments.json
    rows = [
        ("env", "环境搭建", "Environment setup", "done", 1.0, 72, 66, "", ""),
        ("data", "数据整理与质控", "Data curation & QA", "done", 1.0, 66, 50, "（演示）排除 3 例重复扫描", "(demo) 3 duplicate scans excluded"),
        ("literature", "文献调研", "Literature review", "done", 1.0, 50, 30, "", ""),
        ("train_base", "基线训练", "Baseline training", "running", 0.5, 30, None, "", ""),
        ("train_novel", "新方法训练与消融", "Novel method & ablations", "running", 0.3, 20, None, "", ""),
        ("evaluate", "正式评估", "Formal evaluation", "pending", 0.0, None, None, "", ""),
        ("paper", "论文撰写", "Paper writing", "running", 0.35, 6, None, "（演示）引言与方法初稿", "(demo) intro and methods drafted"),
        ("refs", "参考文献核验", "Reference verification", "pending", 0.0, None, None, "", ""),
    ]
    phases = [{"id": i, "name_zh": zh, "name_en": en, "status": st, "progress": pr,
               "started": iso(now - s * H) if s is not None else None, "ended": iso(now - e * H) if e is not None else None,
               "notes_zh": nz, "notes_en": ne} for i, zh, en, st, pr, s, e, nz, ne in rows]
    return {"project": {"zh": "演示项目 · 医学影像分割", "en": "Demo project · medical image segmentation"},
            "updated": iso(now - 0.5 * H), "current_phase": "train_novel", "phases": phases}


def events(now: float) -> list[dict]:
    # (hours ago, type, actor, zh, en); level follows the type (milestone -> info)
    rows = [
        (72, "milestone", "orchestrator", "项目启动（演示数据）", "Project started (demo data)"),
        (70, "info", "orchestrator", "环境检查完成：2 张 GPU", "Environment check done: 2 GPUs"),
        (66, "milestone", "orchestrator", "环境搭建完成", "Environment ready"),
        (60, "info", "data-agent", "数据质控：发现 3 例重复扫描", "Data QA: 3 duplicate scans found"),
        (52, "warn", "data-agent", "2 例掩膜与图像尺寸不一致，已排除", "2 masks do not match their image size; excluded"),
        (50, "milestone", "orchestrator", "数据整理完成，划分训练/验证/测试", "Data curated; train/val/test split fixed"),
        (40, "info", "literature-agent", "文献调研：收录 6 篇（演示）", "Literature review: 6 papers collected (demo)"),
        (30, "milestone", "orchestrator", "文献调研完成，开始基线训练", "Literature review done; baseline training started"),
        (28, "info", "jobrunner", "启动 run_b1（GPU 0）", "Started run_b1 (GPU 0)"),
        (22, "error", "jobrunner", "N3 显存不足（OOM），已剪枝", "N3 ran out of GPU memory (OOM); pruned"),
        (20, "info", "jobrunner", "启动新方法训练 run_n1（GPU 1）", "Started novel run run_n1 (GPU 1)"),
        (12, "milestone", "orchestrator", "N1 完成：验证 Dice 高于两条基线（演示数据）", "N1 done: val Dice above both baselines (demo data)"),
        (8, "warn", "system", "GPU 1 温度偏高（83 °C）", "GPU 1 is running hot (83 °C)"),
        (6, "info", "writer-agent", "开始撰写论文初稿", "Paper draft started"),
        (3, "info", "jobrunner", "启动 run_n2（继承 N1）", "Started run_n2 (child of N1)"),
        (1, "info", "orchestrator", "进展简报已更新", "Progress briefing updated"),
        (0.15, "milestone", "orchestrator", "演示数据已生成，大屏上线", "Demo data generated; dashboard online"),
    ]
    return [{"ts": iso(now - h * H), "type": ty, "level": ty if ty in ("warn", "error") else "info", "actor": a,
             "msg_zh": zh, "msg_en": en} for h, ty, a, zh, en in rows]


def routing(now: float) -> dict:
    return {"updated": iso(now - 70 * H), "routing": {
        "orchestrator": {"model": "claude-fable-5-1", "effort": "max"},
        "subagents": {"model": "claude-opus-5-5", "effort": "by difficulty (low/medium/high/xhigh)"},
        "escalation": {"model": "claude-fable-5-1", "trigger": "same failure twice, or a subagent reports it is stuck"}}}


def literature(now: float) -> dict:
    rows = [
        ("Demo paper A: a promptable segmentation foundation model", "CVPR 2024", 2024, "highlight", 3, ["foundation models", "segmentation"]),
        ("Demo paper B: anisotropic 3D convolutions for thick-slice MRI", "MICCAI 2025", 2025, "oral", 3, ["3D segmentation", "MRI"]),
        ("Demo paper C: self-supervised video pre-training for volumes", "NeurIPS 2024", 2024, "spotlight", 2, ["self-supervised", "foundation models"]),
        ("Demo paper D: boundary-aware losses for small structures", "ICCV 2023", 2023, "poster", 1, ["losses", "small objects"]),
        ("Demo paper E: test-time adaptation across scanners", "ICLR 2025", 2025, "outstanding paper", 2, ["domain shift"]),
        ("Demo paper F: calibrated uncertainty for volumetry", "ECCV 2024", 2024, "poster", 0, ["uncertainty", "volumetry"]),
    ]
    papers = [{"id": k, "title": t, "first_author": "Demo Author", "venue": v, "year": y, "award_tier": tier,
               "url": f"https://example.org/demo-paper-{chr(97 + k)}", "code_url": f"https://example.org/demo-code-{chr(97 + k)}",
               "key_idea": f"(demo) key idea of paper {chr(65 + k)}.",
               "relevance_to_vs": "(demo) why this matters for the project's task.",
               "transferable_component": "(demo) the module worth borrowing.", "verified_count": vc, "themes": th}
              for k, (t, v, y, tier, vc, th) in enumerate(rows)]
    return {"updated": iso(now - 30 * H), "papers": papers}


def write_state(state: Path, now: float) -> None:
    """write the four files under `state` (atomically, like a real producer)"""
    state = Path(state)
    wjson(state / "workflow.json", workflow(now))
    body = "".join(json.dumps(e, ensure_ascii=False) + "\n" for e in events(now))
    tmp = state / "events.jsonl.tmp"
    tmp.write_text(body, encoding="utf-8")
    os.replace(tmp, state / "events.jsonl")
    wjson(state / "routing.json", routing(now))
    wjson(state / "literature.json", literature(now))
