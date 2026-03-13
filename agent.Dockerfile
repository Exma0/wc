FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 python3-pip \
    procps util-linux \
    && rm -rf /var/lib/apt/lists/*

RUN pip3 install --no-cache-dir --break-system-packages \
    flask eventlet psutil

WORKDIR /app
COPY agent.py ./agent.py

RUN mkdir -p /agent_data/regions/world \
             /agent_data/regions/world_nether \
             /agent_data/regions/world_the_end \
             /agent_data/backups \
             /agent_data/plugins \
             /agent_data/configs \
             /agent_data/chunks \
             /agent_data/paper_cache

EXPOSE 8080

CMD ["python3", "/app/agent.py"]
