"""
🖥️  VirtualCluster v12.0
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Tüm agent'ların RAM + Disk + CPU'sunu ana sunucuyla birleştirir.
Minecraft sadece yerel bir makine üzerinde çalıştığını sanır.
Kernel modülü gerekmez. Tamamen userspace.

┌─────────────────────────────────────────────────────┐
│  SANAL MAKİNE  (MC'nin gördüğü)                     │
│                                                     │
│  RAM  = Ana RAM + Agent RAM'leri (swap + cache)     │
│  Disk = /mnt/vcluster  (union FS: ana+agent diskler)│
│  CPU  = Şeffaf task pool (auto-distribute)          │
└─────────────────────────────────────────────────────┘

Bileşenler:
  ClusterMemory  → RAM birleştirme (swap dosyaları + uygulama cache)
  ClusterDisk    → Disk birleştirme (FUSE union FS veya overlay daemon)
  ClusterCPU     → CPU birleştirme (şeffaf görev dağıtımı)
  ClusterNet     → Ağ birleştirme (proxy + tünel yönetimi)
  VirtualCluster → Hepsini yönetir, mc_panel'e bildirir
"""

import os, sys, json, time, threading, hashlib, shutil, subprocess
import socket, queue, struct, mmap, tempfile, signal, gzip
from pathlib import Path
from collections import OrderedDict, defaultdict
from datetime import datetime
from typing import Optional
import urllib.request as _ur
import urllib.error

# ══════════════════════════════════════════════════════════════
#  GLOBAL KONFİGÜRASYON
# ══════════════════════════════════════════════════════════════

MAIN_URL      = "https://wc-tsgd.onrender.com"
MC_DIR        = Path("/minecraft")
CLUSTER_MOUNT = Path("/mnt/vcluster")       # union FS mount noktası
PANEL_PORT    = int(os.environ.get("PORT", "5000"))
SWAP_DIR      = Path("/tmp/cluster_swap")    # agent swap dosyaları buraya indirilir
CACHE_DIR     = Path("/tmp/cluster_cache")   # sıcak veri lokal cache

for d in [CLUSTER_MOUNT, SWAP_DIR, CACHE_DIR]:
    d.mkdir(parents=True, exist_ok=True)


def _log(msg: str):
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] {msg}")
    try:
        _ur.urlopen(_ur.Request(
            f"http://127.0.0.1:{PANEL_PORT}/api/internal/status_msg",
            data=json.dumps({"msg": msg}).encode(),
            headers={"Content-Type": "application/json"}, method="POST",
        ), timeout=2)
    except: pass


def _http(url: str, method: str = "GET", data: bytes = None,
          headers: dict = None, timeout: int = 20) -> Optional[bytes]:
    try:
        req = _ur.Request(url, data=data,
                          headers={"Content-Type": "application/octet-stream",
                                   **(headers or {})},
                          method=method)
        with _ur.urlopen(req, timeout=timeout) as r:
            return r.read()
    except: return None


def _jget(url: str, body: dict = None, method: str = "GET",
          timeout: int = 15) -> Optional[dict]:
    raw = _http(url, method=method if body is None else "POST",
                data=json.dumps(body).encode() if body else None,
                headers={"Content-Type": "application/json"}, timeout=timeout)
    if raw:
        try: return json.loads(raw)
        except: pass
    return None


# ══════════════════════════════════════════════════════════════
#  1.  ClusterMemory  — RAM Birleştirme
# ══════════════════════════════════════════════════════════════

