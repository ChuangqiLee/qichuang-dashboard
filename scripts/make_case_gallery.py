"""Qualitative case gallery v1 (output contract: dashboard/README.md §7).

REFERENCE ONLY. This is the generator of the project the dashboard was first built for (MRI segmentation): it needs
that project's `anvs` package, its data cache and T1 MRI files, and will not run anywhere else. Keep it as an example
of producing results/cases/index.json + PNGs; the dashboard itself only reads those files. The run ids in MODELS
and REF_RUN are placeholders.
PATIENT DATA: the PNGs and index entries are derived from patient scans. Use pseudonymous case ids only, never put
hospital / accession / MRN numbers into images or file names, and never copy results/cases/ or runs/*/samples/ into
the kit, git or a demo.

    python scripts/make_case_gallery.py --stage select   # pick 8 in-house VAL cases -> results/cases/_work/
    python scripts/make_case_gallery.py --stage eval     # anvs.evaluate --save-pred per model (sequential)
    python scripts/make_case_gallery.py --stage render   # PNG per case + results/cases/index.json
    python scripts/make_case_gallery.py --stage all

Selection: the in-house ``val`` split built through ``anvs.data.datasets.build_dataset`` with the data block of
``runs/<REF_RUN>/config.yaml``; cases with an empty / missing T1 reference label are excluded; GT volume = the T1
reference label volume on the original grid (``mask_vol_ml_orig`` of the cache index). Strata: small = volume
<= 25th percentile, large = >= 75th percentile, medium = in between; 2 / 4 / 2 cases drawn with
``numpy.random.default_rng(2026)`` (ids sorted before drawing, so the draw is reproducible).

Evaluation (``--stage eval``): the arguments of ``python -m anvs.evaluate --run runs/<id> --cohort inhouse_val --case-ids <file>
--save-pred --oom cpu --workers 0 --out-dir results/cases/_eval/<id>`` with ``CUDA_VISIBLE_DEVICES=0``,
``ANVS_GPU_MEM_FRAC=0.15`` and 4 OMP threads, run through ``anvs.evaluate.main`` in a child process that first caps
the CUDA allocator (``torch.cuda.set_per_process_memory_fraction``; anvs.evaluate does not read the variable). ``--out-dir`` keeps the 8-case CSV/summary away from the formal
``runs/<id>/eval/inhouse_val_*`` files (which the default output dir would overwrite). Predictions (``ref`` output =
T1-style mask on the original T1 grid) land in ``results/cases/_eval/<id>/pred_inhouse_val/<case>_ref.nii.gz``.

Render: per case one 1 x (1 + N) panel -- T1 slice (original grid, reoriented to the closest canonical RAS frame and
shown in radiological convention) through the GT centroid along the slice (thickest-spacing) axis, cropped around
the tumour; panel 0 = GT contour (white), panel k = GT (white) + model k contour (gold shades = ours,
blue = baseline) with the model's case Dice (``ref`` output, original grid, from the gallery eval CSV) in the
title. 150 dpi, <= 400 KB. ``index.json`` entries carry both the README §7 keys (``file``, ``case_id``,
``dataset``, ``caption_zh``, ``caption_en``) and the design keys (``id``, ``title_zh``, ``title_en``, ``image``,
``dice``, ``note``).
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
CASES = ROOT / "results" / "cases"
WORK = CASES / "_work"
EVAL = CASES / "_eval"
SEED = 2026
COHORT = "inhouse_val"
TAG = "inhouse_val"

#: (run id, short label, colour, family). Gold shades = ours, blue = baseline (dashboard convention).
#: Placeholders: put your own evaluated run ids here.
MODELS = [
    ("N1_ours", "N1 Ours", "#fbbf24", "ours"),
    ("N2_ours_variant", "N2 Ours (variant)", "#fde68a", "ours"),
    ("N3_ours_alt", "N3 Ours (alt.)", "#d97706", "ours"),
    ("B1_baseline", "B1 Baseline", "#60a5fa", "baseline"),
]
REF_RUN = "B1_baseline"   # placeholder: a run whose config.yaml `data:` block defines the validation split
STRATA = (("small", 2), ("medium", 4), ("large", 2))
STRATUM_ZH = {"small": "小", "medium": "中", "large": "大"}


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _dataset(case_ids: Optional[List[str]] = None):
    import yaml

    from anvs.data.datasets import build_dataset

    cfg = yaml.safe_load(open(ROOT / "runs" / REF_RUN / "config.yaml"))
    d = dict(cfg["data"])
    if case_ids:
        d["case_ids"] = list(case_ids)
    return build_dataset(d, "val", train=False)


def model_available(run_id: str) -> bool:
    rd = ROOT / "runs" / run_id
    if not (rd / "ckpt_best.pt").is_file():
        return False
    try:
        return json.loads((rd / "status.json").read_text()).get("state") == "done"
    except Exception:
        return False


# ------------------------------------------------------------------ select
def stage_select() -> Dict[str, Any]:
    ds = _dataset()
    rows = []
    for it in ds.items:
        ref = it["ref"]
        if str(ref.get("has_mask")) != "True":
            continue
        try:
            v = float(ref.get("mask_vol_ml_orig") or ref.get("mask_vol_ml"))
        except (TypeError, ValueError):
            continue
        if not np.isfinite(v) or v <= 0:
            continue
        rows.append({"case_id": it["case_id"], "vol_ml": v, "site": ref.get("site", ""),
                     "has_aux": it.get("aux") is not None})
    vols = np.array([r["vol_ml"] for r in rows])
    q25, q75 = (float(x) for x in np.percentile(vols, [25, 75]))
    for r in rows:
        r["stratum"] = "small" if r["vol_ml"] <= q25 else ("large" if r["vol_ml"] >= q75 else "medium")
    rng = np.random.default_rng(SEED)
    picked: List[Dict[str, Any]] = []
    for st, k in STRATA:
        pool = sorted((r for r in rows if r["stratum"] == st), key=lambda r: r["case_id"])
        idx = sorted(rng.choice(len(pool), size=k, replace=False).tolist())
        picked.extend(pool[i] for i in idx)
    WORK.mkdir(parents=True, exist_ok=True)
    (WORK / "case_ids.txt").write_text("\n".join(r["case_id"] for r in picked) + "\n")
    sel = {"updated": now_iso(), "seed": SEED, "split": "inhouse val (inhouse_v1)", "n_val_labelled": len(rows),
           "q25_ml": q25, "q75_ml": q75, "rule": "small <= q25 < medium < q75 <= large; 2/4/2 per stratum",
           "cases": picked}
    (WORK / "selection.json").write_text(json.dumps(sel, indent=1))
    print(json.dumps(sel, indent=1))
    return sel


# ------------------------------------------------------------------ eval
def stage_eval(models: List[str]) -> None:
    env = dict(os.environ, CUDA_VISIBLE_DEVICES="0", ANVS_GPU_MEM_FRAC="0.15", OMP_NUM_THREADS="4",
               MKL_NUM_THREADS="4", OPENBLAS_NUM_THREADS="4", ANVS_EVAL_THREADS="4",
               PYTHONPATH=str(ROOT / "src") + os.pathsep + os.environ.get("PYTHONPATH", ""))
    for run_id in models:
        if not model_available(run_id):
            print(f"[gallery] skip {run_id}: no ckpt_best.pt / not done", flush=True)
            continue
        out = EVAL / run_id
        out.mkdir(parents=True, exist_ok=True)
        cmd = [sys.executable, "-I", str(Path(__file__).resolve()), "--stage", "_evalchild", "--", "--run", str(ROOT / "runs" / run_id), "--cohort", COHORT,
               "--case-ids", str(WORK / "case_ids.txt"), "--save-pred", "--oom", "cpu", "--workers", "0",
               "--out-dir", str(out)]
        print("[gallery] " + " ".join(cmd), flush=True)
        t0 = time.time()
        with open(out / "gallery_eval_log.txt", "w") as log:
            r = subprocess.run(cmd, cwd=str(ROOT), env=env, stdout=log, stderr=subprocess.STDOUT)
        print(f"[gallery] {run_id}: exit {r.returncode} in {time.time() - t0:.0f}s", flush=True)
        if r.returncode != 0:
            raise SystemExit(f"evaluation of {run_id} failed; see {out / 'gallery_eval_log.txt'}")


def eval_child(argv: List[str]) -> int:
    """``python -m anvs.evaluate <argv>`` with the CUDA allocator capped at ``ANVS_GPU_MEM_FRAC`` first
    (anvs.evaluate itself does not read that variable)."""
    import torch

    if torch.cuda.is_available():
        torch.cuda.set_per_process_memory_fraction(float(os.environ.get("ANVS_GPU_MEM_FRAC", "0.15")), 0)
    from anvs.evaluate import main as ev_main

    return int(ev_main(list(argv)) or 0)


# ------------------------------------------------------------------ render
def _contour(ax, m2d: np.ndarray, color: str, lw: float) -> None:
    if m2d.any():
        ax.contour(m2d.astype(float), levels=[0.5], colors=[color], linewidths=lw)


def _case_dice(run_id: str) -> Dict[str, float]:
    p = EVAL / run_id / f"{TAG}_cases.csv"
    out: Dict[str, float] = {}
    if p.is_file():
        for r in csv.DictReader(open(p)):
            if r.get("output") == "ref":
                try:
                    out[r["case_id"]] = float(r["dice"])
                except (TypeError, ValueError):
                    pass
    return out


def _dice(a: np.ndarray, b: np.ndarray) -> float:
    s = a.sum() + b.sum()
    return float("nan") if s == 0 else float(2.0 * np.logical_and(a, b).sum() / s)


def stage_render() -> List[Dict[str, Any]]:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import nibabel as nib

    from anvs.data.cache import build_jobs, load_original_mask

    sel = json.loads((WORK / "selection.json").read_text())
    ids = [c["case_id"] for c in sel["cases"]]
    info = {c["case_id"]: c for c in sel["cases"]}
    ds = _dataset(ids)
    samples = {ds.items[i]["case_id"]: i for i in range(len(ds))}
    img_path = {j["case_id"]: j["image_path"] for j in build_jobs("inhouse")
                if j["seq_file"] == "T1w_IR" and j["case_id"] in info}
    models = [m for m in MODELS if (EVAL / m[0] / f"pred_{TAG}").is_dir()]
    skipped = [m[0] for m in MODELS if m not in models]
    dice_csv = {m[0]: _case_dice(m[0]) for m in models}
    entries: List[Dict[str, Any]] = []
    for cid in ids:
        s = ds[samples[cid]]
        gt_raw, aff = load_original_mask(s, "ref")
        img_nii = nib.load(img_path[cid])
        if np.abs(img_nii.affine - aff).max() > 1e-3 or tuple(img_nii.shape[:3]) != gt_raw.shape:
            raise SystemExit(f"{cid}: T1 image grid does not match the label grid")
        ornt = nib.orientations.io_orientation(aff)

        def canon(a: np.ndarray) -> np.ndarray:
            return nib.orientations.apply_orientation(np.asarray(a), ornt)

        img = canon(np.asarray(img_nii.dataobj, dtype=np.float32)[..., 0] if img_nii.ndim == 4
                    else np.asarray(img_nii.dataobj, dtype=np.float32))
        gt = canon(gt_raw.astype(bool))
        sp = np.sqrt((aff[:3, :3] ** 2).sum(0))[np.argsort(ornt[:, 0])]  # spacing in canonical axis order
        preds: Dict[str, np.ndarray] = {}
        dice: Dict[str, float] = {}
        for run_id, *_ in models:
            pn = nib.load(str(EVAL / run_id / f"pred_{TAG}" / f"{cid}_ref.nii.gz"))
            pr_raw = np.asarray(pn.dataobj) > 0
            preds[run_id] = canon(pr_raw)
            d_csv = dice_csv[run_id].get(cid)
            d_own = _dice(pr_raw, gt_raw)
            if d_csv is not None and abs(d_csv - d_own) > 1e-4:
                raise SystemExit(f"{cid} {run_id}: CSV Dice {d_csv:.5f} != recomputed {d_own:.5f}")
            dice[run_id] = round(d_own if d_csv is None else d_csv, 4)
        ax_s = int(np.argmax(sp))  # slice axis = thickest spacing
        inpl = [a for a in range(3) if a != ax_s]
        com = np.array(np.nonzero(gt)).mean(1)
        k = int(round(com[ax_s]))
        if not np.take(gt, k, axis=ax_s).any():  # centroid slice without label (curved tumour): largest-area slice
            k = int(np.argmax(gt.sum(axis=tuple(inpl))))

        def sl(a: np.ndarray) -> np.ndarray:
            # rows = second in-plane axis (anterior/superior up via origin='lower'), cols = first in-plane axis,
            # flipped left-right for radiological convention (patient right on the viewer's left)
            return np.take(a, k, axis=ax_s).T[:, ::-1]

        # crop: square window of max(60 mm, 2.2 x tumour extent) around the in-plane centroid
        nz = np.array(np.nonzero(gt))
        ext_mm = max(float((nz[a].max() - nz[a].min() + 1) * sp[a]) for a in inpl)
        half_mm = max(30.0, 1.1 * ext_mm)
        shape2 = sl(img).shape  # (n_rows, n_cols)
        c_col = shape2[1] - 1 - com[inpl[0]]
        c_row = com[inpl[1]]
        hc, hr = half_mm / sp[inpl[0]], half_mm / sp[inpl[1]]
        c0, c1 = int(max(0, c_col - hc)), int(min(shape2[1], c_col + hc))
        r0, r1 = int(max(0, c_row - hr)), int(min(shape2[0], c_row + hr))
        im2 = sl(img)[r0:r1, c0:c1]
        lo, hi = np.percentile(im2, [1, 99.5])
        aspect = float(sp[inpl[1]] / sp[inpl[0]])
        n = 1 + len(models)
        fig, axes = plt.subplots(1, n, figsize=(2.25 * n, 2.85), dpi=150, facecolor="#04080f")
        for j, ax in enumerate(np.atleast_1d(axes)):
            ax.imshow(im2, cmap="gray", vmin=lo, vmax=hi, origin="lower", aspect=aspect, interpolation="bilinear")
            _contour(ax, sl(gt)[r0:r1, c0:c1], "#ffffff", 1.0)
            if j == 0:
                title = f"T1 + GT  {info[cid]['vol_ml']:.2f} mL"
                col = "#d7e3f4"
            else:
                run_id, lab, colr, _fam = models[j - 1]
                _contour(ax, sl(preds[run_id])[r0:r1, c0:c1], colr, 1.3)
                title = f"{lab}\nDice {dice[run_id]:.3f}"
                col = colr
            ax.set_title(title, color=col, fontsize=7.5, pad=3)
            ax.set_xticks([])
            ax.set_yticks([])
            for spn in ax.spines.values():
                spn.set_color("#16263f")
        # no case id in the image itself (images get copied around); it stays in index.json only
        fig.suptitle(f"{info[cid]['stratum']} · slice {k + 1}/{gt.shape[ax_s]}  (white = GT)",
                     color="#8296b3", fontsize=7, y=0.985)
        fig.tight_layout(rect=(0, 0, 1, 0.93), pad=0.4, w_pad=0.3)
        CASES.mkdir(parents=True, exist_ok=True)
        out_png = CASES / f"{cid}.png"
        fig.savefig(out_png, dpi=150, facecolor=fig.get_facecolor())
        plt.close(fig)
        kb = out_png.stat().st_size / 1024
        if kb > 400:
            raise SystemExit(f"{out_png} is {kb:.0f} KB > 400 KB")
        st = info[cid]["stratum"]
        best = max(dice, key=dice.get) if dice else None
        dz = " · ".join(f"{m[0].split('_')[0]} {dice[m[0]]:.3f}" for m in models)
        note = (f"stratum={st}; GT {info[cid]['vol_ml']:.2f} mL; slice {k + 1}/{gt.shape[ax_s]} through the GT "
                f"centroid; Dice = ref output on the original T1 grid (gallery eval, ckpt_best)"
                + (f"; skipped: {', '.join(skipped)}" if skipped else ""))
        entries.append({
            "id": cid, "case_id": cid, "dataset": "inhouse_val", "file": out_png.name, "image": out_png.name,
            "title_zh": f"{cid} · {STRATUM_ZH[st]}肿瘤（{info[cid]['vol_ml']:.2f} mL）",
            "title_en": f"{cid} · {st} tumour ({info[cid]['vol_ml']:.2f} mL)",
            "caption_zh": f"{STRATUM_ZH[st]}肿瘤 {info[cid]['vol_ml']:.2f} mL；Dice：{dz}（白=金标准，金色=我们的模型，蓝=基线）",
            "caption_en": f"{st} tumour {info[cid]['vol_ml']:.2f} mL; Dice: {dz} (white = GT, gold = ours, blue = baseline)",
            "dice": dice, "best_model": best, "gt_volume_ml": round(info[cid]["vol_ml"], 3), "stratum": st,
            "slice_index": k, "note": note})
        print(f"[gallery] {out_png.name} {kb:.0f} KB dice={dice}", flush=True)
    tmp = CASES / "index.json.tmp"
    tmp.write_text(json.dumps(entries, ensure_ascii=False, indent=1))
    os.replace(tmp, CASES / "index.json")
    return entries


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--stage", default="all", choices=["select", "eval", "render", "all", "_evalchild"])
    ap.add_argument("--models", default=",".join(m[0] for m in MODELS))
    argv = sys.argv[1:]
    rest: List[str] = []
    if "--" in argv:
        i = argv.index("--")
        argv, rest = argv[:i], argv[i + 1:]
    a = ap.parse_args(argv)
    if a.stage == "_evalchild":
        return eval_child(rest)
    models = [m for m in a.models.split(",") if m]
    if a.stage in ("select", "all"):
        stage_select()
    if a.stage in ("eval", "all"):
        stage_eval(models)
    if a.stage in ("render", "all"):
        stage_render()
    return 0


if __name__ == "__main__":
    sys.exit(main())
