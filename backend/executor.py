"""Compile-and-run pipeline for untrusted C/C++ sources.

The public entry point is :func:`run_job`. Everything it spawns is constrained
on four axes:

* **wall clock** - the parent kills the whole process group on timeout,
* **CPU time / address space / file size / process count** - ``setrlimit`` in
  the child, so a runaway program dies even if it ignores signals,
* **output volume** - streams land in files, are size-capped by ``RLIMIT_FSIZE``
  and are truncated again on read,
* **filesystem** - each job gets a private directory that is always removed.

None of this makes the service safe to expose without a container boundary;
it makes the container boundary survivable. See ``README.md``.
"""

from __future__ import annotations

import errno
import logging
import os
import re
import shutil
import signal
import subprocess
import time
import uuid
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from .config import Config

logger = logging.getLogger(__name__)

try:  # pragma: no cover - platform dependent
    import resource
except ImportError:  # pragma: no cover - Windows
    resource = None  # type: ignore[assignment]

# OpenMPI refuses to start under a tight address-space limit: it reserves a
# large virtual mapping per rank up front. Give MPI jobs this floor instead.
MPI_ADDRESS_SPACE_FLOOR = 2 * 1024 * 1024 * 1024

# OpenMPI also writes a session directory per run. Below roughly this much the
# ranks die with SIGXFSZ and a thoroughly unhelpful "processes failed to start".
MPI_FILE_SIZE_FLOOR = 8 * 1024 * 1024

# Compiling is memory hungry (a preprocessor bomb more so), but it is our own
# trusted binary doing the work, so the limits are looser than for user code.
COMPILER_ADDRESS_SPACE = 2 * 1024 * 1024 * 1024
COMPILER_FILE_SIZE = 64 * 1024 * 1024


class Language(str, Enum):
    C = "c"
    CPP = "cpp"

    @property
    def source_suffix(self) -> str:
        return ".cpp" if self is Language.CPP else ".c"


class Mode(str, Enum):
    OPENMP = "openmp"
    MPI = "mpi"

    @property
    def worker_noun(self) -> str:
        return "processes" if self is Mode.MPI else "threads"


COMPILERS: dict[tuple[Mode, Language], str] = {
    (Mode.OPENMP, Language.C): "gcc",
    (Mode.OPENMP, Language.CPP): "g++",
    (Mode.MPI, Language.C): "mpicc",
    (Mode.MPI, Language.CPP): "mpicxx",
}


class JobError(Exception):
    """A request that cannot be served, carrying an HTTP status."""

    def __init__(self, error: str, detail: str = "", status: int = 400) -> None:
        super().__init__(detail or error)
        self.error = error
        self.detail = detail
        self.status = status

    def to_dict(self) -> dict[str, object]:
        return {"success": False, "error": self.error, "stderr": self.detail}


@dataclass(frozen=True)
class JobRequest:
    code: str
    language: Language
    mode: Mode
    workers: int

    @classmethod
    def parse(cls, payload: dict, config: Config) -> JobRequest:
        """Validate a raw JSON payload, raising :class:`JobError` on bad input."""
        code = payload.get("code")
        if not isinstance(code, str) or not code.strip():
            raise JobError("Invalid request", "No code provided.")
        if len(code.encode("utf-8")) > config.max_code_bytes:
            raise JobError(
                "Invalid request",
                f"Source is larger than the {config.max_code_bytes // 1024} KB limit.",
                status=413,
            )

        raw_language = str(payload.get("language", Language.C.value)).lower()
        try:
            language = Language(raw_language)
        except ValueError:
            raise JobError("Invalid request", 'Invalid language. Use "c" or "cpp".') from None

        raw_mode = str(payload.get("mode", Mode.OPENMP.value)).lower()
        try:
            mode = Mode(raw_mode)
        except ValueError:
            raise JobError("Invalid request", 'Invalid mode. Use "openmp" or "mpi".') from None

        try:
            workers = int(payload.get("threads", 4))
        except (TypeError, ValueError):
            workers = 4
        workers = max(1, min(workers, config.max_workers))

        return cls(code=code, language=language, mode=mode, workers=workers)


@dataclass
class CommandResult:
    stdout: str
    stderr: str
    returncode: int
    timed_out: bool = False
    duration_ms: int = 0
    truncated: bool = False


