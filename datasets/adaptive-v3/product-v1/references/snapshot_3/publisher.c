#include "state.h"
void publish(State*s,int k){pthread_mutex_lock(&s->mutex); s->epoch=k; sched_yield(); s->payload=k*11; s->valid=1; pthread_mutex_unlock(&s->mutex);}
