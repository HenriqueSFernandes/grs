FROM python:3.12-slim

RUN apt-get update && \
    apt-get install -y --no-install-recommends util-linux iproute2 iputils-ping && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY Dockerfile .
COPY pyproject.toml .
COPY README.md .
COPY injector/ ./injector/
RUN pip install --no-cache-dir .

ENTRYPOINT ["python", "-m", "injector"]
