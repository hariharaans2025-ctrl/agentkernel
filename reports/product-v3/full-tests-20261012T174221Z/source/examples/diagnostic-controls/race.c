/* Synthetic TSan negative and positive controls, not a repair or benchmark fixture. */
#include <pthread.h>
#include <stdio.h>
static volatile int counter;
static pthread_barrier_t start;
#ifdef SAFE
static pthread_mutex_t mutex = PTHREAD_MUTEX_INITIALIZER;
#endif
static void *worker(void *unused) {
    (void)unused;
    pthread_barrier_wait(&start);
    for (int i = 0; i < 10000; ++i) {
#ifdef SAFE
        pthread_mutex_lock(&mutex);
#endif
        counter++;
#ifdef SAFE
        pthread_mutex_unlock(&mutex);
#endif
    }
    return 0;
}
int main(void) {
    pthread_t a, b;
    pthread_barrier_init(&start, 0, 2);
    if (pthread_create(&a, 0, worker, 0) || pthread_create(&b, 0, worker, 0)) return 2;
    pthread_join(a, 0);
    pthread_join(b, 0);
    pthread_barrier_destroy(&start);
    printf("counter=%d\n", counter);
#ifdef SAFE
    if (counter != 20000) return 1;
#endif
    puts("PASS");
    return 0;
}
