#include "state.h"
void update(State*s,int step) { pthread_mutex_lock(&s->mutex); long p=s->produced,c=s->consumed; sched_yield(); s->produced=p+2; s->consumed=c+1; pthread_mutex_unlock(&s->mutex); }
