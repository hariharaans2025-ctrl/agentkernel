#ifndef STATE_H
#define STATE_H
#include <pthread.h>
#include <stdatomic.h>
#include <semaphore.h>
#include <sched.h>
typedef struct {pthread_mutex_t mutex; long credits;} State;
void update(State*,int);
long snapshot(State*);
#endif
