#include "state.h"
void forward(State*s){ready(s);pthread_mutex_lock(&s->left);sched_yield();pthread_mutex_lock(&s->right);s->a-=4;s->b+=4;pthread_mutex_unlock(&s->right);pthread_mutex_unlock(&s->left);}
