#include "state.h"
void publish(State*s){pthread_mutex_lock(&s->mutex);checkpoint(s);sched_yield();s->visits++;s->value=31;pthread_mutex_unlock(&s->mutex);}
