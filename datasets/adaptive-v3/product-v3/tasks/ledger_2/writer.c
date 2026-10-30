#include "state.h"
void update(State*s,int step) { int slot=step&1; long n=s->buckets[slot]; sched_yield(); s->buckets[slot]=n+1; }