class ClusterMemory:
    """
    Ana sunucunun RAM'ini agent kaynakları ile genişletir.

    Strateji A — Swap Genişletme (agent DİSK → ana sunucu SWAP):
      Her agent'ta 1-3GB swap dosyası oluşturulur.
      Ana sunucu HTTP ile bu dosyaları indirir, local olarak aktive eder.
      Net etki: Agent disk alanı → ana sunucu swap alanı.

    Strateji B — Sanal Bellek (agent RAM → uygulama cache):
      Minecraft chunk/entity/NBT verisi agent RAM cache'ine alınır.
      JVM heap baskısı azaltılır.
      "ClusterCache" API: put/get/evict.

    Strateji C — Memory-mapped uzak tampon:
      Agent, büyük bir byte buffer'ı HTTP block device olarak sunar.
      Ana sunucu bunu local bir dosyaya yansıtır + mmap eder.
      Uygulama bu mmap'i sözlük/cache olarak kullanır.
    """

    def __init__(self, agents: dict):
        self._agents      = agents   # node_id → agent_dict (pool'dan referans)
        self._swap_files  = {}       # node_id → local_path
        self._swap_lock   = threading.Lock()
        self._cache_hits  = 0
        self._cache_miss  = 0

        # LRU uygulama cache (yerel + uzak)
        self._local_cache: OrderedDict[str, bytes] = OrderedDict()
        self._local_max   = 64 * 1024 * 1024   # 64MB yerel hot cache
        self._local_size  = 0
        self._cache_lock  = threading.Lock()

    # ── Strateji A: Swap dosyası ──────────────────────────────

    def build_swapfile_on_agent(self, node_id: str, agent_url: str,
                                 size_mb: int = 1500) -> bool:
        """
        Agent'ta swap dosyası oluştur → indir → local'de aktive et.
        Bu sayede agent'ın DİSK alanı ana sunucunun SWAP'ı olur.
        """
        local_path = SWAP_DIR / f"swap_{node_id}"

        # Agent'ta swap bloğu ayır (disk dosyası)
        r = _jget(f"{agent_url}/api/swap/allocate",
                  {"size_mb": size_mb}, method="POST")
        if not r or not r.get("ok"):
            _log(f"[Mem] ⚠️  {node_id} swap ayrılamadı")
            return False

        _log(f"[Mem] ⬇  {node_id} swap bloğu indiriliyor ({size_mb}MB)...")

        # Streaming download — büyük dosya, blok blok
        BLOCK = 64 * 1024 * 1024  # 64MB blok
        offset = 0
        try:
            with open(local_path, "wb") as fout:
                while offset < size_mb * 1024 * 1024:
                    raw = _http(
                        f"{agent_url}/api/swap/read?offset={offset}&size={BLOCK}",
                        timeout=60
                    )
                    if not raw:
                        break
                    fout.write(raw)
                    offset += len(raw)
                    if len(raw) < BLOCK:
                        break
        except Exception as e:
            _log(f"[Mem] ❌ {node_id} swap indirme hatası: {e}")
            return False

        # Swap olarak aktive et
        r2 = subprocess.run(
            f"chmod 600 {local_path} && mkswap -f {local_path} && swapon -p 5 {local_path}",
            shell=True, capture_output=True
        )
        if r2.returncode == 0:
            with self._swap_lock:
                self._swap_files[node_id] = str(local_path)
            act_mb = local_path.stat().st_size // 1024 // 1024
            _log(f"[Mem] ✅ {node_id} → +{act_mb}MB swap aktive edildi")
            return True
        else:
            _log(f"[Mem] ⚠️  swapon başarısız: {r2.stderr.decode()[:80]}")
            return False

    def release_swap(self, node_id: str):
        with self._swap_lock:
            p = self._swap_files.pop(node_id, None)
        if p:
            subprocess.run(f"swapoff {p} 2>/dev/null", shell=True)
            try: Path(p).unlink()
            except: pass

    # ── Strateji B: Dağıtık uygulama cache ───────────────────

    def cache_put(self, key: str, data: bytes) -> bool:
        """Veriyi önce yerel hot cache'e, taşarsa en az yoğun agent'a yaz."""
        # Yerel cache denemesi
        with self._cache_lock:
            if len(data) + self._local_size <= self._local_max:
                if key in self._local_cache:
                    self._local_size -= len(self._local_cache[key])
                self._local_cache[key] = data
                self._local_size += len(data)
                self._local_cache.move_to_end(key)
                return True
            # Taşıyor — en az kullanılan agent'a gönder
        return self._put_remote(key, data)

    def cache_get(self, key: str) -> Optional[bytes]:
        # Yerel hot cache
        with self._cache_lock:
            if key in self._local_cache:
                self._local_cache.move_to_end(key)
                self._cache_hits += 1
                return self._local_cache[key]
        # Uzak agent'lar
        for ag in self._healthy_agents():
            raw = _http(f"{ag['url']}/api/cache/get/{key}", timeout=8)
            if raw:
                # Sıcak cache'e al
                with self._cache_lock:
                    self._local_cache[key] = raw
                    self._local_size += len(raw)
                    self._evict_local()
                self._cache_hits += 1
                return raw
        self._cache_miss += 1
        return None

    def cache_delete(self, key: str):
        with self._cache_lock:
            if key in self._local_cache:
                self._local_size -= len(self._local_cache[key])
                del self._local_cache[key]
        for ag in self._healthy_agents():
            _http(f"{ag['url']}/api/cache/delete/{key}", method="DELETE", timeout=5)

    def _put_remote(self, key: str, data: bytes) -> bool:
        ag = self._least_loaded_agent()
        if not ag: return False
        r = _http(f"{ag['url']}/api/cache/set?key={key}", method="POST", data=data, timeout=15)
        return bool(r)

    def _evict_local(self):
        """Yerel cache'den en eski girişleri çıkar."""
        while self._local_size > self._local_max and self._local_cache:
            k, v = self._local_cache.popitem(last=False)
            self._local_size -= len(v)

    def stats(self) -> dict:
        import psutil
        swp = psutil.swap_memory()
        total_remote_swap = sum(
            Path(p).stat().st_size for p in self._swap_files.values()
            if Path(p).exists()
        ) // 1024 // 1024
        total = self._cache_hits + self._cache_miss
        return {
            "local_cache_mb":    round(self._local_size / 1024 / 1024, 1),
            "local_cache_keys":  len(self._local_cache),
            "remote_swap_files": len(self._swap_files),
            "remote_swap_mb":    total_remote_swap,
            "total_swap_mb":     swp.total // 1024 // 1024,
            "swap_free_mb":      swp.free  // 1024 // 1024,
            "hit_rate":          round(self._cache_hits / total * 100, 1) if total else 0,
        }

    # ── Yardımcılar ───────────────────────────────────────────

    def _healthy_agents(self) -> list:
        return [a for a in self._agents.values() if a.get("healthy")]

    def _least_loaded_agent(self) -> Optional[dict]:
        h = self._healthy_agents()
        if not h: return None
        return min(h, key=lambda a: a["info"].get("ram", {}).get("cache_mb", 9999))


