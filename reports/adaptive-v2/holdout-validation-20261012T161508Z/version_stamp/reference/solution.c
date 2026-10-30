#include "state.h"
#include <sched.h>
void publish_stamp(Stamp *stamp,int generation) {
    pthread_mutex_lock(&stamp->mutex);
    stamp->generation=generation;
    sched_yield();
    stamp->checksum=generation ^ 0x5a5a;
    pthread_mutex_unlock(&stamp->mutex);
}
void read_stamp(Stamp *stamp,int *generation,int *checksum) {
    pthread_mutex_lock(&stamp->mutex);
    *generation=stamp->generation;
    sched_yield();
    *checksum=stamp->checksum;
    pthread_mutex_unlock(&stamp->mutex);
}
