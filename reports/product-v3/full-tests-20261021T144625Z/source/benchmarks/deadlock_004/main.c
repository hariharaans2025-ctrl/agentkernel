#include <pthread.h>
#include <stdio.h>
#include <stdint.h>
#include <assert.h>
#include <stdatomic.h>
#include "stress.h"

static pthread_mutex_t cache_lock = PTHREAD_MUTEX_INITIALIZER, log_lock = PTHREAD_MUTEX_INITIALIZER;
static pthread_barrier_t ready;
static int cache_value=42, logged_value, logs, reads;
static void *cache_reader(void *unused) {
    (void)unused; pthread_mutex_lock(&cache_lock); puts("T1 LOCK cache");
    pthread_barrier_wait(&ready); puts("T1 WAIT logger"); pthread_mutex_lock(&log_lock);
    logged_value=cache_value; reads++; logs++;
    pthread_mutex_unlock(&log_lock); pthread_mutex_unlock(&cache_lock); return NULL;
}
static void *logger(void *unused) {
    (void)unused; pthread_mutex_lock(&log_lock); puts("T2 LOCK logger");
    pthread_barrier_wait(&ready); puts("T2 WAIT cache"); pthread_mutex_lock(&cache_lock);
    logged_value=cache_value; reads++; logs++;
    pthread_mutex_unlock(&cache_lock); pthread_mutex_unlock(&log_lock); return NULL;
}
int main(void) {
    pthread_t a,b; setvbuf(stdout,NULL,_IONBF,0); pthread_barrier_init(&ready,NULL,2);
    pthread_create(&a,NULL,cache_reader,NULL); pthread_create(&b,NULL,logger,NULL);
    pthread_join(a,NULL); pthread_join(b,NULL); pthread_barrier_destroy(&ready); puts("PASS"); return 0;
}
