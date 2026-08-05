"""Runtime configuration, resolved from environment variables.

Every tunable that used to be a magic number scattered through ``app.py`` lives
here so that deployments can adjust limits without editing code.
"""

from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

MEGABYTE = 1024 * 1024


def _env_int(name: str, default: int, *, minimum: int = 0) -> int:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return max(minimum, value)


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Config:
    """Immutable settings bundle shared by the app factory and the executor."""

    # Where compilation jobs are staged. One sub-directory per job.
    workdir: Path = field(
        default_factory=lambda: Path(
            os.environ.get("OPENMP_WORKDIR", Path(tempfile.gettempdir()) / "openmp_compiler")
        )
    )

    # Request shape limits.
    max_workers: int = 16
    max_code_bytes: int = 64 * 1024

    # Wall-clock limits, in seconds.
    compile_timeout: int = 15
    run_timeout: int = 10
    # MPI needs noticeably longer: `mpirun` has to spawn and wire up processes.
    mpi_run_timeout: int = 30

    # Limits applied to the compiled program via setrlimit(2).
    cpu_seconds: int = 10
    address_space_bytes: int = 512 * MEGABYTE
    file_size_bytes: int = 8 * MEGABYTE
    max_processes: int = 256

    # Output captured from compiler/program before truncation kicks in.
    max_output_bytes: int = 256 * 1024

    # Abuse controls.
    rate_limit_requests: int = 20
    rate_limit_window_seconds: int = 60
    max_concurrent_jobs: int = 4

    # Housekeeping.
    job_retention_seconds: int = 3600
    health_cache_seconds: int = 60

    cors_origins: str = "*"

    # Untrusted programs are executed as this user when the server itself runs
    # as root. Without it, the kernel exempts root from RLIMIT_NPROC.
    sandbox_user: str = "sandbox"

    @classmethod
    def from_env(cls) -> Config:
        """Build a config from the process environment, falling back to defaults."""
        defaults = cls()
        return cls(
            workdir=defaults.workdir,
            max_workers=_env_int("OPENMP_MAX_WORKERS", defaults.max_workers, minimum=1),
            max_code_bytes=_env_int("OPENMP_MAX_CODE_BYTES", defaults.max_code_bytes, minimum=1),
            compile_timeout=_env_int("OPENMP_COMPILE_TIMEOUT", defaults.compile_timeout, minimum=1),
            run_timeout=_env_int("OPENMP_RUN_TIMEOUT", defaults.run_timeout, minimum=1),
            mpi_run_timeout=_env_int("OPENMP_MPI_RUN_TIMEOUT", defaults.mpi_run_timeout, minimum=1),
            cpu_seconds=_env_int("OPENMP_CPU_SECONDS", defaults.cpu_seconds, minimum=1),
            address_space_bytes=_env_int(
                "OPENMP_ADDRESS_SPACE_BYTES", defaults.address_space_bytes, minimum=MEGABYTE
            ),
            file_size_bytes=_env_int("OPENMP_FILE_SIZE_BYTES", defaults.file_size_bytes, minimum=0),
            max_processes=_env_int("OPENMP_MAX_PROCESSES", defaults.max_processes, minimum=1),
            max_output_bytes=_env_int(
                "OPENMP_MAX_OUTPUT_BYTES", defaults.max_output_bytes, minimum=1024
            ),
            rate_limit_requests=_env_int(
                "OPENMP_RATE_LIMIT", defaults.rate_limit_requests, minimum=0
            ),
            rate_limit_window_seconds=_env_int(
                "OPENMP_RATE_LIMIT_WINDOW", defaults.rate_limit_window_seconds, minimum=1
            ),
            max_concurrent_jobs=_env_int(
                "OPENMP_MAX_CONCURRENT_JOBS", defaults.max_concurrent_jobs, minimum=1
            ),
            job_retention_seconds=_env_int(
                "OPENMP_JOB_RETENTION", defaults.job_retention_seconds, minimum=0
            ),
            health_cache_seconds=_env_int(
                "OPENMP_HEALTH_CACHE", defaults.health_cache_seconds, minimum=0
            ),
            cors_origins=os.environ.get("OPENMP_CORS_ORIGINS", defaults.cors_origins),
            sandbox_user=os.environ.get("OPENMP_SANDBOX_USER", defaults.sandbox_user),
        )


def debug_enabled() -> bool:
    """True when the Flask debugger should be enabled (never in production)."""
    return _env_bool("FLASK_DEBUG", False)
