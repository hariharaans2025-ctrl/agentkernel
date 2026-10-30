#include "state.h"
int acquire(State*s){pthread_mutex_lock(&s->mutex);if(s->available==0) return 0; sched_yield();s->available--;s->claimed++;pthread_mutex_unlock(&s->mutex);return 1;}