@dataclass
class JobResult:
    success: bool
    stage: str  # "compile" or "run"
    compiler: str
    language: Language
    mode: Mode
    workers: int
    output: str = ""
    stderr: str = ""
    returncode: int = 0
    compile_ms: int = 0
    run_ms: int = 0
    truncated: bool = False
    error: str = ""
    hint: str = ""

    def to_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "success": self.success,
            "stage": self.stage,
            "compiler": self.compiler,
            "language": self.language.value,
            "mode": self.mode.value,
            "workers": self.workers,
            "output": self.output,
            "stderr": self.stderr,
            "returncode": self.returncode,
            "compileMs": self.compile_ms,
            "runMs": self.run_ms,
            "truncated": self.truncated,
        }
        if self.error:
            payload["error"] = self.error
        if self.hint:
            payload["hint"] = self.hint
        return payload


# --------------------------------------------------------------------------
# Process plumbing
# --------------------------------------------------------------------------


def resolve_sandbox_ids(config: Config) -> tuple[int, int] | None:
    """The uid/gid untrusted children should run as, or None to stay put.

    This matters more than it looks. The kernel does **not** enforce
    ``RLIMIT_NPROC`` for a process with ``CAP_SYS_RESOURCE``, which root has -
    so a fork bomb started by a root-owned server ignores the process cap
    entirely and cannot be reliably reaped. Dropping to an unprivileged uid
    before ``exec`` is what makes the limits real. It also stops the compiler
    from reading root-only files through tricks like ``#include "/etc/shadow"``.
    """
    if not hasattr(os, "geteuid") or os.geteuid() != 0:
        return None  # already unprivileged: limits are enforced as-is

    import pwd

    for candidate in (config.sandbox_user, "sandbox", "nobody"):
        if not candidate:
            continue
        try:
            entry = pwd.getpwnam(candidate)
        except KeyError:
            continue
        if entry.pw_uid != 0:
            return entry.pw_uid, entry.pw_gid

    logger.warning(
        "running as root and no unprivileged sandbox user was found; "
        "process limits will not be enforced for user programs"
    )
    return None


def _limit_setter(
    *,
    cpu_seconds: int,
    address_space: int | None,
    file_size: int,
    max_processes: int,
    sandbox_ids: tuple[int, int] | None,
):
    """Build the ``preexec_fn`` that constrains the forked child.

    Runs after ``fork`` and before ``exec``, so it must stay allocation-light
    and must not touch locks held by other threads.
    """

    def apply() -> None:  # pragma: no cover - executes in the child process
        if resource is None:
            return
        # A one second grace between SIGXCPU and SIGKILL lets a well behaved
        # program flush its output before the kernel takes it out.
        resource.setrlimit(resource.RLIMIT_CPU, (cpu_seconds, cpu_seconds + 1))
        resource.setrlimit(resource.RLIMIT_FSIZE, (file_size, file_size))
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
        if address_space is not None:
            resource.setrlimit(resource.RLIMIT_AS, (address_space, address_space))
        try:
            resource.setrlimit(resource.RLIMIT_NPROC, (max_processes, max_processes))
        except (ValueError, OSError):
            pass

        # Limits are set while we still have the privilege to; drop last so the
        # child cannot raise them back.
        if sandbox_ids is not None:
            uid, gid = sandbox_ids
            os.setgid(gid)
            os.setgroups([gid])
            os.setuid(uid)

    return apply


def _read_capped(path: Path, limit: int) -> tuple[str, bool]:
    """Read at most ``limit`` bytes of ``path``, reporting whether it was cut."""
    try:
        size = path.stat().st_size
    except OSError:
        return "", False
    with path.open("rb") as handle:
        raw = handle.read(limit)
    text = raw.decode("utf-8", errors="replace")
    return text, size > limit


# Tearing down a program that forks is a race: killpg signals the members the
# kernel sees during its walk, and anything spawned after that survives. A
# plain SIGKILL loop loses the race against a fork bomb, which doubles faster
# than we can re-scan. SIGSTOP first is what converges - a stopped process
# cannot fork and is never resumed, so every pass strictly shrinks the set of
# processes still able to reproduce.
GROUP_KILL_PASSES = 200
GROUP_KILL_DEADLINE_SECONDS = 20.0


