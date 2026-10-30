#include "state.h"
#include <sched.h>
void publish_stamp(Stamp *stamp,int generation) {
    pthread_mutex_lock(&stamp->mutex);
    stamp->generation=generation;
    pthread_mutex_unlock(&stamp->mutex);
    sched_yield();
    pthread_mutex_lock(&stamp->mutex);
    stamp->checksum=generation ^ 0x5a5a;
    pthread_mutex_unlock(&stamp->mutex);
}
void read_stamp(Stamp *stamp,int *generation,int *checksum) {
    *generation=stamp->generation;
    sched_yield();
    *checksum=stamp->checksum;
}
