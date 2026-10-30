#include "state.h"
#include <pthread.h>
#include <stdatomic.h>
#include <stdio.h>
#include <string.h>
#include <sched.h>
#define LOOPS 300
static Account account = {PTHREAD_MUTEX_INITIALIZER, 0};
static _Atomic int done = 0;
static pthread_barrier_t ready;
static void *writer(void *arg) {
    int amount = (int)(long)arg;
    pthread_barrier_wait(&ready);
    for (int i = 0; i < LOOPS; ++i) deposit(&account, amount);
    atomic_fetch_add(&done, 1);
    return NULL;
}
static void *reader(void *unused) {
    (void)unused; pthread_barrier_wait(&ready);
    while (atomic_load(&done) < 4) { (void)read_balance(&account); sched_yield(); }
    return NULL;
}
int main(int argc, char **argv) {
    pthread_t threads[5]; pthread_barrier_init(&ready, NULL, 5);
    for (long i = 0; i < 4; ++i) pthread_create(&threads[i], NULL, writer, (void *)(i+1));
    pthread_create(&threads[4], NULL, reader, NULL);
    for (int i = 0; i < 5; ++i) pthread_join(threads[i], NULL);
    long final = read_balance(&account);
    if (final != LOOPS * 10) { fprintf(stderr,"Wrong balance: %ld\n",final); return 1; }
    puts(argc > 1 && !strcmp(argv[1],"--check") ? "SEMANTIC_PASS" : "PASS");
    return 0;
}
