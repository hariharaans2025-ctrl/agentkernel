#include "state.h"
void reverse(State*s){ready(s);pthread_mutex_lock(&s->left);sched_yield();pthread_mutex_lock(&s->right);s->a+=2;s->b-=2;pthread_mutex_unlock(&s->right);pthread_mutex_unlock(&s->left);}
