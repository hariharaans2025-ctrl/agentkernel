#include "state.h"
#include <stdatomic.h>
#include <sched.h>
#include <stdio.h>
#include <string.h>
static Inventory stock={PTHREAD_MUTEX_INITIALIZER,500};
static _Atomic int successes=0,bad=0,done=0;
static pthread_barrier_t ready;
static void *worker(void *unused) {
    (void)unused;pthread_barrier_wait(&ready);
    for(int i=0;i<200;++i) {
        int ok=take_item(&stock);
        if(ok==1)atomic_fetch_add(&successes,1);
        else if(ok!=0)atomic_fetch_add(&bad,1);
    }
    atomic_fetch_add(&done,1);return NULL;
}
static void *monitor(void *unused) {
    (void)unused;pthread_barrier_wait(&ready);
    while(atomic_load(&done)<4) {
        int left=remaining_stock(&stock);
        if(left<0 || left>500)atomic_fetch_add(&bad,1);
        sched_yield();
    }
    return NULL;
}
int main(int argc,char **argv) {
    pthread_t t[5];pthread_barrier_init(&ready,NULL,5);
    for(int i=0;i<4;++i)pthread_create(&t[i],NULL,worker,NULL);
    pthread_create(&t[4],NULL,monitor,NULL);
    for(int i=0;i<5;++i)pthread_join(t[i],NULL);
    if(atomic_load(&bad) || atomic_load(&successes)!=500 || remaining_stock(&stock)!=0)return 1;
    puts(argc>1 && !strcmp(argv[1],"--check")?"SEMANTIC_PASS":"PASS");return 0;
}
