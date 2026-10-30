#ifndef STATE_H
#define STATE_H
#include <pthread.h>
#include <stdatomic.h>
#include <semaphore.h>
#include <sched.h>
typedef struct {pthread_mutex_t mutex;pthread_cond_t changed;sem_t waiting;atomic_int awakened;int generation,value;} State;
static inline void wait_change(State*s){sem_post(&s->waiting);pthread_cond_wait(&s->changed,&s->mutex);atomic_fetch_add(&s->awakened,1);}
int await_value(State*);void complete(State*);
#endif