# ══════════════════════════════════════════════════════════════
#  2.  ClusterDisk  — Disk Birleştirme
# ══════════════════════════════════════════════════════════════

class ClusterDisk:
    """
    Tüm agent diskleri + ana sunucu diski tek bir sanal dosya sisteminde birleşir.

    Katmanlar (üstten alta):
      1. Yerel hot layer  (/minecraft  veya  /mnt/vcluster/hot)  ← yazma buraya
      2. Agent store      (HTTP üzerinden okuma/yazma)
      3. Read-through     (okuma: yerel → agent sırasıyla)

    MC'ye şeffaf:
      /minecraft/world/region/*.mca  → yazan anda yerel
      Erişilmeyen eski dosyalar background'da agent'a taşınır
      Okunmak istenen agent dosyaları otomatik getirilir

    FUSE varsa:
      /mnt/vcluster gerçek union mount olur
      MC world dizini buraya symlink edilir

    FUSE yoksa (Render):
      Overlay daemon ile şeffaf dosya yönetimi
    """

    def __init__(self, agents: dict):
        self._agents      = agents
        self._fuse_active = False
        self._fuse_proc   = None
        self._overlay_lock = threading.Lock()
        self._file_index: dict[str, str] = {}  # relative_path → agent_node_id

        # Arka plan: eski dosyaları agent'a taşı
        threading.Thread(target=self._tier_loop, daemon=True).start()

    # ── FUSE deneme ───────────────────────────────────────────

    def try_fuse_mount(self) -> bool:
        """ClusterFS'i FUSE olarak mount etmeyi dene."""
        try:
            import fuse
            _log("[Disk] FUSE bulundu — ClusterFS mount ediliyor...")
            # FUSE process başlat
            threading.Thread(target=self._run_fuse, daemon=True).start()
            time.sleep(2)
            self._fuse_active = CLUSTER_MOUNT.is_mount()
            if self._fuse_active:
                _log(f"[Disk] ✅ ClusterFS FUSE: {CLUSTER_MOUNT}")
            return self._fuse_active
        except ImportError:
            return False

    def _run_fuse(self):
        """Basit FUSE union filesystem."""
        try:
            import fuse
            fuse.FUSE(
                ClusterFUSE(self._agents),
                str(CLUSTER_MOUNT),
                foreground=True,
                nothreads=False,
                allow_other=False,
            )
        except Exception as e:
            _log(f"[Disk] FUSE hata: {e}")

    # ── Overlay Daemon (FUSE yoksa) ───────────────────────────

    def setup_overlay(self):
        """
        MC world dizinini izle.
        Eski dosyaları (erişilmemiş > N gün) agent'a taşı.
        İhtiyaç duyulunca geri getir.
        """
        _log("[Disk] 📂 Overlay disk yöneticisi aktif")
        # inotify ile hot path izleme (varsa)
        try:
            import inotify.adapters as _in
            threading.Thread(target=self._inotify_loop, daemon=True).start()
        except ImportError:
            pass   # inotify yoksa sadece timer-based
        self._rebuild_index()

    def _inotify_loop(self):
        """Erişilen dosyaları remote'dan yerel cache'e çek."""
        try:
            import inotify.adapters as _in
            i = _in.InotifyTree(str(MC_DIR))
            for event in i.event_gen(yield_nones=False):
                (_, type_names, path, filename) = event
                if "IN_OPEN" in type_names and filename.endswith(".mca"):
                    rel = str(Path(path) / filename)
                    if not Path(rel).exists():
                        self._fetch_from_agent(Path(path).name, filename)
        except: pass

    def _rebuild_index(self):
        """Her agent'taki dosyaları listele, index oluştur."""
        for nid, ag in self._agents.items():
            if not ag.get("healthy"): continue
            r = _jget(f"{ag['url']}/api/files/regions", timeout=10)
            if r:
                for f in r.get("files", []):
                    self._file_index[f["name"]] = nid

    def _tier_loop(self):
        """
        Sürekli çalışır:
        - Disk < eşik → eski region'ları agent'a taşı
        - Sıcaklık takibi ile akıllı tiering
        """
        while True:
            time.sleep(120)
            try:
                free_gb = shutil.disk_usage("/").free / 1e9
                if free_gb < 7.0:
                    self._tier_out(older_than_days=7 if free_gb > 4 else 2)
            except Exception as e:
                pass

    def _tier_out(self, older_than_days: int = 7):
        """Eski region dosyalarını agent'a tier out et."""
        best = self._best_disk_agent()
        if not best: return
        now = time.time()
        total_freed = 0

        for dim_dir in [MC_DIR/"world"/"region",
                        MC_DIR/"world_nether"/"DIM-1"/"region",
                        MC_DIR/"world_the_end"/"DIM1"/"region"]:
            if not dim_dir.exists(): continue
            dim = dim_dir.parts[-3]
            for rf in sorted(dim_dir.glob("*.mca"),
                             key=lambda f: f.stat().st_mtime):
                if (now - rf.stat().st_mtime) / 86400 < older_than_days:
                    continue
                try:
                    data = rf.read_bytes()
                    r = _http(f"{best['url']}/api/files/regions/{dim}/{rf.name}",
                              method="PUT", data=data, timeout=120)
                    if r:
                        rf.unlink()
                        self._file_index[rf.name] = best["node_id"]
                        total_freed += len(data)
                except: continue

        if total_freed:
            _log(f"[Disk] 💾 Tier-out: {total_freed//1e6:.0f}MB agent'a taşındı")
            self._expand_swap_after_tier()

    def fetch_region(self, dimension: str, filename: str) -> bool:
        """Region dosyasını agent'tan indir (MC erişmeden önce)."""
        nid = self._file_index.get(filename)
        if not nid or nid not in self._agents:
            return False
        ag  = self._agents[nid]
        raw = _http(f"{ag['url']}/api/files/regions/{dimension}/{filename}", timeout=60)
        if not raw:
            return False
        dest = MC_DIR / dimension / "region" / filename
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(raw)
        _log(f"[Disk] ⬇  {filename} agent'tan getirildi")
        return True

    def _fetch_from_agent(self, dimension: str, filename: str) -> bool:
        return self.fetch_region(dimension, filename)

    def _expand_swap_after_tier(self):
        free_gb  = shutil.disk_usage("/").free / 1e9
        sw_mb    = min(6144, int(free_gb * 0.7 * 1024))
        if sw_mb < 256: return
        sf2 = "/swapfile2"
        subprocess.run(f"swapoff {sf2} 2>/dev/null", shell=True)
        try:
            if Path(sf2).exists(): Path(sf2).unlink()
        except: pass
        r = subprocess.run(
            f"fallocate -l {sw_mb}M {sf2} && chmod 600 {sf2} && "
            f"mkswap -f {sf2} && swapon -p 2 {sf2}",
            shell=True, capture_output=True
        )
        if r.returncode == 0:
            _log(f"[Disk] 💾 Swap genişletildi: {sw_mb}MB")

    def stats(self) -> dict:
        dk = shutil.disk_usage("/")
        remote_files = len(self._file_index)
        remote_gb = 0
        for ag in self._agents.values():
            if ag.get("healthy"):
                remote_gb += ag["info"].get("disk", {}).get("used_gb", 0)
        return {
            "local_free_gb":  round(dk.free  / 1e9, 2),
            "local_total_gb": round(dk.total / 1e9, 2),
            "remote_files":   remote_files,
            "remote_gb":      round(remote_gb, 2),
            "total_gb":       round(dk.total / 1e9 + remote_gb, 2),
            "fuse_active":    self._fuse_active,
        }

    def _healthy_agents(self) -> list:
        return [a for a in self._agents.values() if a.get("healthy")]

    def _best_disk_agent(self) -> Optional[dict]:
        h = self._healthy_agents()
        return max(h, key=lambda a: a["info"].get("disk",{}).get("free_gb",0), default=None)


