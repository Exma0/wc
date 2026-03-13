/*
 * userswap.c — Render.com Userspace Swap  v3
 * ═══════════════════════════════════════════════════════════════════
 * Kernel swapon olmadan JVM'e dosya-destekli sanal bellek sağlar.
 * LD_PRELOAD ile JVM'e enjekte edilir, büyük mmap() çağrılarını
 * yerel dosyalara yönlendirir.
 *
 * v3 Yenilikleri:
 *   • Çok parça (shard) desteği: /swapfile_mmap_0 … _N
 *   • munmap() takibi → shard alanını geri dönüştür
 *   • /tmp/userswap.stats JSON (panel tarafından okunur)
 *   • Atomik istatistikler — thread güvenli
 *   • SIGTERM/SIGINT → temiz kapanış
 *
 * Derleme:
 *   gcc -O2 -shared -fPIC -o userswap.so userswap.c \
 *       -ldl -lpthread -DSWAP_SHARDS=4 -DSHARD_GB=1
 *
 * Kullanım:
 *   LD_PRELOAD=/app/userswap.so java -Xmx300m ...
 * ═══════════════════════════════════════════════════════════════════
 */
#define _GNU_SOURCE
#include <dlfcn.h>
#include <sys/mman.h>
#include <sys/stat.h>
#include <fcntl.h>
#include <unistd.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
#include <stdint.h>
#include <stdatomic.h>
#include <pthread.h>
#include <signal.h>

/* ── Konfigürasyon ──────────────────────────────────────────────── */
#ifndef SWAP_SHARDS
#  define SWAP_SHARDS 4
#endif
#ifndef SHARD_GB
#  define SHARD_GB 1
#endif
#define SHARD_SIZE     ((off_t)(SHARD_GB) * 1024L * 1024L * 1024L)
#define MIN_INTERCEPT  (128L * 1024)
#define STATS_FILE     "/tmp/userswap.stats"
#define ALLOC_TRACK    65536

/* ── Veri yapıları ──────────────────────────────────────────────── */
typedef struct {
    char            path[64];
    int             fd;
    off_t           used;
    off_t           size;
    pthread_mutex_t lock;
} Shard;

typedef struct {
    void*  addr;
    size_t length;
    int    shard_idx;
    off_t  file_offset;
} AllocEntry;

/* ── Globals ────────────────────────────────────────────────────── */
static Shard  shards[SWAP_SHARDS];
static int    num_shards  = 0;
static int    initialized = 0;

static pthread_mutex_t alloc_lock  = PTHREAD_MUTEX_INITIALIZER;
static AllocEntry      alloc_table[ALLOC_TRACK];
static int             alloc_count = 0;

static void* (*real_mmap)(void*,size_t,int,int,int,off_t) = NULL;
static int   (*real_munmap)(void*,size_t)                  = NULL;

static atomic_long stat_intercept = 0;
static atomic_long stat_mb        = 0;
static atomic_long stat_fallback  = 0;
static atomic_long stat_recycle   = 0;
static atomic_long stat_errors    = 0;

/* ── Yardımcılar ────────────────────────────────────────────────── */
static void _write_stats_once(void);

static void _alloc_record(void* addr, size_t len, int si, off_t off) {
    pthread_mutex_lock(&alloc_lock);
    if (alloc_count < ALLOC_TRACK)
        alloc_table[alloc_count++] = (AllocEntry){addr, len, si, off};
    pthread_mutex_unlock(&alloc_lock);
}

static int _alloc_remove(void* addr, size_t len, int* si, off_t* off) {
    pthread_mutex_lock(&alloc_lock);
    for (int i = 0; i < alloc_count; i++) {
        if (alloc_table[i].addr == addr && alloc_table[i].length == len) {
            *si  = alloc_table[i].shard_idx;
            *off = alloc_table[i].file_offset;
            alloc_table[i] = alloc_table[--alloc_count];
            pthread_mutex_unlock(&alloc_lock);
            return 1;
        }
    }
    pthread_mutex_unlock(&alloc_lock);
    return 0;
}

static void* _stats_thread(void* _) {
    (void)_;
    for (;;) {
        sleep(30);
        _write_stats_once();
    }
    return NULL;
}

static void _signal_handler(int sig) {
    (void)sig;
    _write_stats_once();
}

