#ifndef STATE_H
#define STATE_H
#include <pthread.h>
#include <stdatomic.h>
typedef struct { pthread_mutex_t mutex; pthread_barrier_t barrier; _Atomic int arrivals; int value; int observed; } Cache;
void meet(Cache *);
void publish_cache(Cache *);
void observe_cache(Cache *);
#endif
