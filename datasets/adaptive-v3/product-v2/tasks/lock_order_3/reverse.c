#include "state.h"
void reverse(State*s){pthread_mutex_lock(&s->right);ready(s);sched_yield();pthread_mutex_lock(&s->left);pthread_mutex_lock(&s->third);s->a+=4;s->b+=5;s->c+=6;pthread_mutex_unlock(&s->third);pthread_mutex_unlock(&s->left);pthread_mutex_unlock(&s->right);}
