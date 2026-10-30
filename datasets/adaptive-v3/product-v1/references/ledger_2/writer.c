#include "state.h"
void update(State*s,int step) { pthread_mutex_lock(&s->mutex); int slot=step&1; long n=s->buckets[slot]; sched_yield(); s->buckets[slot]=n+1; pthread_mutex_unlock(&s->mutex); }
