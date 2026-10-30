#include <pthread.h>
#include <sched.h>
extern pthread_rwlock_t guard;
extern int value;
void update(void);