/* ── Başlatma ───────────────────────────────────────────────────── */
__attribute__((constructor))
static void userswap_init(void) {
    real_mmap   = dlsym(RTLD_NEXT, "mmap");
    real_munmap = dlsym(RTLD_NEXT, "munmap");
    if (!real_mmap || !real_munmap) {
        fprintf(stderr, "[UserSwap] ❌ dlsym başarısız\n");
        return;
    }

    int ok = 0;
    for (int i = 0; i < SWAP_SHARDS; i++) {
        snprintf(shards[i].path, sizeof(shards[i].path), "/swapfile_mmap_%d", i);
        shards[i].size = SHARD_SIZE;
        shards[i].used = 0;
        pthread_mutex_init(&shards[i].lock, NULL);

        struct stat st;
        int exists = (stat(shards[i].path, &st) == 0 && st.st_size >= SHARD_SIZE);
        int fl = O_RDWR | (exists ? 0 : O_CREAT | O_TRUNC);
        shards[i].fd = open(shards[i].path, fl, 0600);
        if (shards[i].fd < 0) {
            fprintf(stderr, "[UserSwap] ⚠️  Shard %d: open failed %s\n", i, strerror(errno));
            atomic_fetch_add(&stat_errors, 1);
            continue;
        }
        if (!exists) {
            fprintf(stderr, "[UserSwap] 💾 Shard %d/%d: %dGB oluşturuluyor...\n",
                    i+1, SWAP_SHARDS, SHARD_GB);
            if (posix_fallocate(shards[i].fd, 0, SHARD_SIZE) != 0) {
                if (ftruncate(shards[i].fd, SHARD_SIZE) != 0) {
                    fprintf(stderr, "[UserSwap] ❌ Shard %d boyutlandırılamadı\n", i);
                    close(shards[i].fd); shards[i].fd = -1;
                    atomic_fetch_add(&stat_errors, 1);
                    continue;
                }
            }
        }
        ok++;
    }

    num_shards  = ok;
    initialized = (ok > 0);
    if (initialized) {
        fprintf(stderr, "[UserSwap] ✅ v3: %d shard × %dGB = %dGB\n",
                ok, SHARD_GB, ok * SHARD_GB);
    } else {
        fprintf(stderr, "[UserSwap] ❌ Shard oluşturulamadı\n");
        return;
    }

    struct sigaction sa = {0};
    sa.sa_handler = _signal_handler;
    sigaction(SIGTERM, &sa, NULL);
    sigaction(SIGINT,  &sa, NULL);

    pthread_t tid;
    pthread_attr_t attr;
    pthread_attr_init(&attr);
    pthread_attr_setdetachstate(&attr, PTHREAD_CREATE_DETACHED);
    pthread_create(&tid, &attr, _stats_thread, NULL);
    pthread_attr_destroy(&attr);

    _write_stats_once();
}

__attribute__((destructor))
static void userswap_fini(void) {
    _write_stats_once();
    fprintf(stderr,
        "[UserSwap] 📊 intercept=%ld file_mb=%ld fallback=%ld recycle_mb=%ld err=%ld\n",
        (long)atomic_load(&stat_intercept),
        (long)atomic_load(&stat_mb),
        (long)atomic_load(&stat_fallback),
        (long)atomic_load(&stat_recycle),
        (long)atomic_load(&stat_errors));
    for (int i = 0; i < SWAP_SHARDS; i++)
        if (shards[i].fd >= 0) close(shards[i].fd);
}

