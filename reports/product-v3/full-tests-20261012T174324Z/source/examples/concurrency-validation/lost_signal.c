/* Synthetic lost-notification control; REPAIRED guards waits with the predicate. */
#include <pthread.h>
#include <stdio.h>
static pthread_mutex_t mutex = PTHREAD_MUTEX_INITIALIZER;
static pthread_cond_t ready_cv = PTHREAD_COND_INITIALIZER;
static int ready, consumed, value;
static void *producer(void *unused) {
    (void)unused;
    pthread_mutex_lock(&mutex);
    value = 42;
    ready = 1;
    pthread_cond_signal(&ready_cv);
    pthread_mutex_unlock(&mutex);
    return 0;
}
static void *consumer(void *unused) {
    (void)unused;
    pthread_mutex_lock(&mutex);
#ifdef REPAIRED
    while (!ready) pthread_cond_wait(&ready_cv, &mutex);
#else
    fprintf(stderr, "CONSUMER unconditional wait after producer finished\n");
    pthread_cond_wait(&ready_cv, &mutex);
#endif
    consumed = value;
    pthread_mutex_unlock(&mutex);
    return 0;
}
int main(void) {
    pthread_t p, c;
    if (pthread_create(&p, 0, producer, 0)) return 2;
    /* Force signal-before-wait without relying on timing or sleeps. */
    if (pthread_join(p, 0)) return 2;
    if (pthread_create(&c, 0, consumer, 0) || pthread_join(c, 0)) return 2;
    if (ready != 1 || consumed != 42) { puts("SEMANTIC_FAIL"); return 1; }
    puts("SEMANTIC_PASS"); puts("PASS");
    return 0;
}
