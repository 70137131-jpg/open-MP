#!/usr/bin/env python3
"""Generate ``static/js/examples.data.js`` from ``examples/``.

The page bundles the catalogue so the examples still work when it is served
statically and the API is cold or unreachable; the API copy wins whenever
``GET /examples`` succeeds. Run this after editing anything under ``examples/``:

    python3 scripts/build_examples.py

``--check`` verifies the generated file is current without writing (used by CI
and by ``tests/test_examples.py``).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.examples import catalogue  # noqa: E402

OUTPUT = Path(__file__).resolve().parent.parent / "static" / "js" / "examples.data.js"

HEADER = """/* AUTO-GENERATED - do not edit.
 * Source: examples/manifest.json + examples/*.c|cpp
 * Regenerate: python3 scripts/build_examples.py
 */
"""


def render() -> str:
    payload = json.dumps(catalogue(), indent=2, ensure_ascii=False)
    return f"{HEADER}window.OPENMP_EXAMPLES = {payload};\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="fail if the file is stale")
    args = parser.parse_args()

    expected = render()
    current = OUTPUT.read_text(encoding="utf-8") if OUTPUT.exists() else ""

    if args.check:
        if current != expected:
            print(
                "static/js/examples.data.js is out of date; "
                "run: python3 scripts/build_examples.py",
                file=sys.stderr,
            )
            return 1
        print("examples bundle is up to date")
        return 0

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(expected, encoding="utf-8")
    print(f"wrote {OUTPUT.relative_to(OUTPUT.parent.parent.parent)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