/* ── mmap() kancası ─────────────────────────────────────────────── */
void* mmap(void* addr, size_t length, int prot, int flags, int fd, off_t offset) {
    if (!initialized
     || !(flags & MAP_ANONYMOUS)
     ||  (flags & MAP_FIXED)
     || length < (size_t)MIN_INTERCEPT
     || !(prot & (PROT_READ | PROT_WRITE)))
        return real_mmap(addr, length, prot, flags, fd, offset);

    size_t aligned = (length + 4095UL) & ~4095UL;

    /* En az dolu shard'ı bul */
    int   best = -1;
    off_t boff = 0;
    off_t bmin = SHARD_SIZE + 1;

    for (int i = 0; i < SWAP_SHARDS; i++) {
        if (shards[i].fd < 0) continue;
        pthread_mutex_lock(&shards[i].lock);
        if (shards[i].used + (off_t)aligned <= shards[i].size
            && shards[i].used < bmin) {
            bmin = shards[i].used;
            best = i;
            boff = shards[i].used;
        }
        pthread_mutex_unlock(&shards[i].lock);
    }

    if (best < 0) {
        atomic_fetch_add(&stat_fallback, 1);
        return real_mmap(addr, length, prot, flags, fd, offset);
    }

    /* Rezerve et */
    pthread_mutex_lock(&shards[best].lock);
    boff = shards[best].used;
    shards[best].used += (off_t)aligned;
    pthread_mutex_unlock(&shards[best].lock);

    /* MAP_ANONYMOUS + MAP_PRIVATE temizle, MAP_SHARED ekle */
    int nf = (flags & ~MAP_ANONYMOUS & ~MAP_PRIVATE) | MAP_SHARED;
    void* p = real_mmap(addr, length, prot, nf, shards[best].fd, boff);

    if (p == MAP_FAILED) {
        /* Geri al */
        pthread_mutex_lock(&shards[best].lock);
        if (shards[best].used == boff + (off_t)aligned)
            shards[best].used = boff;
        pthread_mutex_unlock(&shards[best].lock);
        atomic_fetch_add(&stat_fallback, 1);
        atomic_fetch_add(&stat_errors, 1);
        return real_mmap(addr, length, prot, flags, fd, offset);
    }

    _alloc_record(p, length, best, boff);
    atomic_fetch_add(&stat_intercept, 1);
    atomic_fetch_add(&stat_mb, (long)(length >> 20));
    return p;
}

/* ── munmap() kancası — alanı geri dönüştür ─────────────────────── */
int munmap(void* addr, size_t length) {
    int   si;
    off_t off;
    if (_alloc_remove(addr, length, &si, &off)) {
        size_t aligned = (length + 4095UL) & ~4095UL;
        pthread_mutex_lock(&shards[si].lock);
        if (off + (off_t)aligned == shards[si].used) {
            shards[si].used = off;
            atomic_fetch_add(&stat_recycle, (long)(aligned >> 20));
        }
        pthread_mutex_unlock(&shards[si].lock);
    }
    return real_munmap(addr, length);
}

/* ── JSON istatistik ────────────────────────────────────────────── */
static void _write_stats_once(void) {
    FILE* f = fopen(STATS_FILE ".tmp", "w");
    if (!f) return;

    long total_cap_mb = (long)num_shards * SHARD_GB * 1024;
    long used_mb      = 0;
    for (int i = 0; i < SWAP_SHARDS; i++) {
        if (shards[i].fd < 0) continue;
        pthread_mutex_lock(&shards[i].lock);
        used_mb += (long)(shards[i].used >> 20);
        pthread_mutex_unlock(&shards[i].lock);
    }

    fprintf(f, "{\n");
    fprintf(f, "  \"version\": 3,\n");
    fprintf(f, "  \"total_mb\": %ld,\n", total_cap_mb);
    fprintf(f, "  \"used_mb\": %ld,\n",  used_mb);
    fprintf(f, "  \"free_mb\": %ld,\n",  total_cap_mb - used_mb);
    fprintf(f, "  \"pct\": %ld,\n",
            total_cap_mb > 0 ? used_mb * 100 / total_cap_mb : 0);
    fprintf(f, "  \"intercept\": %ld,\n", (long)atomic_load(&stat_intercept));
    fprintf(f, "  \"fallback\":  %ld,\n", (long)atomic_load(&stat_fallback));
    fprintf(f, "  \"recycle_mb\": %ld,\n",(long)atomic_load(&stat_recycle));
    fprintf(f, "  \"errors\": %ld,\n",    (long)atomic_load(&stat_errors));
    fprintf(f, "  \"num_shards\": %d,\n", num_shards);
    fprintf(f, "  \"shards\": [\n");
    for (int i = 0; i < SWAP_SHARDS; i++) {
        long su = 0, st = 0;
        if (shards[i].fd >= 0) {
            pthread_mutex_lock(&shards[i].lock);
            su = (long)(shards[i].used >> 20);
            st = (long)(shards[i].size >> 20);
            pthread_mutex_unlock(&shards[i].lock);
        }
        fprintf(f, "    {\"id\":%d,\"used_mb\":%ld,\"total_mb\":%ld,\"ok\":%d}%s\n",
                i, su, st, shards[i].fd >= 0 ? 1 : 0,
                i < SWAP_SHARDS - 1 ? "," : "");
    }
    fprintf(f, "  ]\n}\n");
    fclose(f);
    rename(STATS_FILE ".tmp", STATS_FILE);
}
