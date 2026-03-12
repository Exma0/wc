"""
⛏️  Minecraft Server Boot Sistemi
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Strateji:
  - Render 512MB cgroup limiti → cgroup swap sınırını kaldır
  - Host disk'ini swap'a çevir → JVM büyük heap kullanır
  - Fiziksel RAM kullanımı düşük tut → Render'ı atla
"""

import os, sys, subprocess, time, socket, resource, threading, re, glob

PORT    = int(os.environ.get("PORT", "5000"))
MC_PORT = 25565
MC_RAM  = os.environ.get("MC_RAM", "2G")

base_env = {
    **os.environ,
    "HOME": "/root", "USER": "root", "LOGNAME": "root",
    "LANG": "en_US.UTF-8", "LC_ALL": "en_US.UTF-8",
    "JAVA_HOME": "/usr/lib/jvm/java-21-openjdk-amd64",
    "PATH": "/usr/lib/jvm/java-21-openjdk-amd64/bin"
            ":/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
    "MC_RAM": MC_RAM,
    "PORT":   str(PORT),
}


def w(path, val):
    try:
        with open(path, "w") as f:
            f.write(str(val))
        return True
    except Exception:
        return False


def r(path):
    try:
        with open(path) as f:
            return f.read().strip()
    except Exception:
        return ""


def wait_port(port, timeout=60):
    for _ in range(timeout * 10):
        try:
            s = socket.create_connection(("127.0.0.1", int(port)), 0.1)
            s.close()
            return True
        except OSError:
            time.sleep(0.1)
    return False


# ══════════════════════════════════════════════════════════════
#  AŞAMA 1 — CGROUP LIMITI KALDIR + SWAP AÇ + OPTİMİZASYON
# ══════════════════════════════════════════════════════════════

def unlock_cgroup_memory():
    """
    Render'ın 512MB cgroup limitini aşmak için:
    cgroup v2 ve v1 memory swap limitlerini kaldır.
    Bu sayede fiziksel RAM 512MB üstüne çıkmadan swap kullanılabilir.
    """
    print("🔓 cgroup bellek limitleri kaldırılıyor...")

    unlocked = 0

    # ── cgroup v2 ─────────────────────────────────────────────
    cg2_paths = [
        "/sys/fs/cgroup/memory.max",
        "/sys/fs/cgroup/memory.swap.max",
        "/sys/fs/cgroup/memory.memsw.limit_in_bytes",
    ]
    for path in cg2_paths:
        if w(path, "max"):
            unlocked += 1
            print(f"  ✅ {path} → max")

    # cgroup v2 — container'ın kendi cgroup'u
    for cg_dir in glob.glob("/sys/fs/cgroup/system.slice/*/"):
        for fname in ["memory.max", "memory.swap.max"]:
            w(cg_dir + fname, "max")

    # ── cgroup v1 ─────────────────────────────────────────────
    cg1_pairs = [
        ("/sys/fs/cgroup/memory/memory.limit_in_bytes",         "-1"),
        ("/sys/fs/cgroup/memory/memory.memsw.limit_in_bytes",   "-1"),
        ("/sys/fs/cgroup/memory/memory.soft_limit_in_bytes",    "-1"),
        ("/sys/fs/cgroup/memory/memory.swappiness",             "100"),
        ("/sys/fs/cgroup/memory/memory.oom_control",            "0"),
    ]
    for path, val in cg1_pairs:
        if w(path, val):
            unlocked += 1
            print(f"  ✅ {path} → {val}")

    # Tüm alt cgroup'ları da aç
    for mem_cg in glob.glob("/sys/fs/cgroup/memory/*/"):
        w(mem_cg + "memory.limit_in_bytes",       "-1")
        w(mem_cg + "memory.memsw.limit_in_bytes", "-1")
        w(mem_cg + "memory.swappiness",           "100")
        w(mem_cg + "memory.oom_control",          "0")

    print(f"  {'✅' if unlocked > 0 else '⚠️ '} cgroup: {unlocked} limit kaldırıldı")


