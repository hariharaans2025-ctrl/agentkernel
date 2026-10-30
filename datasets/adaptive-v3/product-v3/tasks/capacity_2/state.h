#ifndef STATE_H
#define STATE_H
#include <pthread.h>
#include <stdatomic.h>
#include <semaphore.h>
#include <sched.h>
typedef struct {pthread_mutex_t mutex;int balance,withdrawn;} State;
int acquire(State*s,int amount);
int inspect(State*);
#endif
