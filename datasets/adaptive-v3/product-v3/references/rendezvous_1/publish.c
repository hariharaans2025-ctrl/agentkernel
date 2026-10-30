#include "state.h"
void publish(State*s){rendezvous(s);pthread_mutex_lock(&s->mutex);sched_yield();s->value=27;pthread_mutex_unlock(&s->mutex);}
