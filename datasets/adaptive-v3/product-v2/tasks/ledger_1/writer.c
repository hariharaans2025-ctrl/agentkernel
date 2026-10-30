#include "state.h"
void update(State*s,int step) { long n=s->credits; sched_yield(); s->credits=n+3; }