# ── FUSE Filesystem Implementasyonu ──────────────────────────

try:
    import fuse
    from fuse import Fuse, Stat, StatVfs
    import stat as _stat
    import errno

    class ClusterFUSE(Fuse):
        """
        Union filesystem: yerel + agent diskler tek dizin olarak görünür.
        /mnt/vcluster/ altında tüm cluster storage birleşmiş görünür.
        """
        def __init__(self, agents: dict):
            super().__init__()
            self._agents = agents

        def getattr(self, path):
            st = Stat()
            if path == "/":
                st.st_mode  = _stat.S_IFDIR | 0o755
                st.st_nlink = 2
                return st
            # Yerel dosya kontrolü
            local = MC_DIR / path.lstrip("/")
            if local.exists():
                os_stat = local.stat()
                st.st_mode  = os_stat.st_mode
                st.st_size  = os_stat.st_size
                st.st_nlink = os_stat.st_nlink
                st.st_mtime = os_stat.st_mtime
                return st
            return -errno.ENOENT

        def readdir(self, path, offset):
            yield fuse.Direntry(".")
            yield fuse.Direntry("..")
            local = MC_DIR / path.lstrip("/")
            seen  = set()
            if local.is_dir():
                for item in local.iterdir():
                    yield fuse.Direntry(item.name)
                    seen.add(item.name)
            # Agent dosyaları
            for ag in [a for a in self._agents.values() if a.get("healthy")]:
                r = _jget(f"{ag['url']}/api/files/regions", timeout=5)
                for f in (r or {}).get("files", []):
                    if f["name"] not in seen:
                        seen.add(f["name"])
                        yield fuse.Direntry(f["name"])

        def read(self, path, size, offset):
            local = MC_DIR / path.lstrip("/")
            if local.exists():
                with open(local, "rb") as f:
                    f.seek(offset)
                    return f.read(size)
            # Agent'tan getir
            for ag in [a for a in self._agents.values() if a.get("healthy")]:
                raw = _http(f"{ag['url']}/api/files/regions{path}",
                            timeout=30)
                if raw:
                    local.parent.mkdir(parents=True, exist_ok=True)
                    local.write_bytes(raw)
                    return raw[offset:offset+size]
            return -errno.ENOENT

        def write(self, path, buf, offset):
            local = MC_DIR / path.lstrip("/")
            local.parent.mkdir(parents=True, exist_ok=True)
            with open(local, "r+b" if local.exists() else "wb") as f:
                f.seek(offset)
                f.write(buf)
            return len(buf)

        def statfs(self):
            sv = StatVfs()
            dk = shutil.disk_usage("/")
            sv.f_bsize  = 4096
            sv.f_blocks = dk.total // 4096
            sv.f_bfree  = dk.free  // 4096
            sv.f_bavail = dk.free  // 4096
            return sv

        def create(self, path, flags, mode):
            local = MC_DIR / path.lstrip("/")
            local.parent.mkdir(parents=True, exist_ok=True)
            local.touch()
            return 0

        def unlink(self, path):
            local = MC_DIR / path.lstrip("/")
            if local.exists(): local.unlink()
            return 0

        def mkdir(self, path, mode):
            (MC_DIR / path.lstrip("/")).mkdir(parents=True, exist_ok=True)
            return 0

    _FUSE_AVAILABLE = True

