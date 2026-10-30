#include <stdio.h>
#include <stdlib.h>
#include <stdatomic.h>
#include <pthread.h>
#include <sched.h>
#include "thpool.h"
enum { JOBS = 256, PRODUCERS = 2 };
static _Atomic int seen[JOBS];
static _Atomic int completed;
static _Atomic long sum;
static int identities[JOBS];
static threadpool pool;
static void execute(void *arg) {
    int id = *(int *)arg;
    if (id < 0 || id >= JOBS) abort();
    sched_yield();
    if (atomic_fetch_add(&seen[id], 1) != 0) abort();
    atomic_fetch_add(&sum, id + 1);
    atomic_fetch_add(&completed, 1);
}
static void *produce(void *arg) {
    int lane = *(int *)arg;
    for (int id = lane; id < JOBS; id += PRODUCERS) {
        identities[id] = id;
        if (thpool_add_work(pool, execute, &identities[id]) != 0) abort();
    }
    return NULL;
}
int main(void) {
    for (int round = 0; round < 2; round++) {
        for (int i = 0; i < JOBS; i++) atomic_store(&seen[i], 0);
        atomic_store(&completed, 0); atomic_store(&sum, 0);
        pool = thpool_init(4);
        if (!pool) return 11;
        int lanes[PRODUCERS]; pthread_t threads[PRODUCERS];
        for (int i = 0; i < PRODUCERS; i++) {
            lanes[i] = i;
            if (pthread_create(&threads[i], NULL, produce, &lanes[i])) return 12;
        }
        for (int i = 0; i < PRODUCERS; i++) if (pthread_join(threads[i], NULL)) return 13;
        thpool_wait(pool); thpool_destroy(pool);
        if (atomic_load(&completed) != JOBS || atomic_load(&sum) != (long)JOBS * (JOBS + 1) / 2) return 14;
        for (int i = 0; i < JOBS; i++) if (atomic_load(&seen[i]) != 1) return 15;
    }
    puts("PASS SEMANTIC_PASS: 512 jobs exactly once; concurrent producers; safe repeated shutdown");
    return 0;
}