def setup_swap_aggressive():
    """
    Host disk'ini maksimum swap'a çevir.
    Render'da /var/lib/render veya / altında yüzlerce GB disk var.
    """
    print("\n💾 Agresif swap kurulumu başlıyor...")

    import psutil

    # Mevcut swap'ı kontrol et
    swp = psutil.swap_memory()
    if swp.total > 2 * 1024 * 1024 * 1024:
        print(f"  ✅ Swap zaten aktif: {swp.total // 1024 // 1024}MB")
        return

    disk = psutil.disk_usage("/")
    free_gb = disk.free / 1024 / 1024 / 1024
    # Boş alanın %60'ını swap yap, max 32GB
    swap_gb = min(32, int(free_gb * 0.60))

    print(f"  📊 Disk boş: {free_gb:.1f}GB → Swap: {swap_gb}GB yapılıyor...")

    if swap_gb < 2:
        print("  ⚠️  Yeterli disk yok")
        return

    swap_file = "/swapfile"
    swap_mb   = swap_gb * 1024

    # Swap dosyası yoksa oluştur
    if not os.path.exists(swap_file):
        # fallocate hızlı ama bazı FS'lerde çalışmaz, dd fallback
        ret = subprocess.run(
            ["fallocate", "-l", f"{swap_mb}M", swap_file],
            capture_output=True
        )
        if ret.returncode != 0:
            print(f"  ⚠️  fallocate başarısız, dd kullanılıyor...")
            subprocess.run([
                "dd", "if=/dev/zero", f"of={swap_file}",
                f"bs=1M", f"count={swap_mb}", "status=none"
            ], capture_output=True)

    subprocess.run(["chmod", "600", swap_file], capture_output=True)
    subprocess.run(["mkswap", "-f", swap_file], capture_output=True)
    ret = subprocess.run(["swapon", swap_file], capture_output=True)

    if ret.returncode == 0:
        swp2 = psutil.swap_memory()
        print(f"  ✅ Swap aktif: {swp2.total // 1024 // 1024}MB")
    else:
        print(f"  ⚠️  swapon: {ret.stderr.decode().strip()}")

    # Swap ayarları — kernel swap'ı agresif kullansın
    for path, val in [
        ("/proc/sys/vm/swappiness",              "200"),   # max agresif (kernel 5.8+ destekler, eskide 100)
        ("/proc/sys/vm/vfs_cache_pressure",      "500"),   # cache'i agresif boşalt
        ("/proc/sys/vm/overcommit_memory",       "1"),
        ("/proc/sys/vm/overcommit_ratio",        "100"),
        ("/proc/sys/vm/dirty_ratio",             "40"),
        ("/proc/sys/vm/dirty_background_ratio",  "10"),
        ("/proc/sys/vm/page-cluster",            "0"),     # swap sayfalarını tek tek oku (latency)
        ("/proc/sys/vm/watermark_boost_factor",  "0"),
        ("/proc/sys/vm/watermark_scale_factor",  "125"),
    ]:
        # swappiness için önce 200 dene, hata verirse 100
        if path == "/proc/sys/vm/swappiness":
            if not w(path, "200"):
                w(path, "100")
        else:
            w(path, val)

    # zram — RAM'i sıkıştırarak daha fazla kullanılabilir alan
    try:
        subprocess.run(["modprobe", "zram"], capture_output=True)
        import psutil
        mem_mb = int(psutil.virtual_memory().total / 1024 / 1024)
        # RAM'in %50'si kadar zram
        zram_mb = min(mem_mb // 2, 4096)
        if w("/sys/block/zram0/disksize", f"{zram_mb}M"):
            subprocess.run(["mkswap", "/dev/zram0"], capture_output=True)
            subprocess.run(["swapon", "-p", "100", "/dev/zram0"], capture_output=True)
            print(f"  ✅ zram: {zram_mb}MB sıkıştırılmış RAM swap")
    except Exception:
        pass

    print(f"  🎯 Toplam kullanılabilir bellek: {(psutil.virtual_memory().total + psutil.swap_memory().total) // 1024 // 1024}MB")


def optimize():
    print("⚡ Sistem optimizasyonu başlıyor...\n")

    # ulimits
    for res, val in [
        (resource.RLIMIT_NOFILE,  (1048576, 1048576)),
        (resource.RLIMIT_NPROC,   (resource.RLIM_INFINITY, resource.RLIM_INFINITY)),
        (resource.RLIMIT_STACK,   (resource.RLIM_INFINITY, resource.RLIM_INFINITY)),
        (resource.RLIMIT_CORE,    (resource.RLIM_INFINITY, resource.RLIM_INFINITY)),
    ]:
        try:
            resource.setrlimit(res, val)
        except Exception:
            pass
    print("  ✅ ulimits → sınırsız")

    # cgroup limitlerini kaldır (EN ÖNEMLİSİ)
    unlock_cgroup_memory()

    # Swap kur
    setup_swap_aggressive()

    # Network
    net_params = {
        "/proc/sys/net/core/rmem_max":             "134217728",
        "/proc/sys/net/core/wmem_max":             "134217728",
        "/proc/sys/net/core/somaxconn":            "65535",
        "/proc/sys/net/ipv4/tcp_fastopen":         "3",
        "/proc/sys/net/ipv4/tcp_tw_reuse":         "1",
        "/proc/sys/net/ipv4/tcp_fin_timeout":      "10",
        "/proc/sys/net/ipv4/ip_local_port_range":  "1024 65535",
    }
    ok = sum(w(p, v) for p, v in net_params.items())
    print(f"\n  ✅ Network → {ok}/{len(net_params)}")

    # FS
    for p, v in [
        ("/proc/sys/fs/file-max",  "2097152"),
        ("/proc/sys/fs/nr_open",   "2097152"),
    ]:
        w(p, v)

    # HugePage — JVM GC için (sadece transparent)
    w("/sys/kernel/mm/transparent_hugepage/enabled", "madvise")
    w("/sys/kernel/mm/transparent_hugepage/defrag",  "defer+madvise")

    # Kernel cache temizle — MC için yer aç
    w("/proc/sys/vm/drop_caches", "3")
    print("  ✅ Kernel cache temizlendi")
    print("\n  🎯 Sistem hazır!")


# ══════════════════════════════════════════════════════════════
#  AŞAMA 2 — PANEL + MC + TUNNEL
# ══════════════════════════════════════════════════════════════

def start_panel():
    print(f"\n🚀 [2/4] Panel başlatılıyor (:{PORT})...")
    proc = subprocess.Popen(
        [sys.executable, "/app/mc_panel.py"],
        env=base_env,
    )
    if wait_port(PORT, 30):
        print(f"  ✅ Panel hazır → http://0.0.0.0:{PORT}")
    else:
        print("  ⚠️  Panel başlatılıyor...")
    return proc


def auto_start_sequence():
    time.sleep(2)

    print("\n⛏️  [3/4] Minecraft Server başlatılıyor...")
    try:
        import urllib.request, json
        req = urllib.request.Request(
            f"http://localhost:{PORT}/api/start",
            data=b"{}",
            headers={"Content-Type": "application/json"},
            method="POST"
        )
        urllib.request.urlopen(req, timeout=10)
        print("  ✅ MC başlatma komutu gönderildi")
    except Exception as e:
        print(f"  ⚠️  {e}")

    print("  ⏳ MC Server bekleniyor (max 5 dk)...")
    if wait_port(MC_PORT, 300):
        print("  ✅ MC Server hazır!")
    else:
        print("  ⚠️  MC portu zaman aşımı — tunnel yine de açılıyor")

    print("\n🌐 [4/4] Cloudflare Tunnel MC:25565 → internet...")
    log = "/tmp/cf_mc.log"
    subprocess.Popen([
        "cloudflared", "tunnel",
        "--url", f"tcp://localhost:{MC_PORT}",
        "--no-autoupdate", "--loglevel", "info",
    ], stdout=open(log, "w"), stderr=subprocess.STDOUT)

    for _ in range(120):
        try:
            content = open(log).read()
            urls = re.findall(r'https://[a-z0-9-]+\.trycloudflare\.com', content)
            if urls:
                import json as _json
                tunnel_url = urls[0]
                host = tunnel_url.replace("https://", "")
                print(f"\n  ┌─────────────────────────────────────────┐")
                print(f"  │  ✅ MC Sunucu Adresi:                    │")
                print(f"  │  📌 {host:<39}│")
                print(f"  └─────────────────────────────────────────┘\n")
                try:
                    data = _json.dumps({"url": tunnel_url, "host": host}).encode()
                    req2 = urllib.request.Request(
                        f"http://localhost:{PORT}/api/internal/tunnel",
                        data=data,
                        headers={"Content-Type": "application/json"},
                        method="POST"
                    )
                    urllib.request.urlopen(req2, timeout=3)
                except Exception:
                    pass
                return
        except Exception:
            pass
        time.sleep(0.5)

    print("  ⚠️  Tunnel URL alınamadı")


# ══════════════════════════════════════════════════════════════
#  MAIN
# ══════════════════════════════════════════════════════════════

print("\n" + "━" * 50)
print("  ⛏️   Minecraft Server Sistemi v3.0")
print(f"      PORT={PORT}  |  MC_RAM={MC_RAM}")
print("━" * 50)

print("\n⚡ [1/4] Sistem optimizasyonu...")
optimize()

panel_proc = start_panel()

threading.Thread(target=auto_start_sequence, daemon=True).start()

print(f"\n{'━'*50}")
print(f"  Panel: http://0.0.0.0:{PORT}")
print(f"{'━'*50}\n")

panel_proc.wait()
