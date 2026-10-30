#include "state.h"
#include <sched.h>
void set_window(Window *window, int lower, int upper) {
    pthread_mutex_lock(&window->mutex);
    window->lower = lower;
    pthread_mutex_unlock(&window->mutex);
    sched_yield();
    pthread_mutex_lock(&window->mutex);
    window->upper = upper;
    pthread_mutex_unlock(&window->mutex);
}
void get_window(Window *window, int *lower, int *upper) {
    *lower = window->lower;
    sched_yield();
    *upper = window->upper;
}
