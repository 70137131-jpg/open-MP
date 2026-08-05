"""Loader for the example catalogue in ``examples/``.

Each entry is a real, compilable source file described by
``examples/manifest.json``, so the samples can be built and tested like any
other code in the repository rather than living as string literals in a route.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

EXAMPLES_DIR = Path(__file__).resolve().parent.parent / "examples"
MANIFEST = EXAMPLES_DIR / "manifest.json"

REQUIRED_FIELDS = ("id", "title", "file", "language", "mode")


@dataclass(frozen=True)
class Example:
    id: str
    title: str
    language: str
    mode: str
    description: str
    source: str

    def to_dict(self) -> dict[str, str]:
        return {
            "id": self.id,
            "title": self.title,
            "language": self.language,
            "mode": self.mode,
            "description": self.description,
            "source": self.source,
        }


@lru_cache(maxsize=1)
def load_examples() -> tuple[Example, ...]:
    """Read and validate the catalogue. Cached for the process lifetime."""
    entries = json.loads(MANIFEST.read_text(encoding="utf-8"))
    if not isinstance(entries, list):
        raise ValueError("examples/manifest.json must contain a list")

    seen: set[str] = set()
    examples: list[Example] = []
    for entry in entries:
        missing = [field for field in REQUIRED_FIELDS if not entry.get(field)]
        if missing:
            raise ValueError(f"example entry {entry!r} is missing {', '.join(missing)}")
        if entry["id"] in seen:
            raise ValueError(f"duplicate example id: {entry['id']}")
        seen.add(entry["id"])

        source_path = EXAMPLES_DIR / entry["file"]
        if not source_path.is_file():
            raise FileNotFoundError(f"example source not found: {source_path}")

        examples.append(
            Example(
                id=entry["id"],
                title=entry["title"],
                language=entry["language"],
                mode=entry["mode"],
                description=entry.get("description", ""),
                source=source_path.read_text(encoding="utf-8").rstrip("\n"),
            )
        )
    return tuple(examples)


def catalogue() -> list[dict[str, str]]:
    """The JSON payload served by ``GET /examples``."""
    return [example.to_dict() for example in load_examples()]


def default_source() -> str:
    """Source shown in the editor on first load."""
    return load_examples()[0].source
