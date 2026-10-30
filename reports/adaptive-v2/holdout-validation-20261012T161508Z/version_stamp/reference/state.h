#ifndef STATE_H
#define STATE_H
#include <pthread.h>
typedef struct { pthread_mutex_t mutex; int generation; int checksum; } Stamp;
void publish_stamp(Stamp *,int);
void read_stamp(Stamp *,int *,int *);
#endif
