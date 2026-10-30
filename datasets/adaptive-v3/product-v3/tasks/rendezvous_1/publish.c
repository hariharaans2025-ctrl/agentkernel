#include "state.h"
void publish(State*s){pthread_mutex_lock(&s->mutex);rendezvous(s);sched_yield();s->value=27;pthread_mutex_unlock(&s->mutex);}
