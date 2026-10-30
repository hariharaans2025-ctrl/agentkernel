#include "state.h"
long snapshot(State*s) { pthread_mutex_lock(&s->mutex); long result=s->credits; pthread_mutex_unlock(&s->mutex); return result; }
