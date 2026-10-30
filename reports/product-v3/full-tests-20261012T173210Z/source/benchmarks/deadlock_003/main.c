#include <pthread.h>
#include <stdio.h>
#include <stdint.h>
#include <assert.h>
#include <stdatomic.h>
#include "stress.h"

static pthread_mutex_t state = PTHREAD_MUTEX_INITIALIZER, delivery = PTHREAD_MUTEX_INITIALIZER;
static pthread_cond_t available = PTHREAD_COND_INITIALIZER;
static pthread_barrier_t ready;
static int value, produced, consumed, received;
static void *producer(void *unused) {
    (void)unused; pthread_barrier_wait(&ready);
    puts("T1 WAIT delivery"); pthread_mutex_lock(&delivery);
    pthread_mutex_lock(&state); value=42; produced=1;
    pthread_cond_signal(&available); pthread_mutex_unlock(&state);
    pthread_mutex_unlock(&delivery); return NULL;
}
static void *consumer(void *unused) {
    (void)unused; pthread_mutex_lock(&delivery); puts("T2 LOCK delivery");
    pthread_barrier_wait(&ready); pthread_mutex_lock(&state);
    while(!produced) { puts("T2 WAIT available"); pthread_cond_wait(&available,&state); }
    received=value; consumed++; pthread_mutex_unlock(&state);
    pthread_mutex_unlock(&delivery); return NULL;
}
int main(void) {
    pthread_t a,b; setvbuf(stdout,NULL,_IONBF,0); pthread_barrier_init(&ready,NULL,2);
    pthread_create(&a,NULL,producer,NULL); pthread_create(&b,NULL,consumer,NULL);
    pthread_join(a,NULL); pthread_join(b,NULL); pthread_barrier_destroy(&ready);
    puts("PASS"); return 0;
}
