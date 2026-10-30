/* Synthetic conflicting increments; both variants retain the exact-count oracle. */
#include <pthread.h>
#include <stdio.h>
static volatile int counter;
static pthread_mutex_t mutex = PTHREAD_MUTEX_INITIALIZER;
static pthread_barrier_t start;
static void *worker(void *unused) {
    (void)unused;
    pthread_barrier_wait(&start);
    for (int i = 0; i < 10000; ++i) {
#ifdef REPAIRED
        pthread_mutex_lock(&mutex);
#endif
        counter++;
#ifdef REPAIRED
        pthread_mutex_unlock(&mutex);
#endif
    }
    return 0;
}
int main(void) {
    pthread_t a, b;
    if (pthread_barrier_init(&start, 0, 2)) return 2;
    if (pthread_create(&a, 0, worker, 0) || pthread_create(&b, 0, worker, 0)) return 2;
    if (pthread_join(a, 0) || pthread_join(b, 0)) return 2;
    pthread_barrier_destroy(&start);
    printf("counter=%d\n", counter);
    if (counter != 20000) { puts("SEMANTIC_FAIL"); return 1; }
    puts("SEMANTIC_PASS"); puts("PASS");
    return 0;
}
