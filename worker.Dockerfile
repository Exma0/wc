FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive
ENV HOME=/root
ENV LANG=en_US.UTF-8
ENV LC_ALL=en_US.UTF-8
ENV PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin

# ── ADIM 1: Temel araçlar ───────────────────────────────────
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl ca-certificates gnupg lsb-release locales \
    && locale-gen en_US.UTF-8 \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

# ── ADIM 2: Cloudflare Tunnel ──────────────────────────────
RUN curl -fsSL https://pkg.cloudflare.com/cloudflare-main.gpg \
    | gpg --dearmor -o /usr/share/keyrings/cloudflare-main.gpg \
    && echo "deb [signed-by=/usr/share/keyrings/cloudflare-main.gpg] \
    https://pkg.cloudflare.com/cloudflared $(lsb_release -cs) main" \
    > /etc/apt/sources.list.d/cloudflared.list \
    && apt-get update && apt-get install -y cloudflared \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

# ── ADIM 3: Python + NBD araçları ───────────────────────────
# kmod      : modprobe komutu
# nbd-server: NBD disk sunucu
# nbd-client: nbd bağlantı testi için
# socat     : TCP fallback için
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 python3-pip \
    kmod \
    nbd-server \
    nbd-client \
    socat \
    net-tools procps \
    && pip3 install --no-cache-dir flask psutil \
    && pip3 cache purge \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

# nbd modülünü önceden tanıt
RUN mkdir -p /etc/modules-load.d \
    && echo "nbd" >> /etc/modules-load.d/nbd.conf

# ── ADIM 4: Uygulama ─────────────────────────────────────────
# worker.Dockerfile artık main.py'yi destek modunda çalıştırır.
# IS_MAIN = False → RENDER_EXTERNAL_URL != MAIN_SERVER_URL
# Bu sayede tek kod tabanı: nbd-server + WS köprüsü + cloudflared HTTP tüneli
WORKDIR /app
COPY main.py     /app/main.py
COPY mc_panel.py /app/mc_panel.py

EXPOSE 5000

CMD ["python3", "/app/main.py"]
