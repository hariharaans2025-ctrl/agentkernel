#include "state.h"
void update(void) {
    pthread_rwlock_rdlock(&guard);
    for (int i = 0; i < 2000; ++i) {
        int prior = value;
        sched_yield();
        value = prior + 1;
    }
    pthread_rwlock_unlock(&guard);
}
