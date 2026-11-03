"""Test-only server: isolate new render outputs while reusing the real FastAPI app."""

from __future__ import annotations

import os
from pathlib import Path

import backend.app.main as application_module


root = os.environ.get("WEB08B_OUTPUT_ROOT")
if not root:
    raise RuntimeError("WEB08B_OUTPUT_ROOT is required for the isolated QA server")
output_root = Path(root).resolve()
if not output_root.is_relative_to(application_module.PROJECT_ROOT / "temporary"):
    raise RuntimeError("WEB08B_OUTPUT_ROOT must be inside the ignored temporary directory")
application_module.PROJECT_RENDER_OUTPUT_DIRECTORY = output_root
app = application_module.app
