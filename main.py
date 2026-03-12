"""
⛏️  Minecraft Server Boot — RENDER BYPASS v9.1
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
FIX v9.1:
  - try_connect_worker: event yerine panel API poll
  - cgroup RAM okuma düzeltildi
"""

import os, sys, subprocess, time, socket, resource, threading, re, glob
import psutil

RENDER_RAM_LIMIT_MB  = 512
RENDER_DISK_LIMIT_GB = 18.0

def read_cgroup_ram_limit_mb():
    for path in [
        "/sys/fs/cgroup/memory.max",
        "/sys/fs/cgroup/memory/memory.limit_in_bytes",
    ]:
        try:
            val = open(path).read().strip()
            if val in ("max", "-1"):
                continue
            limit_mb = int(val) // 1024 // 1024
            if 64 < limit_mb < 65536:
                return limit_mb
        except: pass
    return RENDER_RAM_LIMIT_MB

def read_actual_disk_used_gb():
    try:
        total = 0
        for f in ["/nbd_disk.img", "/swapfile", "/tmp/nbd_ram.img"]:
            if os.path.exists(f):
                total += os.path.getsize(f)
        base_gb = 4.0
        return base_gb + total / 1024**3
    except:
        return 4.0

CONTAINER_RAM_MB = read_cgroup_ram_limit_mb()

MAIN_SERVER_URL = "https://wc-tsgd.onrender.com"
MY_URL  = os.environ.get("RENDER_EXTERNAL_URL", "").rstrip("/")
IS_MAIN = (MY_URL == MAIN_SERVER_URL or MY_URL == ""
           or os.environ.get("FORCE_MAIN", "") == "1")

PORT    = int(os.environ.get("PORT", "5000"))
MC_PORT = 25565
MC_RAM  = os.environ.get("MC_RAM", "2G")

print("\n" + "━"*56)
print("  ⛏️   Minecraft Server — RENDER BYPASS v9.1")
print(f"      MOD      : {'🟢 ANA SUNUCU' if IS_MAIN else '🔵 DESTEK SUNUCUSU'}")
print(f"      RAM LİMİT: {CONTAINER_RAM_MB}MB  (Render: 512MB)")
print(f"      DISK LİMİT: {RENDER_DISK_LIMIT_GB}GB  (Render sabit)")
print("━"*56 + "\n")

base_env = {
    **os.environ,
    "HOME": "/root", "USER": "root", "LOGNAME": "root",
    "LANG": "en_US.UTF-8", "LC_ALL": "en_US.UTF-8",
    "JAVA_HOME": "/usr/lib/jvm/java-21-openjdk-amd64",
    "PATH": "/usr/lib/jvm/java-21-openjdk-amd64/bin"
            ":/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
    "MC_RAM": MC_RAM, "PORT": str(PORT),
    "CONTAINER_RAM_MB": str(CONTAINER_RAM_MB),
}
INF = resource.RLIM_INFINITY

def w(path, val):
    try:
        with open(path, "w") as f: f.write(str(val))
        return True
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

def calc_swap_budget_mb(mode="main"):
    if mode != "main":
        return 0
    used_gb  = read_actual_disk_used_gb()
    reserve  = 4.0 + 3.0
    available = RENDER_DISK_LIMIT_GB - used_gb - reserve
    swap_gb   = min(3.0, max(0.0, available))
    return int(swap_gb * 1024)

def calc_nbd_disk_gb():
    used_gb   = read_actual_disk_used_gb()
    available = RENDER_DISK_LIMIT_GB - used_gb - 3.0
    nbd_gb    = min(11.0, max(0.5, available))
    return nbd_gb

def calc_ram_disk_mb():
    system_mb    = 150
    safety_mb    = 62
    available_mb = CONTAINER_RAM_MB - system_mb - safety_mb
    ram_disk_mb  = min(200, max(0, available_mb))
    return ram_disk_mb

