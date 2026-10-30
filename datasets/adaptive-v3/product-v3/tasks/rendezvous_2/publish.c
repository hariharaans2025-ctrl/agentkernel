#include "state.h"
void publish(State*s){pthread_mutex_lock(&s->mutex);exchange_gate(s,0);sched_yield();s->slot[0]=4;s->slot[1]=9;pthread_mutex_unlock(&s->mutex);}
