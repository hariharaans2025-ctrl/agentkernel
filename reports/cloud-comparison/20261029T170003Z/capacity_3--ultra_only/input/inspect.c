#include "state.h"
int inspect(State*s){pthread_mutex_lock(&s->mutex);s->cancelled++;int n=s->reserved;pthread_mutex_unlock(&s->mutex);return n;}