def bypass_cgroups():
    print("  [cgroup] Limitler kaldırılıyor...")
    n = 0
    for path, val in [
        ("/sys/fs/cgroup/memory.max",      "max"),
        ("/sys/fs/cgroup/memory.swap.max", "max"),
        ("/sys/fs/cgroup/memory.high",     "max"),
        ("/sys/fs/cgroup/cpu.max",         "max"),
        ("/sys/fs/cgroup/pids.max",        "max"),
        ("/sys/fs/cgroup/memory/memory.limit_in_bytes",       "-1"),
        ("/sys/fs/cgroup/memory/memory.memsw.limit_in_bytes", "-1"),
        ("/sys/fs/cgroup/memory/memory.soft_limit_in_bytes",  "-1"),
        ("/sys/fs/cgroup/memory/memory.swappiness",           "100"),
        ("/sys/fs/cgroup/memory/memory.oom_control",          "0"),
        ("/sys/fs/cgroup/cpu/cpu.cfs_quota_us",               "-1"),
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
    print(f"  ✅ cgroup → {n} limit kaldırıldı")

def setup_swap(mode="main"):
    print("  [swap] Kurulum başlıyor...")

    sh("modprobe zram num_devices=1 2>/dev/null")
    zram_mb = 128
    w("/sys/block/zram0/comp_algorithm", "lz4")
    if w("/sys/block/zram0/disksize", f"{zram_mb}M"):
        if sh("mkswap /dev/zram0 && swapon -p 100 /dev/zram0").returncode == 0:
            print(f"  ✅ zram: {zram_mb}MB")

    if mode == "main":
        swap_mb = calc_swap_budget_mb(mode)
        if swap_mb >= 256:
            swap_file = "/swapfile"
            print(f"  💾 Swap dosyası: {swap_mb}MB")
            if os.path.exists(swap_file):
                sh(f"swapoff {swap_file} 2>/dev/null")
                try: os.remove(swap_file)
                except: pass
            r = sh(f"fallocate -l {swap_mb}M {swap_file}")
            if r.returncode != 0:
                sh(f"dd if=/dev/zero of={swap_file} bs=64M "
                   f"count={max(1, swap_mb//64)} status=none")
            sh(f"chmod 600 {swap_file} && mkswap -f {swap_file}")
            r2 = sh(f"swapon -p 0 {swap_file}")
            if r2.returncode == 0:
                print(f"  ✅ Swap dosyası aktif: {swap_mb}MB")
            else:
                print(f"  ⚠️  swapon: {r2.stderr.decode().strip()}")
                try: os.remove(swap_file)
                except: pass
        else:
            print(f"  ⚠️  Disk bütçesi yetersiz — sadece zram")
    else:
        print("  ℹ️  Destek modu — swap yok")

    for path, val in [
        ("/proc/sys/vm/swappiness",             "100"),
        ("/proc/sys/vm/vfs_cache_pressure",     "200"),
        ("/proc/sys/vm/overcommit_memory",      "1"),
        ("/proc/sys/vm/overcommit_ratio",       "100"),
        ("/proc/sys/vm/page-cluster",           "0"),
        ("/proc/sys/vm/drop_caches",            "3"),
        ("/proc/sys/vm/watermark_boost_factor", "0"),
        ("/proc/sys/vm/min_free_kbytes",        "32768"),
    ]:
        w(path, val)

    swp = psutil.swap_memory()
    print(f"  🎯 Swap toplam: {swp.total//1024//1024}MB")

def optimize_kernel():
    for res, val in [
        (resource.RLIMIT_NOFILE,  (1048576, 1048576)),
        (resource.RLIMIT_NPROC,   (INF, INF)),
        (resource.RLIMIT_MEMLOCK, (INF, INF)),
    ]:
        try: resource.setrlimit(res, val)
        except: pass
    for p, v in [
        ("/proc/sys/fs/file-max",           "2097152"),
        ("/proc/sys/net/core/somaxconn",    "65535"),
        ("/proc/sys/net/ipv4/tcp_tw_reuse", "1"),
        ("/sys/kernel/mm/transparent_hugepage/enabled", "madvise"),
    ]:
        w(p, v)

def optimize_all(mode="main"):
    print("\n" + "═"*56)
    print(f"  🔓 BYPASS + OPTİMİZASYON ({mode.upper()} MODU)")
    print("═"*56 + "\n")
    bypass_cgroups()
    print()
    setup_swap(mode)
    optimize_kernel()
    swp  = psutil.swap_memory()
    print("\n" + "═"*56)
    print(f"  RAM LİMİT  : {CONTAINER_RAM_MB}MB (cgroup)")
    print(f"  SWAP       : {swp.total//1024//1024}MB")
    print(f"  DISK LİMİT : {RENDER_DISK_LIMIT_GB}GB (Render)")
    print("═"*56)


# ══════════════════════════════════════════════════════════════
#  ANA SUNUCU
# ══════════════════════════════════════════════════════════════

def start_panel():
    print(f"\n🚀 Panel başlatılıyor (:{PORT})...")
    proc = subprocess.Popen([sys.executable, "/app/mc_panel.py"], env=base_env)
    if wait_port(PORT, 30):
        print(f"  ✅ Panel hazır → http://0.0.0.0:{PORT}")
    else:
        print("  ⚠️  Panel başlıyor...")
    return proc


def auto_start_sequence():
    time.sleep(2)
    print("\n⛏️  Minecraft Server başlatılıyor...")
    try:
        import urllib.request
        req = urllib.request.Request(
            f"http://localhost:{PORT}/api/start",
            data=b"{}", headers={"Content-Type": "application/json"}, method="POST"
        )
        urllib.request.urlopen(req, timeout=10)
        print("  ✅ MC başlatma komutu gönderildi")
    except Exception as e:
        print(f"  ⚠️  {e}")

    print("  ⏳ MC Server bekleniyor (max 5 dk)...")
    if wait_port(MC_PORT, 300):
        print("  ✅ MC Server hazır!")
    else:
        print("  ⚠️  MC portu zaman aşımı")

    print("\n🌐 Cloudflare Tunnel...")
    log_file = "/tmp/cf_mc.log"
    subprocess.Popen([
        "cloudflared", "tunnel",
        "--url", f"tcp://localhost:{MC_PORT}",
        "--no-autoupdate", "--loglevel", "info",
    ], stdout=open(log_file, "w"), stderr=subprocess.STDOUT)

    for _ in range(120):
        try:
            content = open(log_file).read()
            urls = re.findall(r'https://[a-z0-9-]+\.trycloudflare\.com', content)
            if urls:
                import json as _j, urllib.request as _ur
                tunnel_url = urls[0]
                host = tunnel_url.replace("https://", "")
                print(f"\n  ✅ MC Sunucu Adresi: {host}\n")
                try:
                    data = _j.dumps({"url": tunnel_url, "host": host}).encode()
                    req2 = _ur.Request(
                        f"http://localhost:{PORT}/api/internal/tunnel",
                        data=data, headers={"Content-Type": "application/json"}, method="POST"
                    )
                    _ur.urlopen(req2, timeout=3)
                except: pass
                return
        except: pass
        time.sleep(0.5)
    print("  ⚠️  Tunnel URL alınamadı")


def connect_worker_nbd(host: str, tunnel_port: int = 10810):
    print(f"\n  [worker-nbd] Bağlanılıyor: {host}...")
    sh("modprobe nbd max_part=0 2>/dev/null")

    cf_proc = subprocess.Popen([
        "cloudflared", "access", "tcp",
        "--hostname", host,
        "--url", f"localhost:{tunnel_port}",
    ], stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    time.sleep(4)

    connected = False

    ret_ram = sh(f"nbd-client localhost {tunnel_port} /dev/nbd0 "
                 f"-N ram -b 4096 -t 60 2>&1")
    if ret_ram.returncode == 0:
        sh("mkswap /dev/nbd0")
        if sh("swapon -p 10 /dev/nbd0").returncode == 0:
            print(f"  ✅ Destek RAM diski swap'a eklendi (öncelik:10)")
            connected = True

    ret_disk = sh(f"nbd-client localhost {tunnel_port} /dev/nbd1 "
                  f"-N disk -b 4096 -t 60 2>&1")
    if ret_disk.returncode == 0:
        sh("mkswap /dev/nbd1")
        if sh("swapon -p 5 /dev/nbd1").returncode == 0:
            print(f"  ✅ Destek disk swap'a eklendi (öncelik:5)")
            connected = True

    if connected:
        swp = psutil.swap_memory()
        print(f"  🎯 YENİ SWAP TOPLAM: {swp.total//1024//1024}MB")
    else:
        cf_proc.terminate()
    return connected


# ══════════════════════════════════════════════════════════════
#  FIX: Panel API üzerinden worker polling (cross-process safe)
# ══════════════════════════════════════════════════════════════

def try_connect_worker():
    import urllib.request, json as _j

    # Env'den direkt host varsa kullan
    host = os.environ.get("WORKER_HOST", "").strip()
    if host:
        print(f"  [worker] WORKER_HOST env: {host}")
        connect_worker_nbd(host)
        return

    print("  [worker] Panel API üzerinden destek sunucusu bekleniyor (120sn)...")

    # Panel hazır olana kadar bekle
    for _ in range(30):
        try:
            urllib.request.urlopen(f"http://localhost:{PORT}/", timeout=2)
            break
        except: time.sleep(1)

    # Panel API'yi poll et — subprocess sınırını aş
    for i in range(120):
        try:
            resp = urllib.request.urlopen(
                f"http://localhost:{PORT}/api/worker/status", timeout=3
            )
            data = _j.loads(resp.read())
            nodes = data.get("nodes", [])
            if nodes:
                host = nodes[0].get("host", "")
                if host:
                    print(f"  [worker] ✅ Destek bulundu: {host}")
                    connect_worker_nbd(host)
                    return
        except Exception as e:
            if i % 15 == 0:
                print(f"  [worker] Bekleniyor... ({i}sn): {e}")
        time.sleep(1)

    print("  [worker] Timeout — destek yok, lokal swap ile devam")


# ══════════════════════════════════════════════════════════════
#  DESTEK SUNUCUSU
# ══════════════════════════════════════════════════════════════

SUPPORT_NBD_PORT = 10809
SUPPORT_NBD_FILE = "/nbd_disk.img"
SUPPORT_RAM_FILE = "/tmp/nbd_ram.img"
SUPPORT_NODE_ID  = (MY_URL.replace("https://","").replace(".onrender.com","") or "support")


def support_install_tools():
    import shutil as _s
    missing = [t for t in ["nbd-server","socat","nbd-client"] if not _s.which(t)]
    if missing:
        print(f"  [destek] 📦 Kuruluyor: {', '.join(missing)}...")
        ret = sh("apt-get update -qq 2>/dev/null && "
                 f"DEBIAN_FRONTEND=noninteractive apt-get install -y "
                 f"--no-install-recommends {' '.join(missing)}")
        if ret.returncode == 0:
            print(f"  [destek] ✅ Kuruldu: {', '.join(missing)}")
        else:
            print(f"  [destek] ⚠️  Kurulum hatası")


def support_create_ram_disk():
    ram_disk_mb = calc_ram_disk_mb()
    print(f"  [destek] 🧠 RAM disk: {ram_disk_mb}MB")

    if ram_disk_mb <= 0:
        print("  [destek] ⚠️  RAM bütçesi yok")
        return 0

    if os.path.exists(SUPPORT_RAM_FILE):
        existing = os.path.getsize(SUPPORT_RAM_FILE) // 1024 // 1024
        if existing >= ram_disk_mb * 0.85:
            print(f"  [destek] ✅ RAM disk zaten var: {existing}MB"); return existing
        try: os.remove(SUPPORT_RAM_FILE)
        except: pass

    r = sh(f"fallocate -l {ram_disk_mb}M {SUPPORT_RAM_FILE}")
    if r.returncode != 0:
        sh(f"dd if=/dev/zero of={SUPPORT_RAM_FILE} bs=1M count={ram_disk_mb} status=none")

    if os.path.exists(SUPPORT_RAM_FILE):
        actual = os.path.getsize(SUPPORT_RAM_FILE) // 1024 // 1024
        print(f"  [destek] ✅ RAM disk hazır: {actual}MB")
        return actual
    return 0


def support_create_disk_file():
    nbd_gb = calc_nbd_disk_gb()
    nbd_mb = int(nbd_gb * 1024)
    print(f"  [destek] 💾 NBD disk: {nbd_gb:.1f}GB")

    if nbd_gb < 0.5:
        print("  [destek] ⚠️  Disk bütçesi yetersiz")
        return 0.0

    if os.path.exists(SUPPORT_NBD_FILE):
        existing = os.path.getsize(SUPPORT_NBD_FILE) / 1024**3
        if existing >= nbd_gb * 0.85:
            print(f"  [destek] ✅ Disk dosyası zaten var: {existing:.1f}GB"); return existing
        try: os.remove(SUPPORT_NBD_FILE)
        except: pass

    r = sh(f"fallocate -l {nbd_mb}M {SUPPORT_NBD_FILE}")
    if r.returncode != 0:
        chunk = 512
        for i in range(nbd_mb // chunk):
            used_now = read_actual_disk_used_gb()
            if used_now > RENDER_DISK_LIMIT_GB - 3.0:
                print(f"  [destek] ⛔ Disk limiti yakın ({used_now:.1f}GB)")
                break
            sh(f"dd if=/dev/zero of={SUPPORT_NBD_FILE} bs={chunk}M "
               f"count=1 seek={i} conv=notrunc 2>/dev/null")
            if i % 4 == 0:
                print(f"  [destek] {(i+1)*chunk}MB / {nbd_mb}MB...")

    actual = 0.0
    if os.path.exists(SUPPORT_NBD_FILE):
        actual = os.path.getsize(SUPPORT_NBD_FILE) / 1024**3
        print(f"  [destek] ✅ Disk dosyası: {actual:.1f}GB")
    return actual


def support_start_nbd(ram_disk_mb, disk_gb):
    support_install_tools()
    sh("modprobe nbd max_part=0 2>/dev/null")

    import shutil as _s
    if _s.which("nbd-server"):
        try:
            os.makedirs("/etc/nbd-server", exist_ok=True)
            cfg = f"[generic]\n    port = {SUPPORT_NBD_PORT}\n    allowlist = true\n"
            if ram_disk_mb > 0 and os.path.exists(SUPPORT_RAM_FILE):
                cfg += f"\n[ram]\n    exportname = {SUPPORT_RAM_FILE}\n    readonly = false\n"
            if disk_gb > 0 and os.path.exists(SUPPORT_NBD_FILE):
                cfg += f"\n[disk]\n    exportname = {SUPPORT_NBD_FILE}\n    readonly = false\n"
            open("/etc/nbd-server/config", "w").write(cfg)

            proc = subprocess.Popen(
                ["nbd-server", "-C", "/etc/nbd-server/config"],
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT
            )
            time.sleep(2)
            if proc.poll() is None:
                print(f"  [destek] ✅ nbd-server aktif (port {SUPPORT_NBD_PORT})")
                return True
        except Exception as e:
            print(f"  [destek] ⚠️  nbd-server hatası: {e}")

    if _s.which("socat"):
        target = SUPPORT_NBD_FILE if disk_gb > 0 else SUPPORT_RAM_FILE
        try:
            subprocess.Popen([
                "socat", f"TCP-LISTEN:{SUPPORT_NBD_PORT},reuseaddr,fork",
                f"FILE:{target},rdwr"
            ], stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
            time.sleep(1)
            print(f"  [destek] ✅ socat fallback aktif (port {SUPPORT_NBD_PORT})")
            return True
        except Exception as e:
            print(f"  [destek] ⚠️  socat: {e}")

    return False


def support_start_tunnel_and_register(ram_disk_mb, disk_gb):
    log = "/tmp/cf_support.log"
    print(f"  [destek] 🌐 Cloudflare tüneli açılıyor...")
    subprocess.Popen([
        "cloudflared", "tunnel",
        "--url", f"tcp://localhost:{SUPPORT_NBD_PORT}",
        "--no-autoupdate", "--loglevel", "info",
    ], stdout=open(log, "w"), stderr=subprocess.STDOUT)

    for _ in range(120):
        try:
            content = open(log).read()
            urls = re.findall(r'https://[a-z0-9-]+\.trycloudflare\.com', content)
            if urls:
                url  = urls[0]
                host = url.replace("https://", "")
                print(f"\n  [destek] ✅ DESTEK SUNUCU HAZIR: {host}\n")
                _support_register(url, host, ram_disk_mb, disk_gb)
                threading.Thread(target=_support_heartbeat, daemon=True).start()
                return url
        except: pass
        time.sleep(0.5)
    print("  [destek] ⚠️  Tünel URL alınamadı")
    return ""


def _support_register(url, host, ram_disk_mb, disk_gb):
    import urllib.request, json as _j
    try:
        data = _j.dumps({
            "worker_host":  host,
            "worker_url":   url,
            "nbd_gb":       round(disk_gb, 1),
            "ram_disk_mb":  ram_disk_mb,
            "node_id":      SUPPORT_NODE_ID,
            "ram_limit_mb": CONTAINER_RAM_MB,
            "disk_limit_gb": RENDER_DISK_LIMIT_GB,
        }).encode()
        req = urllib.request.Request(
            f"{MAIN_SERVER_URL}/api/worker/register",
            data=data, headers={"Content-Type": "application/json"}, method="POST"
        )
        urllib.request.urlopen(req, timeout=15)
        print(f"  [destek] ✅ Ana sunucuya kayıt tamamlandı")
    except Exception as e:
        print(f"  [destek] ⚠️  Kayıt hatası: {e}")
        # Retry after 30s
        time.sleep(30)
        try:
            urllib.request.urlopen(
                urllib.request.Request(
                    f"{MAIN_SERVER_URL}/api/worker/register",
                    data=data, headers={"Content-Type": "application/json"}, method="POST"
                ), timeout=15
            )
            print(f"  [destek] ✅ Kayıt yeniden denendi — başarılı")
        except Exception as e2:
            print(f"  [destek] ⚠️  Kayıt yeniden denemesi başarısız: {e2}")


def _support_heartbeat():
    import urllib.request, json as _j
    while True:
        time.sleep(30)
        try:
            try:
                vmrss = int([l for l in open("/proc/self/status")
                             if l.startswith("VmRSS:")][0].split()[1])
                rss_mb = vmrss // 1024
            except:
                rss_mb = 0
            used_disk_gb = read_actual_disk_used_gb()
            data = _j.dumps({
                "node_id":       SUPPORT_NODE_ID,
                "rss_mb":        rss_mb,
                "disk_used_gb":  round(used_disk_gb, 1),
                "ram_limit_mb":  CONTAINER_RAM_MB,
                "disk_limit_gb": RENDER_DISK_LIMIT_GB,
            }).encode()
            req = urllib.request.Request(
                f"{MAIN_SERVER_URL}/api/worker/heartbeat",
                data=data, headers={"Content-Type": "application/json"}, method="POST"
            )
            urllib.request.urlopen(req, timeout=10)
        except: pass


def _support_ram_watchdog():
    limit_mb = CONTAINER_RAM_MB
    while True:
        time.sleep(8)
        try:
            vmrss = int([l for l in open("/proc/self/status")
                         if l.startswith("VmRSS:")][0].split()[1])
            rss_mb = vmrss // 1024
            pct = rss_mb / limit_mb * 100
            if pct > 95:
                print(f"  [RAM WD] 🚨 KRİTİK: {rss_mb}MB/{limit_mb}MB")
                w("/proc/sys/vm/drop_caches", "3")
                if os.path.exists(SUPPORT_RAM_FILE):
                    try:
                        os.remove(SUPPORT_RAM_FILE)
                        print(f"  [RAM WD] ⚠️  RAM disk silindi")
                    except: pass
            elif pct > 90:
                w("/proc/sys/vm/drop_caches", "1")
        except: pass


def run_support_mode():
    from flask import Flask, jsonify

    print("\n" + "═"*56)
    print("  🔵 DESTEK MODU")
    print(f"  RAM={CONTAINER_RAM_MB}MB, DISK={RENDER_DISK_LIMIT_GB}GB")
    print(f"  Ana sunucu: {MAIN_SERVER_URL}")
    print("═"*56 + "\n")

    ram_disk_mb = support_create_ram_disk()
    disk_gb = support_create_disk_file()
    support_start_nbd(ram_disk_mb, disk_gb)

    threading.Thread(
        target=support_start_tunnel_and_register,
        args=(ram_disk_mb, disk_gb), daemon=True
    ).start()
    threading.Thread(target=_support_ram_watchdog, daemon=True).start()

    support_app = Flask(__name__)

    @support_app.route("/")
    @support_app.route("/health")
    def health():
        try:
            vmrss = int([l for l in open("/proc/self/status")
                         if l.startswith("VmRSS:")][0].split()[1])
            rss_mb = vmrss // 1024
        except: rss_mb = 0
        used_disk = read_actual_disk_used_gb()
        ram_pct   = min(100, int(rss_mb / CONTAINER_RAM_MB * 100))
        disk_pct  = min(100, int(used_disk / RENDER_DISK_LIMIT_GB * 100))
        ram_color = "#ff4757" if ram_pct > 85 else "#00e5ff"
        disk_color= "#ff4757" if disk_pct > 85 else "#00e5ff"
        swp = psutil.swap_memory()
        return SUPPORT_HTML.format(
            main_url    = MAIN_SERVER_URL,
            node_id     = SUPPORT_NODE_ID,
            ram_disk_mb = ram_disk_mb,
            disk_gb     = f"{disk_gb:.1f}",
            rss_mb      = rss_mb,
            ram_limit   = CONTAINER_RAM_MB,
            ram_pct     = ram_pct,
            ram_color   = ram_color,
            disk_used   = round(used_disk, 1),
            disk_limit  = RENDER_DISK_LIMIT_GB,
            disk_pct    = disk_pct,
            disk_color  = disk_color,
            swap_mb     = swp.total // 1024 // 1024,
        )

    @support_app.route("/api/worker/status")
    def status():
        try:
            vmrss = int([l for l in open("/proc/self/status")
                         if l.startswith("VmRSS:")][0].split()[1])
            rss_mb = vmrss // 1024
        except: rss_mb = 0
        return jsonify({
            "mode":          "support",
            "node_id":       SUPPORT_NODE_ID,
            "ram_disk_mb":   ram_disk_mb,
            "disk_gb":       round(disk_gb, 1),
            "rss_mb":        rss_mb,
            "ram_limit_mb":  CONTAINER_RAM_MB,
            "disk_used_gb":  round(read_actual_disk_used_gb(), 1),
            "disk_limit_gb": RENDER_DISK_LIMIT_GB,
        })

    print(f"[Destek] Sağlık paneli :{PORT}...")
    support_app.run(host="0.0.0.0", port=PORT, debug=False, use_reloader=False)


SUPPORT_HTML = """<!DOCTYPE html>
<html lang="tr">
<head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="refresh" content="8">
<title>🔵 Destek Sunucusu</title>
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{background:#0a0b12;color:#eef0f8;font-family:'Segoe UI',sans-serif;
  min-height:100vh;display:flex;align-items:center;justify-content:center}}
.card{{background:#0f1120;border:1px solid rgba(124,106,255,.3);border-radius:16px;
  padding:28px 32px;max-width:520px;width:92%;text-align:center}}
h1{{font-size:19px;font-weight:700;margin-bottom:4px;color:#7c6aff}}
.sub{{font-size:11px;color:#8892a4;margin-bottom:16px}}
.grid{{display:grid;grid-template-columns:1fr 1fr;gap:9px;margin-bottom:14px}}
.s{{background:rgba(255,255,255,.04);border:1px solid rgba(255,255,255,.07);
  border-radius:10px;padding:12px 10px}}
.sv{{font-size:17px;font-weight:700;font-family:monospace}}
.sl{{font-size:10px;color:#8892a4;margin-top:2px}}
.bar-wrap{{background:rgba(255,255,255,.06);border-radius:4px;height:4px;
  margin-top:5px;overflow:hidden}}
.bar{{height:100%;border-radius:4px}}
.limit-row{{display:flex;justify-content:space-between;font-size:10px;
  color:#8892a4;margin-top:4px}}
.badge{{display:inline-flex;align-items:center;gap:5px;padding:3px 10px;
  border-radius:20px;font-size:10px;font-weight:700;
  background:rgba(124,106,255,.12);border:1px solid rgba(124,106,255,.3);
  color:#7c6aff;margin-bottom:13px}}
.dot{{width:7px;height:7px;border-radius:50%;background:#7c6aff;
  box-shadow:0 0 5px #7c6aff;animation:blink 1.5s infinite}}
@keyframes blink{{0%,100%{{opacity:1}}50%{{opacity:.3}}}}
.link{{display:inline-block;margin-top:10px;padding:9px 22px;
  background:linear-gradient(135deg,#7c6aff,#00e5ff);color:#000;
  border-radius:8px;font-weight:700;text-decoration:none;font-size:12px}}
</style>
</head>
<body>
<div class="card">
  <div style="font-size:40px;margin-bottom:8px">🔵</div>
  <div class="badge"><div class="dot"></div> DESTEK MODU AKTİF</div>
  <h1>Destek Sunucusu</h1>
  <div class="sub">Node: {node_id}</div>
  <div class="grid">
    <div class="s">
      <div class="sv" style="color:{ram_color}">{rss_mb}MB</div>
      <div class="sl">🧠 RAM Kullanımı</div>
      <div class="bar-wrap"><div class="bar" style="width:{ram_pct}%;background:{ram_color}"></div></div>
      <div class="limit-row"><span>%{ram_pct}</span><span>/{ram_limit}MB</span></div>
    </div>
    <div class="s">
      <div class="sv" style="color:{disk_color}">{disk_used}GB</div>
      <div class="sl">💾 Disk Kullanımı</div>
      <div class="bar-wrap"><div class="bar" style="width:{disk_pct}%;background:{disk_color}"></div></div>
      <div class="limit-row"><span>%{disk_pct}</span><span>/{disk_limit}GB</span></div>
    </div>
    <div class="s">
      <div class="sv" style="color:#00e5ff">{ram_disk_mb}MB</div>
      <div class="sl">💡 Paylaşılan RAM Diski</div>
    </div>
    <div class="s">
      <div class="sv" style="color:#00e5ff">{disk_gb}GB</div>
      <div class="sl">📦 Paylaşılan NBD Disk</div>
    </div>
  </div>
  <a class="link" href="{main_url}" target="_blank">→ Ana Sunucuya Git</a>
</div>
</body>
</html>"""


# ══════════════════════════════════════════════════════════════
#  BAŞLAT
# ══════════════════════════════════════════════════════════════

mode = "main" if IS_MAIN else "support"
optimize_all(mode)

if IS_MAIN:
    print(f"\n{'━'*56}")
    print(f"  🟢 ANA SUNUCU — Panel: http://0.0.0.0:{PORT}")
    print(f"{'━'*56}\n")
    panel_proc = start_panel()
    threading.Thread(target=auto_start_sequence, daemon=True).start()
    threading.Thread(target=try_connect_worker,  daemon=True).start()
    panel_proc.wait()
else:
    run_support_mode()
