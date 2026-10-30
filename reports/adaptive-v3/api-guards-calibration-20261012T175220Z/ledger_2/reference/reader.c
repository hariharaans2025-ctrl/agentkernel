#include "state.h"
long snapshot(State*s) { pthread_mutex_lock(&s->mutex); long result=s->buckets[0]+s->buckets[1]; pthread_mutex_unlock(&s->mutex); return result; }
