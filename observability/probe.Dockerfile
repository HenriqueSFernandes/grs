FROM python:3.12-slim

RUN apt-get update && \
    apt-get install -y --no-install-recommends iputils-ping && \
    rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir docker>=7.0.0

WORKDIR /workspace

COPY observability/probe.py /workspace/probe.py

ENTRYPOINT ["python", "/workspace/probe.py"]