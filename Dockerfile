# syntax=docker/dockerfile:1
FROM gcc:14-bookworm

# OpenMPI provides mpicc/mpicxx/mpirun; python3-venv keeps pip off the system
# interpreter so we never need --break-system-packages.
RUN apt-get update && apt-get install -y --no-install-recommends \
        python3 \
        python3-venv \
        openmpi-bin \
        libopenmpi-dev \
        curl \
    && rm -rf /var/lib/apt/lists/*

# Untrusted programs execute as this user, never as the server's user.
# See backend/executor.py: the kernel exempts root from RLIMIT_NPROC, so a
# program running as root can fork without bound.
RUN useradd --system --no-create-home --shell /usr/sbin/nologin sandbox

ENV VIRTUAL_ENV=/opt/venv \
    PATH=/opt/venv/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1
RUN python3 -m venv "$VIRTUAL_ENV"

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py gunicorn.conf.py index.html ./
COPY backend/ ./backend/
COPY examples/ ./examples/
COPY static/ ./static/

# Job directories are created here at runtime, one per compilation.
ENV OPENMP_WORKDIR=/tmp/openmp_compiler
RUN mkdir -p "$OPENMP_WORKDIR" && chmod 1777 "$OPENMP_WORKDIR"

ENV PORT=5000
EXPOSE 5000

HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
    CMD curl -fsS "http://localhost:${PORT:-5000}/health" || exit 1

# This image intentionally starts as root: the server needs CAP_SETUID and
# CAP_SETGID to drop every compiled program to the unprivileged `sandbox` user,
# which is what makes the per-process rlimits enforceable. docker-compose.yml
# drops every other capability. To run the container as non-root instead, set
# OPENMP_SANDBOX_USER="" and rely on the container pids limit -- user programs
# then share the server's process quota.
CMD ["gunicorn", "--config", "gunicorn.conf.py", "app:app"]
