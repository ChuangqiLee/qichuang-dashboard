# AN Research Monitor · 听神经瘤研究监控

> **Kit note.** This is the full API and data-contract reference of the dashboard. It was written for the project the
> dashboard was first deployed on (acoustic neuroma / vestibular schwannoma, "VS", on a Vast.ai instance); the
> service names, ports and paths in the *Access* and *Service management* sections are that deployment's and serve as
> examples. For a new project start with `../使用指南.md` (setup, environment variables, what to change).

A bilingual (中文 / English) monitoring dashboard for the acoustic neuroma / vestibular schwannoma
deep-learning project. It is **read-only** except for a few files it owns: the Session view's composer appends messages to
`state/session_inbox.jsonl` (§17), and the leaderboard keeps `state/leaderboard_state.json` and
`state/leaderboard_events.jsonl` and appends its `ahead` / `★ SOTA` milestones to `state/events.jsonl` (§18). It never
writes any other project file. It reads the files
described below and shows them live (the browser polls every 4 s), so new runs, results and
papers show up **without restarting the service**.

- Backend: `server.py` (FastAPI + uvicorn; Python ≥ 3.11, pinned in `../requirements.txt`), binds **127.0.0.1:17100** only.
- Frontend: `static/{index.html, app.js, style.css, i18n.js}`. Vanilla JS with no build step.
  ECharts 5.5.0, marked 12.0.2 and DOMPurify 3.1.6 are bundled in `static/vendor/` (versions, licenses and SRI hashes
  in `static/vendor/README.md`), so no CDN is needed. If a library does not load, the page still works: charts show a
  notice and Markdown falls back to escaped plain text.
- Views (URL hash routing): `#/overview #/workflow #/training #/results #/leaderboard #/agents #/session #/literature #/paper #/system #/events`.
- Language: header button or the **L** key. The choice is stored in `localStorage.an_lang`.
- Large-screen helpers (see "Keyboard shortcuts, kiosk mode and link parameters" below): a global alert
  strip under the header on every view, a tab title such as `2 运行中 · 基线训练 · AN` (prefixed with `⚠ `
  when an error-level alert exists), kiosk auto-rotation (**K**), full screen (**F**), page zoom
  (**+ / - / 0**), view switching (**1–9**) and a help overlay (**?**).

## Access (VS deployment on Vast.ai; example)

| What | URL |
|---|---|
| Inside the container (no auth) | `http://127.0.0.1:17100/` |
| External, through the Caddy auth edge | `http://$PUBLIC_IPADDR:$VAST_TCP_PORT_10100/?token=$OPEN_BUTTON_TOKEN` (http unless `ENABLE_HTTPS=true`) |
| SSH tunnel (private) | `ssh -p $VAST_TCP_PORT_22 -L 8080:127.0.0.1:17100 root@$PUBLIC_IPADDR`, then open `http://localhost:8080` |

Caddy also accepts `Authorization: Bearer $OPEN_BUTTON_TOKEN`. The first `?token=` visit sets an
auth cookie, so later API calls from the page are authenticated; the page then removes `token` from the address bar
(`history.replaceState`), so it does not stay in the browser history or on a photo of the screen. Never paste the
token value into logs or documents.

## Service management (supervisor; VS deployment, template in `../deploy/`)

| Piece | Path |
|---|---|
| Wrapper script | `/opt/supervisor-scripts/an_dashboard.sh` (sources `logging.sh`, `environment.sh`, `exit_portal.sh "AN Dashboard"`) |
| Supervisor program | `/etc/supervisor/conf.d/an_dashboard.conf` (`[program:an_dashboard]`, `stdout_logfile=/dev/stdout`) |
| Portal entry | `/etc/portal.yaml` → `AN Dashboard: {hostname: localhost, external_port: 10100, internal_port: 17100, open_path: /}` |
| Logs | `/var/log/portal/an_dashboard.log` |

```bash
supervisorctl status an_dashboard
supervisorctl restart an_dashboard        # after editing server.py (static files need no restart; just reload the page)
supervisorctl reread && supervisorctl update   # after editing the .conf
supervisorctl restart caddy               # after editing /etc/portal.yaml
curl -s http://127.0.0.1:17100/api/health
```

These files live on the container filesystem. They survive stop/start but **not** recycle/destroy
(`/workspace` is not a persistent volume on this instance). To rebuild, recreate the wrapper, the
conf and the portal entry exactly as listed above.

Environment variables (all optional; `python -I` still passes `AN_*`):

| Variable | Default | Meaning |
|---|---|---|
| `AN_ROOT` | the directory that holds `dashboard/` | project root (`state/`, `runs/`, `results/`, `paper/`, `configs/`) |
| `AN_TRANSCRIPTS` | unset = off | Claude Code transcript directory for the Agents / Session views (§10, §17) |
| `AN_SESSION_FILE` | unset | absolute path of the main-session `.jsonl` (else the newest top-level transcript) |
| `AN_RAW`, `AN_RAW_TOTAL` | unset = off | System view: `du -sb $AN_RAW` against `$AN_RAW_TOTAL` bytes (§11) |
| `AN_DISK_PATH` | `$AN_ROOT` | disk shown on the System view and checked by the low-disk alert |
| `AN_ALERT_SERVICES` | empty | comma-separated supervisor programs that must be `RUNNING` (§13) |
| `AN_DASH_HOST`, `AN_DASH_PORT` | `127.0.0.1`, `17100` | bind address and port |
| `AN_DASH_ALLOWED_HOSTS` | empty | extra Host / Origin names for `POST /api/session/send` (§17) |
| `AN_LEADERBOARD_READONLY` | unset | `1`: compute the leaderboard timeline in memory only and never write `state/leaderboard_*` or `state/events.jsonl`. **Required** for any test instance that points at a real project, so that only the live service writes those files |
| `AN_DEMO` | unset | `1` (set by `demo/run_demo.sh`): the System view does not list this machine's processes or supervisor programs |

For the VS project these are `AN_ROOT=/workspace/an_project`, `AN_TRANSCRIPTS=/root/.claude/projects/-workspace`,
`AN_RAW=/workspace/an_data/raw`, `AN_RAW_TOTAL=104236481492` and
`AN_ALERT_SERVICES=an_jobrunner0,an_jobrunner1,an_diskguard` (written into the template `../deploy/an_dashboard.sh`).

---

## Data contracts

All paths are relative to the project root (`$AN_ROOT`) unless they are absolute. All timestamps are
**ISO-8601 UTC** (for example `2026-10-28T21:10:37Z`). A file may be missing, empty or half
written; the dashboard then shows a "waiting" state and never fails. **Write JSON files
atomically**: write `x.json.tmp`, then `os.replace(tmp, x.json)`. Append to JSONL files one
complete line at a time and end every line with `\n`. A trailing partial line is ignored until
its newline arrives. Non-finite numbers (`NaN`, `Infinity`) are tolerated: metric lines with a
non-finite `value` are skipped (counted in `bad_lines`), and any other NaN/Infinity in a state or
status file is sent to the browser as `null` (shown as "—"). Prefer writing `null` yourself.

Fields marked *bilingual* come as a `_zh` / `_en` pair (for example `name_zh` and `name_en`), and
the UI shows the pair that matches the active language. Please always fill both.

