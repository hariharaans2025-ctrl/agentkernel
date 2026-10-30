#include "state.h"
int await_value(State*s){pthread_mutex_lock(&s->mutex);while(!s->ready)wait_change(s);sched_yield();int result=s->value;s->ready=0;pthread_mutex_unlock(&s->mutex);return result;}
