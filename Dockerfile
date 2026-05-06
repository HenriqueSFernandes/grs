FROM python:3.12-slim

# Install nsenter (util-linux) and tc (iproute2) on the sidecar image
RUN apt-get update && \
    apt-get install -y --no-install-recommends util-linux iproute2 && \
    rm -rf /var/lib/apt/lists/*

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

# Copy project files
COPY pyproject.toml uv.lock ./
COPY injector/ ./injector/

# Sync dependencies
RUN uv sync --frozen

ENTRYPOINT ["uv", "run", "python", "-m", "injector"]