### 1. `state/events.jsonl` — event timeline (Overview feed and Events view)
One JSON object per line:
```json
{"ts": "2026-10-28T21:10:37Z", "type": "milestone|info|warn|error", "level": "info|warn|error",
 "actor": "<role, e.g. orchestrator(fable-5.1)>", "msg_zh": "中文消息", "msg_en": "English message"}
```
"Project elapsed time" is measured from the earliest `ts` in this file.

### 2. `state/workflow.json` — pipeline phases (Workflow stepper and Gantt)
```json
{"project": {"zh": "…", "en": "…"}, "updated": "ISO", "current_phase": "<phase id>",
 "phases": [{"id": "env", "name_zh": "…", "name_en": "…",
             "status": "pending|running|done|failed|skipped", "progress": 0.0,
             "started": "ISO|null", "ended": "ISO|null", "notes_zh": "", "notes_en": ""}]}
```
`progress` is a value from 0 to 1. A phase that has `started` but no `ended` is drawn up to "now".

### 3. `state/experiments.json` — experiment lineage graph
```json
{"updated": "ISO", "experiments": [
  {"id": "N2", "name": "Novel-A + aniso", "family": "baseline|novel|ablation",
   "status": "queued|running|done|pruned|failed", "parent_id": "N1|null",
   "hypothesis_zh": "…", "hypothesis_en": "…", "verdict_zh": "…", "verdict_en": "…",
   "metrics_summary": {"val_dice": 0.91, "val_hd95": 2.3}, "run_dir": "runs/<run_id>", "gpu": 0}]}
```
`parent_id` draws the edges. Pruned nodes are greyed out and running nodes pulse. When
`results/summary.json` has no cells yet, the Overview "best Dice" tile falls back to the highest
`metrics_summary` key that matches `dice` / `dsc` (case-insensitive), compared between our family (`novel`, or
`ours`) and `baseline`. The "Open in Training" button, the leaderboard and the queue use only the last path component
of `run_dir` as the run id (absolute or relative paths both work).

### 4. `state/routing.json` — model routing card
```json
{"updated": "ISO", "routing": {"orchestrator": {"model": "claude-fable-5-1", "effort": "max"},
  "subagents": {"model": "claude-opus-5-5", "effort": "…"}, "escalation": {"model": "…", "trigger": "…"}}}
```

### 5. `runs/<run_id>/` — one directory per training run (Training view)
`<run_id>` should match `[A-Za-z0-9_.-]+`. New directories are picked up automatically.

**`metrics.jsonl`**: append-only, one scalar per line:
```json
{"ts": "ISO", "epoch": 3, "step": 1200, "split": "train|val|test", "name": "loss|dice|hd95|…", "value": 0.123}
```
- `name` + `split` identify a series. `value` must be a finite number; other lines count as bad lines.
- The x-axis can be `step` or `epoch` (the UI toggles; a missing axis falls back to the other one).
- The server reads files incrementally (byte offsets) and downsamples to ≤ 2000 points per series
  for display, keeping the minimum and maximum of each bucket. Names that match
  `loss|hd|asd|error|nll|ece|…` are treated as lower-is-better when the best-value marker is placed.

**`status.json`**: rewrite atomically about every epoch:
```json
{"state": "queued|running|done|failed", "epoch": 3, "total_epochs": 300, "eta_s": 5400.0, "gpu": 0,
 "best": {"val_dice": 0.91, "val_hd95": 2.1}, "config": {…}, "started": "ISO", "updated": "ISO",
 "exp_id": "N2", "name": "human readable run name"}
```
A run in `running` state whose `updated` is more than 10 min old gets a "stale" badge.

**`log.txt`**: plain-text log. The UI tails the last 200 lines.
**`samples/*.png|jpg|webp|svg`**: prediction snapshots. The newest 24 are shown, served from
`/api/runs/{run_id}/samples/{file}`.

Minimal writer for training scripts:
```python
import json, os, time, datetime
def _now(): return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
class RunLog:
    def __init__(self, run_dir):
        self.d = run_dir; os.makedirs(os.path.join(run_dir, "samples"), exist_ok=True)
        self.f = open(os.path.join(run_dir, "metrics.jsonl"), "a", buffering=1)
    def scalar(self, name, value, step, epoch, split="train"):
        self.f.write(json.dumps({"ts": _now(), "epoch": epoch, "step": step, "split": split,
                                 "name": name, "value": float(value)}) + "\n")
    def status(self, **kw):
        kw.setdefault("updated", _now()); p = os.path.join(self.d, "status.json")
        with open(p + ".tmp", "w") as fh: json.dump(kw, fh)
        os.replace(p + ".tmp", p)
```

### 6. `results/summary.json` — Results view and Overview "best Dice"
```json
{"updated": "ISO",
 "datasets": [{"id": "inhouse", "name_zh": "院内测试集", "name_en": "In-house test", "n": 120}],
 "metrics":  [{"id": "dice", "name_zh": "Dice", "name_en": "Dice", "higher_is_better": true, "unit": ""}],
 "methods":  [{"id": "ours", "name": "Ours", "family": "baseline|ours|ablation", "is_primary": true}],
 "cells":    [{"method": "ours", "dataset": "inhouse", "metric": "dice", "mean": 0.89, "std": 0.05,
               "ci_low": 0.88, "ci_high": 0.90, "n": 120}],
 "per_case": [{"method": "ours", "dataset": "inhouse", "case_id": "c001", "metric": "dice", "value": 0.91}],
 "pvalues":  [{"method_a": "ours", "method_b": "nnunet", "dataset": "inhouse", "metric": "dice", "p": 0.0004}]}
```
- Leaderboard: one table per dataset. The best value in each column is bold. The Δ column compares
  each method with the **best baseline** on the selected metric, with stars `* <0.05`, `** <0.01`,
  `*** <0.001` looked up from `pvalues` (either order of `method_a`/`method_b`).
- Grouped bars use `ci_low`/`ci_high` for error bars (falling back to mean ± std).
- The radar normalizes each metric to [0, 1] across methods, inverting lower-is-better metrics.
- The box plot uses `per_case` for the selected dataset and metric.
- Volume agreement and Bland–Altman appear when `per_case` contains `metric: "volume_ml"` rows,
  including `method: "ground_truth"`, paired by `case_id`.
- `family` (lowercase): `ours` (or `novel`, the experiments.json spelling) = our method, `ablation`, `baseline`;
  anything else counts as other.
- The Overview "best Dice" uses the first metric whose id matches `dice|dsc`, on the validation dataset (§19).
  It compares the primary (or best) method of our family with the best `baseline`.

- Results controls: **统计量 / Statistic** toggles mean (± std, 95 % CI) and median ([q1, q3]); the best
  value, best baseline, Δ, SOTA stars and the grouped bars (bars = statistic, whiskers = CI or IQR) all
  follow it. Cells without `median` fall back to `mean` (marked `†`, explained in the tooltip). Family chips
  (本文 / 消融 / 基线) hide rows only; **the best baseline and SOTA are always computed over every
  baseline**. **仅主数据集 / Primary datasets only** (default on) hides datasets whose `postprocess` is not
  `none`. The method column is sticky when the tables scroll horizontally.
