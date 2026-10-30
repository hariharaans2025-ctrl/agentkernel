#include "pair.h"
#include <pthread.h>
static pthread_mutex_t guard = PTHREAD_MUTEX_INITIALIZER;
static int32_t first, second;
void set_pair(int32_t a, int32_t b) {
    pthread_mutex_lock(&guard); first=a; second=b; pthread_mutex_unlock(&guard);
}
void get_pair(int32_t *a, int32_t *b) {
    pthread_mutex_lock(&guard); *a=first; *b=second; pthread_mutex_unlock(&guard);
}