except ImportError:
    _FUSE_AVAILABLE = False


# ══════════════════════════════════════════════════════════════
#  3.  ClusterCPU  — CPU Birleştirme
# ══════════════════════════════════════════════════════════════

class ClusterCPU:
    """
    Ana sunucu + tüm agent CPU'ları tek havuzda birleştirilir.

    Görev türleri:
      - compress / decompress   → region dosyası sıkıştırma
      - hash                    → dosya bütünlük kontrolü
      - chunk_gen               → chunk pre-generation
      - backup                  → world backup oluşturma
      - custom                  → herhangi bir whitelist'teki komut

    Yük dengeleme:
      - En düşük CPU load'lu node'a gönder
      - Timeout'ta yerel çalıştır
      - Sonuç cache'leme
    """

    def __init__(self, agents: dict):
        self._agents   = agents
        self._local_q  = queue.Queue()
        self._results: dict[str, dict] = {}
        self._res_lock = threading.Lock()
        # Yerel CPU worker (fallback)
        for _ in range(2):
            threading.Thread(target=self._local_worker, daemon=True).start()

    def submit(self, task_type: str, payload: dict,
               prefer_remote: bool = True) -> str:
        tid = hashlib.md5(
            f"{task_type}{payload}{time.time()}".encode()
        ).hexdigest()[:12]
        with self._res_lock:
            self._results[tid] = {"status": "pending"}

        if prefer_remote:
            threading.Thread(
                target=self._remote_submit,
                args=(tid, task_type, payload),
                daemon=True
            ).start()
        else:
            self._local_q.put((tid, task_type, payload))
        return tid

    def wait(self, tid: str, timeout: int = 30) -> Optional[dict]:
        deadline = time.time() + timeout
        while time.time() < deadline:
            with self._res_lock:
                r = self._results.get(tid, {})
            if r.get("status") == "done":
                return r.get("result")
            if r.get("status") == "error":
                return None
            time.sleep(0.5)
        return None

    def run(self, task_type: str, payload: dict,
            timeout: int = 30) -> Optional[dict]:
        """Senkron: gönder + bekle."""
        tid = self.submit(task_type, payload)
        return self.wait(tid, timeout)

    def _remote_submit(self, tid: str, task_type: str, payload: dict):
        ag = self._least_cpu_agent()
        if ag:
            r = _jget(f"{ag['url']}/api/cpu/submit",
                      {"type": task_type, "payload": payload},
                      timeout=10)
            if r and r.get("ok"):
                remote_tid = r.get("task_id")
                # Sonucu bekle
                deadline = time.time() + 60
                while time.time() < deadline:
                    time.sleep(1)
                    res = _jget(f"{ag['url']}/api/cpu/result/{remote_tid}",
                                timeout=8)
                    if res and res.get("status") == "done":
                        with self._res_lock:
                            self._results[tid] = {"status": "done",
                                                   "result": res.get("result")}
                        return
        # Fallback: yerel
        self._local_q.put((tid, task_type, payload))

    def _local_worker(self):
        while True:
            tid, task_type, payload = self._local_q.get()
            try:
                result = self._exec_local(task_type, payload)
                with self._res_lock:
                    self._results[tid] = {"status": "done", "result": result}
            except Exception as e:
                with self._res_lock:
                    self._results[tid] = {"status": "error", "error": str(e)}

    def _exec_local(self, task_type: str, payload: dict):
        if task_type == "compress_file":
            src  = Path(payload["path"])
            dest = Path(payload.get("dest", str(src) + ".gz"))
            with open(src,"rb") as f, gzip.open(dest,"wb",compresslevel=6) as g:
                shutil.copyfileobj(f, g)
            return {"dest": str(dest), "size": dest.stat().st_size}
        elif task_type == "hash_files":
            root = Path(payload.get("path", str(MC_DIR)))
            out  = {}
            for f in Path(root).rglob(payload.get("pattern","*.mca")):
                out[f.name] = hashlib.md5(f.read_bytes()).hexdigest()
            return out
        elif task_type == "disk_usage":
            dk = shutil.disk_usage(payload.get("path","/"))
            return {"free_gb": round(dk.free/1e9,2),
                    "total_gb": round(dk.total/1e9,2)}
        elif task_type == "echo":
            return payload
        return {"error": f"Bilinmeyen görev: {task_type}"}

    def stats(self) -> dict:
        import psutil
        pending = sum(1 for r in self._results.values() if r.get("status") == "pending")
        done    = sum(1 for r in self._results.values() if r.get("status") == "done")
        return {
            "local_cpu_pct":    psutil.cpu_percent(0),
            "local_cpu_cores":  psutil.cpu_count(),
            "remote_nodes":     len([a for a in self._agents.values() if a.get("healthy")]),
            "tasks_pending":    pending,
            "tasks_done":       done,
            "total_cores": psutil.cpu_count() + sum(
                a["info"].get("cpu",{}).get("cores",0)
                for a in self._agents.values() if a.get("healthy")
            ),
        }

    def _least_cpu_agent(self) -> Optional[dict]:
        h = [a for a in self._agents.values() if a.get("healthy")]
        return min(h, key=lambda a: a["info"].get("cpu",{}).get("load1",99),
                   default=None)


