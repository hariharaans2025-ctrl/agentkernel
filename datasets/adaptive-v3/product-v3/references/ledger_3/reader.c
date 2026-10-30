#include "state.h"
long snapshot(State*s) { pthread_mutex_lock(&s->mutex); long result=s->produced-2*s->consumed; pthread_mutex_unlock(&s->mutex); return result; }
