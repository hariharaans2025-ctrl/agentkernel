#include "state.h"
long snapshot(State*s) { long result=s->buckets[0]+s->buckets[1]; return result; }
