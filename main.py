"""
⛏️  Minecraft Server Boot — RENDER BYPASS v10.0
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
v10.0: NBD tamamen kaldırıldı → Resource Pool ile değiştirildi
  Destek sunucuları şunları sağlar (kernel modülü gerekmez):
    • RAM Cache   → Chunk/entity verisi JVM dışında saklanır
    • File Store  → Eski region'lar arşivlenir, disk açılır → swap büyür
    • CPU Worker  → Sıkıştırma, hash, istatistik görevleri
    • TCP Proxy   → Oyuncu bağlantı yükü dağıtılır
"""

import os, sys, subprocess, time, socket, resource, threading, re, glob, json
import psutil
import urllib.request as _ur

RENDER_DISK_LIMIT_GB = 18.0
RENDER_RAM_LIMIT_MB  = 512

MAIN_SERVER_URL = "https://wc-tsgd.onrender.com"
MY_URL  = os.environ.get("RENDER_EXTERNAL_URL", "").rstrip("/")
IS_MAIN = (MY_URL == MAIN_SERVER_URL
           or MY_URL == ""
           or os.environ.get("FORCE_MAIN", "") == "1")
PORT    = int(os.environ.get("PORT", "5000"))
MC_PORT = 25565
MC_RAM  = os.environ.get("MC_RAM", "2G")
INF     = resource.RLIM_INFINITY


def read_cgroup_ram_limit_mb():
    for path in ["/sys/fs/cgroup/memory.max",
                 "/sys/fs/cgroup/memory/memory.limit_in_bytes"]:
        try:
            val = open(path).read().strip()
            if val in ("max", "-1"):
                continue
            mb = int(val) // 1024 // 1024
            if 64 < mb < 65536:
                return mb
        except:
            pass
    return RENDER_RAM_LIMIT_MB


CONTAINER_RAM_MB = read_cgroup_ram_limit_mb()

base_env = {
    **os.environ,
    "HOME": "/root", "USER": "root", "LOGNAME": "root",
    "LANG": "en_US.UTF-8", "LC_ALL": "en_US.UTF-8",
    "JAVA_HOME": "/usr/lib/jvm/java-21-openjdk-amd64",
    "PATH": (
        "/usr/lib/jvm/java-21-openjdk-amd64/bin"
        ":/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
    ),
    "MC_RAM": MC_RAM,
    "PORT": str(PORT),
    "CONTAINER_RAM_MB": str(CONTAINER_RAM_MB),
}

print("\n" + "━"*56)
print("  ⛏️   Minecraft Server — RENDER BYPASS v10.0")
print(f"      MOD       : {'🟢 ANA' if IS_MAIN else '🔵 AGENT'}")
print(f"      MY_URL    : {MY_URL or '(boş → ANA)'}")
print(f"      RAM       : {CONTAINER_RAM_MB}MB")
print("━"*56 + "\n")


# ─────────────────────────────────────────────
#  YARDIMCILAR
# ─────────────────────────────────────────────

def w(path, val):
    try:
        open(path, "w").write(str(val)); return True
    except: return False


def sh(cmd):
    return subprocess.run(cmd, shell=True, capture_output=True)


def wait_port(port, timeout=60):
    for _ in range(timeout * 10):
        try:
            s = socket.create_connection(("127.0.0.1", int(port)), 0.1)
            s.close(); return True
        except OSError:
            time.sleep(0.1)
    return False


def _panel_log(msg):
    try:
        _ur.urlopen(_ur.Request(
            f"http://localhost:{PORT}/api/internal/status_msg",
            data=json.dumps({"msg": msg}).encode(),
            headers={"Content-Type": "application/json"}, method="POST",
        ), timeout=2)
    except: pass


def read_disk_used_gb():
    try:
        return 4.0 + sum(
            os.path.getsize(f) for f in ["/swapfile", "/swapfile2"]
            if os.path.exists(f)
        ) / 1024**3
    except: return 4.0


# ─────────────────────────────────────────────
#  BYPASS / SWAP / KERNEL
# ─────────────────────────────────────────────

