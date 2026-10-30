#include <pthread.h>
#include <stdatomic.h>
static atomic_int lock_events, join_events;
static int counted_lock(pthread_mutex_t *m) { int r=pthread_mutex_lock(m); if(!r) atomic_fetch_add(&lock_events,1); return r; }
static int counted_join(pthread_t t,void **r) { int s=pthread_join(t,r); if(!s) atomic_fetch_add(&join_events,1); return s; }
#define pthread_mutex_lock counted_lock
#define pthread_join counted_join
#define main fixture_main
#include "main.c"
#undef main
#undef pthread_mutex_lock
#undef pthread_join
int main(void) { if(fixture_main()!=0) return 1; if(!(atomic_load(&lock_events)>=4 && atomic_load(&join_events)==2)) { puts("SEMANTIC_FAIL"); return 2; } puts("SEMANTIC_PASS"); return 0; }
