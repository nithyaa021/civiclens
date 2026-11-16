"""Idempotent first-boot bootstrap for hosted deployments (Render/Railway).

    python scripts/bootstrap_deploy.py

On a fresh environment the database is empty and the trained model artifacts are
missing, so the API would answer with empty dashboards and 503s from the AI
endpoints.  This script makes a deploy self-contained:

1. if the ``complaints`` collection already has documents, it does nothing to
   the data (safe to run on every boot);
2. otherwise it seeds the deterministic benchmark corpus;
3. it installs the deterministic model artifacts bundled in
   ``app/data/models`` (or trains them if a configured path is missing and no
   bundled copy exists);
4. it warms the local ONNX caches that the worker needs (embeddings are loaded
   lazily, so this is best-effort).

Set ``CIVICLENS_FORCE_BOOTSTRAP=1`` to reseed and retrain from scratch (useful
after changing the corpus).  Set ``CIVICLENS_SKIP_BOOTSTRAP=1`` to force a no-op
when the data lives in a managed cluster seeded out of band.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

from pymongo.errors import DuplicateKeyError  # noqa: E402

from app.core.config import get_settings  # noqa: E402
from app.db.sync_mongo import get_sync_database  # noqa: E402

LOCK_ID = "bootstrap"
LOCK_WAIT_SECONDS = 900
BUNDLED_MODELS = BACKEND_ROOT / "app" / "data" / "models"


def _run(script: str, *extra: str) -> None:
    command = [sys.executable, str(BACKEND_ROOT / "scripts" / script), *extra]
    print(f"\n$ {' '.join(command)}", flush=True)
    result = subprocess.run(command, check=False)
    if result.returncode != 0:
        raise SystemExit(f"{script} failed with exit code {result.returncode}")


def _ensure_seeded(db) -> None:
    """Seed the corpus exactly once, even if the API and worker boot together."""
    if db["complaints"].estimated_document_count():
        print(f"Database already has {db['complaints'].estimated_document_count()} complaints.")
        return
    try:
        db["deploy_state"].insert_one(
            {"_id": LOCK_ID, "started_at": datetime.now(UTC)}
        )
    except DuplicateKeyError:
        # Another process is seeding; wait for it to publish complaints.
        deadline = time.monotonic() + LOCK_WAIT_SECONDS
        print("Another process holds the bootstrap lock; waiting for the corpus...")
        while time.monotonic() < deadline:
            if db["complaints"].estimated_document_count():
                print("Corpus available.")
                return
            time.sleep(5)
        raise SystemExit("Timed out waiting for the bootstrap lock holder.") from None
    try:
        _run("seed_dataset.py", "--reset")
    finally:
        db["deploy_state"].delete_one({"_id": LOCK_ID})


def _ensure_models(settings, force: bool) -> None:
    """Install bundled artifacts, falling back to training when needed."""
    targets = {
        "category_classifier.joblib": Path(settings.models_dir)
        / "category_classifier.joblib",
        "resolution_comparator.joblib": Path(settings.resolution_model_path),
        "forecast_xgb.joblib": Path(settings.forecast_model_path),
    }
    if not force and all(path.exists() for path in targets.values()):
        print(f"Model artifacts present in {settings.models_dir} -> training skipped.")
        return

    if not force:
        copied: list[str] = []
        for name, target in targets.items():
            source = BUNDLED_MODELS / name
            if not target.exists() and source.exists():
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)
                copied.append(name)
        if copied:
            print(f"Installed bundled model artifacts: {', '.join(copied)}")
        if all(path.exists() for path in targets.values()):
            return

    print("Model artifacts missing -> training on the seeded corpus.")
    _run("train_models.py")


def main() -> int:
    if os.environ.get("CIVICLENS_SKIP_BOOTSTRAP") == "1":
        print("CIVICLENS_SKIP_BOOTSTRAP=1 -> skipping bootstrap.")
        return 0

    settings = get_settings()
    db = get_sync_database()
    force = os.environ.get("CIVICLENS_FORCE_BOOTSTRAP") == "1"

    if force:
        _run("seed_dataset.py", "--reset")
    else:
        _ensure_seeded(db)

    _ensure_models(settings, force)

    print("\nBootstrap complete.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())