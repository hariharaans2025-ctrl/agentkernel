#include "state.h"
void publish(void) {
    pthread_mutex_lock(&guard);
    while (waiting != 2) pthread_cond_wait(&arrived,&guard);
    ready = 1;
    pthread_cond_signal(&available);
    pthread_mutex_unlock(&guard);
}
