"""Executor tests: these actually invoke the compiler and run the binaries."""

from __future__ import annotations

import os
import time
from dataclasses import replace

import pytest

from backend.executor import (
    JobError,
    JobRequest,
    Language,
    Mode,
    cleanup_stale_jobs,
    resolve_sandbox_ids,
    run_job,
)

from .conftest import requires_gcc, requires_mpi

HELLO = """
#include <stdio.h>
#include <omp.h>
int main(void) {
    #pragma omp parallel
    {
        #pragma omp critical
        printf("thread %d\\n", omp_get_thread_num());
    }
    return 0;
}
"""


def make(code: str, config, **kwargs) -> JobRequest:
    payload = {"code": code, "language": "c", "mode": "openmp", "threads": 2}
    payload.update(kwargs)
    return JobRequest.parse(payload, config)


# ----------------------------------------------------------------- validation


def test_rejects_empty_code(config):
    with pytest.raises(JobError) as excinfo:
        JobRequest.parse({"code": "   "}, config)
    assert excinfo.value.status == 400


def test_rejects_oversized_code(config):
    with pytest.raises(JobError) as excinfo:
        JobRequest.parse({"code": "x" * (config.max_code_bytes + 1)}, config)
    assert excinfo.value.status == 413


def test_rejects_unknown_language_and_mode(config):
    with pytest.raises(JobError):
        JobRequest.parse({"code": "int main(){}", "language": "rust"}, config)
    with pytest.raises(JobError):
        JobRequest.parse({"code": "int main(){}", "mode": "cuda"}, config)


@pytest.mark.parametrize(
    ("requested", "expected"),
    [(0, 1), (-5, 1), (3, 3), (99, 4), ("not a number", 4), (None, 4)],
)
def test_worker_count_is_clamped(config, requested, expected):
    assert make("int main(void){return 0;}", config, threads=requested).workers == expected


# -------------------------------------------------------------------- happy path


@requires_gcc
def test_openmp_program_runs(config):
    result = run_job(make(HELLO, config, threads=3), config)
    assert result.success, result.stderr
    assert result.returncode == 0
    assert result.output.count("thread ") == 3
    assert result.compiler == "gcc"
    assert result.stage == "run"


@requires_gcc
def test_cpp_program_runs(config):
    code = '#include <iostream>\nint main(){ std::cout << "hi from c++\\n"; }'
    result = run_job(make(code, config, language="cpp"), config)
    assert result.success, result.stderr
    assert "hi from c++" in result.output
    assert result.compiler == "g++"


@requires_gcc
def test_thread_count_is_honoured(config):
    code = """
    #include <stdio.h>
    #include <omp.h>
    int main(void){ printf("%d\\n", omp_get_max_threads()); return 0; }
    """
    result = run_job(make(code, config, threads=3), config)
    assert result.output.strip() == "3"


@requires_mpi
def test_mpi_program_runs(config):
    code = """
    #include <mpi.h>
    #include <stdio.h>
    int main(int argc, char **argv){
        MPI_Init(&argc, &argv);
        int rank; MPI_Comm_rank(MPI_COMM_WORLD, &rank);
        printf("rank %d\\n", rank);
        MPI_Finalize();
        return 0;
    }
    """
    result = run_job(make(code, config, mode="mpi", threads=2), config)
    assert result.success, result.stderr
    assert "rank 0" in result.output


# ------------------------------------------------------------------- failures


@requires_gcc
def test_compile_error_is_reported_without_server_paths(config):
    result = run_job(make("int main(void) { this is not c }", config), config)
    assert not result.success
    assert result.stage == "compile"
    assert result.error == "Compilation error"
    assert "program.c" in result.stderr
    assert str(config.workdir) not in result.stderr


@requires_gcc
def test_nonzero_exit_is_surfaced(config):
    result = run_job(make("int main(void){ return 3; }", config), config)
    assert result.returncode == 3
    assert result.stage == "run"


@requires_gcc
def test_segfault_gets_an_explanation(config):
    code = "int main(void){ int *p = 0; *p = 1; return 0; }"
    result = run_job(make(code, config), config)
    assert "Segmentation fault" in result.stderr


@requires_gcc
def test_language_mismatch_produces_a_hint(config):
    code = '#include <iostream>\nint main(){ std::cout << "x"; }'
    result = run_job(make(code, config, language="c"), config)
    assert not result.success
    assert "C++" in result.hint


@requires_gcc
def test_mpi_program_in_openmp_mode_produces_a_hint(config):
    code = '#include <mpi.h>\nint main(){ MPI_Init(0,0); return 0; }'
    result = run_job(make(code, config), config)
    assert not result.success
    assert "MPI" in result.hint


# ------------------------------------------------------------------ sandboxing


@requires_gcc
def test_busy_loop_is_killed_by_the_cpu_limit(config):
    """A spinning program burns CPU, so RLIMIT_CPU fires before the wall clock."""
    result = run_job(make("int main(void){ for(;;); return 0; }", config), config)
    assert not result.success
    assert result.error == "Resource limit exceeded"
    assert "CPU time limit" in result.stderr
    assert result.run_ms < config.run_timeout * 1000


@requires_gcc
def test_idle_loop_is_killed_by_the_wall_clock(config):
    """A sleeping program uses no CPU, so only the wall-clock timeout catches it."""
    code = "#include <unistd.h>\nint main(void){ for(;;) sleep(1); return 0; }"
    result = run_job(make(code, config), config)
    assert not result.success
    assert result.error == "Execution timeout"
    assert result.run_ms >= config.run_timeout * 1000 - 500


