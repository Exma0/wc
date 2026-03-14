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
cd /server
if [ -f "Cuberite" ]; then
    BINARY="./Cuberite"
elif [ -f "Server/Cuberite" ]; then
    cd Server; BINARY="./Cuberite"
else
    echo "[HATA] Cuberite binary bulunamadı!"; ls -la; exit 1
fi
chmod +x "$BINARY" 2>/dev/null || true
echo "[✓] Cuberite binary: $BINARY"

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
