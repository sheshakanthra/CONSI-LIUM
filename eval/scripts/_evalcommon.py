"""Shared bootstrap for the eval scripts.

WHY a tiny shared module: all three runners (golden, RAGAS, fact-checker) need to
(a) put the FastAPI service package on ``sys.path`` and (b) load the same golden
set from the same place, whether they run from the repo (``eval/scripts/…``) or
inside the api container (files copied to ``/tmp``, code at ``/app``). Centralising
that here keeps the runners themselves about the eval logic, not path plumbing.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path


def bootstrap_api_path() -> str:
    """Ensure the api service package (app/, agents/, retrieval/) is importable.

    Resolution order: explicit ``CONSILIUM_API_DIR`` env, then the in-container
    ``/app`` layout, then the repo-relative ``apps/api``. Returns the dir used.
    """
    api_dir = os.environ.get("CONSILIUM_API_DIR")
    if not api_dir:
        if os.path.isdir("/app/agents"):
            api_dir = "/app"
        else:
            api_dir = str(Path(__file__).resolve().parents[2] / "apps" / "api")
    if api_dir not in sys.path:
        sys.path.insert(0, api_dir)
    return api_dir


def golden_set_path(explicit: str | None = None) -> Path:
    """Locate golden_set.json (flag > env > next-to-this-file > /tmp copy)."""
    for candidate in (
        explicit,
        os.environ.get("CONSILIUM_GOLDEN_SET"),
        str(Path(__file__).resolve().parents[1] / "golden_set" / "golden_set.json"),
        "/tmp/golden_set.json",
    ):
        if candidate and Path(candidate).is_file():
            return Path(candidate)
    raise FileNotFoundError(
        "golden_set.json not found; pass --golden-set or set CONSILIUM_GOLDEN_SET"
    )


def load_entries(explicit: str | None = None) -> list[dict]:
    data = json.loads(golden_set_path(explicit).read_text(encoding="utf-8"))
    return data["entries"]
