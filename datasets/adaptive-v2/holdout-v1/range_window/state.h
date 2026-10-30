#ifndef STATE_H
#define STATE_H
#include <pthread.h>
typedef struct { pthread_mutex_t mutex; int lower; int upper; } Window;
void set_window(Window *, int, int);
void get_window(Window *, int *, int *);
#endif
