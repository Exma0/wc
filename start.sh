#!/bin/bash
export PYTHONUNBUFFERED=1

echo "[SİSTEM] Swap (Sanal RAM) alanı oluşturuluyor (2.5 GB)..."

# 2.5 GB boyutunda swap dosyası oluştur
dd if=/dev/zero of=/swapfile bs=1M count=2560 status=none
chmod 600 /swapfile
mkswap /swapfile

# Swap alanını aktif etmeye çalış
swapon /swapfile

if [ $? -eq 0 ]; then
    echo "[SİSTEM] Başarılı! 2.5 GB Swap alanı aktif."
else
    echo "[SİSTEM] HATA: Swap aktifleştirilemedi! Konteyneri --privileged ile başlattığınızdan emin olun."
fi

echo "[SİSTEM] Sınırsız madenci başlatılıyor..."
# Swap işlemi bitince, madenciyi güvenli kullanıcı (appuser) ile başlatıyoruz
exec su - appuser -c "python3 /app/engine.py"
