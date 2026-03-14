#!/bin/bash
# Otomatik baslatici (LF formatinda kaydedilmeli!)

echo "[SISTEM] Baslatma dizisi basliyor..."

if [[ "$RENDER_EXTERNAL_HOSTNAME" == *"wc-yccy"* ]]; then
    export ENGINE_MODE="all"
    export DATA_DIR="/data"
    echo "[START] Otomatik ALL modu algilandi: $RENDER_EXTERNAL_HOSTNAME"
else
    export ENGINE_MODE="gameserver"
    export SERVER_DIR="/server"
    export DATA_DIR="/server/world"
    export PROXY_URL="https://wc-yccy.onrender.com"
    export SERVER_LABEL="${RENDER_EXTERNAL_HOSTNAME:-$(hostname)}"
    echo "[START] GameServer modu algilandi — Proxy: $PROXY_URL — Etiket: $SERVER_LABEL"
fi

# Bellek tahsisini optimize ederek sinirda rahatlamasini saglar
export PYTHONMALLOC=malloc

exec python3 /engine.py
