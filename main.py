"""
⛏️  Minecraft Server Boot — RENDER BYPASS v7.0
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
DİSK BÜTÇESİ (18GB limit):
  ANA SUNUCU  : swap ≤ 3GB  | MC world ≤ 4GB | buffer 3GB
  DESTEK MODU : NBD = disk_boş - 3GB (buffer) | swap yok

RAM LİMİTİ (512MB fiziksel):
  - JVM Xms=32M, Xmx hesaplanır  (RSS < 450MB hedef)
  - zram: disk kullanmaz, RAM'i sıkıştırır
  - swap dosyası: sadece disk müsaitse kur
"""

import os, sys, subprocess, time, socket, resource, threading, re, glob
import psutil

# ══════════════════════════════════════════════════════════════
#  ANA SUNUCU TESPİTİ
# ══════════════════════════════════════════════════════════════

MAIN_SERVER_URL = "https://wc-tsgd.onrender.com"
MY_URL = os.environ.get("RENDER_EXTERNAL_URL", "").rstrip("/")

IS_MAIN = (
    MY_URL == MAIN_SERVER_URL
    or MY_URL == ""
    or os.environ.get("FORCE_MAIN", "") == "1"
)

PORT    = int(os.environ.get("PORT", "5000"))
MC_PORT = 25565
MC_RAM  = os.environ.get("MC_RAM", "2G")

print("\n" + "━"*54)
print("  ⛏️   Minecraft Server — RENDER BYPASS v7.0")
print(f"      URL : {MY_URL or '(belirlenemedi)'}")
print(f"      MOD : {'🟢 ANA SUNUCU' if IS_MAIN else '🔵 DESTEK SUNUCUSU'}")
disk0 = psutil.disk_usage("/")
print(f"      DISK: kullanılan={disk0.used/1e9:.1f}GB / toplam={disk0.total/1e9:.1f}GB / boş={disk0.free/1e9:.1f}GB")
print("━"*54 + "\n")

base_env = {
    **os.environ,
    "HOME": "/root", "USER": "root", "LOGNAME": "root",
    "LANG": "en_US.UTF-8", "LC_ALL": "en_US.UTF-8",
    "JAVA_HOME": "/usr/lib/jvm/java-21-openjdk-amd64",
    "PATH": "/usr/lib/jvm/java-21-openjdk-amd64/bin"
            ":/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
    "MC_RAM": MC_RAM, "PORT": str(PORT),
}

INF = resource.RLIM_INFINITY

# ── Sabitler ──────────────────────────────────────────────────
DISK_LIMIT_GB    = 17.5   # Render 18GB — 0.5GB güvenlik payı
DISK_BUFFER_GB   = 3.0    # Her zaman bu kadar boş bırak
RAM_LIMIT_MB     = 480    # 512MB limit — 32MB güvenlik payı

def w(path, val):
    try:
        with open(path, "w") as f: f.write(str(val))
        return True
    except Exception:
        return False

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

def safe_disk_free_gb():
    """Gerçek boş disk alanı (GB)."""
    return psutil.disk_usage("/").free / 1024**3

def max_safe_file_gb(reserve_gb=DISK_BUFFER_GB):
    """Bu anda güvenle oluşturulabilecek max dosya boyutu."""
    free = safe_disk_free_gb()
    available = free - reserve_gb
    return max(0, available)


# ══════════════════════════════════════════════════════════════
#  CGROUP BYPASS
# ══════════════════════════════════════════════════════════════

def bypass_cgroups():
    print("  [cgroup] Limitler kaldırılıyor...")
    n = 0
    targets = [
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
        ("/sys/fs/cgroup/pids/pids.max",                      "max"),
    ]
    for path, val in targets:
        if w(path, val): n += 1

    for cg in glob.glob("/sys/fs/cgroup/*/") + glob.glob("/sys/fs/cgroup/*/*/"):
        for fn, v in [("memory.max","max"),("memory.swap.max","max"),
                      ("memory.high","max"),("memory.oom_control","0"),
                      ("cpu.max","max"),("pids.max","max")]:
            w(cg + fn, v)

    w("/proc/sys/vm/oom_kill_allocating_task", "0")
    w("/proc/sys/vm/panic_on_oom",             "0")
    try: w(f"/proc/{os.getpid()}/oom_score_adj", "-1000")
    except: pass
    print(f"  ✅ cgroup → {n} limit kaldırıldı")