- **SOTA matrix / SOTA 矩阵** (above the leaderboard): rows = methods (ours, ablations, baselines), columns =
  displayed dataset × metric, labelled `split[·output][·LCC]` + metric (the output token is added only when
  two datasets would otherwise share a label). Colour = Δ vs the best baseline of that column,
  sign-normalised (positive = better, negated for lower-is-better metrics) and divided by the column's
  max |Δ|; blue = better, orange = worse. Cell text = rank in the column (1 = best); `★` = SOTA. The SOTA
  rule is a single helper (`sotaModel()` in `app.js`) shared by the leaderboard, the matrix, the bars and
  the exports: a method of family `ours`/`novel` is SOTA in a column when it is **strictly better than
  every baseline** on the selected statistic. A slider appears when there are more than 14 columns.
- Export: **导出 CSV** downloads one row per displayed dataset × method × metric (statistic, value, std,
  CI, median, q1, q3, n, best baseline, its value, `delta_vs_best_baseline` (raw, value − baseline),
  `p_vs_best_baseline`, `sota` 0/1, `median_missing_used_mean`), UTF-8 with BOM. **复制 Markdown** copies one
  table per displayed dataset (★ = SOTA, Δ column with significance stars) to the clipboard.

### 7. `results/cases/index.json` + images — qualitative gallery
```json
[{"file": "case_001.png", "case_id": "c001", "dataset": "inhouse", "caption_zh": "…", "caption_en": "…"}]
```
`file` is relative to `results/cases/`. Entries whose file does not exist are hidden.

Optional keys, rendered by the Results gallery card when present: `id`, `title_zh` / `title_en`
(preferred over `caption_*` as the card title), `image` (same as `file`; the server still requires `file`), `dice`
(`{model_id: value}`, shown as chips in the family colours: gold ours, violet ablation, blue baseline, best value
outlined; families come from `summary.json` methods, else from id prefixes B/N/T/V), `note` (string or
`{zh, en}`), and informational `stratum`, `gt_volume_ml`, `best_model`, `slice_index`. Cases of the selected Results
dataset are listed first; other datasets stay visible. A broken image is hidden.

**Generator (reference only):** `scripts/make_case_gallery.py` is the VS project's generator (stages `select`, `eval`,
`render`); it needs that project's `anvs` package and MRI data, and its run ids are placeholders. It picks 8
validation cases by GT volume (2 small ≤ q25, 4 medium, 2 large ≥ q75; fixed seed), evaluates each model on them into
`results/cases/_eval/<run_id>` (never `runs/<id>/eval`, which holds the formal evaluation), then renders one 1×(1+N)
PNG per case (slice through the GT centroid, GT contour white, gold = ours, blue = baseline, Dice in each panel title)
and writes `index.json` with both key sets above. Re-run such a generator after a new model is evaluated; the System
view's freshness table lists the gallery as a manual source. **The gallery (and `runs/*/samples/`) is derived from
patient scans:** pseudonymous case ids only, no hospital / accession / MRN numbers in images or file names, and never
copy these files into the kit, git or a demo.

### 8. `state/literature.json` — Literature view
```json
{"updated": "ISO", "papers": [{"title": "…", "first_author": "…", "venue": "CVPR 2024", "year": 2024,
  "award_tier": "best_paper|outstanding|spotlight|oral|highlight|poster", "url": "https://…", "code_url": "https://…",
  "key_idea": "…", "relevance_to_vs": "…", "transferable_component": "…", "verified_count": 0, "themes": ["…"]}]}
```
`verified_count` is shown as progress towards 3. Only `http(s)` links are rendered.

### 9. `state/paper.json` + `paper/` — Paper view
```json
{"updated": "ISO", "target_journal": "…",
 "sections": [{"name": "Introduction", "status": "pending|draft|writing|review|done|final", "words": 900}],
 "figures": [{"file": "fig1.png", "caption_zh": "…", "caption_en": "…", "status": "pending|draft|done"}],
 "references": {"total": 40, "verified_1x": 40, "verified_2x": 31, "verified_3x": 22}}
```
Figure files live in `paper/figures/` (thumbnails for image types). When `paper/main.pdf`
exists it is linked and served at `/api/paper/pdf`. A section counts as "done" when its status is
`done`, `final`, `complete` or `completed`.

### 10. Agents view (Claude Code transcripts, read-only)
The server scans `$AN_TRANSCRIPTS/**/*.jsonl` and skips `memory/` (with `AN_TRANSCRIPTS` unset there are no
transcripts and the view says so; Claude Code keeps them in `~/.claude/projects/<dir>/`, where `<dir>` is the session's
working directory with each `/` written as `-`, e.g. `/root/.claude/projects/-workspace` for sessions started in
`/workspace`). A top-level
`<uuid>.jsonl` is the main orchestrator session; files in subdirectories (`agent-<id>.jsonl`) are
subagents. Display names come from `custom-title` / `agent-name` lines, from workflow
`journal.jsonl` "started" labels, and from `agent-<id>.meta.json`. Only `user` / `assistant` lines
are rendered: text (Markdown through marked + DOMPurify), tool calls (the most informative input),
tool results (truncated to 4000 chars on the server and to 600 in the UI, with an expand button)
and thinking blocks (collapsed). Parsing is incremental (byte offsets, a truncated last line is
tolerated) and bounded to the last 3000 messages per agent. An agent counts as *active* when its
file changed within the last 120 s.

