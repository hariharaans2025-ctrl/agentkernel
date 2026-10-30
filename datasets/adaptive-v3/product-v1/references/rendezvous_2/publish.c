#include "state.h"
void publish(State*s){exchange_gate(s,0);pthread_mutex_lock(&s->mutex);sched_yield();s->slot[0]=4;s->slot[1]=9;pthread_mutex_unlock(&s->mutex);}
