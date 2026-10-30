#include "state.h"
void observe(State*s){exchange_gate(s,1);pthread_mutex_lock(&s->mutex);sched_yield();s->seen=s->slot[0]+s->slot[1];pthread_mutex_unlock(&s->mutex);}
