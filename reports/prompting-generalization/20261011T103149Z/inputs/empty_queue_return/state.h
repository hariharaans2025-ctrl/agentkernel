#include <pthread.h>
#include <sched.h>
extern pthread_mutex_t queue_guard;
extern int occupied, item;
int take(int *out);
void put(int n);
