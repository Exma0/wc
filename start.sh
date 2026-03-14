#!/bin/bash

BORE_ADDR_FILE="/tmp/bore_address.txt"
MC_PORT=25565

echo "================================================"
echo "  🎮 Cuberite Minecraft Sunucu Başlatılıyor"
echo "  Mode: Offline (Crack Girişi Aktif)"
echo "  Platform: Render.com"
echo "================================================"

# ─── 1. Config dosyalarını yaz ──────────────────────
echo "[✓] Config dosyaları yazılıyor..."
python3 /server.py config

# ─── 2. Cuberite binary'yi bul ──────────────────────
MC_BIN=$(find /server -name "Cuberite" -type f | head -1)
if [ -z "$MC_BIN" ]; then
    echo "[HATA] Cuberite binary bulunamadı!"
    find /server -type f | head -30
    exit 1
fi
MC_DIR=$(dirname "$MC_BIN")
chmod +x "$MC_BIN"
echo "[✓] Cuberite: $MC_BIN  |  Dizin: $MC_DIR"

# ─── 3. Dünya sıfırlama — SADECE İLK SEFERINDE ────────
# Yapılar da regions/ içinde saklanır, bu yüzden bir kez sil
# ve bayrak dosyası bırak → bir daha asla silme
#
#   world/regions/      ← terrain + oyuncu yapıları  → İLK SEFERDE SİL
#   world/players/      ← envanter, can, konum       → HİÇ DOKUNMA
#   world/.initialized  ← bayrak dosyası             → sonraki açılışlarda atla
#
FLAG="/server/world/.void_initialized"

if [ ! -f "$FLAG" ]; then
    echo "[✓] İlk başlatma: eski dünya temizleniyor..."
    for WORLD_PATH in "/server/world" "/server/Server/world" "$MC_DIR/world"; do
        if [ -d "$WORLD_PATH" ]; then
            rm -rf "$WORLD_PATH/regions"       2>/dev/null || true
            rm -rf "$WORLD_PATH/nether"        2>/dev/null || true
            rm -rf "$WORLD_PATH/end"           2>/dev/null || true
            rm -f  "$WORLD_PATH"/*.mca         2>/dev/null || true
            rm -f  "$WORLD_PATH"/*.mcr         2>/dev/null || true
            echo "[✓] Eski terrain silindi: $WORLD_PATH"
        fi
    done
    mkdir -p /server/world/players
    touch "$FLAG"
    echo "[✓] Yeni void dünya hazır. Bayrak bırakıldı → bir daha silinmeyecek."
else
    echo "[✓] Dünya verisi korunuyor (yapılar + oyuncu verisi güvende)."
fi

# ─── 4. HTTP Durum Sayfası ──────────────────────────
echo "[✓] HTTP durum sayfası başlatılıyor (port 8080)..."
python3 /server.py http &

# ─── 4. bore.pub Tunnel (arka planda, yeniden bağlanan) ─
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
    echo "[!] bore kesildi, 5sn sonra yeniden bağlanılıyor..."
    sleep 5
  done
) &

# ─── 5. stdin için kalıcı FIFO oluştur ──────────────
# SORUN: Docker'da TTY yok → Cuberite stdin EOF alır → hemen kapanır
# ÇÖZÜM: mkfifo ile asla kapanmayan bir pipe stdin olarak ver
FIFO=/tmp/mc_stdin
rm -f "$FIFO"
mkfifo "$FIFO"
# Bu process fifo'yu sonsuza kadar açık tutar
tail -f /dev/null > "$FIFO" &

echo "================================================"
echo "  Servisler hazır, Cuberite döngüsü başlıyor..."
echo "================================================"

# ─── 6. Cuberite döngüsü — crash olursa yeniden başlat ─
while true; do
    echo "[MC] Cuberite başlatılıyor..."
    cd "$MC_DIR"
    # stdin olarak fifo'yu bağla → EOF almaz, kapanmaz
    "$MC_BIN" < "$FIFO" &
    MC_PID=$!
    echo "[MC] PID: $MC_PID"
    wait $MC_PID
    echo "[MC] Cuberite kapandı. 5sn sonra yeniden başlıyor..."
    sleep 5
done
