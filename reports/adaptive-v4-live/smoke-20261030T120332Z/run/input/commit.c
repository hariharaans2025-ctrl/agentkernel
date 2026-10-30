#include "state.h"
void commit(State*s){pthread_mutex_lock(&s->mutex);s->committed++;s->bytes+=13;sched_yield();audit(s);pthread_mutex_unlock(&s->mutex);}
