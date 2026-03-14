FROM debian:bookworm-slim

# Minimal bağımlılıklar
RUN apt-get update && apt-get install -y --no-install-recommends \
    wget curl ca-certificates python3 \
    && rm -rf /var/lib/apt/lists/* \
    && apt-get clean

# bore (TCP tunnel → bore.pub)
RUN BORE_VER=$(curl -s https://api.github.com/repos/ekzhang/bore/releases/latest \
        | grep '"tag_name"' | cut -d'"' -f4) \
    && echo "bore: $BORE_VER" \
    && wget -qO /tmp/bore.tar.gz \
        "https://github.com/ekzhang/bore/releases/download/${BORE_VER}/bore-${BORE_VER}-x86_64-unknown-linux-musl.tar.gz" \
    && tar xzf /tmp/bore.tar.gz -C /usr/local/bin \
    && rm /tmp/bore.tar.gz \
    && chmod +x /usr/local/bin/bore

# Cuberite (resmi canonical download URL — daima güncel)
WORKDIR /server
RUN wget -qO /tmp/cuberite.tar.gz \
        "https://download.cuberite.org/linux-x86_64/Cuberite.tar.gz" \
    && tar xzf /tmp/cuberite.tar.gz -C /server \
    && rm /tmp/cuberite.tar.gz \
    && find /server -name "Cuberite" -type f

# Tek Python dosyası — tüm config + HTTP sunucu burada
COPY server.py /server.py
COPY start.sh  /start.sh
RUN chmod +x /start.sh

EXPOSE 8080

CMD ["/start.sh"]
