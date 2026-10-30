#include <pthread.h>
#include <sched.h>
extern pthread_mutex_t stock_guard, sales_guard;
extern int stock;
void restock(void);
void sell(void);
