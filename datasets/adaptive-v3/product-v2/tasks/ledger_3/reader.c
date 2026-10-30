#include "state.h"
long snapshot(State*s) { long result=s->produced-2*s->consumed; return result; }
