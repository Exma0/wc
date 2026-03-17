#!/bin/bash
# WC Network Engine — Başlatıcı
# ÖNEMLI: Bu dosya LF (Unix) satır sonu formatında kaydedilmelidir.
# Windows'ta düzenlendiyse: dos2unix start.sh ile dönüştürün.

echo "════════════════════════════════════════"
echo "  WC Network Engine — Başlatma Dizisi  "
echo "════════════════════════════════════════"
echo "[$(date '+%H:%M:%S')] Ortam: ${RENDER_EXTERNAL_HOSTNAME:-lokal}"

# ── Mod Tespiti ───────────────────────────────────────────────────────────────
if [[ "${RENDER_EXTERNAL_HOSTNAME}" == *"wc-yccy"* ]]; then
    export ENGINE_MODE="all"
    export DATA_DIR="${DATA_DIR:-/data}"
    echo "[START] Mod: ALL (Ana Hub) — DATA_DIR: ${DATA_DIR}"
else
    export ENGINE_MODE="gameserver"
    export SERVER_DIR="${SERVER_DIR:-/server}"
    export DATA_DIR="${DATA_DIR:-/server/world}"
    export PROXY_URL="${PROXY_URL:-https://wc-yccy.onrender.com}"
    echo "[START] Mod: GAMESERVER (Alt Sunucu) — Proxy: ${PROXY_URL}"
fi

# ── Dizin Hazırlığı ───────────────────────────────────────────────────────────
mkdir -p "${DATA_DIR}" "${DATA_DIR}/players" 2>/dev/null || true
echo "[START] Veri dizini hazır: ${DATA_DIR}"

# ── Python Kontrolü ───────────────────────────────────────────────────────────
if ! command -v python3 &>/dev/null; then
    echo "[HATA] python3 bulunamadı! Docker image eksik veya bozuk."
    exit 1
fi

if [[ ! -f /engine.py ]]; then
    echo "[HATA] /engine.py bulunamadı! Dosyanın container'a kopyalandığını doğrulayın."
    exit 1
fi

# ── Bellek Optimizasyonu ──────────────────────────────────────────────────────
export PYTHONMALLOC=malloc
export PYTHONUNBUFFERED=1

# ── Engine Başlat ─────────────────────────────────────────────────────────────
echo "[START] engine.py başlatılıyor..."
exec python3 /engine.py