def _signal_group(pgid: int, sig: int) -> bool:
    """Send ``sig`` to a process group. False means the group is gone."""
    try:
        os.killpg(pgid, sig)
        return True
    except ProcessLookupError:
        return False
    except PermissionError as exc:  # pragma: no cover - misconfigured host
        logger.warning("not permitted to signal process group %s: %s", pgid, exc)
        return False
    except OSError as exc:  # pragma: no cover
        if getattr(exc, "errno", None) == errno.ESRCH:
            return False
        logger.warning("failed to signal process group %s: %s", pgid, exc)
        return False


def _live_group_members(pgid: int) -> int:
    """Count processes in ``pgid`` that are still alive, ignoring zombies.

    ``killpg`` cannot answer this: it succeeds as long as *any* entry exists,
    and a killed process stays in the table as a zombie until its parent reaps
    it. Walking ``/proc`` is the only precise check. Returns -1 when ``/proc``
    is unavailable, so callers can fall back to a bounded retry.
    """
    try:
        entries = os.listdir("/proc")
    except OSError:  # pragma: no cover - non-Linux
        return -1

    alive = 0
    for name in entries:
        if not name.isdigit():
            continue
        try:
            with open(f"/proc/{name}/stat", "rb") as handle:
                data = handle.read()
        except OSError:
            continue  # process exited while we looked at it
        # The comm field is parenthesised and may contain spaces, so parse
        # from the last ')': then fields are state, ppid, pgrp, ...
        close = data.rfind(b")")
        fields = data[close + 2 :].split() if close >= 0 else []
        if len(fields) < 3 or fields[0] == b"Z":
            continue
        try:
            if int(fields[2]) == pgid:
                alive += 1
        except ValueError:  # pragma: no cover
            continue
    return alive


def _terminate_group(process: subprocess.Popen) -> None:
    """Freeze then kill the child's whole process group, leaving nothing behind.

    ``mpirun`` spawns ranks and a runaway program may fork, so killing only the
    direct child leaks processes onto the host.
    """
    try:
        pgid = os.getpgid(process.pid)
    except (ProcessLookupError, OSError):
        pgid = None

    if pgid is None or pgid == os.getpgrp():
        # Never signal our own group - that would take the server down with it.
        _reap(process)
        return

    deadline = time.monotonic() + GROUP_KILL_DEADLINE_SECONDS
    for attempt in range(1, GROUP_KILL_PASSES + 1):
        # Freeze everything the kernel can currently see, then kill the frozen
        # set. Anything spawned in the race window is caught on the next pass,
        # and it can only have been spawned by a process that was still
        # running - so the population of processes able to fork keeps shrinking.
        _signal_group(pgid, signal.SIGSTOP)
        group_existed = _signal_group(pgid, signal.SIGKILL)

        # Reap our own child promptly, otherwise it lingers as a zombie group
        # member and hides the fact that the group is finished.
        try:
            process.wait(timeout=0.05)
        except subprocess.TimeoutExpired:
            pass

        alive = _live_group_members(pgid)
        if alive == 0 or (alive < 0 and not group_existed):
            return
        if time.monotonic() > deadline:  # pragma: no cover - pathological
            logger.error(
                "process group %s still has %s live members after %d passes",
                pgid,
                alive,
                attempt,
            )
            break
    else:  # pragma: no cover - pathological
        logger.error("gave up killing process group %s after %d passes", pgid, GROUP_KILL_PASSES)

    _reap(process)


def _reap(process: subprocess.Popen) -> None:
    """Wait for the direct child so it does not linger as a zombie."""
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:  # pragma: no cover - kernel would be wedged
        logger.error("process %s survived SIGKILL", process.pid)


def _run_command(
    cmd: Sequence[str],
    *,
    cwd: Path,
    timeout: int,
    env: dict[str, str],
    limits,
    max_output_bytes: int,
) -> CommandResult:
    """Run ``cmd`` in its own session with output redirected to files."""
    stdout_path = cwd / ".stdout"
    stderr_path = cwd / ".stderr"
    started = time.monotonic()

    with stdout_path.open("wb") as out, stderr_path.open("wb") as err:
        try:
            process = subprocess.Popen(  # noqa: S603 - argv is built from a fixed table
                list(cmd),
                cwd=str(cwd),
                stdin=subprocess.DEVNULL,
                stdout=out,
                stderr=err,
                env=env,
                start_new_session=True,
                preexec_fn=limits if resource is not None else None,
            )
        except BlockingIOError as exc:
            # The host is out of process slots - usually the tail of somebody
            # else's runaway program being reaped. Fail loudly but politely.
            raise JobError(
                "Server busy",
                "The server could not start a new process. Try again in a moment.",
                status=503,
            ) from exc
        timed_out = False
        try:
            returncode = process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            _terminate_group(process)
            returncode = process.returncode if process.returncode is not None else -signal.SIGKILL

    duration_ms = int((time.monotonic() - started) * 1000)
    stdout, out_truncated = _read_capped(stdout_path, max_output_bytes)
    stderr, err_truncated = _read_capped(stderr_path, max_output_bytes)
    stdout_path.unlink(missing_ok=True)
    stderr_path.unlink(missing_ok=True)

    return CommandResult(
        stdout=stdout,
        stderr=stderr,
        returncode=returncode,
        timed_out=timed_out,
        duration_ms=duration_ms,
        truncated=out_truncated or err_truncated,
    )


