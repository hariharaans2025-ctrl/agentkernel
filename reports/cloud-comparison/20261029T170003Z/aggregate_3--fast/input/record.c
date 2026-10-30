#include "state.h"
void record(State*s,int step){int n=s->parity[step&1],t=s->total;sched_yield();s->parity[step&1]=n+1;s->total=t+1;}
