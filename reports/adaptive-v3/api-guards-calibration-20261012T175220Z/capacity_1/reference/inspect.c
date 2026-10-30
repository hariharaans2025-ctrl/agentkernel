#include "state.h"
int inspect(State*s){pthread_mutex_lock(&s->mutex);int n=s->claimed;pthread_mutex_unlock(&s->mutex);return n;}