# --------------------------------------------------------------------------
# Job orchestration
# --------------------------------------------------------------------------


def _compile_command(request: JobRequest, source: Path, executable: Path) -> list[str]:
    compiler = COMPILERS[(request.mode, request.language)]
    cmd = [compiler, source.name, "-o", executable.name, "-O2", "-Wall"]
    if request.mode is Mode.OPENMP:
        cmd.append("-fopenmp")
    if request.language is Language.CPP:
        cmd.append("-std=c++17")
    else:
        cmd.append("-std=c11")
    cmd.append("-lm")
    return cmd


def _run_command_for(
    request: JobRequest, executable: Path, sandbox_ids: tuple[int, int] | None
) -> list[str]:
    if request.mode is Mode.MPI:
        cmd = ["mpirun"]
        stays_root = sandbox_ids is None and hasattr(os, "geteuid") and os.geteuid() == 0
        if stays_root:
            # Only needed when the program really will run as root; when we can
            # drop privileges, mpirun has nothing to complain about.
            cmd.append("--allow-run-as-root")
        cmd += ["--oversubscribe", "-np", str(request.workers), f"./{executable.name}"]
        return cmd
    return [f"./{executable.name}"]


def _child_env(request: JobRequest) -> dict[str, str]:
    env = {
        "PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"),
        "HOME": os.environ.get("HOME", "/tmp"),
        "LANG": "C.UTF-8",
        "TMPDIR": os.environ.get("TMPDIR", "/tmp"),
    }
    if request.mode is Mode.MPI:
        env["OMPI_ALLOW_RUN_AS_ROOT"] = "1"
        env["OMPI_ALLOW_RUN_AS_ROOT_CONFIRM"] = "1"
        # Keep OpenMPI from probing network fabrics that do not exist in a
        # container; without this every rank prints a stack of warnings.
        env["OMPI_MCA_btl_vader_single_copy_mechanism"] = "none"
    else:
        env["OMP_NUM_THREADS"] = str(request.workers)
    return env


_PATH_NOISE = re.compile(r"(?:/[^\s:]+/)?(program\.c(?:pp)?)")


def _scrub(text: str, job_dir: Path) -> str:
    """Strip server paths out of compiler diagnostics."""
    if not text:
        return ""
    return _PATH_NOISE.sub(r"\1", text.replace(str(job_dir) + os.sep, "").replace(str(job_dir), ""))


def _hint_for(request: JobRequest, diagnostics: str) -> str:
    """Turn the usual first-time mistakes into a one-line nudge."""
    lowered = diagnostics.lower()
    code = request.code

    if "omp.h" in lowered and "no such file" in lowered:
        return (
            "Your compiler cannot find <omp.h>. OpenMP mode compiles with "
            "-fopenmp; check the include name."
        )
    if "mpi.h" in lowered and "no such file" in lowered:
        return (
            "MPI headers are only available in MPI mode - switch Mode to "
            '"MPI" before running this program.'
        )
    if "mpi_init" in lowered and request.mode is not Mode.MPI:
        return 'This program calls MPI functions but Mode is set to "OpenMP". Switch Mode to "MPI".'
    if "omp_get_thread_num" in lowered and request.mode is not Mode.OPENMP:
        return (
            'This program uses OpenMP runtime calls but Mode is set to "MPI". '
            'Switch Mode to "OpenMP".'
        )
    if request.language is Language.CPP and "cout" in code and "iostream" not in code:
        return "std::cout needs #include <iostream>."
    if request.language is Language.C and ("std::" in code or "cout" in code):
        return 'This looks like C++ but Language is set to "C". Switch Language to "C++".'
    return ""