### 11. System view
GPU data comes from NVML (fallback: `nvidia-smi --query-gpu`). CPU, RAM, the disk that holds `$AN_DISK_PATH` (default
the project root; the card shows the path), the container pids limit, Python processes whose command line contains
`train` (with their GPU when NVML or `CUDA_VISIBLE_DEVICES` shows it) and `supervisorctl status` (cached 10 s) are also
shown. Command lines are shown with secrets masked (`--hf-token ***`, `--api-key=***`, `PASSWORD=***`,
`https://***@host`, `unzip -P ***`; `redact_cmd()`). With `AN_DEMO=1` the process and supervisor lists stay empty
(demo data is synthetic; GPU, CPU, RAM and disk are still this machine's).
Dataset extraction progress (optional) is `du -sb $AN_RAW` against `$AN_RAW_TOTAL` bytes; without `AN_RAW` the card
says it is off. It is re-measured every 30 s while an `unzip` process exists, otherwise every 10 min, in a
background thread.

### 12. `state/briefing.json` — Overview "进展简报 / Progress briefing"
Written by the orchestrator; the dashboard only reads it.
```json
{"updated": "ISO", "author": "orchestrator (fable-5.1)", "zh": "## 中文 Markdown …", "en": "## English Markdown …"}
```
The language-matching Markdown is rendered (marked + DOMPurify, same sanitisation as agent messages) in a
full-width card right under the KPI tiles, with "更新于 <time>" and an author chip. Missing / empty file →
`{"missing": true}` and an empty-state box. Also returned as `briefing` in `/api/overview`.

### 13. Alerts (`GET /api/alerts`, also `alerts` in `/api/overview`)
```json
{"alerts": [{"id": "stale:run_n2", "level": "error|warn|info", "msg_zh": "…", "msg_en": "…", "ts": "ISO", "view": "training"}],
 "counts": {"warn": 1}, "n_running": 2, "now": "ISO"}
```
Rules (computed server-side, cached 3 s; disk / supervisor reuse the `/api/system` caches):

| Alert | Level | View |
|---|---|---|
| experiment with `status: "failed"` in `state/experiments.json` | error | training |
| `runs/<id>/status.json` with `state: "running"` and `updated` older than 10 min ("stale") | warn | training |
| `state/jobrunner.pause` exists (job runner paused) | warn | workflow |
| free space on `$AN_DISK_PATH` (default the project root) < 60 GB (warn) or < 40 GB (error) | warn / error | system |
| a supervisor program listed in `$AN_ALERT_SERVICES` (comma-separated; none by default) not `RUNNING` | warn | system |
| `milestone` event in the last 15 min | info | events (opens `#/events?type=milestone`) |

The browser fetches `/api/alerts` on every 4 s poll, whatever the view: one chip per alert in the strip
under the header (hidden when empty; click = go to its view), a count badge in the status bar, and the tab
title `<n running> 运行中 · <phase> · AN` (English when the UI is English; `⚠ ` prefix on an error).

### 14. Experiment queue (`GET /api/queue`, summary as `queue` in `/api/overview`)
```json
{"now": "ISO", "eta_end": "ISO|null", "eta_s": 86400,
 "lanes": [{"lane": "0|1|any", "items": [{"id": "A1", "name": "…", "family": "ablation", "status": "queued",
   "priority": 95, "start": "ISO", "end": "ISO", "estimated": true, "eta_s": null, "val_dice": null,
   "duration_s": 7200.0, "duration_src": "family|all|default", "any_lane": false}]}],
 "durations": {"median_s_by_family": {"baseline": 3600.0}, "median_s_all": 5400.0, "default_s": 7200},
 "counts": {"done": 5, "running": 2, "queued": 21, "skipped_planned": 9, "skipped_pruned": 0, "skipped_eval_only": 0}}
```
- `done` / `failed`: actual times from `runs/<id>/status.json` `started` → `updated` (fallback: the
  experiment's `started` / `ended`); lane = the status `gpu` (else the experiment `gpu`, else `any`).
- `running`: `started` → now + `eta_s` (`estimated: true`).
- `queued`: projected in priority order (higher first) after the lane's running run; `gpu: null` entries
  go to whichever lane frees first (`any_lane: true`). Projected duration = median duration of finished
  (`done`) runs of the same family when ≥ 2 exist, else the median of all finished runs, else 2 h.
- `planned`, `pruned` and evaluation-only entries (`notes` starting with `evaluation-only`) are skipped
  and only counted. The run behind an experiment is found from `run_dir` (last path component), or from a
  status file whose `exp_id` matches.
- Workflow view: full-width "实验队列时间轴 / Experiment queue timeline" card at the top: one Gantt row per
  lane (done = green, running = cyan with the estimated remainder dashed, failed = red, queued = dim with a
  dashed border; a family-colour stripe on the left; label = id), a "now" line, zoom (wheel/drag + slider;
  the zoom window survives the 4 s refresh), and a table (running row highlighted, `≈` = projected).
  Overview KPI "队列 ETA / Queue ETA" = the latest projected end, with running / queued counts.

### 15. Overview "里程碑与决策 / Milestones & decisions"
The last 12 events with `type: "milestone"` (field `milestones` of `/api/overview`), shown as a timeline
(actor chip, absolute + relative time). "查看全部 →" opens `#/events?type=milestone`.

### 16. Paper PDF preview
The Paper view has a **预览 PDF / Preview PDF** toggle that embeds `/api/paper/pdf` in an 80vh iframe. The
iframe is created only while the toggle is on (state in `localStorage.an_pp_pdf`) and only when
`paper/main.pdf` exists; the "open main.pdf ↗" link stays.

### 17. Session view (`#/session`, tab 会话 / Session)
Mirrors **this local Claude Code session** (the orchestrator) and lets you continue it from anywhere — it is
the same conversation as in the Code tab, not a separate chat.

- **Status card**: title, CCD session id and transcript id (short), badges for model (`claude-fable-5-1` →
  `Fable 5.1`), effort, permission mode, fast mode and Remote Control; the **listening pill** (监听在线 /
  Listening when the watcher heartbeat is < 15 s old, otherwise 监听离线 / Not listening with the heartbeat
  age); last activity; `截至 {t} / as of {t}` for orchestrator-written facts. Token panel: plan windows (5-hour,
  weekly all models, weekly Fable: used %, left %, reset time), context window (used / window, auto-compact
  marker at 97 %, categories), turn budget left, and live transcript counters (turns, assistant messages,
  output tokens incl. thinking, last context = input + cache read + cache creation, cache read / write, last
  model, pending inbox messages). Meters turn amber at ≥ 70 % and red at ≥ 90 %.
- **Conversation**: transcript records merged with the inbox by timestamp (inbox first on ties). User text =
  right-aligned bubble (escaped, `pre-wrap`); assistant text = Markdown through `marked` + `DOMPurify`; tool
  calls = collapsed 🔧 chips (runs of consecutive calls collapse into `N 次工具调用 / N tool calls`; results only
  when expanded); thinking hidden behind 显示思考 / show thinking (`localStorage`); harness lines
  (`<task-notification>`, `<system-reminder>`, …) and harness-injected user lines (`isMeta` skill text and image notes,
the `isCompactSummary` line written at auto-compaction — flagged `meta: "meta"|"compact"` on the record) collapse
into one 系统消息 / System message row. Dashboard
  messages carry a 大屏 / dashboard badge, the delegate target and a state glyph `✓ 已送达` (delivered) →
  `✓✓ 已读` (read) → `↩ 已回复` (replied). Polls `after=<cursor>` with the shared 4 s poller; first load =
  last 150 messages; 加载更早 / load earlier uses `before=<oldest seq>`; a 新消息 ↓ pill appears when you are
  not at the bottom (it counts only transcript records / inbox messages not seen before). When the main
transcript changes (new session file) or the server answers `reset: true` (cursor beyond `latest_seq`), the feed
restarts from the tail; stream responses issued before such a reset are dropped.
- **Composer** (sticky at the bottom on phones): textarea (draft kept in `localStorage`), target model,
  effort, quick chips, `Ctrl/⌘+Enter` or Send, and a Remote Control button (second click within 5 s confirms;
  posts a `control` record). A yellow note appears while the orchestrator is not listening — the message is
  then handled at its next wake-up.

**Delegation semantics — a session cannot re-price itself.** The platform does not let a session change its
own model or effort; only the user can, in the Code tab's model menu. The target-model select therefore means:
`Fable 5.1（本会话）` = this session handles the instruction itself; `Opus / Sonnet / Haiku 5.5（委派）` = this
session delegates it to a sub-agent of that model (with the chosen effort) and relays the result. The
session's own model / effort / permission mode / fast mode / Remote Control are shown read-only.

State files (all under `state/`, UTF-8; any field may be missing — the UI shows what exists):

| File | Writer → reader | Content |
|---|---|---|
| `session_inbox.jsonl` | server (`POST /api/session/send`) → orchestrator | one JSON per line: `{id, ts, kind: message\|control, text, model: fable-5.1\|opus-5.5\|sonnet-5.5\|haiku-5.5, effort: low\|medium\|high\|xhigh\|max, control?, value?, source: "dashboard", client}`; `id` strictly increasing and never reused (new id = max of the inbox ids, the ack ids and the in-process high-water mark, + 1, so the watcher's `since_id` never skips a message after the inbox is rotated), appended under an `fcntl` lock on `session_inbox.jsonl.lock` |
| `session_inbox_ack.json` | orchestrator → server | `{updated, last_read_id, read: {id: iso}, replied: {id: iso}}` → state `delivered` (id > `last_read_id`), `read`, `replied` |
| `session_watch.json` | watcher → server | heartbeat `{pid, ts, since_id, started}` every 3 s; listening = `ts` younger than 15 s |
| `session_status.json` | orchestrator (every wake-up / wrap-up) → server | `{updated, author, ccd_session_id, transcript_session_id, title, model, effort, permission_mode, fast_mode, remote_control, context: {tokens_used, window, percent_used, autocompact_at_percent, categories[]}, plan: {name, windows: [{label, percent_used, resets_at}]}, turn_budget_left, notes_zh, notes_en}` |

The transcript is the top-level `<uuid>.jsonl` under `AN_TRANSCRIPTS` (no default: unset means no session; the VS
deployment uses `/root/.claude/projects/-workspace`): `$AN_SESSION_FILE` (absolute `.jsonl`) when set, else the
newest-mtime main transcript. It is parsed by the existing `AgentFile` (incremental, byte offsets, last 3000 messages);
`usage` counts each API `message.id` once (Claude Code repeats the same usage on every content-block line) and
ignores `<synthetic>` lines. `turns` counts user text lines that are not tool results, not `isMeta` /
`isCompactSummary` and not `<task-notification>` (background-task completions).

**The watcher** — `AN_ROOT=<project> bash scripts/session_inbox_watch.sh <since_id> [cap_hours=8]` (orchestrator-only;
do not edit the contract; without `AN_ROOT` the root is the parent of the `scripts/` directory holding the script,
and it exits 2 when `<root>/state` is missing): writes the heartbeat every 3 s, exits 0 printing `SESSION_INBOX_NEW` plus the new inbox lines
as soon as an id > `since_id` appears, or exits 3 (`SESSION_INBOX_WATCH_CAP`) after the cap. The orchestrator
runs it in the background; its exit wakes the orchestrator, which reads the message(s), acts, acknowledges them
in `session_inbox_ack.json`, refreshes `session_status.json` and re-arms the watcher at the end of every turn.
The server never acts on inbox messages.

**Security**: the dashboard is reachable from outside only through the Caddy token edge (or an SSH tunnel). `POST
/api/session/send` first checks the **Host** header and, when present, the **Origin** header against an allowlist —
`127.0.0.1`, `localhost`, `::1`, `$PUBLIC_IPADDR`, `*.trycloudflare.com`, plus the comma-separated
`AN_DASH_ALLOWED_HOSTS` (`host`, or `*.domain` for a suffix; needed for a named Cloudflare tunnel on your own
domain) — and rejects everything else (and `Origin: null`) with `code: bad_host`. This blocks DNS rebinding through
the SSH tunnel (a rebound page is same-origin and could otherwise set the custom header). Origin is not compared
with Host because Caddy rewrites Host to `localhost:17100`. It additionally requires the header `X-AN-Session: 1` (a custom header forces a CORS
preflight, so other sites cannot replay the auth cookie) and `Content-Type: application/json`; body ≤ 32 KB,
text 1–20 000 characters after trimming, 1 message / s and 60 / 10 min per server process. Messages are stored
and shown as text; no shell, no path from input, no eval. Rejections are HTTP 200
`{"ok": false, "error", "code"}` with `code` one of `bad_host, no_header, bad_content_type, too_large, bad_json, bad_kind,
bad_model, bad_effort, bad_text, empty_text, text_too_long, bad_control, bad_value, rate_limited, error`; the UI
shows an i18n message per code and checks the UTF-8 body size (≤ 32 768 bytes, ≈ 10 900 CJK characters) before
posting.

### 18. Leaderboard (`#/leaderboard`, tab 排行榜 / Leaderboard)
Answers "where do our models stand against the baselines right now, and when did that change?"

**Sources** (no new parsers): validation series from `runs/<id>/metrics.jsonl` (the Training view's `RunMetrics`
reader), `runs/<id>/status.json`, `state/experiments.json` (family, name, status, GPU) and `results/summary.json`.
Run dirs that are not registered in `experiments.json`, `*_smoke`, `_*` and `_discarded` are skipped. Families are
normalised to `ours` (`novel` / `ours`, gold), `ablation` (violet, shown but **never** counted as a baseline),
`baseline` (blue) and `other`.

**Scopes and metrics**
- `live` (training-time validation, in-house val): `val_dice` (default), `val_hd95`, `val_dice_aux`, `val_dice_mean`.
  The value is the **best so far** (max for Dice, **min of the series** for HD95, so it can differ from
  `status.best.val_hd95`, which is recorded at the best-Dice epoch); `current` = last point; `best_epoch`.
  Each series has one point per epoch, sorted by epoch: a resumed run re-logs earlier epochs (`metrics.jsonl` is
  appended to), and the last point written for an epoch wins. The global step is used as x only when no point of the
  series carries an epoch (row `x_unit: "step"`, shown as 第 N 步 / step N; the 6-epoch trend window is then not
  applied); otherwise points without an epoch are dropped.
- `final` (`results/summary.json`): every dataset × metric with a mean or median (`stat=mean|median`, default
  dataset `inhouse_val`, metric `dice`); rows also carry `ci_low`, `ci_high`, `n`. Live ids map onto final ones
  (`val_dice` → `dice`, `val_hd95` → `hd95`).

**Verdict rule** (per row, against `B` = best baseline value among **counted** baselines that have one, i.e. done or
running; a running best baseline makes our verdicts `provisional` / 暂定). Runs whose `status.json` state or
`experiments.json` status is `failed`, `pruned`, `crashed`, `killed`, `error`, `aborted` or `cancelled` stay in the
table, greyed, with a 不计入 / not counted chip (`not_counted: true`, `rank: null`, `verdict: null`,
`is_best_baseline: false`): they never set `B`, take a rank, hold SOTA or produce new timeline events (events they
produced earlier stay). Final-scope rows (evaluated models) are always counted. Tolerance `tol` by metric type: Dice-like ratios default **0.003**
(clamped to 0–0.05), distances (unit mm or ids matching `hd|assd|asd|dist`) default **0.3 mm** (clamped to 0–5);
an invalid `tol` falls back to the default.

| Verdict | Higher-is-better (Dice) | Lower-is-better (HD95) |
|---|---|---|
| `ahead` 超越 | `v > B + tol` | `v < B − tol` |
| `tie` 持平 | `|v − B| ≤ tol` | `|v − B| ≤ tol` |
| `behind` 落后 | otherwise | otherwise |
| `sota` ★ SOTA | ranked **#1 of all rows** and `ahead` | same |

`delta` is signed so that **positive always means better than the best baseline**; `delta_sota` is the distance to
the #1 row. Verdicts are also computed for ablation / other rows (baseline rows have `verdict: null`). `trend`: `up`
(进步中) when the best is one of the last 3 validation points or `last_epoch − best_epoch < 6`; `flat` otherwise;
`final` for runs that are neither running nor queued. `crossings[run_id]` = first epoch at which the run reached
`tie` / `ahead` / `sota`, replayed against the **current** best baseline (the UI says 按当前最佳基线 / vs the current
best baseline).

**Change timeline** (server-side, persisted). At most every 5 s, triggered by `/api/leaderboard` or `/api/overview`
polls, the server replays each of our runs on `val_dice` and `val_hd95` at the default tolerance and appends to
`state/leaderboard_events.jsonl` one event per verdict change (`kind: "verdict"`, `from` → `to`, including tie → sota
in one step and losing SOTA) and one `kind: "improved"` (再进步) event whenever a run that is already tie / ahead /
SOTA improves its best by ≥ 0.002 Dice or ≥ 0.2 mm HD95. Event fields: `id` (dedupe key), `ts` (the historical
timestamp of the validation point, so back-fill is correct from day one), `kind, run_id, name, family, metric, epoch,
from, to, value, prev, baseline, baseline_id, provisional, tol, backfill, msg_zh, msg_en`. `state/leaderboard_state.json`
records, per run and metric, how many points were processed, a fingerprint of that prefix (x, value and ts of the
first and of the last processed point) and the last verdict, so restarts never duplicate events (ids are also checked
against the events file). When the fingerprint no longer matches (`metrics.jsonl` replaced, truncated or rewritten,
e.g. a run restarted under the same id) or the state file is lost or broken after events were recorded, the series is
rebuilt **silently** and at most one reconciling event is emitted (`ts = now`, `reset: true`), from the verdict the
timeline last showed (the stored one, or the last event of that run and metric) to the current one; no transition is
attributed to historical epochs. When the best baseline or the #1 rival changes without new points from our run, the
event gets `ts = now`. `backfill: true` marks reconstructed history only: events from the first replay of a series,
or from a validation point older than the previous timeline update (more than 60 s); live changes and `ts = now`
events have `backfill: false`. Lists are newest first; at equal `ts` verdict changes come before `improved` events
and `val_dice` before `val_hd95`. Upgrades **into `ahead` or `★ SOTA`**
are also appended to `state/events.jsonl` as `type: milestone, actor: leaderboard` (Overview feed, Events view);
downgrades and improvements are not. Events are only produced while some browser polls the dashboard, but nothing is
lost: the next poll back-fills with the original timestamps.

**UI**
- Controls: scope (实时验证 / 正式评估), metric, dataset + statistic (final scope), tolerance (number input; step and max
  follow the metric type; remembered per type), 只看我们的 vs 基线 / only ours vs baselines (hides ablation and other
  rows; client-side), 浏览器通知 / browser notifications.
- KPI strip: best baseline; our best (value, verdict chip, Δ); gap to SOTA / best baseline for our top running run
  (falls back to the best finished one); latest change.
- Table: rank badge, name with the gold `★ 我们的模型 / OURS` chip (violet ablation chip, `最佳基线 / best baseline`
  tag), status with epoch/total, progress bar and ETA, best (with its epoch), current, Δ (green / red / grey), verdict
  chip (`★ SOTA`, 超越 / Ahead, 持平 / Tie, 落后 / Behind; `暂定` suffix when provisional), trend, 90×22 sparkline.
  Clicking a row (or Enter) opens `#/training?run=<id>` with that run selected; final-scope rows open `#/results`
  with the same dataset / metric / statistic. At 390 px the table scrolls inside its card with a sticky first column.
- Race chart (ECharts): every run's best-so-far curve (toggle 历史最佳 / 每轮数值 for raw per-epoch values), dashed
  best-baseline line, dotted "ahead" line at `B ± tol`, shaded ±tol tie band, markers at our runs' first tie /
  ahead / SOTA epochs, x-axis zoom slider, `聚焦基线附近 / zoom to baseline` y-window toggle. In the final scope it is a
  ranked horizontal bar chart with the same reference lines. With 中位数 / median, a row without a median is ranked by
  its mean (`median_fallback: true`); the value gets a `†` and the table header shows the Results view's fallback chip.
- Change timeline: newest first, coloured by the new verdict, filterable by run.
- Notifications: an in-page toast for every new `ahead` / `sota` event (only events newer than the last one this
  browser saw and under 30 minutes old, so there is no backlog; only upgrades, not losing SOTA); with the toggle on and
  permission granted, also a system notification. Seen events are remembered by `id` as well as by time, so events
  that share a timestamp are not dropped; the Overview card checks the `recent_events` list (last 20) of
  `/api/overview.leaderboard`, not only `latest_event`.
- Overview card 赛况 / Race (`leaderboard` field of `/api/overview`): best baseline, one line per our run (value,
  verdict, Δ, trend), latest event, link to the leaderboard.
- `localStorage` keys: `an_lb_scope, an_lb_metric, an_lb_fmetric, an_lb_ds, an_lb_stat, an_lb_tol` (`{dice, hd}`),
  `an_lb_only, an_lb_focus, an_lb_curve, an_lb_notify, an_lb_seen_ts, an_lb_seen_ids`.

### 19. Data freshness and auto progress (`GET /api/freshness`)
Answers "how old is the data on this card, and should it be newer?".

**Sources and cadence classes** (15 rows; `updated` = the file's own `updated` field when present, else its mtime):

| Class | Sources | Stale rule |
|---|---|---|
| `live` (60 s; `runs` 180 s) | `runs` (newest of `metrics.jsonl`, `status.json`, `log.txt` of the runs), `events` (`state/events.jsonl`), `system` (NVML sample time), `session` (newest of the main transcript and the watcher heartbeat `state/session_watch.json`) | `runs`: stale only when a non-hidden **running** run has written nothing for > 180 s (`stale_runs`; some validation passes write nothing for about a minute), never while no run is running. `events`: `stale_rule: sporadic`, age shown, never stale. `session`: stale when both are older than 60 s |
| `event` | `results_summary` (`results/summary.json`), `experiments` (`state/experiments.json`), `leaderboard_events`, `run_eval` (`runs/*/eval/*_summary.json`) | never stale; shown with "updates when a run finishes / is evaluated" |
| `periodic` (2 h) | `briefing`, `session_status` | stale when older than 2 h |
| `manual` | `workflow` (12 h while a running phase still has manual progress), `paper` (12 h while phase `paper` or `refs` runs), `literature` (12 h while phase `literature` runs), `routing`, `cases` (`results/cases/index.json`, never) | stale only while a dependent phase runs (`depends_on`, `depends_running`) |

A missing file gives `missing: true, stale: false` (shown as 无数据 / no data, not as stale); a half-written file gives
`error` and falls back to its mtime. An `updated` field ≥ 5 s in the future (clock skew) is ignored: the mtime is used,
and the row carries `clock_skew_s` and an `error` note. `workflow` depends on every running phase whose progress is
still manual after the auto derivation (including an auto phase with nothing countable). Each row: `id, label_zh/en, path, updated, updated_from, mtime, age_s, cadence,
expected_max_age_s, stale_rule, stale, stale_reason, reason_zh/en (stale rows), missing, error, used_by[] (view.part),
hint_zh/en, detail, depends_on, depends_running`. The response adds `stale_ids, n_stale, tiles` (Overview tile → source
id), `rules` and `now`; it is cached 5 s and **read-only** (it never writes a file).

**Payload timestamps.** `/api/overview` gains `freshness {stale_ids, tiles, by_id, now}` and `workflow_updated`,
`experiments.updated`, `literature.updated`, `paper.updated`, `routing_updated`, `gpus_ts`, `best_dice.updated`;
`/api/results` gains `updated`, `cases_updated`; `/api/runs` and `/api/agents` gain `updated`.

**UI.**
- Every card title on every view carries a badge from one helper, `asOf(ts, cadence)`: `更新于 16:22 · 11 分钟前` /
  `as of 16:22 · 11 min ago` (`手动 · …` / `manual · …` for manual sources); amber `⚠ 可能过期 · …` / `may be stale` when
  the server flags the source, with a tooltip giving the source, its rhythm and the reason. The card's `data-src`
  names its source; `none` means no badge. The stale flag comes only from `/api/freshness` rows; the Overview's
  `freshness.stale_ids` is used only until the first `/api/freshness` answer (so a recovered source clears on every
  view). Without `/api/freshness` (older server) the badge falls back to the payload timestamps. Relative times refresh every 10 s.
- Overview: KPI tiles share one badge per source in the 数据时间 / Data as of strip under the tiles; a tile whose
  source is stale gets an amber outline. The best-Dice tile uses `inhouse_val` (else the first validation dataset;
  never a test split; the experiments.json fallback uses `metrics_summary.val_dice`, else other `val` Dice keys,
  never a `test` key nor the `aux` / `mean` variants), is labelled 最佳 Dice（院内验证 · 正式评估）, shows the `results/summary.json` time and one
  line such as `实时：N2 0.912 vs B1 0.910（持平）→` from `best_dice.live` (built from the same leaderboard result as
  `/api/overview.leaderboard`; client fallback: `leaderboard.top_ours` vs `best_baseline`), linking to `#/leaderboard`.
- System: card 数据源新鲜度 / Data freshness (source with hint and path, cadence, updated, age, state, used by), stale
  rows first, then rows without data; a header count of stale sources.
- Workflow: phases `train_base`, `train_novel`, `vjepa`, `evaluate`, `r2` get their progress from
  `state/experiments.json` in the `/api/workflow` payload only (`workflow.json` is never written). These phase ids and
  membership rules are the VS project's (`AUTO_PHASES`, `experiment_phase()`; rewrite them for a new project, see
  `../使用指南.md` §9):
  `progress = done / (done + running + queued)` (planned, pruned and failed do not count). r2 = config split
  `public_v3` or a baseline whose `data.cohorts` contain a non-inhouse cohort (takes priority); train_base = other
  baselines; vjepa = novel `V*`; train_novel = other novel runs (`T*`) and ablations (`N*`); evaluate = done runs
  with `eval_status.aggregate == ok` / all done runs. Config: `runs/<run_dir>/config.yaml`, else `runs/<id>/config.yaml`,
  else `configs/exp/<id>.yaml`. Each phase carries `progress_source: auto|manual`, `progress_manual`,
  `progress_auto {done, running, queued, total, members, rule}`; with nothing countable the file's value stays
  (`manual`). Each phase shows a small 自动 / 手动 tag (tooltip: counts and rule); the pipeline header counts them.
  `current_phase` stays from the file; `/api/health` and the Overview phases use the derived values.
- Training: `/api/runs` hides `_discarded`, `*_smoke` and other `_*` dirs (the leaderboard's exclusion rule) unless
  `?hidden=1` (`hidden` flag per run, `n_hidden`, `show_hidden`). The run list has a 显示隐藏运行 / show hidden runs
  toggle (`localStorage.an_tr_hidden`); hidden runs get a 隐藏 / hidden chip and stay reachable by id. `/api/overview`
  uses the same rule: `runs.total` / `runs.by_state` and the mini curves exclude hidden runs (`runs.n_hidden`).

Tests: `tests/test_freshness_api.py` (fixture `tests/make_freshness_fixture.py`, controlled mtimes and `updated`
fields: stale rules per cadence incl. the 2 h boundary, 5 s cache, auto progress against a synthetic registry, manual
fallback, hidden runs, half-written/missing files, empty root, bilingual reasons).

### Keyboard shortcuts, kiosk mode and link parameters

| Key | Action |
|---|---|
| `L` | switch 中文 / English |
| `K` | toggle kiosk mode (also the 大屏模式 / Kiosk header button) |
| `F` | full screen on / off |
| `+` / `=`, `-`, `0` | page zoom ±10 % (CSS `zoom` on `body`, 80–160 %, `localStorage.an_zoom`; status-bar pill, click = reset) |
| `1`–`9` | switch view (Overview=1, Workflow=2, Training=3, Results=4, Agents=5, Session=6, Literature=7, Paper=8, System=9; Leaderboard and Events have no digit) |
| `G` then `S` | open the Session view (`#/session`) |
| `G` then `B` | open the Leaderboard (`#/leaderboard`) |
| `?` | help overlay (`Esc` closes) |

Shortcuts are ignored while the focus is in an input / select / textarea / contenteditable element, or
when Ctrl / ⌘ / Alt is held.

**Kiosk mode** rotates overview → training → results → leaderboard → agents → workflow every 30 / 45 / 60 / 120 s
(select next to the button; `localStorage.an_kiosk`, `an_kiosk_int`). A thin bar under the tabs fills
until the next switch. Any click or key press pauses the rotation for 60 s (the bar turns amber and
shrinks), then it resumes. Rotation is driven by the existing 1 s clock tick; data polling stays at 4 s.

Hash parameters (bookmarkable): `#/overview?kiosk=45` (start kiosk, nearest of 30/45/60/120; `kiosk=0`
stops it), `?lang=en|zh` (force the language for this page load without saving it — handy for links and
screenshots), `#/results?ds=<dataset id>&metric=<metric id>&stat=mean|median` (written back while you
change those controls; `localStorage` stays the fallback), `#/leaderboard?scope=live|final&metric=<id>&ds=<dataset>&stat=mean|median&tol=<number>`,
`#/training?run=<run id>` (adds the run to the selection and focuses it), `#/events?type=milestone`, `#/session?lang=en`
(Session view), `?help=1`.

---

## API (read-only JSON except `POST /api/session/send`; GET leaderboard polls may append leaderboard state/events, §18; HTTP 200 with `{"ok": false, "error": …}` on bad data)

| Endpoint | Purpose |
|---|---|
| `GET /api/health` | `{"ok": true, "ts", "uptime_s", "phase"}` |
| `GET /api/overview` | KPIs, phases, mini curves of running runs, latest 15 events, last 12 milestones, routing, `briefing`, `alerts`, `queue` summary, `leaderboard` {metric, tol, best_baseline, sota, top_ours, ours[], latest_event}, `freshness` {stale_ids, tiles, by_id, now}, `best_dice` {dataset, updated, freshness_id, live, …} (§19) |
| `GET /api/briefing` | `state/briefing.json` (`{missing: true}` when absent) |
| `GET /api/alerts` | alert list (failed / stale / paused / disk / supervisor / recent milestones) + `n_running` |
| `GET /api/queue` | experiment queue per GPU lane with actual and projected times |
| `GET /api/workflow`, `/api/experiments`, `/api/routing` | state files (normalized); workflow phases carry `progress_source`, `progress_manual`, `progress_auto` (auto-derived progress, §19) |
| `GET /api/events?limit=&level=&actor=&type=` | events, newest first, plus actor/type lists |
| `GET /api/runs?hidden=0\|1` | runs with status, available series, sample counts, `hidden`, `n_hidden`, `show_hidden`, `updated` (`_discarded`, `*_smoke`, `_*` hidden unless `hidden=1`, §19) |
| `GET /api/runs/{id}/metrics?name=&split=&max_points=` | series (step[], epoch[], value[]), ≤ 2000 points |
| `GET /api/runs/{id}/log?lines=200` | tail of `log.txt` |
| `GET /api/runs/{id}/samples`, `/api/runs/{id}/samples/{file}` | sample list / image |
| `GET /api/results`, `/api/results/cases/{file}` | summary + cases index (`updated`, `cases_updated`) / case image |
| `GET /api/leaderboard?scope=live\|final&metric=&dataset=&stat=mean\|median&tol=` | ranked rows with verdicts (§18): `{ok, scope, metric, dataset, stat, hib, kind, tol, tol_default, tol_max, best_baseline {id, name, value, status, provisional}, sota {id, name, family, value, verdict, is_ours}, rows[] {run_id, name, family, family_raw, status, epoch, total_epochs, eta_s, value, current, best_epoch, delta, delta_sota, verdict, trend, rank, provisional, is_best_baseline, sparkline, sparkline_best, …; final scope also ci_low, ci_high, n, mean, median}, crossings, events (last 50), metrics[], datasets[], readonly, updated, now}`; cached 3 s per (scope, metric, dataset, stat, tol) |
| `GET /api/leaderboard/events?limit=200&run_id=` | leaderboard change events, newest first (`limit` 1–2000), `total`, `readonly` |
| `GET /api/freshness` | data-source freshness (§19): `{ok, sources[] {id, label_zh/en, path, updated, age_s, cadence, expected_max_age_s, stale, reason_zh/en, missing, used_by, …}, stale_ids, n_stale, tiles, rules, now}`; cached 5 s, read-only |
| `GET /api/literature` | papers |
| `GET /api/paper`, `/api/paper/figures/{file}`, `/api/paper/pdf` | paper status / figure / PDF |
| `GET /api/system` | GPUs, host (`disk_workspace` = disk of `disk_path`), training processes (secrets masked), extraction (`configured`), supervisor, `demo` |
| `GET /api/agents` | agent list + live activity strip; `root` = `$AN_TRANSCRIPTS` (null when unset) |
| `GET /api/agents/{id}/messages?since=<cursor>&limit=200` | incremental messages (`since=-1` returns the latest `limit`) |
| `GET /api/session` | main session: `session` {file, id, title, first_ts, last_ts, n_messages, n_tool_calls, active, model_seen, latest_seq}, `status` (`session_status.json`), `status_age_s`, `listening`, `heartbeat_age_s`, `watcher`, `ack`, `usage` {turns, assistant_messages, output_tokens_total, thinking_tokens_total, cache_read_total, cache_creation_total, input_tokens_total, last_context_tokens, last_model, last_ts}, `inbox_pending`, `transcripts_set` (false when neither `AN_TRANSCRIPTS` nor `AN_SESSION_FILE` is set), `now` (TTL-cached 2 s) |
| `GET /api/session/stream?after=<seq>&limit=200[&before=<seq>]` | transcript records + last 200 inbox messages with `state`; `cursor`, `latest_seq`, `first_seq`, `gap`, `more`, `more_before`, `reset` (true when `after` > `latest_seq`: restart from the tail) (same cursor semantics as the agents endpoint; `limit` 1–500); records may carry `meta: "meta"|"compact"` |
| `GET /api/session/inbox?limit=200` | inbox messages with state, `ack`, `listening`, `heartbeat_age_s`, `watcher`, `pending` |
| `POST /api/session/send` | **the only write endpoint**: body `{text, model, effort, kind, control, value}`, header `X-AN-Session: 1`, JSON only → `{ok, id, ts}` (appends to `state/session_inbox.jsonl`; see §17) |

Invalid query parameters (for example `?limit=abc`) also return HTTP 200 with
`{"ok": false, "error": "bad request: …"}`. Metric series are downsampled server-side to at most
2000 points (min/max per bucket, first and last point always kept).

File-serving endpoints only serve files inside their own directory (path traversal is rejected)
and only image types for samples and cases.

## Development and tests

Run from this `dashboard/` directory with the kit's venv (`PY=../.venv/bin/python`; on the VS machine it was
`/venv/main/bin/python`, and Node came from `. /opt/nvm/nvm.sh`). The whole demo is one command:
`bash ../demo/run_demo.sh`.

```bash
node --check static/app.js && node --check static/i18n.js
node tests/check_i18n.js            # zh/en key parity, placeholders, every referenced key defined
# render every view with SYNTHETIC data (numbers are random test data). The generators wipe their target first, so
# they only accept a new or empty directory or one they built before (marker .qichuang-demo-root; tests/_fixture_guard.py)
$PY -I tests/make_fixture.py /tmp/an_fixture
AN_ROOT=/tmp/an_fixture AN_DASH_PORT=17199 $PY -I server.py
# Session view: base fixture + synthetic 300-line transcript and session state files; also set AN_TRANSCRIPTS
$PY -I tests/make_session_fixture.py /tmp/an_fixture
AN_ROOT=/tmp/an_fixture AN_TRANSCRIPTS=/tmp/an_fixture/transcripts AN_DASH_PORT=17199 $PY -I server.py
# Leaderboard: base fixture + synthetic baselines / our runs / ablation (crossing, behind, queued, malformed lines)
$PY -I tests/make_leaderboard_fixture.py /tmp/an_fixture --merge
# Freshness / auto progress: on top of the base (+ leaderboard) fixture; --merge keeps the base gallery and adds design keys
$PY -I tests/make_freshness_fixture.py /tmp/an_fixture --merge
OMP_NUM_THREADS=1 $PY -m pytest tests/ -q   # 73 tests; every fixture is built in pytest's temporary directory
# a test instance on a REAL project root must not write leaderboard state:
AN_ROOT=/path/to/project AN_LEADERBOARD_READONLY=1 AN_DASH_PORT=17199 $PY -I server.py
```
Never POST test messages to the live server (port 17100): it appends to the real `state/session_inbox.jsonl`,
which wakes the orchestrator.
Rules for UI strings: every string must exist in both `I18N.zh` and `I18N.en` in `static/i18n.js`,
with the same `{placeholders}`.

The server keeps its thread use low (the sync thread pool is capped at 6, and BLAS/OMP threads
are set to 1) because some containers have a tight pids limit (the VS machine: 3840 tasks, threads included).

## Branding

`static/logo.svg` is the Qichuang Era (奇创纪元) company logo (vector paths cropped from the supplied Illustrator file, original colours, shown on a white plate in the header). The header title comes from the i18n keys `app_title` / `app_subtitle`; the browser-tab title from `title_fmt`.
