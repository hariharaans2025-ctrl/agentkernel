#include "state.h"
int await_value(State*s){pthread_mutex_lock(&s->mutex);while(s->generation<2)wait_change(s);sched_yield();int result=s->value;s->generation=3;pthread_mutex_unlock(&s->mutex);return result;}
