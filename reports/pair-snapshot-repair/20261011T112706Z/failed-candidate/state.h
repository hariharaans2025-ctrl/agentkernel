#include <pthread.h>
#include <sched.h>
extern pthread_mutex_t guard;
extern int left, right;
void update_pair(int n);
int snapshot_ok(void);
