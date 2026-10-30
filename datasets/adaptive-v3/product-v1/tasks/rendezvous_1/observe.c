#include "state.h"
void observe(State*s){pthread_mutex_lock(&s->mutex);rendezvous(s);sched_yield();s->seen=s->value;pthread_mutex_unlock(&s->mutex);}
