#include "state.h"
void publish(State*s,int k){ s->epoch=k; sched_yield(); s->payload=k*11; s->valid=1; }
