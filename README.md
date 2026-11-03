# Qichuang Era research dashboard kit · 奇创纪元科研监控大屏代码包

**EN** — Bilingual (中文 / English) large-screen monitor for research projects: workflow and queue Gantt, training curves, results, a live leaderboard (gold ★ ours vs baselines, red ★ SOTA), agent and session views, literature, paper and system status, with a freshness badge on every card. One FastAPI file (`dashboard/server.py`) serves a static single-page app (`dashboard/static/`) and only reads the JSON / JSONL files your project writes.

**中文** — 双语科研监控大屏：工作流与队列甘特图、训练曲线、结果、实时排行榜（金色 ★ 我们的模型 vs 基线，红色 ★ SOTA）、智能体与会话、文献、论文、系统状态，每张卡片都有数据新鲜度徽章。后端是一个 FastAPI 文件，前端是无需构建的静态页面，只读取项目按约定写出的文件。

Quick start / 快速开始 (Python ≥ 3.12): `python3 -m venv .venv && .venv/bin/pip install -r requirements.txt -r requirements-dev.txt && bash demo/run_demo.sh` → http://127.0.0.1:17199/ (synthetic demo data / 合成演示数据)

Connect a project / 接入项目: `cd dashboard && AN_ROOT=/path/to/project ../.venv/bin/python -I server.py` — optional features (transcripts, raw-data progress, supervisor alerts) stay off until their `AN_*` variable is set / 可选功能设了对应变量才启用（使用指南 §5）.

**Read the guide / 使用说明 → [使用指南.md](使用指南.md)** (data contract, env vars, rebranding, deployment, security, per-project changes / 数据契约、环境变量、换品牌、部署、安全、换项目要改的地方). Full API and contract reference / 完整接口参考: [dashboard/README.md](dashboard/README.md).

Layout / 目录: `dashboard/` server + static (front-end libraries bundled in `static/vendor/`, no CDN) + tests · `demo/` demo launcher · `deploy/` supervisor template (Vast.ai) · `scripts/` session inbox watcher, case-gallery generator (VS project reference) · `requirements*.txt` pinned dependencies (Python 3.12, FastAPI 0.162.0, uvicorn 0.54.0, Starlette 1.10.0).
