FROM debian:bookworm-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    wget curl ca-certificates python3 python3-pip libstdc++6 \
    && rm -rf /var/lib/apt/lists/*

# Veritabani icin asenkron SQLite kutuphanesi (Tak-Calistir icin gerekli)
RUN pip3 install aiosqlite --break-system-packages

# Bore tunnel (Port yonlendirmesi)
RUN BORE_VER=$(curl -s https://api.github.com/repos/ekzhang/bore/releases/latest \
        | grep '"tag_name"' | cut -d'"' -f4) \
    && wget -qO /tmp/bore.tar.gz \
        "https://github.com/ekzhang/bore/releases/download/${BORE_VER}/bore-${BORE_VER}-x86_64-unknown-linux-musl.tar.gz" \
    && tar xzf /tmp/bore.tar.gz -C /usr/local/bin \
    && rm /tmp/bore.tar.gz && chmod +x /usr/local/bin/bore

# Cuberite (Minecraft Sunucu Motoru)
WORKDIR /server
RUN wget -qO /tmp/cuberite.tar.gz \
      "https://download.cuberite.org/linux-x86_64/Cuberite.tar.gz" \
    && tar xzf /tmp/cuberite.tar.gz -C /server \
    && rm /tmp/cuberite.tar.gz \
    && find /server -name "Cuberite" -type f

# Betikleri tasi ve yetki ver
COPY engine.py /engine.py
COPY start.sh  /start.sh
RUN chmod +x /start.sh

# Disariya acilacak portlar
EXPOSE 8080 25565
CMD ["/start.sh"]
