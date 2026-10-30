#include "state.h"
int count_audits(State*s){return atomic_load(&s->audits);}
