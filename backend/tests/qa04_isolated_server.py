"""QA-04 test-only server: the real FastAPI app with isolated DB, sources and outputs.

Refuses to start unless every write target is isolated:
- QA04_ROOT inside the git-ignored ``temporary/`` directory (sources/ and outputs/ below it)
- POSTGRES_PORT 55432 and POSTGRES_DB starting with ``cutory_qa04_``
The STT model is not loaded (rendering does not need it).
"""

from __future__ import annotations

import os
from pathlib import Path

import backend.app.main as application_module

root_value = os.environ.get("QA04_ROOT")
if not root_value:
    raise RuntimeError("QA04_ROOT is required for the isolated QA-04 server")
root = Path(root_value).resolve()
if not root.is_relative_to(application_module.PROJECT_ROOT / "temporary"):
    raise RuntimeError("QA04_ROOT must be inside the ignored temporary directory")
if os.environ.get("POSTGRES_PORT") != "55432" or not os.environ.get("POSTGRES_DB", "").startswith("cutory_qa04_"):
    raise RuntimeError("QA-04 server only runs against an isolated cutory_qa04_* database on port 55432")

application_module.PRODUCT_SOURCE_DIRECTORY = root / "sources"
application_module.PRODUCT_TEMPORARY_DIRECTORY = root / "work"
application_module.PROJECT_RENDER_OUTPUT_DIRECTORY = root / "outputs"
application_module.load_model = lambda: object()
app = application_module.app
