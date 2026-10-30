#ifndef AK_STRESS_H
#define AK_STRESS_H
#include <stdlib.h>
#include <sched.h>
#include <time.h>
static int setting(const char *name, int fallback, int maximum) {
    const char *value = getenv(name);
    int n = value ? atoi(value) : fallback;
    return n > 0 && n <= maximum ? n : fallback;
}
static void perturb(unsigned worker, unsigned iteration) {
    unsigned seed = (unsigned)setting("AK_SEED", 1, 2147483647);
    if ((seed + worker * 17u + iteration * 31u) % 7u == 0) sched_yield();
    if (iteration == 0) {
        struct timespec delay = {0, setting("AK_START_DELAY_US", 10, 100000) * 1000L};
        nanosleep(&delay, NULL);
    }
}
#endif
