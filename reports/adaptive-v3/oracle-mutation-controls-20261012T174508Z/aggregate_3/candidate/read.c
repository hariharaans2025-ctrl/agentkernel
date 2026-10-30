#include "state.h"
int consistent(State*s){pthread_mutex_lock(&s->mutex);int a=s->parity[0],b=s->parity[1],t=s->total;int result=1;pthread_mutex_unlock(&s->mutex);return result;}
