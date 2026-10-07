FROM python:3.12-slim

# Keep Python output unbuffered
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# Install small set of OS build deps required by some Python packages (napalm/drivers may need them).
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    gcc \
    libssl-dev \
    libffi-dev \
    git \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Install runtime dependencies directly without building the Python package.
RUN pip install --no-cache-dir --upgrade pip setuptools wheel

# Install the backend runtime dependencies.
RUN pip install --no-cache-dir \
    "nornir==3.5.0" \
    "nornir-napalm" \
    "mcp[cli]==1.15.0" \
    "sse-starlette"

# Copy the stdio backend; .dockerignore excludes the unused HTTP entrypoints.
COPY . /app

# Create a non-root user and fix permissions
RUN useradd -m appuser || true && chown -R appuser:appuser /app
USER appuser

# Claude Code starts each stdio session through docker exec.
CMD ["sleep", "infinity"]
