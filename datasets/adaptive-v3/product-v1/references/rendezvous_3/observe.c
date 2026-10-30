#include "state.h"
void observe(State*s){checkpoint(s);pthread_mutex_lock(&s->mutex);sched_yield();s->visits++;s->seen=s->value;pthread_mutex_unlock(&s->mutex);}
