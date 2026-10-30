#include "state.h"
void record(State*s,int step){pthread_mutex_lock(&s->mutex);int n=s->count,t=s->sum;sched_yield();s->count=n+1;s->sum=t+5;pthread_mutex_unlock(&s->mutex);}
