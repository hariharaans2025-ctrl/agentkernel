#include "state.h"
void complete(State*s){pthread_mutex_lock(&s->mutex);s->value=88;s->generation=2;sched_yield();pthread_cond_broadcast(&s->changed);pthread_mutex_unlock(&s->mutex);}
