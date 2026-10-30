#ifndef STATE_H
#define STATE_H
#include <pthread.h>
#include <stdatomic.h>
#include <semaphore.h>
#include <sched.h>
typedef struct {pthread_mutex_t mutex; int lo,hi;} State;
void publish(State*,int);
int check_snapshot(State*);
#endif
