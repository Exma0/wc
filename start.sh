#!/bin/bash
# Otomatik baslatici (LF formatinda kaydedilmeli!)

echo "[SISTEM] Hub Mimarisi Baslatma dizisi basliyor..."

# MySQL degiskenlerinin tanimli olup olmadigini kontrol et
if [ -z "$DB_HOST" ]; then
    echo "[UYARI] DB_HOST tanimli degil! Veritabani baglantisi basarisiz olabilir."
fi

if [[ "$RENDER_EXTERNAL_HOSTNAME" == *"wc-yccy"* ]]; then
    export ENGINE_MODE="all"
    export DATA_DIR="/data"
    echo "[START] Otomatik ALL (Proxy+Game) modu algilandi: $RENDER_EXTERNAL_HOSTNAME"
else
    export ENGINE_MODE="gameserver"
    export SERVER_DIR="/server"
    export DATA_DIR="/server/world"
    export PROXY_URL="https://wc-yccy.onrender.com"
    echo "[START] GameServer modu algilandi — Proxy: $PROXY_URL"
fi

# Bellek tahsisini optimize ederek sinirda rahatlamasini saglar
export PYTHONMALLOC=malloc

exec python3 /engine.py
