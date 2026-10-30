#include "state.h"
#include <pthread.h>
#include <stdatomic.h>
#include <stdio.h>
#include <string.h>
#include <sched.h>
#define TOTAL 400
static TicketOffice office = {PTHREAD_MUTEX_INITIALIZER, 0};
static _Atomic int seen[TOTAL];
static _Atomic int bad=0,done=0;
static pthread_barrier_t ready;
static void *worker(void *unused) {
    (void)unused; pthread_barrier_wait(&ready);
    for (int i=0;i<100;++i) {
        int ticket=reserve_ticket(&office);
        if (ticket<0 || ticket>=TOTAL) atomic_fetch_add(&bad,1);
        else if (atomic_fetch_add(&seen[ticket],1)) atomic_fetch_add(&bad,1);
    }
    atomic_fetch_add(&done,1); return NULL;
}
static void *monitor(void *unused) {
    (void)unused; pthread_barrier_wait(&ready);
    while (atomic_load(&done)<4) {
        int count=issued_count(&office);
        if(count<0 || count>TOTAL)atomic_fetch_add(&bad,1);
        sched_yield();
    }
    return NULL;
}
int main(int argc,char **argv) {
    pthread_t threads[5];pthread_barrier_init(&ready,NULL,5);
    for(int i=0;i<4;++i)pthread_create(&threads[i],NULL,worker,NULL);
    pthread_create(&threads[4],NULL,monitor,NULL);
    for(int i=0;i<5;++i)pthread_join(threads[i],NULL);
    if(atomic_load(&bad) || issued_count(&office)!=TOTAL)return 1;
    for(int i=0;i<TOTAL;++i)if(atomic_load(&seen[i])!=1)return 1;
    puts(argc>1 && !strcmp(argv[1],"--check")?"SEMANTIC_PASS":"PASS");return 0;
}
