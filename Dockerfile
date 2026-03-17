FROM python:3.10-slim

# Gerekli paketler: xmrig için (tar, gzip) ve pycryptodome gerekmez ama urllib zaten var
RUN apt-get update && apt-get install -y --no-install-recommends \
    tar \
    gzip \
    && rm -rf /var/lib/apt/lists/*

COPY backup_agent.py /opt/backup_agent.py
COPY start.sh /start.sh
RUN chmod +x /start.sh /opt/backup_agent.py

# Çalışma zamanında indirileceği için ek bir şey yok

CMD ["/start.sh"]
