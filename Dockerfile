FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    LANG=en_US.UTF-8

# Paketler (hem ana hem agent modu için)
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 python3-pip python3-dev \
    openjdk-21-jre-headless \
    gcc make \
    wget curl ca-certificates \
    procps util-linux kmod iproute2 \
    && rm -rf /var/lib/apt/lists/*

# cloudflared
RUN wget -q https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64 \
    -O /usr/local/bin/cloudflared && chmod +x /usr/local/bin/cloudflared

# Python bağımlılıkları
RUN pip3 install --no-cache-dir --break-system-packages \
    flask flask-socketio eventlet psutil

WORKDIR /app

# ── Tüm kaynak dosyaları kopyala (hem ANA hem AGENT modu için) ──
COPY mc_panel.py  ./mc_panel.py
COPY cluster.py   ./cluster.py
COPY main.py      ./main.py
COPY agent.py     ./agent.py
COPY userswap.c   ./userswap.c

# userswap.so derle
RUN gcc -O2 -shared -fPIC -o /app/userswap.so /app/userswap.c \
        -ldl -lpthread -DSWAP_SHARDS=4 -DSHARD_GB=1 \
    && echo "✅ userswap.so hazır ($(du -sh /app/userswap.so | cut -f1))"

# Dizinler
RUN mkdir -p /minecraft/world/region \
             /minecraft/world_nether/DIM-1/region \
             /minecraft/world_the_end/DIM1/region \
             /minecraft/config \
             /mnt/vcluster \
             /tmp/cluster_cache \
             /agent_data/regions/world \
             /agent_data/regions/world_nether \
             /agent_data/regions/world_the_end \
             /agent_data/backups /agent_data/plugins \
             /agent_data/configs /agent_data/chunks \
             /agent_data/paper_cache

EXPOSE 5000 8080 25565

# main.py IS_MAIN kontrolü yapar:
#   RENDER_EXTERNAL_URL == wc-tsgd.onrender.com → ANA mod (panel + MC)
#   diğer URL → AGENT mod (agent.py başlatır)
CMD ["python3", "/app/main.py"]
