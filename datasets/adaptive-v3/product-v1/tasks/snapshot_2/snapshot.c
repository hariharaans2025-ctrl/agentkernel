#include "state.h"
int check_snapshot(State*s){ int a=s->lo; sched_yield(); int b=s->hi; return b-a==7; }
