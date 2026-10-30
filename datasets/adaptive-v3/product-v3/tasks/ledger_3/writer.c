#include "state.h"
void update(State*s,int step) { long p=s->produced,c=s->consumed; sched_yield(); s->produced=p+2; s->consumed=c+1; }
