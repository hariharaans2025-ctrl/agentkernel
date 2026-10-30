#include "state.h"
int consistent(State*s){pthread_mutex_lock(&s->mutex);int t=s->total,a=s->accepted,r=s->rejected;int result=1;pthread_mutex_unlock(&s->mutex);return result;}
