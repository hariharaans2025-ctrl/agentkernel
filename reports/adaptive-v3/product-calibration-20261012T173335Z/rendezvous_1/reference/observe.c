#include "state.h"
void observe(State*s){rendezvous(s);pthread_mutex_lock(&s->mutex);sched_yield();s->seen=s->value;pthread_mutex_unlock(&s->mutex);}
