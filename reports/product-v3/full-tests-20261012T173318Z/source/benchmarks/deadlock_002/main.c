#include <pthread.h>
#include <stdio.h>
#include <stdint.h>
#include <assert.h>
#include <stdatomic.h>
#include "stress.h"

static long accounts[2] = {1000, 1000};
static int transfers;
static pthread_mutex_t locks[2] = {PTHREAD_MUTEX_INITIALIZER, PTHREAD_MUTEX_INITIALIZER};
static pthread_barrier_t ready;
static void *worker(void *arg) {
    int from = (int)(intptr_t)arg, to = 1-from;
    long amount = from == 0 ? 100 : 50;
    pthread_mutex_lock(&locks[from]); printf("T%d LOCK A%d\n", from, from);
    pthread_barrier_wait(&ready);
    printf("T%d WAIT A%d\n", from, to); pthread_mutex_lock(&locks[to]);
    accounts[from] -= amount; accounts[to] += amount; transfers++;
    pthread_mutex_unlock(&locks[to]); pthread_mutex_unlock(&locks[from]);
    return NULL;
}
int main(void) {
    pthread_t t[2]; setvbuf(stdout,NULL,_IONBF,0); pthread_barrier_init(&ready,NULL,2);
    for(int i=0;i<2;i++) pthread_create(&t[i],NULL,worker,(void *)(intptr_t)i);
    for(int i=0;i<2;i++) pthread_join(t[i],NULL);
    pthread_barrier_destroy(&ready); puts("PASS"); return 0;
}