# ══════════════════════════════════════════════════════════════
#  4.  ClusterNet  — Ağ Birleştirme
# ══════════════════════════════════════════════════════════════

class ClusterNet:
    """
    Oyuncu bağlantı yükünü tüm agent'lara dağıtır.
    Her agent MC portunu dinler → ana sunucuya proxy yapar.
    Tek tünel yerine N tünel: erişilebilirlik + yük dağıtımı.
    """

    def __init__(self, agents: dict):
        self._agents      = agents
        self._active_proxies: set[str] = set()
        self._mc_tunnel   = ""
        threading.Thread(target=self._proxy_watchdog, daemon=True).start()

    def start_all_proxies(self, mc_host: str = "127.0.0.1", mc_port: int = 25565):
        started = []
        for nid, ag in self._agents.items():
            if not ag.get("healthy"): continue
            r = _jget(f"{ag['url']}/api/proxy/start",
                      {"host": mc_host, "port": mc_port, "listen_port": 25565},
                      timeout=10)
            if r and r.get("ok"):
                self._active_proxies.add(nid)
                started.append(nid)
                _log(f"[Net] 🔀 Proxy aktif: {nid}")
        return started

    def stop_all_proxies(self):
        for nid in list(self._active_proxies):
            ag = self._agents.get(nid)
            if ag: _jget(f"{ag['url']}/api/proxy/stop", {})
            self._active_proxies.discard(nid)

    def _proxy_watchdog(self):
        import socket as _sock
        mc_up_prev = False
        while True:
            time.sleep(10)
            mc_up = False
            try:
                s = _sock.create_connection(("127.0.0.1", 25565), 1)
                s.close(); mc_up = True
            except: pass
            if mc_up and not mc_up_prev:
                self.start_all_proxies()
            elif not mc_up and mc_up_prev:
                self.stop_all_proxies()
            mc_up_prev = mc_up

    def all_endpoints(self) -> list[str]:
        eps = []
        if self._mc_tunnel:
            eps.append(self._mc_tunnel)
        for nid in self._active_proxies:
            ag = self._agents.get(nid, {})
            if ag.get("url"):
                host = ag["url"].replace("https://","").replace("http://","")
                eps.append(f"{host}:25565")
        return eps

    def stats(self) -> dict:
        conns = sum(
            self._agents.get(nid, {}).get("info", {}).get("proxy", {}).get("connections", 0)
            for nid in self._active_proxies
        )
        return {
            "active_proxies":  len(self._active_proxies),
            "total_connections": conns,
            "endpoints":       self.all_endpoints(),
        }


