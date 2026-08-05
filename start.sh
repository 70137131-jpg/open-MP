#!/usr/bin/env bash
# Development bootstrap: check the toolchain, install dependencies into a
# virtualenv, then serve the app on http://localhost:5000.
#
# For anything resembling production use `docker compose up --build` instead -
# this script runs the compiler on your own machine with no container boundary.

set -euo pipefail

cd "$(dirname "$0")"

VENV="${VENV:-.venv}"
PORT="${PORT:-5000}"

info() { printf '  %s\n' "$*"; }
fail() { printf 'error: %s\n' "$*" >&2; exit 1; }

echo "OpenMP / MPI online compiler - development setup"
echo "================================================"

command -v python3 >/dev/null || fail "python3 not found (need 3.10 or newer)"
info "python:  $(python3 --version)"

command -v gcc >/dev/null || fail "gcc not found. Ubuntu/Debian: sudo apt install gcc"
info "gcc:     $(gcc --version | head -n1)"

if command -v g++ >/dev/null; then
    info "g++:     $(g++ --version | head -n1)"
else
    info "g++:     not found - C++ support will be unavailable"
fi

if command -v mpicc >/dev/null && command -v mpirun >/dev/null; then
    info "mpi:     $(mpicc --version | head -n1)"
else
    info "mpi:     not found - MPI mode will be unavailable"
    info "         Ubuntu/Debian: sudo apt install openmpi-bin libopenmpi-dev"
fi

# OpenMP is a compiler feature rather than a package, so probe for it directly.
probe="$(mktemp -d)"
trap 'rm -rf "$probe"' EXIT
printf '#include <omp.h>\nint main(void){ return omp_get_max_threads() > 0 ? 0 : 1; }\n' > "$probe/probe.c"
if gcc -fopenmp "$probe/probe.c" -o "$probe/probe" 2>/dev/null && "$probe/probe"; then
    info "openmp:  supported"
else
    fail "gcc cannot compile OpenMP code (-fopenmp). Install a GCC build with OpenMP support."
fi

echo
echo "Installing dependencies into $VENV"
[ -d "$VENV" ] || python3 -m venv "$VENV"
"$VENV/bin/pip" install --quiet --upgrade pip
"$VENV/bin/pip" install --quiet -r requirements.txt
info "dependencies installed"

if [ "$(id -u)" -eq 0 ]; then
    echo
    echo "WARNING: running as root. The kernel does not enforce RLIMIT_NPROC for"
    echo "         root, so a program that forks cannot be reliably contained"
    echo "         unless an unprivileged 'sandbox' user exists to drop to."
    echo "         Prefer a normal user, or use 'docker compose up' instead."
fi

echo
echo "Serving on http://localhost:$PORT   (Ctrl+C to stop)"
echo
exec "$VENV/bin/python" app.py
