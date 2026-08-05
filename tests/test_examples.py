"""The example catalogue is real code, so it is tested like real code."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from backend.examples import catalogue, load_examples
from backend.executor import COMPILERS, JobRequest, Language, Mode, run_job

from .conftest import HAS_MPI, requires_gcc

REPO_ROOT = Path(__file__).resolve().parent.parent


def test_manifest_loads_and_is_well_formed():
    examples = load_examples()
    assert examples, "catalogue is empty"
    for example in examples:
        assert example.language in {"c", "cpp"}
        assert example.mode in {"openmp", "mpi"}
        assert example.description, f"{example.id} has no description"
        assert "int main" in example.source, f"{example.id} has no entry point"


def test_every_source_file_is_listed_in_the_manifest():
    listed = {example.id for example in load_examples()}
    on_disk = {
        path.stem
        for path in (REPO_ROOT / "examples").iterdir()
        if path.suffix in {".c", ".cpp"}
    }
    # ids match filenames by convention, which keeps orphaned files visible.
    assert on_disk == listed


def test_bundled_javascript_catalogue_is_current():
    """`static/js/examples.data.js` is generated - fail loudly when it drifts."""
    result = subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "build_examples.py"), "--check"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr


@requires_gcc
@pytest.mark.parametrize("example", catalogue(), ids=lambda e: e["id"])
def test_example_compiles_and_runs(example, config):
    """Every shipped example must survive the same pipeline users hit."""
    mode = Mode(example["mode"])
    language = Language(example["language"])
    if mode is Mode.MPI and not HAS_MPI:
        pytest.skip("OpenMPI is not installed")

    request = JobRequest.parse(
        {
            "code": example["source"],
            "language": language.value,
            "mode": mode.value,
            "threads": 2,
        },
        config,
    )
    result = run_job(request, config)
    assert result.success, f"{example['id']} failed:\n{result.stderr}"
    assert result.returncode == 0, f"{example['id']} exited {result.returncode}:\n{result.stderr}"
    assert result.output.strip(), f"{example['id']} produced no output"


def test_compiler_table_covers_every_combination():
    assert set(COMPILERS) == {(mode, lang) for mode in Mode for lang in Language}
