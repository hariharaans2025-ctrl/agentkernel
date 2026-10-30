#include <pthread.h>
#include <stdio.h>
#include <stdint.h>

static pthread_mutex_t a = PTHREAD_MUTEX_INITIALIZER;
static pthread_mutex_t b = PTHREAD_MUTEX_INITIALIZER;
static pthread_barrier_t ready;

static void *worker(void *arg) {
    int id = (int)(intptr_t)arg;
    pthread_mutex_t *first = id == 1 ? &a : &b;
    pthread_mutex_t *second = id == 1 ? &b : &a;
    pthread_mutex_lock(first);
    printf("T%d LOCK %s\n", id, first == &a ? "A" : "B");
    pthread_barrier_wait(&ready);
    printf("T%d WAIT %s\n", id, second == &a ? "A" : "B");
    pthread_mutex_lock(second);
    pthread_mutex_unlock(second);
    pthread_mutex_unlock(first);
    return NULL;
}

int main(void) {
    pthread_t t1, t2;
    setvbuf(stdout, NULL, _IONBF, 0);
    pthread_barrier_init(&ready, NULL, 2);
    pthread_create(&t1, NULL, worker, (void *)(intptr_t)1);
    pthread_create(&t2, NULL, worker, (void *)(intptr_t)2);
    pthread_join(t1, NULL);
    pthread_join(t2, NULL);
    pthread_barrier_destroy(&ready);
    puts("PASS");
    return 0;
}