# Signals the kernel raises because *we* capped the process. A program killed
# this way did not produce a real result, so the job is reported as failed;
# SIGSEGV and friends are the program's own outcome and are reported as such.
SANDBOX_SIGNALS = {signal.SIGXCPU, signal.SIGXFSZ, signal.SIGKILL}


def _sandbox_killed(result: CommandResult) -> bool:
    if result.timed_out:
        return True
    if result.returncode >= 0:
        return False
    try:
        return signal.Signals(-result.returncode) in SANDBOX_SIGNALS
    except ValueError:
        return False


def _runtime_note(result: CommandResult, request: JobRequest, config: Config) -> str:
    """Explain a non-zero exit status in terms the user can act on."""
    if result.timed_out:
        limit = config.mpi_run_timeout if request.mode is Mode.MPI else config.run_timeout
        return f"Execution exceeded the {limit}s time limit and was terminated."
    if result.returncode >= 0:
        return ""
    try:
        sig = signal.Signals(-result.returncode)
    except ValueError:
        return f"Program terminated by signal {-result.returncode}."
    reasons = {
        signal.SIGSEGV: "Segmentation fault - check array bounds and pointer use.",
        signal.SIGABRT: "Program aborted (assertion failure or uncaught exception).",
        signal.SIGFPE: "Arithmetic error - most often integer division by zero.",
        signal.SIGKILL: "Program was killed, usually after exceeding the memory limit.",
        signal.SIGXCPU: "Program exceeded its CPU time limit.",
        signal.SIGXFSZ: "Program wrote more output or file data than the limit allows.",
    }
    return reasons.get(sig, f"Program terminated by {sig.name}.")


def _job_dirs(config: Config) -> Iterator[Path]:
    try:
        yield from config.workdir.iterdir()
    except OSError:  # pragma: no cover - workdir vanished under us
        return


def cleanup_stale_jobs(config: Config) -> int:
    """Remove job directories left behind by crashed workers. Returns the count."""
    if config.job_retention_seconds <= 0:
        return 0
    cutoff = time.time() - config.job_retention_seconds
    removed = 0
    for item in _job_dirs(config):
        try:
            if item.stat().st_mtime > cutoff:
                continue
            if item.is_dir():
                shutil.rmtree(item, ignore_errors=True)
            else:
                item.unlink(missing_ok=True)
            removed += 1
        except OSError as exc:
            logger.debug("could not remove stale job %s: %s", item, exc)
    return removed


