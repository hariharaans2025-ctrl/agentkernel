#include "state.h"
void publish(State*s,int k){pthread_mutex_lock(&s->mutex); s->tag=k; sched_yield(); s->checksum=k^0x65; pthread_mutex_unlock(&s->mutex);}
