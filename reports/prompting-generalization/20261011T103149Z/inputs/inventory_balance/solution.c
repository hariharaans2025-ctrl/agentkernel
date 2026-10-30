#include "state.h"
void restock(void) {
    pthread_mutex_lock(&stock_guard);
    int n = stock;
    sched_yield();
    stock = n + 1;
    pthread_mutex_unlock(&stock_guard);
}
void sell(void) {
    pthread_mutex_lock(&sales_guard);
    int n = stock;
    sched_yield();
    stock = n - 1;
    pthread_mutex_unlock(&sales_guard);
}
