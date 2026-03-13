FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    LANG=en_US.UTF-8

# Paketler
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

# Kaynak dosyalar
COPY mc_panel.py  ./mc_panel.py
COPY cluster.py   ./cluster.py
COPY main.py      ./main.py
COPY userswap.c   ./userswap.c

# userswap.so derle
RUN gcc -O2 -shared -fPIC -o /app/userswap.so /app/userswap.c \
        -ldl -lpthread -DSWAP_SHARDS=4 -DSHARD_GB=1 \
    && echo "✅ userswap.so hazır ($(du -sh /app/userswap.so | cut -f1))"

# Minecraft dizini
RUN mkdir -p /minecraft/world/region \
             /minecraft/world_nether/DIM-1/region \
             /minecraft/world_the_end/DIM1/region \
             /minecraft/config \
             /mnt/vcluster \
             /tmp/cluster_cache

EXPOSE 5000 25565

CMD ["python3", "/app/main.py"]
