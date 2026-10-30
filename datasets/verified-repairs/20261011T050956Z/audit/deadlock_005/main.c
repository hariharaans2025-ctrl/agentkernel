#include <pthread.h>
#include <stdio.h>
#include <stdint.h>
#include <assert.h>
#include <stdatomic.h>
#include "stress.h"

static pthread_mutex_t state = PTHREAD_MUTEX_INITIALIZER;
static pthread_barrier_t ready;
static int shutdown_requested, pending=3, completed;
static void *worker(void *unused) {
    (void)unused; pthread_barrier_wait(&ready); puts("T2 WAIT state"); pthread_mutex_lock(&state);
    while(pending) { pending--; completed++; }
    int stopped=shutdown_requested; pthread_mutex_unlock(&state);
    assert(stopped); return NULL;
}
int main(void) {
    pthread_t t; setvbuf(stdout,NULL,_IONBF,0); pthread_barrier_init(&ready,NULL,2);
    pthread_mutex_lock(&state); puts("T1 LOCK state"); shutdown_requested=1;
    pthread_mutex_unlock(&state);
    pthread_create(&t,NULL,worker,NULL); pthread_barrier_wait(&ready);
    puts("T1 WAIT worker_exit"); pthread_join(t,NULL);
    pthread_barrier_destroy(&ready); puts("PASS"); return 0;
}
