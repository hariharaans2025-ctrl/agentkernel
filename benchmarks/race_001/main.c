#include <pthread.h>
#include <stdio.h>
#include <stdint.h>
#include <assert.h>
#include "stress.h"

static long counter;
static pthread_mutex_t counter_lock = PTHREAD_MUTEX_INITIALIZER;
static pthread_barrier_t ready;
static int workload;
static void *worker(void *arg) {
    unsigned id = (unsigned)(uintptr_t)arg;
    pthread_barrier_wait(&ready);
    for (int i = 0; i < workload; ++i) {
        perturb(id, (unsigned)i);
    counter++;
    }
    return NULL;
}
int main(void) {
    pthread_t t[16]; int workers = setting("AK_WORKERS", 4, 16);
    workload = setting("AK_WORKLOAD", 10000, 1000000);
    pthread_barrier_init(&ready, NULL, (unsigned)workers);
    for (int i = 0; i < workers; ++i) pthread_create(&t[i], NULL, worker, (void *)(uintptr_t)i);
    for (int i = 0; i < workers; ++i) pthread_join(t[i], NULL);
    pthread_barrier_destroy(&ready);
    assert(counter == (long)workers * workload); puts("PASS"); return 0;
}
