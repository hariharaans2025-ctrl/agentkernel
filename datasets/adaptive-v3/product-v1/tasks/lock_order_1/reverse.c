#include "state.h"
void reverse(State*s){pthread_mutex_lock(&s->right);ready(s);sched_yield();pthread_mutex_lock(&s->left);s->a+=5;s->b+=11;pthread_mutex_unlock(&s->left);pthread_mutex_unlock(&s->right);}
