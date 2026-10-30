#include "state.h"
#include <stdio.h>
#include <string.h>
static Cache cache;
void meet(Cache *c) {
    atomic_fetch_add(&c->arrivals,1);
    pthread_barrier_wait(&c->barrier);
}
static void *publisher(void *unused) {(void)unused;publish_cache(&cache);return NULL;}
static void *observer(void *unused) {(void)unused;observe_cache(&cache);return NULL;}
int main(int argc,char **argv) {
    pthread_mutex_init(&cache.mutex,NULL);pthread_barrier_init(&cache.barrier,NULL,2);
    atomic_init(&cache.arrivals,0);cache.value=0;cache.observed=-1;
    pthread_t a,b;pthread_create(&a,NULL,publisher,NULL);pthread_create(&b,NULL,observer,NULL);
    pthread_join(a,NULL);pthread_join(b,NULL);
    if(atomic_load(&cache.arrivals)!=2 || cache.value!=42 || (cache.observed!=0 && cache.observed!=42))return 1;
    puts(argc>1 && !strcmp(argv[1],"--check")?"SEMANTIC_PASS":"PASS");return 0;
}