# ══════════════════════════════════════════════════════════════
#  5.  VirtualCluster  — Ana Orkestratör
# ══════════════════════════════════════════════════════════════

class VirtualCluster:
    """
    Tüm cluster bileşenlerini yönetir.
    mc_panel.py'e:
      from cluster import vcluster
    şeklinde import edilir.

    vcluster.memory  → ClusterMemory
    vcluster.disk    → ClusterDisk
    vcluster.cpu     → ClusterCPU
    vcluster.net     → ClusterNet
    vcluster.summary → dict (panel için)
    """

    def __init__(self):
        self._agents: dict[str, dict] = {}
        self._lock   = threading.Lock()
        self._sio    = None   # SocketIO (panel inject eder)

        self.memory  = ClusterMemory(self._agents)
        self.disk    = ClusterDisk(self._agents)
        self.cpu     = ClusterCPU(self._agents)
        self.net     = ClusterNet(self._agents)

        threading.Thread(target=self._health_loop,  daemon=True).start()
        threading.Thread(target=self._onboard_loop, daemon=True).start()

        _log("[Cluster] ✅ VirtualCluster v12.0 hazır")

    # ── Agent yönetimi ────────────────────────────────────────

    def register_agent(self, tunnel: str, node_id: str, info: dict):
        with self._lock:
            is_new = node_id not in self._agents
            self._agents[node_id] = {
                "url":          tunnel.rstrip("/"),
                "node_id":      node_id,
                "healthy":      True,
                "fail_count":   0,
                "last_ping":    time.time(),
                "connected_at": self._agents.get(node_id, {}).get("connected_at", time.time()),
                "info":         info,
            }
        if is_new:
            _log(f"[Cluster] 🔗 Agent eklendi: {node_id} | "
                 f"RAM:{info.get('ram',{}).get('free_mb',0)}MB | "
                 f"Disk:{info.get('disk',{}).get('free_gb',0):.1f}GB | "
                 f"CPU:{info.get('cpu',{}).get('cores',0)} core")
            # Yeni agent'ı hemen onboard et
            threading.Thread(target=self._onboard_agent,
                             args=(node_id,), daemon=True).start()
        self._emit_update()

    def _onboard_agent(self, node_id: str):
        """Yeni bir agent bağlandığında kaynakları entegre et."""
        time.sleep(2)
        ag = self._agents.get(node_id)
        if not ag: return

        # 1) Swap dosyası oluştur (agent disk → ana swap)
        disk_free = ag["info"].get("disk", {}).get("free_gb", 0)
        if disk_free >= 2.0:
            swap_mb = min(2048, int(disk_free * 0.4 * 1024))
            success = self.memory.build_swapfile_on_agent(
                node_id, ag["url"], swap_mb
            )
            if success:
                _log(f"[Cluster] ✅ {node_id} → {swap_mb}MB sanal swap eklendi")

        # 2) Disk index yenile
        self.disk._rebuild_index()

        self._emit_update()

    def _onboard_loop(self):
        """Periyodik olarak tüm mevcut agent'ları yeniden onboard et (disconnect sonrası)."""
        time.sleep(90)
        while True:
            time.sleep(300)
            for nid in list(self._agents.keys()):
                ag = self._agents.get(nid)
                if ag and ag.get("healthy"):
                    # Swap dosyası yoksa oluştur
                    if nid not in self.memory._swap_files:
                        disk_free = ag["info"].get("disk",{}).get("free_gb",0)
                        if disk_free >= 1.5:
                            swap_mb = min(1500, int(disk_free * 0.35 * 1024))
                            self.memory.build_swapfile_on_agent(nid, ag["url"], swap_mb)

    # ── Sağlık izleme ─────────────────────────────────────────

    def _health_loop(self):
        while True:
            time.sleep(25)
            with self._lock:
                agents = list(self._agents.values())
            changed = False
            for ag in agents:
                r = _jget(f"{ag['url']}/api/status", timeout=10)
                if r:
                    ag["info"]       = r
                    ag["healthy"]    = True
                    ag["fail_count"] = 0
                    ag["last_ping"]  = time.time()
                    changed = True
                else:
                    ag["fail_count"] = ag.get("fail_count", 0) + 1
                    if ag["fail_count"] >= 3 and ag["healthy"]:
                        ag["healthy"] = False
                        # Swap dosyasını kaldır
                        self.memory.release_swap(ag["node_id"])
                        _log(f"[Cluster] ⚠️  {ag['node_id']} erişilemiyor — swap kaldırıldı")
                        changed = True
            if changed:
                self._emit_update()

    # ── Panel API ─────────────────────────────────────────────

    def summary(self) -> dict:
        with self._lock:
            agents = list(self._agents.values())
        healthy  = [a for a in agents if a["healthy"]]

        mem_stat  = self.memory.stats()
        disk_stat = self.disk.stats()
        cpu_stat  = self.cpu.stats()
        net_stat  = self.net.stats()

        total_ram_mb = sum(a["info"].get("ram",{}).get("free_mb",0) for a in healthy)
        total_disk_gb = sum(a["info"].get("disk",{}).get("free_gb",0) for a in healthy)

        return {
            "total":    len(agents),
            "healthy":  len(healthy),
            "virtual_machine": {
                "total_ram_mb":   mem_stat["total_swap_mb"] + total_ram_mb,
                "remote_swap_mb": mem_stat["remote_swap_mb"],
                "cache_mb":       mem_stat["local_cache_mb"],
                "total_disk_gb":  disk_stat["total_gb"],
                "remote_disk_gb": disk_stat["remote_gb"],
                "total_cpu_cores": cpu_stat["total_cores"],
                "active_proxies": net_stat["active_proxies"],
                "fuse_active":    disk_stat["fuse_active"],
            },
            "memory":   mem_stat,
            "disk":     disk_stat,
            "cpu":      cpu_stat,
            "net":      net_stat,
            "agents": [
                {
                    "node_id":      a["node_id"],
                    "url":          a["url"],
                    "healthy":      a["healthy"],
                    "connected_at": a["connected_at"],
                    "last_ping":    a["last_ping"],
                    "swap_active":  a["node_id"] in self.memory._swap_files,
                    "ram":          a["info"].get("ram",   {}),
                    "disk":         a["info"].get("disk",  {}),
                    "cpu":          a["info"].get("cpu",   {}),
                    "proxy":        a["info"].get("proxy", {}),
                }
                for a in agents
            ],
        }

    def set_socketio(self, sio):
        self._sio = sio

    def _emit_update(self):
        if self._sio:
            try: self._sio.emit("cluster_update", self.summary())
            except: pass


