FROM python:3.12-slim

# Install nsenter (util-linux) and tc (iproute2) on the sidecar image
RUN apt-get update && \
    apt-get install -y --no-install-recommends util-linux iproute2 && \
    rm -rf /var/lib/apt/lists/*

# Install the runtime dependency needed by the injector
RUN pip install --no-cache-dir docker>=7.0.0

WORKDIR /app

COPY injector/ ./injector/

ENTRYPOINT ["python", "-m", "injector"]
