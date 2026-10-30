#include "state.h"
void publish(State*s,int k){ s->tag=k; sched_yield(); s->checksum=k^0x65; }
