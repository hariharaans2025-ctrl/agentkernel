#include "state.h"
#include <sched.h>
int take_item(Inventory *stock) {
    int old = stock->remaining;
    if (old == 0) return 0;
    sched_yield();
    stock->remaining = old - 1;
    return 1;
}
int remaining_stock(Inventory *stock) {
    return stock->remaining;
}
