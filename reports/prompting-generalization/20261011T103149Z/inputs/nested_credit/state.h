#include <pthread.h>
#include <sched.h>
extern pthread_mutex_t ledger;
extern int accounts[2];
void transfer(int from, int to);
