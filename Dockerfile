FROM ubuntu:24.04
# ── Cuberite C++ Minecraft Server (1.8.8 uyumlu) ──────────────
# JVM yok → ~50MB RAM (Paper 400MB yerine)
# Cuberite binary runtime sırasında /minecraft'a indirilir

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    LANG=en_US.UTF-8

# Paketler (hem ana hem agent modu için)
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 python3-pip python3-dev \
    gcc make \
    wget curl ca-certificates \
    procps util-linux kmod iproute2 \
    libstdc++6 libgcc-s1 \
    libssl3 libcrypto3 2>/dev/null || true \
    && apt-get install -y --no-install-recommends libssl-dev 2>/dev/null || true \
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
# userswap.c kaldırıldı — Cuberite C++ kullanılıyor

# userswap kaldırıldı — Cuberite C++ JVM gerektirmiyor

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
             /agent_data/cuberite_cache

EXPOSE 5000 8080 25565

# main.py IS_MAIN kontrolü yapar:
#   RENDER_EXTERNAL_URL == wc-tsgd.onrender.com → ANA mod (panel + MC)
#   diğer URL → AGENT mod (agent.py başlatır)
CMD ["python3", "/app/main.py"]
