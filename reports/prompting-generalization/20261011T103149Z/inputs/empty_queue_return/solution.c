#include "state.h"
int take(int *out) {
    pthread_mutex_lock(&queue_guard);
    if (!occupied) return 0;
    *out = item;
    occupied = 0;
    pthread_mutex_unlock(&queue_guard);
    return 1;
}
void put(int n) {
    pthread_mutex_lock(&queue_guard);
    item = n;
    occupied = 1;
    pthread_mutex_unlock(&queue_guard);
}
