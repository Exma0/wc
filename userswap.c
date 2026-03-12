/*
 * userswap.c — Render.com Userspace Swap  v2
 * swapon olmadan JVM'e swap eşdeğeri sağlar.
 * BUG FIX: MAP_PRIVATE de temizleniyor (MAP_SHARED|MAP_PRIVATE = EINVAL)
 */
#define _GNU_SOURCE
#include <dlfcn.h>
#include <sys/mman.h>
#include <sys/stat.h>
#include <fcntl.h>
#include <unistd.h>
#include <stdio.h>
#include <errno.h>
#include <stdint.h>
#include <pthread.h>

#define SWAP_FILE     "/swapfile_mmap"
#define SWAP_SIZE     (4L*1024L*1024L*1024L)
#define MIN_INTERCEPT (256L*1024)

static int             swap_fd  = -1;
static off_t           swap_pos = 0;
static pthread_mutex_t swap_mx  = PTHREAD_MUTEX_INITIALIZER;
static void* (*real_mmap)(void*,size_t,int,int,int,off_t) = NULL;
static volatile long stat_ok=0, stat_mb=0, stat_fb=0;

__attribute__((constructor))
static void userswap_init(void) {
    real_mmap = dlsym(RTLD_NEXT,"mmap");
    if (!real_mmap) return;

    struct stat st;
    if (stat(SWAP_FILE,&st)==0 && st.st_size>=SWAP_SIZE) {
        swap_fd = open(SWAP_FILE,O_RDWR);
        if (swap_fd>=0) {
            fprintf(stderr,"[UserSwap] ✅ Mevcut %dGB swap kullanılıyor\n",(int)(SWAP_SIZE>>30));
            return;
        }
    }

    swap_fd = open(SWAP_FILE,O_RDWR|O_CREAT|O_TRUNC,0600);
    if (swap_fd<0) { fprintf(stderr,"[UserSwap] ❌ open errno=%d\n",errno); return; }

    fprintf(stderr,"[UserSwap] 💾 %dGB dosya-destekli swap oluşturuluyor...\n",(int)(SWAP_SIZE>>30));
    if (posix_fallocate(swap_fd,0,SWAP_SIZE)!=0)
        ftruncate(swap_fd,SWAP_SIZE);

    fprintf(stderr,"[UserSwap] ✅ Userspace Swap hazır: %s (%dGB)\n",SWAP_FILE,(int)(SWAP_SIZE>>30));
    fprintf(stderr,"[UserSwap]    Kernel RAM basıncında JVM sayfalarını bu dosyaya yazar\n");
}

__attribute__((destructor))
static void userswap_fini(void) {
    if (swap_fd>=0) {
        fprintf(stderr,"[UserSwap] 📊 %ld intercept | %ldMB file-backed | %ld fallback\n",stat_ok,stat_mb,stat_fb);
        close(swap_fd);
    }
}

void* mmap(void *addr, size_t length, int prot, int flags, int fd, off_t offset) {
    if (swap_fd>=0
     && (flags & MAP_ANONYMOUS)
     && !(flags & MAP_FIXED)
     && length>=(size_t)MIN_INTERCEPT
     && (prot & (PROT_READ|PROT_WRITE)))
    {
        size_t aligned = (length+4095UL)&~4095UL;
        off_t  swap_off;
        pthread_mutex_lock(&swap_mx);
        int has_space = (swap_pos+(off_t)aligned <= SWAP_SIZE);
        if (has_space) { swap_off=swap_pos; swap_pos+=(off_t)aligned; }
        pthread_mutex_unlock(&swap_mx);

        if (has_space) {
            /* DÜZELTME: MAP_ANONYMOUS ve MAP_PRIVATE ikisi de temizlenmeli */
            int nf = (flags & ~MAP_ANONYMOUS & ~MAP_PRIVATE) | MAP_SHARED;
            void* p = real_mmap(addr,length,prot,nf,swap_fd,swap_off);
            if (p!=MAP_FAILED) {
                __sync_fetch_and_add(&stat_ok,1L);
                __sync_fetch_and_add(&stat_mb,(long)(length>>20));
                return p;
            }
            pthread_mutex_lock(&swap_mx);
            if (swap_pos==swap_off+(off_t)aligned) swap_pos=swap_off;
            pthread_mutex_unlock(&swap_mx);
            __sync_fetch_and_add(&stat_fb,1L);
        }
    }
    return real_mmap(addr,length,prot,flags,fd,offset);
}
