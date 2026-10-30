#include "state.h"
void forward(State*s){pthread_mutex_lock(&s->left);ready(s);sched_yield();pthread_mutex_lock(&s->right);pthread_mutex_lock(&s->third);s->a++;s->b+=2;s->c+=3;pthread_mutex_unlock(&s->third);pthread_mutex_unlock(&s->right);pthread_mutex_unlock(&s->left);}
