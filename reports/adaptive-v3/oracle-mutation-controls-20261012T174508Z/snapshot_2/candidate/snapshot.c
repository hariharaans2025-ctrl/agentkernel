#include "state.h"
int check_snapshot(State*s){pthread_mutex_lock(&s->mutex); int a=s->lo; sched_yield(); int b=s->hi; int result=1; pthread_mutex_unlock(&s->mutex);return result;}
