#ifndef STATE_H
#define STATE_H
#include <pthread.h>
#include <stdatomic.h>
#include <semaphore.h>
#include <sched.h>
typedef struct {pthread_mutex_t mutex;int available,reserved,cancelled;} State;
int acquire(State*s);
int inspect(State*);
#endif
