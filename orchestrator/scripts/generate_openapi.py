#!/usr/bin/env python
"""Generate the orchestrator's OpenAPI document from the running application (T030).

The application is the source of runtime truth: this reads the live FastAPI router rather
than a hand-maintained description, so the generated artifact cannot drift from what the
service actually serves.

    python scripts/generate_openapi.py [output_path]
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.api.app import app

DEFAULT_OUTPUT = Path(__file__).resolve().parents[2] / "docs" / "contracts" / "orchestrator-openapi.json"


def generate(output: Path) -> dict:
    spec = app.openapi()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(spec, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return spec


if __name__ == "__main__":
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_OUTPUT
    document = generate(target)
    print(f"wrote {target} ({len(document['paths'])} paths)")
