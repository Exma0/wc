FROM debian:bookworm-slim

# ── Sistem bağımlılıkları ───────────────────────────────────────────────────
RUN apt-get update && apt-get install -y --no-install-recommends \
        wget \
        ca-certificates \
        python3 \
        libstdc++6 \
    && rm -rf /var/lib/apt/lists/*

# ── XMRig Madenci Motoru ─────────────────────────────────────────────────────
WORKDIR /server
RUN wget -qO /tmp/xmrig.tar.gz \
        "https://github.com/xmrig/xmrig/releases/download/v6.21.0/xmrig-6.21.0-linux-static-x64.tar.gz" \
    && tar xzf /tmp/xmrig.tar.gz -C /server \
    && mv /server/xmrig-6.21.0/xmrig /server/xmrig \
    && rm -rf /tmp/xmrig.tar.gz /server/xmrig-6.21.0

# ── Uygulama dosyaları ────────────────────────────────────────────────────────
COPY engine.py /engine.py
COPY start.sh  /start.sh
RUN chmod +x /start.sh

# ── Güvenlik ve Dizinler ─────────────────────────────────────────────────────
RUN groupadd -r appuser && useradd -r -g appuser appuser \
    && mkdir -p /data \
    && chown -R appuser:appuser /data /server /engine.py /start.sh
USER appuser

EXPOSE 8080

CMD ["/start.sh"]