# ══════════════════════════════════════════════════════════════
#  SWAP KURULUMU — DİSK BÜTÇE KONTROLLÜ
# ══════════════════════════════════════════════════════════════

def setup_swap(mode="main"):
    """
    ANA SUNUCU : swap ≤ 3GB, MC world için 4GB + 3GB buffer ayır
    DESTEK     : swap dosyası kurma (disk NBD'ye lazım)
    """
    print("  [swap] Kurulum başlıyor...")

    # ── zram (disk kullanmaz, her zaman kur) ─────────────────
    sh("modprobe zram num_devices=1 2>/dev/null")
    mem_mb  = psutil.virtual_memory().total // 1024 // 1024
    # zram: RAM'in 2x'i kadar sanal alan (sıkıştırma ile)
    zram_mb = min(1024, mem_mb)   # max 1GB zram (disk yok)
    w("/sys/block/zram0/comp_algorithm", "lz4")
    if w("/sys/block/zram0/disksize", f"{zram_mb}M"):
        r = sh("mkswap /dev/zram0 && swapon -p 100 /dev/zram0")
        if r.returncode == 0:
            print(f"  ✅ zram aktif: {zram_mb}MB (disk kullanmaz)")

    # ── Swap dosyası — sadece ana sunucuda ve disk varsa ─────
    swap_file = "/swapfile"
    if mode == "main":
        # Disk bütçesi:
        # kullanılan + swap + MC_world(4GB) + buffer(3GB) ≤ 18GB
        disk       = psutil.disk_usage("/")
        used_gb    = disk.used  / 1024**3
        # MC world + log için 4GB + buffer 3GB = 7GB ayır
        max_swap_gb = DISK_LIMIT_GB - used_gb - 7.0
        max_swap_gb = min(3.0, max(0, max_swap_gb))   # max 3GB swap dosyası
        swap_mb     = int(max_swap_gb * 1024)

        if swap_mb < 512:
            print(f"  ⚠️  Disk dolu ({used_gb:.1f}GB kullanıldı) — swap dosyası atlanıyor")
        else:
            swp = psutil.swap_memory()
            if swp.total >= swap_mb * 1024 * 1024 * 0.8:
                print(f"  ✅ Swap zaten aktif: {swp.total//1024//1024}MB")
            else:
                print(f"  💾 Swap oluşturuluyor: {swap_mb}MB (disk: {used_gb:.1f}/{DISK_LIMIT_GB}GB)")
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
                    print(f"  ⚠️  swapon başarısız: {r2.stderr.decode().strip()}")
                    try: os.remove(swap_file)
                    except: pass
    else:
        print("  ℹ️  Destek modu — swap dosyası yok (disk NBD için ayrılıyor)")

    # ── VM parametreleri ─────────────────────────────────────
    for path, val in [
        ("/proc/sys/vm/swappiness",             "100"),
        ("/proc/sys/vm/vfs_cache_pressure",     "200"),
        ("/proc/sys/vm/overcommit_memory",      "1"),
        ("/proc/sys/vm/overcommit_ratio",       "100"),
        ("/proc/sys/vm/page-cluster",           "0"),
        ("/proc/sys/vm/drop_caches",            "3"),
        ("/proc/sys/vm/watermark_boost_factor", "0"),
    ]:
        w(path, val)

    swp2 = psutil.swap_memory()
    mem  = psutil.virtual_memory()
    disk2 = psutil.disk_usage("/")
    print(f"  🎯 RAM={mem.total//1024//1024}MB + Swap={swp2.total//1024//1024}MB | "
          f"Disk boş: {disk2.free/1024**3:.1f}GB")
    return (mem.total + swp2.total) // 1024 // 1024


# ══════════════════════════════════════════════════════════════
#  KERNEL OPTİMİZASYONU
# ══════════════════════════════════════════════════════════════

