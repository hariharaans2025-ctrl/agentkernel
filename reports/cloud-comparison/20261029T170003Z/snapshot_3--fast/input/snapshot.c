#include "state.h"
int check_snapshot(State*s){ int valid=s->valid, a=s->epoch; sched_yield(); int b=s->payload; return !valid || b==a*11; }
