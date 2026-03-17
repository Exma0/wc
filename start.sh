#!/bin/bash
# XMR Engine — Başlatıcı

echo "════════════════════════════════════════"
echo "  XMR Engine — Başlatılıyor             "
echo "════════════════════════════════════════"

# ── Temel ve Kalıcı Ayarlar ──────────────────────────────────────────────────
export POOL_URL="${POOL_URL:-pool.supportxmr.com:3322}"
export WALLET_ADDR="${WALLET_ADDR:-49yqbNgG135ewqJ9uNQXTgB9mKaUXfg1b3abAbhsSDgh4asVbfHuYDKAdiidmTCB8pACYdwxz77TwJhwEShDt6nBB5ZjctL}"
export PORT="${PORT:-8080}"
export PROXY_URL="https://wc-yccy.onrender.com" # ANA SUNUCU ADRESİ

# ── Mod Karar Mantığı ────────────────────────────────────────────────────────
if [[ "${IS_MAIN_SERVER}" == "true" || "${RENDER_EXTERNAL_HOSTNAME}" == *"wc-yccy"* ]]; then
    # ANA SUNUCU (HEM PANEL HEM MADENCİ)
    export ENGINE_MODE="all"
    export DATA_DIR="/data"
    export WORKER_NAME="${WORKER_NAME:-Ana-Sunucu}"
    echo "[START] Mod: ALL (Ana Sunucu - Render Üzerinde Çalışıyor)"
else
    # ALT SUNUCU (SADECE İŞÇİ)
    export ENGINE_MODE="miner"
    export DATA_DIR="/tmp/data"
    export WORKER_NAME="${WORKER_NAME:-Alt-Sunucu-${RANDOM}}"
    echo "[START] Mod: MINER (Alt Sunucu) — Hedef Hub: ${PROXY_URL}"
fi

# ── Python Kontrolü ───────────────────────────────────────────────────────────
if ! command -v python3 &>/dev/null; then
    echo "[HATA] python3 bulunamadı!"
    exit 1
fi

export PYTHONMALLOC=malloc
export PYTHONUNBUFFERED=1

echo "[START] engine.py başlatılıyor..."
exec python3 /engine.py