def optimize_kernel():
    print("  [kernel] Parametreler ayarlanıyor...")
    params = {
        "/proc/sys/kernel/pid_max":        "4194304",
        "/proc/sys/kernel/threads-max":    "4194304",
        "/proc/sys/fs/file-max":           "2097152",
        "/proc/sys/fs/nr_open":            "2097152",
        "/proc/sys/net/core/somaxconn":    "65535",
        "/proc/sys/net/ipv4/tcp_tw_reuse": "1",
        "/proc/sys/net/ipv4/tcp_fin_timeout": "10",
        "/proc/sys/vm/min_free_kbytes":    "65536",  # 64MB min free
    }
    ok = sum(w(p, v) for p, v in params.items())
    for res, val in [
        (resource.RLIMIT_NOFILE,  (1048576, 1048576)),
        (resource.RLIMIT_NPROC,   (INF, INF)),
        (resource.RLIMIT_MEMLOCK, (INF, INF)),
    ]:
        try: resource.setrlimit(res, val)
        except: pass
    w("/sys/kernel/mm/transparent_hugepage/enabled", "madvise")
    print(f"  ✅ {ok}/{len(params)} parametre ayarlandı")


def optimize_all(mode="main"):
    print("\n" + "═"*54)
    print("  🔓 RENDER BYPASS — LİMİTLER KALDIRILIYOR")
    print("═"*54 + "\n")

    bypass_cgroups()
    print()
    setup_swap(mode)
    print()
    optimize_kernel()

    mem  = psutil.virtual_memory()
    swp  = psutil.swap_memory()
    disk = psutil.disk_usage("/")
    print("\n" + "═"*54)
    print(f"  CPU  : {psutil.cpu_count()} çekirdek")
    print(f"  RAM  : {mem.total//1024//1024}MB fiziksel (limit: ~512MB)")
    print(f"  Swap : {swp.total//1024//1024}MB")
    print(f"  Disk : {disk.used/1e9:.1f}GB / {disk.total/1e9:.1f}GB kullanılıyor")
    print(f"  Boş  : {disk.free/1e9:.1f}GB kaldı")
    print("═"*54)


# ══════════════════════════════════════════════════════════════
#  ANA SUNUCU: Panel + MC + Tunnel
# ══════════════════════════════════════════════════════════════

_worker_registered = threading.Event()
_worker_info       = {}


def start_panel():
    print(f"\n🚀 Panel başlatılıyor (:{PORT})...")
    proc = subprocess.Popen([sys.executable, "/app/mc_panel.py"], env=base_env)
    if wait_port(PORT, 30):
        print(f"  ✅ Panel hazır → http://0.0.0.0:{PORT}")
    else:
        print("  ⚠️  Panel başlıyor (bekleniyor)...")
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

    print("\n🌐 Cloudflare Tunnel başlatılıyor...")
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
                import json as _j
                tunnel_url = urls[0]
                host = tunnel_url.replace("https://", "")
                print(f"\n  ┌──────────────────────────────────────────┐")
                print(f"  │  ✅ MC Sunucu Adresi:                     │")
                print(f"  │  📌 {host:<40}│")
                print(f"  └──────────────────────────────────────────┘\n")
                try:
                    import urllib.request
                    data = _j.dumps({"url": tunnel_url, "host": host}).encode()
                    req2 = urllib.request.Request(
                        f"http://localhost:{PORT}/api/internal/tunnel",
                        data=data, headers={"Content-Type": "application/json"}, method="POST"
                    )
                    urllib.request.urlopen(req2, timeout=3)
                except: pass
                return
        except: pass
        time.sleep(0.5)
    print("  ⚠️  Tunnel URL alınamadı")