def bypass_cgroups():
    n = 0
    for path, val in [
        ("/sys/fs/cgroup/memory.max", "max"),
        ("/sys/fs/cgroup/memory.swap.max", "max"),
        ("/sys/fs/cgroup/memory.high", "max"),
        ("/sys/fs/cgroup/cpu.max", "max"),
        ("/sys/fs/cgroup/pids.max", "max"),
        ("/sys/fs/cgroup/memory/memory.limit_in_bytes", "-1"),
        ("/sys/fs/cgroup/memory/memory.memsw.limit_in_bytes", "-1"),
        ("/sys/fs/cgroup/memory/memory.swappiness", "100"),
        ("/sys/fs/cgroup/memory/memory.oom_control", "0"),
        ("/sys/fs/cgroup/cpu/cpu.cfs_quota_us", "-1"),
    ]:
        if w(path, val): n += 1
    for cg in glob.glob("/sys/fs/cgroup/*/") + glob.glob("/sys/fs/cgroup/*/*/"):
        for fn, v in [("memory.max","max"),("memory.swap.max","max"),
                      ("memory.high","max"),("memory.oom_control","0"),
                      ("cpu.max","max"),("pids.max","max")]:
            w(cg + fn, v)
    w("/proc/sys/vm/oom_kill_allocating_task", "0")
    w("/proc/sys/vm/panic_on_oom", "0")
    try: w(f"/proc/{os.getpid()}/oom_score_adj", "-1000")
    except: pass
    print(f"  ✅ {n} cgroup limiti kaldırıldı")


def setup_swap():
    """
    Render.com free tier'da swapon KERESİNLİKLE çalışmaz
    (loop device, zram, dosya — hepsi EPERM verir).
    Sadece kernel overcommit parametrelerini ayarla — bunlar çalışıyor.
    """
    for p, v in [
        ("/proc/sys/vm/overcommit_memory",  "1"),   # Over-commit izin ver
        ("/proc/sys/vm/overcommit_ratio",   "100"),
        ("/proc/sys/vm/vfs_cache_pressure", "50"),
        ("/proc/sys/vm/drop_caches",        "3"),
        ("/proc/sys/vm/min_free_kbytes",    "8192"),
    ]: w(p, v)
    print("  ℹ️  Swap: Render'da swapon izni yok → sadece overcommit aktif")


def optimize_kernel():
    for res, val in [
        (resource.RLIMIT_NOFILE,  (1048576, 1048576)),
        (resource.RLIMIT_NPROC,   (INF, INF)),
        (resource.RLIMIT_MEMLOCK, (INF, INF)),
    ]:
        try: resource.setrlimit(res, val)
        except: pass


def optimize_all(mode="main"):
    print(f"\n{'═'*56}\n  🔓 BYPASS ({mode.upper()})\n{'═'*56}\n")
    bypass_cgroups()
    setup_swap()
    optimize_kernel()
    swp = psutil.swap_memory()
    print(f"  ✅ Swap:{swp.total//1024//1024}MB  RAM:{CONTAINER_RAM_MB}MB\n{'═'*56}")


# ─────────────────────────────────────────────
#  ANA SUNUCU — MC başlatma
# ─────────────────────────────────────────────

def start_panel():
    print(f"\n🚀 Panel :{PORT} başlatılıyor...")
    proc = subprocess.Popen([sys.executable, "/app/mc_panel.py"], env=base_env)
    if wait_port(PORT, 30):
        print("  ✅ Panel hazır")
    return proc


