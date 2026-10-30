#ifndef STATE_H
#define STATE_H
#include <pthread.h>
#include <stdatomic.h>
#include <semaphore.h>
#include <sched.h>
typedef struct {pthread_mutex_t mutex;int total,accepted,rejected;} State;
void record(State*,int);int consistent(State*);
#endif
