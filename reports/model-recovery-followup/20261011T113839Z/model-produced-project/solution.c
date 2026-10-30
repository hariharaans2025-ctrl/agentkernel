#include "state.h"
void update_pair(int n) {
    pthread_mutex_lock(&guard);
    left = n;
    right = -n;
    pthread_mutex_unlock(&guard);
}
int snapshot_ok(void) {
    pthread_mutex_lock(&guard);
    int a = left;
    int b = right;
    pthread_mutex_unlock(&guard);
    return a + b == 0;
}
