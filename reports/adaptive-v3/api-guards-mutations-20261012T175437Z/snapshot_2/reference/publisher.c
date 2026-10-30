#include "state.h"
void publish(State*s,int k){pthread_mutex_lock(&s->mutex); s->lo=k; sched_yield(); s->hi=k+7; pthread_mutex_unlock(&s->mutex);}
