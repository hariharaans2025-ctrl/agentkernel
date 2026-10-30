#include "state.h"
#include <sched.h>
void publish_cache(Cache *cache) {
    meet(cache);
    pthread_mutex_lock(&cache->mutex);
    sched_yield();
    cache->value = 42;
    pthread_mutex_unlock(&cache->mutex);
}
void observe_cache(Cache *cache) {
    meet(cache);
    pthread_mutex_lock(&cache->mutex);
    sched_yield();
    cache->observed = cache->value;
    pthread_mutex_unlock(&cache->mutex);
}
