#include "state.h"
#include <stdio.h>
pthread_mutex_t guard = PTHREAD_MUTEX_INITIALIZER;
pthread_cond_t arrived = PTHREAD_COND_INITIALIZER, available = PTHREAD_COND_INITIALIZER;
int waiting, ready;
static int consumed;
static void *consumer(void *unused) {
    (void)unused;
    pthread_mutex_lock(&guard);
    ++waiting;
    pthread_cond_signal(&arrived);
    while (!ready) pthread_cond_wait(&available,&guard);
    ++consumed;
    pthread_mutex_unlock(&guard);
    return 0;
}
int main(void) {
    pthread_t a,b;
    if (pthread_create(&a,0,consumer,0) || pthread_create(&b,0,consumer,0)) return 2;
    publish();
    if (pthread_join(a,0) || pthread_join(b,0)) return 2;
    if (waiting != 2 || consumed != 2 || ready != 1) { puts("SEMANTIC_FAIL"); return 1; }
    puts("SEMANTIC_PASS"); puts("PASS");
    return 0;
}
