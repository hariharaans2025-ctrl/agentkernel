#include "state.h"
int acquire(State*s,int amount){pthread_mutex_lock(&s->mutex);if(amount<=0 || s->balance<amount) {pthread_mutex_unlock(&s->mutex);return 0;} sched_yield();s->balance-=amount;s->withdrawn+=amount;pthread_mutex_unlock(&s->mutex);return 1;}
