"""Safety guard shared by the fixture generators (make_*_fixture.py) and demo/demo_extras.py.

Those scripts wipe or overwrite the directory they are given, so a target is accepted only when
  * it does not exist yet, is empty, or carries the marker file MARKER (written after every build by the
    generators and by demo/run_demo.sh), and
  * it is not "/", $HOME, the directory that holds this dashboard (the kit, or the project the dashboard was
    copied into), $AN_ROOT or $AN_REAL_ROOT; it is not inside one of the last three; and it does not contain
    any of them.
So `python -I dashboard/tests/make_fixture.py ~/myproject` stops with a message instead of deleting a project.
Fresh temporary directories (pytest's tmp_path) and rebuilds of an earlier fixture / demo directory still work.
"""
from __future__ import annotations

import os
from pathlib import Path

MARKER = ".qichuang-demo-root"
# <base>/dashboard/tests/_fixture_guard.py -> <base>: the kit root, or the project that holds a copied dashboard/
BASE = Path(__file__).resolve().parents[2]


class UnsafeTarget(SystemExit):
    """A refused target. A SystemExit, so a command-line run prints the reason (exit 1) without a traceback."""


def _real(p) -> Path:
    return Path(os.path.realpath(os.path.expanduser(str(p))))


def protected() -> list[tuple[str, Path, bool]]:
    """(label, resolved path, also refuse anything inside it) for every directory a fixture must never replace"""
    out = [("the file system root", Path("/"), False)]
    home = os.environ.get("HOME", "").strip()
    if home:
        out.append(("$HOME", _real(home), False))
    out.append(("the directory that holds this dashboard", _real(BASE), True))
    for var in ("AN_REAL_ROOT", "AN_ROOT"):
        v = os.environ.get(var, "").strip()
        if v:
            out.append((f"${var}", _real(v), True))
    return out


def check(target) -> Path:
    """Return the resolved target, or raise UnsafeTarget when wiping / overwriting it could destroy real data."""
    t = _real(target)
    for label, p, refuse_inside in protected():
        if t == p or t in p.parents:
            raise UnsafeTarget(f"refusing to use {t} as a fixture directory: it is or contains {label} ({p})")
        if refuse_inside and p in t.parents:
            raise UnsafeTarget(f"refusing to use {t} as a fixture directory: it is inside {label} ({p})")
    if t.exists() and not t.is_dir():
        raise UnsafeTarget(f"refusing to use {t} as a fixture directory: it exists and is not a directory")
    if t.is_dir() and any(t.iterdir()) and not (t / MARKER).is_file():
        raise UnsafeTarget(f"refusing to wipe or overwrite {t}: it is not empty and has no {MARKER} marker "
                           "(use a new or empty directory, or one built earlier by these generators)")
    return t


def mark(target) -> None:
    """Mark `target` as synthetic data built by the kit, so a later rebuild may wipe it."""
    p = Path(target)
    p.mkdir(parents=True, exist_ok=True)
    (p / MARKER).write_text("synthetic dashboard test / demo data (dashboard/tests generators, demo/run_demo.sh); "
                            "safe to delete\n", encoding="utf-8")
