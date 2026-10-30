#include "state.h"
int check_snapshot(State*s){pthread_mutex_lock(&s->mutex); int valid=s->valid, a=s->epoch; sched_yield(); int b=s->payload; int result=1; pthread_mutex_unlock(&s->mutex);return result;}
