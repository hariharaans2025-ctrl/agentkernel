#include "state.h"
void publish(State*s){checkpoint(s);pthread_mutex_lock(&s->mutex);sched_yield();s->visits++;s->value=31;pthread_mutex_unlock(&s->mutex);}
