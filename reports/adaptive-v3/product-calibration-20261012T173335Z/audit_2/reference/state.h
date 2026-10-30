#ifndef STATE_H
#define STATE_H
#include <pthread.h>
#include <stdatomic.h>
#include <semaphore.h>
#include <sched.h>
typedef struct {pthread_mutex_t mutex;atomic_int audits;int count,sum;} State;
static inline void audit(State*s){pthread_mutex_lock(&s->mutex);int v=s->count+s->sum;(void)v;atomic_fetch_add(&s->audits,1);pthread_mutex_unlock(&s->mutex);}
void commit(State*);int count_audits(State*);
#endif
