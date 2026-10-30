#ifndef STATE_H
#define STATE_H
#include <pthread.h>
#include <stdatomic.h>
#include <semaphore.h>
#include <sched.h>
typedef struct {pthread_mutex_t left,right,third;pthread_barrier_t gate;atomic_int arrivals;int a,b,c;} State;
static inline void ready(State*s){atomic_fetch_add(&s->arrivals,1);pthread_barrier_wait(&s->gate);}
void forward(State*);void reverse(State*);
#endif