@requires_gcc
def test_runaway_allocation_is_capped(config):
    code = """
    #include <stdlib.h>
    #include <string.h>
    int main(void){
        for (long i = 0; i < 100000; i++) {
            void *p = malloc(64L * 1024 * 1024);
            if (!p) return 42;          /* the rlimit made malloc fail */
            memset(p, 1, 1024);
        }
        return 0;
    }
    """
    result = run_job(make(code, config), config)
    # Either malloc refuses (exit 42) or the kernel kills the process; both mean
    # the address-space limit held and the host stayed healthy.
    assert result.returncode != 0


@requires_gcc
def test_enormous_output_is_truncated(config):
    code = """
    #include <stdio.h>
    int main(void){
        for (long i = 0; i < 200000; i++) puts("noise noise noise noise noise");
        return 0;
    }
    """
    result = run_job(make(code, config), config)
    assert result.truncated
    assert len(result.output.encode()) <= config.max_output_bytes


@requires_gcc
def test_job_directory_is_always_removed(config):
    run_job(make(HELLO, config), config)
    run_job(make("this will not compile", config), config)
    assert list(config.workdir.iterdir()) == []


@requires_gcc
def test_child_cannot_see_server_environment(config, monkeypatch):
    monkeypatch.setenv("SECRET_TOKEN", "hunter2")
    code = """
    #include <stdio.h>
    #include <stdlib.h>
    int main(void){
        const char *v = getenv("SECRET_TOKEN");
        printf("%s\\n", v ? v : "absent");
        return 0;
    }
    """
    assert run_job(make(code, config), config).output.strip() == "absent"


def test_missing_toolchain_raises_service_unavailable(config, monkeypatch):
    monkeypatch.setattr("backend.executor.shutil.which", lambda _binary: None)
    with pytest.raises(JobError) as excinfo:
        run_job(make("int main(void){return 0;}", config), config)
    assert excinfo.value.status == 503


# ----------------------------------------------------------------- maintenance


def test_cleanup_removes_only_stale_jobs(config):
    config.workdir.mkdir(parents=True, exist_ok=True)
    fresh = config.workdir / "fresh"
    stale = config.workdir / "stale"
    fresh.mkdir()
    stale.mkdir()
    import os
    import time

    old = time.time() - config.job_retention_seconds - 60
    os.utime(stale, (old, old))

    assert cleanup_stale_jobs(config) == 1
    assert fresh.exists()
    assert not stale.exists()


def test_language_and_mode_metadata():
    assert Language.CPP.source_suffix == ".cpp"
    assert Language.C.source_suffix == ".c"
    assert Mode.MPI.worker_noun == "processes"
    assert Mode.OPENMP.worker_noun == "threads"


# --------------------------------------------------- process-group containment


def test_live_group_members_sees_this_process():
    from backend.executor import _live_group_members

    count = _live_group_members(os.getpgrp())
    if count < 0:
        pytest.skip("/proc is not available")
    assert count >= 1


def test_live_group_members_reports_empty_for_unused_group():
    from backend.executor import _live_group_members

    count = _live_group_members(0x7FFFFFF0)  # no such process group
    if count < 0:
        pytest.skip("/proc is not available")
    assert count == 0


@requires_gcc
def test_privileges_are_dropped_when_running_as_root(config):
    """When the server is root, user programs must not be."""
    if os.geteuid() != 0:
        pytest.skip("not running as root")
    if resolve_sandbox_ids(config) is None:
        pytest.skip("no unprivileged sandbox user on this host")

    code = "#include <stdio.h>\n#include <unistd.h>\nint main(void){ printf(\"%d\\n\", getuid()); return 0; }"
    result = run_job(make(code, config), config)
    assert result.output.strip() != "0", "user program ran as root"


@requires_gcc
def test_fork_bomb_is_contained_without_leaking_processes(config):
    """The headline safety property: a forking program leaves nothing behind.

    Skipped when the limits provably cannot be enforced (running as root with
    no unprivileged user to drop to), because the kernel exempts root from
    RLIMIT_NPROC and the bomb would take the test host down with it.
    """
    if os.geteuid() == 0 and resolve_sandbox_ids(config) is None:
        pytest.skip("running as root with no sandbox user: NPROC is unenforceable")

    def process_count() -> int:
        return len(
            [name for name in os.listdir("/proc") if name.isdigit()]
        )

    if not os.path.isdir("/proc"):
        pytest.skip("/proc is not available")

    before = process_count()
    result = run_job(make("#include <unistd.h>\nint main(void){ while(1) fork(); return 0; }", config), config)
    assert not result.success

    # Give the kernel a moment to finish reaping, then confirm nothing survived.
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        after = process_count()
        if after <= before + 5:
            break
        time.sleep(0.5)
    assert after <= before + 5, f"leaked {after - before} processes"


@requires_mpi
def test_mpi_survives_a_tight_file_size_limit(config):
    """OpenMPI writes a session directory; too small an FSIZE kills the ranks.

    The executor raises the limit for MPI jobs specifically, so an operator who
    tightens OPENMP_FILE_SIZE_BYTES does not silently break MPI with a
    "processes failed to start" message that explains nothing.
    """
    tight = replace(config, file_size_bytes=32 * 1024)
    code = """
    #include <mpi.h>
    #include <stdio.h>
    int main(int argc, char **argv){
        MPI_Init(&argc, &argv);
        int rank; MPI_Comm_rank(MPI_COMM_WORLD, &rank);
        printf("rank %d\\n", rank);
        MPI_Finalize();
        return 0;
    }
    """
    result = run_job(make(code, tight, mode="mpi", threads=2), tight)
    assert result.success, result.stderr
    assert "rank 0" in result.output
