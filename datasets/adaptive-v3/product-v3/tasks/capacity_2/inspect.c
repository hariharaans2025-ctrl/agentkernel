#include "state.h"
int inspect(State*s){pthread_mutex_lock(&s->mutex);int n=s->withdrawn;pthread_mutex_unlock(&s->mutex);return n;}
