#include "state.h"
void update_pair(int n) {
    pthread_mutex_lock(&guard);
    left = n;
    sched_yield();
    right = -n;
    pthread_mutex_unlock(&guard);
}
int snapshot_ok(void) {
    /* Read both fields in the same critical section as the writer. */
    pthread_mutex_lock(&guard);
    int a = left;
    sched_yield();
    int b = right;
    pthread_mutex_unlock(&guard);
    return a + b == 0;
}
