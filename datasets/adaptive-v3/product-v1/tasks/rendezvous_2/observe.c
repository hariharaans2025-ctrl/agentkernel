#include "state.h"
void observe(State*s){pthread_mutex_lock(&s->mutex);exchange_gate(s,1);sched_yield();s->seen=s->slot[0]+s->slot[1];pthread_mutex_unlock(&s->mutex);}
