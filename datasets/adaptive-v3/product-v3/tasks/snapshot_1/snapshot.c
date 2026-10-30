#include "state.h"
int check_snapshot(State*s){ int a=s->tag; sched_yield(); int b=s->checksum; return b==(a^0x65); }
