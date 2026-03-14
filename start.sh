#!/bin/bash
set -e

BORE_ADDR_FILE="/tmp/bore_address.txt"
MC_PORT=25565

echo "================================================"
echo "  🎮 Cuberite Minecraft Sunucu Başlatılıyor"
echo "  Mode: Offline (Crack Girişi Aktif)"
echo "  Platform: Render.com"
echo "================================================"

# ─── 1. Config dosyalarını yaz (server.py → .ini) ───
echo "[✓] Config dosyaları yazılıyor..."
python3 /server.py config

# ─── 2. Cuberite binary'yi bul ──────────────────────
# find komutuyla nerede olursa olsun bul
MC_BIN=$(find /server -name "Cuberite" -type f | head -1)
if [ -z "$MC_BIN" ]; then
    echo "[HATA] Cuberite binary bulunamadı!"
    find /server -type f | head -30
    exit 1
fi
MC_DIR=$(dirname "$MC_BIN")
chmod +x "$MC_BIN"
cd "$MC_DIR"
BINARY="$MC_BIN"
echo "[✓] Cuberite binary: $BINARY (dizin: $MC_DIR)"

# ─── 3. HTTP Durum Sayfası (port 8080) ──────────────
echo "[✓] HTTP durum sayfası başlatılıyor..."
python3 /server.py http &
HTTP_PID=$!

# ─── 4. Cuberite Başlat ─────────────────────────────
echo "[✓] Cuberite başlatılıyor..."
"$BINARY" &
MC_PID=$!
sleep 5

# ─── 5. bore.pub Tunnel ─────────────────────────────
echo "[✓] bore.pub tunnel başlatılıyor (port $MC_PORT)..."
(
  while true; do
    rm -f "$BORE_ADDR_FILE"
    bore local "$MC_PORT" --to bore.pub 2>&1 | while IFS= read -r line; do
      echo "[BORE] $line"
      ADDR=$(echo "$line" | grep -oE "bore\.pub:[0-9]+" || true)
      if [ -n "$ADDR" ]; then
        echo "$ADDR" > "$BORE_ADDR_FILE"
        echo "[✓✓] BAĞLANTI ADRESİ: $ADDR"
      fi
    done
    echo "[!] bore kesildi, yeniden bağlanılıyor..."; sleep 3
  done
) &

# ─── 6. Bekle ───────────────────────────────────────
echo "================================================"
echo "  Çalışıyor → Cuberite:$MC_PID  HTTP:$HTTP_PID"
echo "  Adres: https://<servis>.onrender.com"
echo "================================================"
wait $MC_PID
echo "[!] Cuberite kapandı, yeniden başlatılıyor..."
exit 1
