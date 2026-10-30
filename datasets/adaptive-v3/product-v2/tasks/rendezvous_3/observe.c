#include "state.h"
void observe(State*s){pthread_mutex_lock(&s->mutex);checkpoint(s);sched_yield();s->visits++;s->seen=s->value;pthread_mutex_unlock(&s->mutex);}
