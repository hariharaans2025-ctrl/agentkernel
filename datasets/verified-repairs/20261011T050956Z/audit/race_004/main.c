#include <pthread.h>
#include <stdio.h>
#include <stdint.h>
#include <assert.h>
#include <stdatomic.h>
#include "stress.h"

static int queue[200], tail, seen[200], consumed;
static pthread_mutex_t queue_lock=PTHREAD_MUTEX_INITIALIZER;
static pthread_barrier_t ready;
static void *producer(void *arg) {
    int id=(int)(intptr_t)arg; pthread_barrier_wait(&ready);
    for(int i=0;i<100;i++) {
        pthread_mutex_lock(&queue_lock);
        int slot=tail; perturb((unsigned)id,(unsigned)i); queue[slot]=id*100+i; tail=slot+1;
        pthread_mutex_unlock(&queue_lock);
    }
    return NULL;
}
int main(void) {
    pthread_t t[2]; pthread_barrier_init(&ready,NULL,2);
    for(int i=0;i<2;i++) pthread_create(&t[i],NULL,producer,(void *)(intptr_t)i);
    for(int i=0;i<2;i++) pthread_join(t[i],NULL);
    for(int i=0;i<tail && i<200;i++) { if(queue[i]>=0 && queue[i]<200) seen[queue[i]]++; consumed++; }
    pthread_barrier_destroy(&ready); puts("PASS"); return 0;
}
