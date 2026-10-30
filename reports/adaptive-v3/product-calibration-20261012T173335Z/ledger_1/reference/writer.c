#include "state.h"
void update(State*s,int step) { pthread_mutex_lock(&s->mutex); long n=s->credits; sched_yield(); s->credits=n+3; pthread_mutex_unlock(&s->mutex); }
