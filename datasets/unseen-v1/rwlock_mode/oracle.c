#include "state.h"
#include <stdio.h>
pthread_rwlock_t guard = PTHREAD_RWLOCK_INITIALIZER;
int value;
static pthread_barrier_t start;
static void *worker(void *unused) {
    (void)unused;
    pthread_barrier_wait(&start);
    update();
    return 0;
}
int main(void) {
    pthread_t a,b;
    if (pthread_barrier_init(&start,0,2)) return 2;
    if (pthread_create(&a,0,worker,0) || pthread_create(&b,0,worker,0)) return 2;
    if (pthread_join(a,0) || pthread_join(b,0)) return 2;
    if (value != 4000) { printf("SEMANTIC_FAIL value=%d\n",value); return 1; }
    puts("SEMANTIC_PASS"); puts("PASS");
    return 0;
}
