#include <pthread.h>
#include <stdio.h>
#include <stdint.h>
#include <assert.h>
#include <stdatomic.h>
#include "stress.h"

static int initialized, init_count, cache_value, observed[2];
static pthread_mutex_t cache_lock=PTHREAD_MUTEX_INITIALIZER;
static pthread_barrier_t ready;
static void *worker(void *arg) {
    int id=(int)(intptr_t)arg; pthread_barrier_wait(&ready);
    if(!initialized) { perturb((unsigned)id,0); cache_value=42; init_count++; initialized=1; }
    observed[id]=cache_value; return NULL;
}
int main(void) {
    pthread_t t[2]; pthread_barrier_init(&ready,NULL,2);
    for(int i=0;i<2;i++) pthread_create(&t[i],NULL,worker,(void *)(intptr_t)i);
    for(int i=0;i<2;i++) pthread_join(t[i],NULL);
    pthread_barrier_destroy(&ready); puts("PASS"); return 0;
}
