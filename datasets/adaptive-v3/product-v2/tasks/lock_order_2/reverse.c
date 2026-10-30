#include "state.h"
void reverse(State*s){pthread_mutex_lock(&s->right);ready(s);sched_yield();pthread_mutex_lock(&s->left);s->a+=2;s->b-=2;pthread_mutex_unlock(&s->left);pthread_mutex_unlock(&s->right);}
