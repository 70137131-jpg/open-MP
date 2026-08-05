# OpenMP & MPI Online Compiler

Write, compile and run parallel **C and C++** programs from the browser — OpenMP
threads or MPI ranks, with the output streamed back.

**Live demo:** [open-mp-theta.vercel.app](https://open-mp-theta.vercel.app/)

---

## What it does

| | |
|---|---|
| **Languages** | C (`gcc` / `mpicc`) and C++17 (`g++` / `mpicxx`) |
| **Modes** | OpenMP (1–16 threads) and MPI (1–16 ranks, single node) |
| **Editor** | CodeMirror with C/C++ highlighting, bracket matching, `Ctrl`+`Enter` to run |
| **Examples** | 10 annotated programs, compiled and tested in CI |
| **UI** | Light/dark themes, responsive, code and settings persisted locally |
| **Resilience** | Falls back to a plain textarea if the CodeMirror CDN is unreachable |

---

## Quick start

### Docker (recommended)

```bash
docker compose up --build
```

Open <http://localhost:8080>. nginx serves the page and proxies `/compile`,
`/health` and `/examples` to the backend.

### Local development

```bash
./start.sh
```

Checks your toolchain, creates `.venv`, installs dependencies and serves
<http://localhost:5000>. On Debian/Ubuntu you will want:

```bash
sudo apt install gcc g++ openmpi-bin libopenmpi-dev
```

### Tests

```bash
pip install -r requirements-dev.txt
pytest -q          # compiles and runs real programs; MPI tests skip if absent
ruff check .
```

---

## How the sandbox works

The service compiles and executes code that anyone can submit. That is
inherently dangerous, so every child process is constrained on five axes:

| Axis | Mechanism | Default |
|---|---|---|
| Wall clock | parent kills the process **group** | 10s run, 30s MPI, 15s compile |
| CPU time | `RLIMIT_CPU` | 10s |
| Memory | `RLIMIT_AS` | 512 MB (2 GB floor for MPI) |
| Output / files | `RLIMIT_FSIZE` + truncation on read | 8 MB, 256 KB returned |
| Processes | `RLIMIT_NPROC` + privilege drop | 256 |

Plus: a private per-job directory that is always removed, a scrubbed
environment (the server's variables are not inherited), compiler diagnostics
with server paths stripped out, per-IP rate limiting and a concurrency gate.

> **Rate limiting is per worker process.** The in-app limiter keeps its counters
> in memory, so with `WEB_CONCURRENCY=4` a client gets up to `4 x
> OPENMP_RATE_LIMIT` requests per window. It is a backstop; the nginx
> `limit_req` zone in `nginx.conf` is what enforces one shared limit in front of
> all the workers. A multi-host deployment needs a shared store such as Redis.

### The part that is easy to get wrong

**`RLIMIT_NPROC` is not enforced for root.** A process holding
`CAP_SYS_RESOURCE` — which root has — is exempt from the process-count limit.
A fork bomb started by a root-owned server therefore ignores the cap entirely,
and no amount of `killpg` in userspace reliably wins the race against it.

So the executor **drops each compiled program to an unprivileged user**
(`OPENMP_SANDBOX_USER`, default `sandbox`) before `exec`. This is what makes
the limits real, and it also stops the compiler reading root-only files through
tricks like `#include "/etc/shadow"`. The Docker image runs as root *only* so it
can perform that drop, and `docker-compose.yml` removes every capability except
the five needed for it (`SETUID`, `SETGID`, `CHOWN`, `DAC_OVERRIDE`, `KILL`).

Teardown matters too: killing a forking program takes `SIGSTOP` on the whole
process group *before* `SIGKILL`, because a stopped process cannot fork, and
repeating until `/proc` shows no live members of the group. A plain `SIGKILL`
loop loses the race. `tests/test_executor.py` runs an actual fork bomb and
asserts nothing leaks.

### What this still is not

A container boundary is required, not optional. The sandbox makes that boundary
survivable; it does not replace it. Do not run `start.sh` as root on a machine
you care about, and do not expose the backend directly to the internet without
the rate limiting, the pids limit and a read-only root filesystem that
`docker-compose.yml` sets up.

---

## Configuration

Everything is environment driven; defaults live in `backend/config.py`.

| Variable | Default | Meaning |
|---|---|---|
| `PORT` | `5000` | Listen port |
| `OPENMP_WORKDIR` | `$TMPDIR/openmp_compiler` | Job staging root (must be world-traversable) |
| `OPENMP_SANDBOX_USER` | `sandbox` | User to run compiled programs as; empty disables the drop |
| `OPENMP_MAX_WORKERS` | `16` | Ceiling on threads / ranks |
| `OPENMP_MAX_CODE_BYTES` | `65536` | Largest accepted source |
| `OPENMP_COMPILE_TIMEOUT` | `15` | Compile wall clock (s) |
| `OPENMP_RUN_TIMEOUT` | `10` | OpenMP run wall clock (s) |
| `OPENMP_MPI_RUN_TIMEOUT` | `30` | MPI run wall clock (s) |
| `OPENMP_CPU_SECONDS` | `10` | `RLIMIT_CPU` for user programs |
| `OPENMP_ADDRESS_SPACE_BYTES` | `536870912` | `RLIMIT_AS` (MPI gets ≥ 2 GB) |
| `OPENMP_FILE_SIZE_BYTES` | `8388608` | `RLIMIT_FSIZE` (MPI gets ≥ 8 MB) |
| `OPENMP_MAX_PROCESSES` | `256` | `RLIMIT_NPROC` |
| `OPENMP_MAX_OUTPUT_BYTES` | `262144` | Output returned before truncation |
| `OPENMP_RATE_LIMIT` | `20` | Requests per window per client **per worker** (see note) |
| `OPENMP_RATE_LIMIT_WINDOW` | `60` | Rate-limit window (s) |
| `OPENMP_MAX_CONCURRENT_JOBS` | `4` | Simultaneous compilations before 503 |
| `OPENMP_CORS_ORIGINS` | `*` | Allowed origins |
| `OPENMP_LOG_LEVEL` | `INFO` | Log verbosity |
| `WEB_CONCURRENCY` | `min(4, 2·cpus+1)` | gunicorn workers |

---

## API

### `POST /compile`

```json
{ "code": "#include <stdio.h>\n...", "language": "c", "mode": "openmp", "threads": 4 }
```

`language` is `c` or `cpp`; `mode` is `openmp` or `mpi`; `threads` is clamped to
`[1, OPENMP_MAX_WORKERS]`.

```json
{
  "success": true,
  "stage": "run",
  "output": "Hello from thread 0 of 4\n",
  "stderr": "",
  "returncode": 0,
  "compiler": "gcc",
  "language": "c",
  "mode": "openmp",
  "workers": 4,
  "compileMs": 118,
  "runMs": 7,
  "truncated": false
}
```

`success` means *the job ran to completion*. A program that exits non-zero or
segfaults still returns `success: true` with the real `returncode` — that is
the program's result. `success: false` means compilation failed or the sandbox
intervened, and `error` says which (`Compilation error`, `Execution timeout`,
`Resource limit exceeded`, `Rate limit exceeded`, `Server busy`,
`Toolchain unavailable`). Failures may also carry a `hint` with a one-line
diagnosis, e.g. selecting OpenMP mode for a program that calls `MPI_Init`.

### `GET /examples`

```json
{ "examples": [ { "id": "hello_world", "title": "Hello World",
                  "language": "c", "mode": "openmp",
                  "description": "...", "source": "#include <stdio.h>..." } ] }
```

### `GET /health`

Reports which compilers are present and the limits currently in force. Cached
for `OPENMP_HEALTH_CACHE` seconds because the frontend polls it.

---

## Layout

```
app.py                  WSGI entry point
gunicorn.conf.py        production server settings
backend/
  __init__.py           application factory
  config.py             every tunable, resolved from the environment
  executor.py           the sandbox: compile, run, constrain, clean up
  routes.py             HTTP surface
  examples.py           example catalogue loader
  ratelimit.py          sliding-window limiter and concurrency gate
examples/               real .c/.cpp sources + manifest.json
static/css, static/js   frontend (no build step)
scripts/build_examples.py   regenerates static/js/examples.data.js
tests/                  pytest suite; compiles and runs real programs
```

### Frontend notes

There is no build step: `index.html` loads `static/css/styles.css` and
`static/js/app.js` directly, so the page also works served as plain static
files with the API on another origin.

CodeMirror comes from cdnjs with subresource-integrity hashes. If it cannot be
loaded the editor degrades to a plain textarea (tab-indent included) and says
so in the output pane — a dead CDN costs syntax highlighting, not the page.

### Adding an example

1. Drop the source in `examples/` (the filename stem becomes its id).
2. Add an entry to `examples/manifest.json`.
3. `python3 scripts/build_examples.py` to refresh the bundled copy.

`pytest` then compiles and runs it like any other example, and CI fails if the
generated bundle is stale.

---

## Deployment

* **Render** — `render.yaml` builds the Dockerfile and health-checks `/health`.
* **Vercel** — serves the static page and rewrites the three API paths to the
  backend; edit the URLs in `vercel.json` to point at your own deployment.
* **Anywhere else** — `docker compose up`, or `gunicorn --config
  gunicorn.conf.py app:app` behind a reverse proxy.

---

## License

MIT.
