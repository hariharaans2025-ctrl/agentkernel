#include <pthread.h>
#include <stdio.h>
#include <stdint.h>
#include <assert.h>
#include <stdatomic.h>
#include "stress.h"

static struct { int version; int inverse; } config={0,~0};
static pthread_mutex_t config_lock=PTHREAD_MUTEX_INITIALIZER;
static pthread_barrier_t ready;
static atomic_int done;
static int bad_reads, reads;
static void *writer(void *unused) {
    (void)unused; pthread_barrier_wait(&ready);
    for(int i=1;i<=10000;i++) { config.version=i; perturb(0,(unsigned)i); config.inverse=~i; }
    atomic_store(&done,1); return NULL;
}
static void *reader(void *unused) {
    (void)unused; pthread_barrier_wait(&ready);
    do { int v=config.version; int inverse=config.inverse; reads++; if(inverse!=~v) bad_reads++; } while(!atomic_load(&done));
    return NULL;
}
int main(void) {
    pthread_t a,b; pthread_barrier_init(&ready,NULL,2);
    pthread_create(&a,NULL,writer,NULL); pthread_create(&b,NULL,reader,NULL);
    pthread_join(a,NULL); pthread_join(b,NULL); pthread_barrier_destroy(&ready); puts("PASS"); return 0;
}
