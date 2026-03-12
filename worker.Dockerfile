FROM ubuntu:22.04
ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y \
    python3 python3-pip \
    nbd-server nbd-client \
    socat netcat-openbsd \
    curl wget \
    && pip3 install flask psutil \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

# cloudflared
RUN curl -fsSL https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64 \
    -o /usr/local/bin/cloudflared && chmod +x /usr/local/bin/cloudflared

WORKDIR /app
COPY worker.py .

EXPOSE 5000
CMD ["python3", "worker.py"]