def toolchain_status(config: Config) -> dict[str, object]:
    """Report which compilers are installed. Cached by the caller."""
    tools = {
        "gcc": "gcc",
        "g++": "g++",
        "mpicc": "mpicc",
        "mpicxx": "mpicxx",
        "mpirun": "mpirun",
    }
    detail: dict[str, dict[str, object]] = {}
    for name, binary in tools.items():
        path = shutil.which(binary)
        entry: dict[str, object] = {"available": path is not None, "version": None}
        if path:
            try:
                probe = subprocess.run(  # noqa: S603 - fixed argv
                    [binary, "--version"],
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                if probe.returncode == 0:
                    entry["version"] = probe.stdout.splitlines()[0] if probe.stdout else None
                else:
                    entry["available"] = False
            except (OSError, subprocess.SubprocessError):
                entry["available"] = False
        detail[name] = entry

    openmp_ready = bool(detail["gcc"]["available"])
    mpi_ready = bool(detail["mpicc"]["available"] and detail["mpirun"]["available"])
    return {
        "status": "ok" if openmp_ready else "degraded",
        "openmp_available": openmp_ready,
        "mpi_available": mpi_ready,
        "cpp_available": bool(detail["g++"]["available"]),
        "toolchain": detail,
        "limits": {
            "maxWorkers": config.max_workers,
            "maxCodeBytes": config.max_code_bytes,
            "runTimeout": config.run_timeout,
            "mpiRunTimeout": config.mpi_run_timeout,
            "memoryBytes": config.address_space_bytes,
        },
    }


def run_job(request: JobRequest, config: Config) -> JobResult:
    """Compile and execute ``request``, always cleaning up after itself."""
    compiler = COMPILERS[(request.mode, request.language)]
    sandbox_ids = resolve_sandbox_ids(config)
    if shutil.which(compiler) is None:
        raise JobError(
            "Toolchain unavailable",
            f"{compiler} is not installed on this server, so {request.mode.value.upper()} "
            f"{request.language.value.upper()} programs cannot be built here.",
            status=503,
        )

    config.workdir.mkdir(parents=True, exist_ok=True)
    if sandbox_ids is not None:
        # The sandbox user has to traverse into its own job directory, so the
        # staging root needs the execute bit for "other". Everything above
        # OPENMP_WORKDIR is the operator's responsibility - keep it under /tmp
        # or another world-traversable path.
        os.chmod(config.workdir, 0o711)

    job_dir = config.workdir / uuid.uuid4().hex
    job_dir.mkdir(mode=0o700)
    if sandbox_ids is not None:
        # The child runs as another user, so hand it ownership of its workspace.
        os.chown(job_dir, sandbox_ids[0], sandbox_ids[1])
    try:
        source = job_dir / f"program{request.language.source_suffix}"
        executable = job_dir / "program"
        source.write_text(request.code, encoding="utf-8")

        compile_result = _run_command(
            _compile_command(request, source, executable),
            cwd=job_dir,
            timeout=config.compile_timeout,
            env=_child_env(request),
            limits=_limit_setter(
                cpu_seconds=config.compile_timeout,
                address_space=COMPILER_ADDRESS_SPACE,
                file_size=COMPILER_FILE_SIZE,
                max_processes=config.max_processes,
                sandbox_ids=sandbox_ids,
            ),
            max_output_bytes=config.max_output_bytes,
        )
        diagnostics = _scrub(compile_result.stderr, job_dir)

        if compile_result.timed_out:
            return JobResult(
                success=False,
                stage="compile",
                compiler=compiler,
                language=request.language,
                mode=request.mode,
                workers=request.workers,
                error="Compilation timeout",
                stderr=f"Compilation exceeded the {config.compile_timeout}s limit.",
                compile_ms=compile_result.duration_ms,
            )

        if compile_result.returncode != 0:
            return JobResult(
                success=False,
                stage="compile",
                compiler=compiler,
                language=request.language,
                mode=request.mode,
                workers=request.workers,
                error="Compilation error",
                output=_scrub(compile_result.stdout, job_dir),
                stderr=diagnostics or "Compilation failed with no diagnostics.",
                returncode=compile_result.returncode,
                compile_ms=compile_result.duration_ms,
                truncated=compile_result.truncated,
                hint=_hint_for(request, diagnostics),
            )

        address_space = config.address_space_bytes
        file_size = config.file_size_bytes
        if request.mode is Mode.MPI:
            address_space = max(address_space, MPI_ADDRESS_SPACE_FLOOR)
            file_size = max(file_size, MPI_FILE_SIZE_FLOOR)

        run_result = _run_command(
            _run_command_for(request, executable, sandbox_ids),
            cwd=job_dir,
            timeout=config.mpi_run_timeout if request.mode is Mode.MPI else config.run_timeout,
            env=_child_env(request),
            limits=_limit_setter(
                cpu_seconds=config.cpu_seconds,
                address_space=address_space,
                file_size=file_size,
                max_processes=config.max_processes,
                sandbox_ids=sandbox_ids,
            ),
            max_output_bytes=config.max_output_bytes,
        )

        note = _runtime_note(run_result, request, config)
        stderr = _scrub(run_result.stderr, job_dir)
        if note:
            stderr = f"{stderr}\n{note}".strip() if stderr else note

        killed = _sandbox_killed(run_result)
        if run_result.timed_out:
            error = "Execution timeout"
        elif killed:
            error = "Resource limit exceeded"
        else:
            error = ""

        return JobResult(
            # A program that exits non-zero still "succeeded" as a job - that
            # exit code is its result. Only a sandbox kill counts as a failure.
            success=not killed,
            stage="run",
            compiler=compiler,
            language=request.language,
            mode=request.mode,
            workers=request.workers,
            output=_scrub(run_result.stdout, job_dir),
            stderr=stderr,
            returncode=run_result.returncode,
            compile_ms=compile_result.duration_ms,
            run_ms=run_result.duration_ms,
            truncated=compile_result.truncated or run_result.truncated,
            error=error,
            hint=_hint_for(request, stderr) if run_result.returncode != 0 else "",
        )
    finally:
        shutil.rmtree(job_dir, ignore_errors=True)
