#include "state.h"
#include <sched.h>
void set_window(Window *window, int lower, int upper) {
    pthread_mutex_lock(&window->mutex);
    window->lower = lower;
    sched_yield();
    window->upper = upper;
    pthread_mutex_unlock(&window->mutex);
}
void get_window(Window *window, int *lower, int *upper) {
    pthread_mutex_lock(&window->mutex);
    *lower = window->lower;
    sched_yield();
    *upper = window->upper;
    pthread_mutex_unlock(&window->mutex);
}
