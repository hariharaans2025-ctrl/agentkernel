#include "state.h"
void commit(State*s){pthread_mutex_lock(&s->mutex);s->value++;sched_yield();pthread_mutex_unlock(&s->mutex);audit(s);}
