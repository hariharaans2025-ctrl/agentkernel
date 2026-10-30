#include <pthread.h>
extern pthread_mutex_t guard;
extern pthread_cond_t arrived, available;
extern int waiting, ready;
void publish(void);
