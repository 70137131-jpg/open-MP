from __future__ import annotations

import shutil
import sys
import tempfile
from collections.abc import Iterator
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend import create_app  # noqa: E402
from backend.config import Config  # noqa: E402

HAS_GCC = shutil.which("gcc") is not None
HAS_MPI = shutil.which("mpicc") is not None and shutil.which("mpirun") is not None

requires_gcc = pytest.mark.skipif(not HAS_GCC, reason="gcc is not installed")
requires_mpi = pytest.mark.skipif(not HAS_MPI, reason="OpenMPI is not installed")


@pytest.fixture
def workdir() -> Iterator[Path]:
    """A staging root whose ancestors the sandbox user can traverse.

    pytest's tmp_path lives under a 0700 directory, which an unprivileged
    sandbox user cannot enter - so jobs are staged directly under the system
    temp directory instead.
    """
    path = Path(tempfile.mkdtemp(prefix="openmp-test-"))
    path.chmod(0o711)  # mkdtemp creates 0700; the sandbox user needs to enter
    try:
        yield path / "jobs"
    finally:
        shutil.rmtree(path, ignore_errors=True)


@pytest.fixture
def config(workdir: Path) -> Config:
    """Fast, tightly bounded limits so the suite stays quick."""
    return Config(
        workdir=workdir,
        max_workers=4,
        max_code_bytes=8 * 1024,
        compile_timeout=20,
        run_timeout=5,
        mpi_run_timeout=20,
        cpu_seconds=3,
        address_space_bytes=512 * 1024 * 1024,
        file_size_bytes=1024 * 1024,
        max_output_bytes=4096,
        rate_limit_requests=0,  # disabled unless a test opts in
        max_concurrent_jobs=2,
        health_cache_seconds=0,
    )


@pytest.fixture
def app(config: Config):
    application = create_app(config)
    application.config.update(TESTING=True)
    return application


@pytest.fixture
def client(app):
    return app.test_client()
