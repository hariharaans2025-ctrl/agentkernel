#include "state.h"
void publish(State*s,int k){ s->lo=k; sched_yield(); s->hi=k+7; }
