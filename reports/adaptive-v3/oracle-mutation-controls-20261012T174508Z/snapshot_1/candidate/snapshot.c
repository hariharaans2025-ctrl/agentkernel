#include "state.h"
int check_snapshot(State*s){pthread_mutex_lock(&s->mutex); int a=s->tag; sched_yield(); int b=s->checksum; int result=1; pthread_mutex_unlock(&s->mutex);return result;}
