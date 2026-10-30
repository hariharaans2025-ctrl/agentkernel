#ifndef STATE_H
#define STATE_H
#include <pthread.h>
#include <stdatomic.h>
#include <semaphore.h>
#include <sched.h>
typedef struct {pthread_mutex_t mutex;pthread_barrier_t gate;atomic_int arrivals;int slot[2],seen;} State;
static inline void exchange_gate(State*s,int slot){atomic_fetch_add(&s->arrivals,1);pthread_barrier_wait(&s->gate);}
void publish(State*);
void observe(State*);
#endif
