# Copyright 2026 Anthropic PBC
# SPDX-License-Identifier: Apache-2.0

"""Export deterministic OpenAPI contracts for APIMatic and other API tooling.

    python scripts/export_openapi.py
    python scripts/export_openapi.py --vertical retail

Each output uses APIMatic's project layout (``<vertical>/src/spec/openapi.json``),
so it can be validated or used for SDK generation without copying files around.
"""

from __future__ import annotations

import argparse
import importlib
import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
EXAMPLES_ROOT = REPO_ROOT / "examples"
DEFAULT_OUTPUT = REPO_ROOT / "integrations" / "apimatic"
VERTICALS = ("retail", "travel", "telecom", "entertainment")


def export_contract(vertical: str, output_root: Path) -> Path:
    """Load a vertical's actual FastAPI app and export the schema it serves."""
    sys.path.insert(0, str(EXAMPLES_ROOT)) if str(EXAMPLES_ROOT) not in sys.path else None
    module = importlib.import_module(f"{vertical}.api.main")
    schema: dict[str, Any] = module.app.openapi()
    schema["info"]["description"] = (
        f"{schema['info'].get('description', '').strip()}\n\n"
        "Generated from the running commerce-agent FastAPI routes for APIMatic validation, "
        "SDK generation, and documentation. X-Session-Id is an opaque host session identifier."
    ).strip()
    schema["servers"] = [
        {
            "url": f"http://localhost:{8000 + VERTICALS.index(vertical)}",
            "description": "Local demo",
        }
    ]

    destination = output_root / vertical / "src" / "spec" / "openapi.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(schema, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return destination


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vertical", choices=(*VERTICALS, "all"), default="all")
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    selected = VERTICALS if args.vertical == "all" else (args.vertical,)
    for vertical in selected:
        destination = export_contract(vertical, args.output_root.resolve())
        print(f"{vertical}: {destination.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
