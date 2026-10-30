#include "state.h"
void record(State*s,int step){int n=s->count,t=s->sum;sched_yield();s->count=n+1;s->sum=t+5;}
