#include "state.h"
void update_pair(int n) {
    pthread_mutex_lock(&guard);
    left = n;
    pthread_mutex_unlock(&guard);
    sched_yield();
    pthread_mutex_lock(&guard);
    right = -n;
    pthread_mutex_unlock(&guard);
}
int snapshot_ok(void) {
    int a = left;
    sched_yield();
    int b = right;
    return a + b == 0;
}
