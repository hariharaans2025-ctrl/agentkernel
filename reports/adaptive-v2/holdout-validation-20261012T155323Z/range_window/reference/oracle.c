#include "state.h"
#include <pthread.h>
#include <stdatomic.h>
#include <stdio.h>
#include <string.h>
#include <sched.h>
static Window window = {PTHREAD_MUTEX_INITIALIZER, 0, 16};
static _Atomic int bad = 0;
static pthread_barrier_t ready;
static void *writer(void *unused) {
    (void)unused; pthread_barrier_wait(&ready);
    for (int i = 1; i <= 300; ++i) set_window(&window, i, i + 16);
    return NULL;
}
static void *reader(void *unused) {
    (void)unused; pthread_barrier_wait(&ready);
    for (int i = 0; i < 600; ++i) {
        int lower, upper; get_window(&window, &lower, &upper);
        if (upper - lower != 16) atomic_fetch_add(&bad, 1);
    }
    return NULL;
}
int main(int argc, char **argv) {
    pthread_t threads[3]; pthread_barrier_init(&ready, NULL, 3);
    pthread_create(&threads[0], NULL, writer, NULL);
    pthread_create(&threads[1], NULL, reader, NULL);
    pthread_create(&threads[2], NULL, reader, NULL);
    for (int i = 0; i < 3; ++i) pthread_join(threads[i], NULL);
    set_window(&window, 10000, 10016);
    int lower, upper; get_window(&window, &lower, &upper);
    if (atomic_load(&bad) || lower != 10000 || upper != 10016) return 1;
    puts(argc > 1 && !strcmp(argv[1],"--check") ? "SEMANTIC_PASS" : "PASS");
    return 0;
}
