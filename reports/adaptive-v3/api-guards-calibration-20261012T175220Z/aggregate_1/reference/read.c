#include "state.h"
int consistent(State*s){pthread_mutex_lock(&s->mutex);int n=s->count,t=s->sum;int result=t==n*5;pthread_mutex_unlock(&s->mutex);return result;}