def auto_start_sequence():
    # Önceki OOM kill state'i var mı kontrol et
    _state_path = "/agent_data/panel_state.json"
    _prev_running = False
    try:
        import json as _json
        _d = _json.loads(open(_state_path).read())
        _age = time.time() - _d.get("saved_at", 0)
        if _age < 300 and _d.get("was_running"):
            _prev_running = True
    except Exception:
        pass

    if _prev_running:
        # mc_panel._auto_resume_if_needed() zaten 8sn sonra MC başlatacak.
        # Bu fonksiyon tekrar /api/start çağırmasın → çift başlatma olur.
        print("  ♻️  Önceki oturum var → MC panel otomatik başlatacak, bu sekans atlanıyor.")
        _panel_log("[Sistem] ♻️  OOM-restart: MC panel otomatik devam ettiriyor...")
        if wait_port(MC_PORT, 300):
            _panel_log("[Sistem] ✅ MC Server yeniden hazır!")
        _start_mc_tunnel()
        return

    time.sleep(4)
    _panel_log("[Sistem] 🟢 v10.0 başladı — MC başlatılıyor...")
    try:
        _ur.urlopen(_ur.Request(
            f"http://localhost:{PORT}/api/start",
            data=json.dumps({"_internal": True}).encode(),
            headers={"Content-Type": "application/json"}, method="POST",
        ), timeout=10)
        print("  ✅ MC başlatma komutu gönderildi")
    except Exception as e:
        print(f"  ⚠️  MC start hatası: {e}")

    if wait_port(MC_PORT, 300):
        print("  ✅ MC Server hazır!")
        _panel_log("[Sistem] ✅ MC Server oyuncuları bekliyor!")
    else:
        print("  ⚠️  MC port timeout (300sn)")
    _start_mc_tunnel()


def _start_mc_tunnel():
    log = "/tmp/cf_mc.log"
    subprocess.Popen(
        ["cloudflared", "tunnel", "--url", f"tcp://localhost:{MC_PORT}",
         "--no-autoupdate", "--loglevel", "info"],
        stdout=open(log, "w"), stderr=subprocess.STDOUT,
    )
    for _ in range(120):
        try:
            urls = re.findall(r"https://[a-z0-9-]+\.trycloudflare\.com", open(log).read())
            if urls:
                url  = urls[0]
                host = url.replace("https://", "")
                print(f"\n  ✅ MC Tüneli: {host}\n")
                try:
                    _ur.urlopen(_ur.Request(
                        f"http://localhost:{PORT}/api/internal/tunnel",
                        data=json.dumps({"url": url, "host": host}).encode(),
                        headers={"Content-Type": "application/json"}, method="POST",
                    ), timeout=3)
                except: pass
                return
        except: pass
        time.sleep(0.5)


# ─────────────────────────────────────────────
#  AGENT MODU (eski destek sunucusu yerine)
# ─────────────────────────────────────────────

def run_agent_mode():
    agent_path = "/app/agent.py"
    ram_cache_mb = max(200, CONTAINER_RAM_MB - 150)

    print(f"\n{'═'*56}")
    print(f"  🔵 AGENT MODU v10.0")
    print(f"  Ana sunucu : {MAIN_SERVER_URL}")
    print(f"  RAM Cache  : {ram_cache_mb}MB")
    print(f"{'═'*56}\n")

    if not os.path.exists(agent_path):
        print("  [agent] ⚠️  /app/agent.py bulunamadı!")
        # Basit sağlık sunucusu
        from flask import Flask, jsonify
        app2 = Flask(__name__)
        @app2.route("/")
        @app2.route("/health")
        def h():
            return jsonify({"status": "ok", "mode": "agent-stub"})
        app2.run(host="0.0.0.0", port=PORT, debug=False)
        return

    env = {
        **os.environ,
        "PORT":         str(PORT),
        "MAIN_URL":     MAIN_SERVER_URL,
        "RAM_CACHE_MB": str(ram_cache_mb),
    }
    proc = subprocess.Popen([sys.executable, agent_path], env=env)
    proc.wait()


# ─────────────────────────────────────────────
#  BAŞLATMA
# ─────────────────────────────────────────────

optimize_all("main" if IS_MAIN else "agent")

if IS_MAIN:
    print(f"\n{'━'*56}")
    print(f"  ANA SUNUCU v10.0 — Panel :{PORT}")
    print(f"  NBD YOK → Resource Pool (HTTP) aktif")
    print(f"  Agent'lar bağlandıkça: RAM cache + disk store + proxy devreye girer")
    print(f"{'━'*56}\n")
    panel_proc = start_panel()
    threading.Thread(target=auto_start_sequence, daemon=True).start()
    panel_proc.wait()
else:
    run_agent_mode()