def connect_worker_nbd(host: str, local_port: int = 10810, nbd_dev: str = "/dev/nbd0"):
    print(f"\n  [worker-nbd] Bağlanılıyor: {host}...")
    sh("modprobe nbd max_part=0 2>/dev/null")

    cf_proc = subprocess.Popen([
        "cloudflared", "access", "tcp",
        "--hostname", host, "--url", f"localhost:{local_port}",
    ], stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    time.sleep(4)

    ret = sh(f"nbd-client localhost {local_port} {nbd_dev} -N disk -b 4096 -t 60")
    if ret.returncode != 0:
        print(f"  ⚠️  nbd-client başarısız: {ret.stderr.decode().strip()}")
        cf_proc.terminate()
        return False

    sh(f"mkswap {nbd_dev}")
    ret2 = sh(f"swapon -p 5 {nbd_dev}")
    if ret2.returncode == 0:
        swp = psutil.swap_memory()
        mem = psutil.virtual_memory()
        print(f"  ✅ Worker diski swap'a eklendi!")
        print(f"  🎯 YENİ TOPLAM: RAM={mem.total//1024//1024}MB + Swap={swp.total//1024//1024}MB")
        return True
    else:
        print(f"  ⚠️  swapon worker: {ret2.stderr.decode().strip()}")
        return False


def try_connect_worker():
    host = os.environ.get("WORKER_HOST", "").strip()
    if host:
        print(f"  [worker] WORKER_HOST env: {host}")
        connect_worker_nbd(host)
        return
    print("  [worker] WORKER_HOST bekleniyor (90sn timeout)...")
    if _worker_registered.wait(timeout=90):
        host = _worker_info.get("worker_host", "")
        if host:
            connect_worker_nbd(host)
    else:
        print("  [worker] Timeout — worker yok, lokal swap ile devam")


# ══════════════════════════════════════════════════════════════
#  DESTEK SUNUCUSU: Disk Paylaşımı
# ══════════════════════════════════════════════════════════════

SUPPORT_NBD_PORT = 10809
SUPPORT_NBD_FILE = "/nbd_disk.img"
SUPPORT_NODE_ID  = MY_URL.replace("https://", "").replace(".onrender.com", "") or "support"


def support_calc_nbd_size():
    """
    Güvenli NBD boyutu hesapla:
      boş_disk - DISK_BUFFER_GB  (her zaman 3GB buffer bırak)
      Max 13GB (18GB limit - 3GB OS - 2GB apt/cache)
    """
    free_gb = safe_disk_free_gb()
    safe_gb = free_gb - DISK_BUFFER_GB
    safe_gb = min(13.0, max(1.0, safe_gb))
    return safe_gb


def support_install_tools():
    """nbd-server ve socat kurulu değilse apt ile otomatik kur."""
    import shutil as _shutil
    missing = []
    if not _shutil.which("nbd-server"): missing.append("nbd-server")
    if not _shutil.which("socat"):      missing.append("socat")
    if not _shutil.which("nbd-client"): missing.append("nbd-client")

    if missing:
        print(f"  [destek] 📦 Kuruluyor: {', '.join(missing)}...")
        ret = sh(
            "apt-get update -qq 2>/dev/null && "
            f"DEBIAN_FRONTEND=noninteractive apt-get install -y "
            f"--no-install-recommends {' '.join(missing)}"
        )
        if ret.returncode == 0:
            print(f"  [destek] ✅ Kuruldu: {', '.join(missing)}")
        else:
            out = (ret.stdout.decode() + ret.stderr.decode())[-300:]
            print(f"  [destek] ⚠️  Kurulum hatası: {out}")
    else:
        print("  [destek] ✅ nbd-server + socat zaten kurulu")


def support_create_disk():
    nbd_gb  = support_calc_nbd_size()
    nbd_mb  = int(nbd_gb * 1024)
    disk    = psutil.disk_usage("/")
    used_gb = disk.used / 1024**3
    free_gb = disk.free / 1024**3

    print(f"  [destek] 📊 Disk: {used_gb:.1f}GB kullanıldı, {free_gb:.1f}GB boş")
    print(f"  [destek] 💾 NBD boyutu: {nbd_gb:.1f}GB (3GB buffer bırakılıyor)")

    # Varsa boyut kontrolü
    if os.path.exists(SUPPORT_NBD_FILE):
        existing_gb = os.path.getsize(SUPPORT_NBD_FILE) / 1024**3
        if existing_gb >= nbd_gb * 0.85:
            print(f"  [destek] ✅ Blok dosya zaten var: {existing_gb:.1f}GB")
            return int(existing_gb)
        else:
            print(f"  [destek] ♻️  Eski dosya küçük ({existing_gb:.1f}GB), yeniden oluşturuluyor...")
            try: os.remove(SUPPORT_NBD_FILE)
            except: pass

    print(f"  [destek] 💾 {nbd_gb:.1f}GB blok dosya oluşturuluyor (fallocate)...")
    ret = sh(f"fallocate -l {nbd_mb}M {SUPPORT_NBD_FILE}")

    if ret.returncode != 0:
        # fallocate yoksa dd ile oluştur (chunk chunk — disk dolmasın diye kontrol et)
        print(f"  [destek] ⚠️  fallocate yok → dd ile oluşturuluyor...")
        chunk_mb = 512
        chunks   = nbd_mb // chunk_mb
        for i in range(chunks):
            # Her chunk'ta disk kontrolü
            d = psutil.disk_usage("/")
            if d.free / 1024**2 < chunk_mb + (DISK_BUFFER_GB * 1024):
                print(f"  [destek] ⛔ Disk dolmak üzere — {i*chunk_mb}MB'de duruldu")
                break
            sh(f"dd if=/dev/zero of={SUPPORT_NBD_FILE} bs={chunk_mb}M count=1 "
               f"seek={i} oflag=seek_bytes conv=notrunc 2>/dev/null")
            if i % 4 == 0:
                print(f"  [destek] {(i+1)*chunk_mb}MB / {nbd_mb}MB...")

    actual_gb = 0
    if os.path.exists(SUPPORT_NBD_FILE):
        actual_gb = os.path.getsize(SUPPORT_NBD_FILE) / 1024**3
        disk2 = psutil.disk_usage("/")
        print(f"  [destek] ✅ Blok dosya hazır: {actual_gb:.1f}GB | Disk boş: {disk2.free/1024**3:.1f}GB")
    else:
        print("  [destek] ❌ Blok dosya oluşturulamadı!")

    return actual_gb


def support_start_nbd(actual_gb):
    support_install_tools()
    sh("modprobe nbd max_part=0 2>/dev/null")

    import shutil as _shutil

    # ── nbd-server ────────────────────────────────────────────
    if _shutil.which("nbd-server"):
        try:
            os.makedirs("/etc/nbd-server", exist_ok=True)
            open("/etc/nbd-server/config", "w").write(f"""
[generic]
    port = {SUPPORT_NBD_PORT}
    allowlist = true
[disk]
    exportname = {SUPPORT_NBD_FILE}
    readonly = false
    flush = true
    fua = true
""")
            print(f"  [destek] 🔌 nbd-server başlatılıyor ({actual_gb:.1f}GB)...")
            proc = subprocess.Popen(
                ["nbd-server", "-C", "/etc/nbd-server/config"],
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT
            )
            time.sleep(2)
            if proc.poll() is None:
                print(f"  [destek] ✅ nbd-server aktif (port {SUPPORT_NBD_PORT})")
                return True
            err = proc.stdout.read().decode()[-200:]
            print(f"  [destek] ⚠️  nbd-server çöktü: {err}")
        except Exception as e:
            print(f"  [destek] ⚠️  nbd-server hatası: {e}")

    # ── socat fallback ────────────────────────────────────────
    if _shutil.which("socat"):
        try:
            subprocess.Popen([
                "socat",
                f"TCP-LISTEN:{SUPPORT_NBD_PORT},reuseaddr,fork",
                f"FILE:{SUPPORT_NBD_FILE},rdwr"
            ], stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
            time.sleep(1)
            print(f"  [destek] ✅ socat TCP köprüsü aktif (port {SUPPORT_NBD_PORT})")
            return True
        except Exception as e:
            print(f"  [destek] ⚠️  socat hatası: {e}")

    # ── Pure-Python TCP fallback ──────────────────────────────
    def _py_server():
        import socketserver, struct
        class H(socketserver.BaseRequestHandler):
            def handle(self):
                try:
                    with open(SUPPORT_NBD_FILE, "r+b") as f:
                        conn = self.request
                        conn.settimeout(60)
                        while True:
                            hdr = conn.recv(8)
                            if not hdr or len(hdr) < 8: break
                            cmd, offset, length = struct.unpack(">BIH", hdr[:7])
                            if cmd == 0:
                                f.seek(offset); conn.sendall(f.read(length))
                            elif cmd == 1:
                                data = conn.recv(length); f.seek(offset); f.write(data)
                except: pass
        srv = socketserver.ThreadingTCPServer(("0.0.0.0", SUPPORT_NBD_PORT), H)
        srv.allow_reuse_address = True
        print(f"  [destek] ✅ Python TCP sunucusu aktif (port {SUPPORT_NBD_PORT})")
        srv.serve_forever()

    threading.Thread(target=_py_server, daemon=True).start()
    time.sleep(1)
    return True


def support_start_tunnel_and_register(actual_gb):
    log = "/tmp/cf_support.log"
    print(f"  [destek] 🌐 Cloudflare TCP tüneli açılıyor...")
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
                print(f"\n  [destek] ╔══════════════════════════════════════╗")
                print(f"  [destek] ║  ✅ DESTEK SUNUCU HAZIR               ║")
                print(f"  [destek] ║  Host  : {host:<28}║")
                print(f"  [destek] ║  Disk  : {actual_gb:.1f}GB NBD{'':<22}║")
                print(f"  [destek] ╚══════════════════════════════════════╝\n")
                _support_register(url, host, actual_gb)
                threading.Thread(target=_support_heartbeat, daemon=True).start()
                return url
        except: pass
        time.sleep(0.5)
    print("  [destek] ⚠️  Tünel URL alınamadı")
    return ""


def _support_register(url, host, actual_gb):
    import urllib.request, json as _j
    try:
        mem  = psutil.virtual_memory()
        disk = psutil.disk_usage("/")
        data = _j.dumps({
            "worker_host":  host,
            "worker_url":   url,
            "nbd_gb":       round(actual_gb, 1),
            "node_id":      SUPPORT_NODE_ID,
            "ram_mb":       mem.total // 1024 // 1024,
            "disk_free_gb": round(disk.free / 1024**3, 1),
        }).encode()
        req = urllib.request.Request(
            f"{MAIN_SERVER_URL}/api/worker/register",
            data=data, headers={"Content-Type": "application/json"}, method="POST"
        )
        urllib.request.urlopen(req, timeout=15)
        print(f"  [destek] ✅ Ana sunucuya kayıt tamamlandı")
    except Exception as e:
        print(f"  [destek] ⚠️  Kayıt hatası: {e}")


def _support_heartbeat():
    import urllib.request, json as _j
    while True:
        time.sleep(30)
        try:
            mem  = psutil.virtual_memory()
            disk = psutil.disk_usage("/")
            data = _j.dumps({
                "node_id":      SUPPORT_NODE_ID,
                "ram_mb":       mem.available // 1024 // 1024,
                "disk_free_gb": round(disk.free / 1024**3, 1),
            }).encode()
            req = urllib.request.Request(
                f"{MAIN_SERVER_URL}/api/worker/heartbeat",
                data=data, headers={"Content-Type": "application/json"}, method="POST"
            )
            urllib.request.urlopen(req, timeout=10)
        except: pass


def run_support_mode():
    from flask import Flask, jsonify

    print("\n" + "═"*54)
    print("  🔵 DESTEK MODU — MC Panel kapalı")
    print(f"  Ana sunucu: {MAIN_SERVER_URL}")
    print("═"*54 + "\n")

    actual_gb = support_create_disk()
    support_start_nbd(actual_gb)
    threading.Thread(
        target=support_start_tunnel_and_register,
        args=(actual_gb,), daemon=True
    ).start()

    support_app = Flask(__name__)

    @support_app.route("/")
    @support_app.route("/health")
    def health():
        mem  = psutil.virtual_memory()
        disk = psutil.disk_usage("/")
        swp  = psutil.swap_memory()
        return SUPPORT_HTML.format(
            main_url=MAIN_SERVER_URL,
            node_id=SUPPORT_NODE_ID,
            nbd_gb=f"{actual_gb:.1f}",
            ram_free=mem.available//1024//1024,
            disk_used=round(disk.used/1e9,1),
            disk_total=round(disk.total/1e9,1),
            disk_free=round(disk.free/1e9,1),
            swap_total=swp.total//1024//1024,
        )

    @support_app.route("/api/worker/status")
    def status():
        mem  = psutil.virtual_memory()
        disk = psutil.disk_usage("/")
        return jsonify({
            "mode":         "support",
            "node_id":      SUPPORT_NODE_ID,
            "main":         MAIN_SERVER_URL,
            "nbd_gb":       round(actual_gb, 1),
            "ram_mb":       mem.total // 1024 // 1024,
            "disk_used_gb": round(disk.used/1e9, 1),
            "disk_free_gb": round(disk.free/1e9, 1),
        })

    print(f"[Destek] Flask sağlık paneli :{PORT}...")
    support_app.run(host="0.0.0.0", port=PORT, debug=False, use_reloader=False)


SUPPORT_HTML = """<!DOCTYPE html>
<html lang="tr">
<head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>🔵 Destek Sunucusu</title>
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{background:#0a0b12;color:#eef0f8;font-family:'Segoe UI',sans-serif;min-height:100vh;
  display:flex;align-items:center;justify-content:center}}
.card{{background:#0f1120;border:1px solid rgba(124,106,255,.3);border-radius:16px;
  padding:36px 44px;max-width:540px;width:90%;text-align:center}}
.icon{{font-size:52px;margin-bottom:14px}}
h1{{font-size:21px;font-weight:700;margin-bottom:6px;color:#7c6aff}}
.sub{{font-size:12px;color:#8892a4;margin-bottom:22px}}
.stat{{display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-bottom:20px}}
.s{{background:rgba(255,255,255,.04);border:1px solid rgba(255,255,255,.07);border-radius:10px;padding:13px}}
.sv{{font-size:20px;font-weight:700;color:#00e5ff;font-family:monospace}}
.sl{{font-size:10px;color:#8892a4;margin-top:3px}}
.warn{{background:rgba(255,165,2,.08);border:1px solid rgba(255,165,2,.2);border-radius:9px;
  padding:10px;font-size:11px;color:#ffa502;margin-bottom:16px}}
.link{{display:inline-block;margin-top:6px;padding:10px 24px;
  background:linear-gradient(135deg,#7c6aff,#00e5ff);color:#000;
  border-radius:9px;font-weight:700;text-decoration:none;font-size:13px}}
.badge{{display:inline-flex;align-items:center;gap:6px;padding:4px 12px;border-radius:20px;
  font-size:11px;font-weight:700;background:rgba(124,106,255,.12);
  border:1px solid rgba(124,106,255,.3);color:#7c6aff;margin-bottom:18px}}
.dot{{width:8px;height:8px;border-radius:50%;background:#7c6aff;
  box-shadow:0 0 6px #7c6aff;animation:blink 1.5s infinite}}
@keyframes blink{{0%,100%{{opacity:1}}50%{{opacity:.3}}}}
</style>
</head>
<body>
<div class="card">
  <div class="icon">🔵</div>
  <div class="badge"><div class="dot"></div> DESTEK MODU AKTİF</div>
  <h1>Destek Sunucusu</h1>
  <div class="sub">Bu sunucu MC Panel açmaz.<br>Ana sunucuya disk + RAM desteği sağlar.</div>
  <div class="warn">⚠️ Disk: {disk_used}GB kullanıldı / {disk_total}GB toplam | {disk_free}GB boş kaldı</div>
  <div class="stat">
    <div class="s"><div class="sv">{nbd_gb}GB</div><div class="sl">💾 Paylaşılan NBD Disk</div></div>
    <div class="s"><div class="sv">{ram_free}MB</div><div class="sl">🧠 Boş RAM</div></div>
    <div class="s"><div class="sv">{disk_free}GB</div><div class="sl">📦 Disk Boş</div></div>
    <div class="s"><div class="sv">{swap_total}MB</div><div class="sl">⚡ Swap (zram)</div></div>
  </div>
  <div style="font-size:11px;color:#3d4558;margin-bottom:14px">
    Node: <span style="color:#7c6aff;font-family:monospace">{node_id}</span>
  </div>
  <a class="link" href="{main_url}" target="_blank">→ Ana Sunucuya Git</a>
</div>
</body>
</html>"""


# ══════════════════════════════════════════════════════════════
#  BAŞLAT
# ══════════════════════════════════════════════════════════════

mode = "main" if IS_MAIN else "support"
print(f"\n⚡ Limit bypass + Optimizasyon ({mode} modu)...")
optimize_all(mode)

if IS_MAIN:
    print(f"\n{'━'*54}")
    print(f"  🟢 ANA SUNUCU MODU — Panel: http://0.0.0.0:{PORT}")
    print(f"{'━'*54}\n")
    panel_proc = start_panel()
    threading.Thread(target=auto_start_sequence, daemon=True).start()
    threading.Thread(target=try_connect_worker,  daemon=True).start()
    panel_proc.wait()
else:
    run_support_mode()
