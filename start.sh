#!/bin/bash
# Otomatik başlatıcı — Render hostname'e göre otomatik mod seçer

# Render'daki URL'miz wc-yccy ise otomatik Proxy moduna geç
if [[ "$RENDER_EXTERNAL_HOSTNAME" == *"wc-yccy"* ]]; then
    export ENGINE_MODE="proxy"
    export DATA_DIR="/data"
    echo "[START] Otomatik Proxy modu algilandi: $RENDER_EXTERNAL_HOSTNAME"
else
    # Farklı bir sunucuda çalışıyorsa GameServer moduna geç
    export ENGINE_MODE="gameserver"
    export SERVER_DIR="/server"
    export DATA_DIR="/server/world"
    
    # Ana proxy adresimiz sabit
    export PROXY_URL="https://wc-yccy.onrender.com"
    
    # Etiket: hostname'den otomatik üret (her Render servisi unique hostname alır)
    export SERVER_LABEL="${SERVER_LABEL:-$(hostname)}"
    
    echo "[START] GameServer modu algilandi — Proxy: $PROXY_URL — Etiket: $SERVER_LABEL"
fi

exec python3 /engine.py
