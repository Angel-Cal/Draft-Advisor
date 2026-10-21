"""Run manifest and freshness checks: which code and params produced the current outputs, and are they stale."""

import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from src.data.validate import DataIntegrityError, _warn

ROOT = Path(__file__).parent.parent.parent
MANIFEST_PATH = ROOT / "data" / "processed" / "run_manifest.json"
PARAM_FILES = ["qb_params", "rb_params", "wr_params", "te_params"]


def _git(*args):
    try:
        return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, check=True).stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None


def params_checksums():
    out = {}
    for name in PARAM_FILES:
        path = ROOT / "models" / name
        out[name] = hashlib.md5(path.read_bytes()).hexdigest()[:12] if path.exists() else None
    return out


def update_manifest(stage, info):
    """Record a pipeline stage (pipeline, predict, ...) with the commit, timestamp and params that produced it."""
    manifest = json.loads(MANIFEST_PATH.read_text()) if MANIFEST_PATH.exists() else {}
    manifest[stage] = {
        **info,
        "timestamp_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "git_commit": _git("rev-parse", "--short", "HEAD"),
        "uncommitted_changes": bool(_git("status", "--porcelain", "--", "src", "tests")),
        "params_md5": params_checksums(),
    }
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2, default=str))


def check_freshness(inputs, outputs, label, strict=True):
    """Every output must be at least as new as every input; otherwise it was built from older data."""
    missing = [str(p) for p in [*inputs, *outputs] if not Path(p).exists()]
    if missing:
        raise DataIntegrityError(f"[freshness:{label}] missing files {missing}")
    newest_input = max(Path(p).stat().st_mtime for p in inputs)
    stale = [Path(p).name for p in outputs if Path(p).stat().st_mtime < newest_input]
    if stale:
        message = f"outputs older than their inputs (rerun the producing step): {stale}"
        if strict:
            raise DataIntegrityError(f"[freshness:{label}] {message}")
        _warn(message, f"freshness:{label}")
