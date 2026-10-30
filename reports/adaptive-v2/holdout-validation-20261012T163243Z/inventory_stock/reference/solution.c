#include "state.h"
#include <sched.h>
int take_item(Inventory *stock) {
    pthread_mutex_lock(&stock->mutex);
    int old = stock->remaining;
    if (old == 0) { pthread_mutex_unlock(&stock->mutex); return 0; }
    sched_yield();
    stock->remaining = old - 1;
    pthread_mutex_unlock(&stock->mutex);
    return 1;
}
int remaining_stock(Inventory *stock) {
    pthread_mutex_lock(&stock->mutex);
    int result = stock->remaining;
    pthread_mutex_unlock(&stock->mutex);
    return result;
}
