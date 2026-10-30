#include "state.h"
void record(State*s,int step){int n=s->total;int a=s->accepted,r=s->rejected;sched_yield();s->total=n+1;if(step%3==0)s->rejected=r+1;else s->accepted=a+1;}
