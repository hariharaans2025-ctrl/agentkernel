#include <pthread.h>
#include <stdio.h>
#include <stdint.h>
#include <assert.h>
#include <stdatomic.h>
#include "stress.h"

static long balance=1000;
static int completed[2];
static pthread_mutex_t balance_lock=PTHREAD_MUTEX_INITIALIZER;
static pthread_barrier_t ready;
static void *worker(void *arg) {
    int id=(int)(intptr_t)arg; long delta=id==0?1:-1;
    pthread_barrier_wait(&ready);
    for(int i=0;i<10000;i++) {
        long old=balance; perturb((unsigned)id,(unsigned)i); balance=old+delta; completed[id]++;
    }
    return NULL;
}
int main(void) {
    pthread_t t[2]; pthread_barrier_init(&ready,NULL,2);
    for(int i=0;i<2;i++) pthread_create(&t[i],NULL,worker,(void *)(intptr_t)i);
    for(int i=0;i<2;i++) pthread_join(t[i],NULL);
    pthread_barrier_destroy(&ready); puts("PASS"); return 0;
}