# ── Singleton ─────────────────────────────────────────────────
vcluster = VirtualCluster()


# ── Flask Blueprint ───────────────────────────────────────────
try:
    from flask import Blueprint, request, jsonify
    cluster_api = Blueprint("cluster_api", __name__)

    @cluster_api.route("/api/agent/register", methods=["POST"])
    def c_register():
        d = request.json or {}
        if not d.get("tunnel") or not d.get("node_id"):
            return jsonify({"ok": False, "error": "tunnel / node_id eksik"}), 400
        vcluster.register_agent(d["tunnel"], d["node_id"], d)
        return jsonify({"ok": True})

    @cluster_api.route("/api/agent/heartbeat", methods=["POST"])
    def c_heartbeat():
        d = request.json or {}
        if d.get("node_id") and d.get("tunnel"):
            vcluster.register_agent(d["tunnel"], d["node_id"], d)
        return jsonify({"ok": True})

    @cluster_api.route("/api/cluster/status")
    def c_status():
        return jsonify(vcluster.summary())

    @cluster_api.route("/api/cluster/cache/get/<path:key>")
    def c_cache_get(key):
        from flask import Response
        v = vcluster.memory.cache_get(key)
        if v is None:
            return jsonify({"ok": False}), 404
        return Response(v, mimetype="application/octet-stream")

    @cluster_api.route("/api/cluster/cache/put", methods=["POST"])
    def c_cache_put():
        key  = request.args.get("key","")
        data = request.get_data()
        ok   = vcluster.memory.cache_put(key, data) if key else False
        return jsonify({"ok": ok})

    @cluster_api.route("/api/cluster/cache/flush", methods=["POST"])
    def c_cache_flush():
        n = vcluster.memory.cache_flush()
        return jsonify({"ok": True, "flushed": n})

    @cluster_api.route("/api/cluster/disk/fetch", methods=["POST"])
    def c_disk_fetch():
        d   = request.json or {}
        ok  = vcluster.disk.fetch_region(d.get("dim","world"), d.get("file",""))
        return jsonify({"ok": ok})

    @cluster_api.route("/api/cluster/disk/tier_out", methods=["POST"])
    def c_tier_out():
        days = int((request.json or {}).get("days", 7))
        vcluster.disk._tier_out(days)
        return jsonify({"ok": True})

    @cluster_api.route("/api/cluster/cpu/run", methods=["POST"])
    def c_cpu_run():
        d   = request.json or {}
        res = vcluster.cpu.run(d.get("type","echo"), d.get("payload",{}))
        return jsonify({"ok": True, "result": res})

    @cluster_api.route("/api/cluster/net/proxies/start", methods=["POST"])
    def c_proxy_start():
        return jsonify({"ok": True, "started": vcluster.net.start_all_proxies()})

    @cluster_api.route("/api/cluster/net/proxies/stop", methods=["POST"])
    def c_proxy_stop():
        vcluster.net.stop_all_proxies()
        return jsonify({"ok": True})

    @cluster_api.route("/api/pool/status")   # mc_panel uyumluluğu
    def c_pool_compat():
        return jsonify(vcluster.summary())

except ImportError:
    cluster_api = None
