#include "state.h"
#include <pthread.h>
#include <stdatomic.h>
#include <stdio.h>
#include <string.h>
static Stamp stamp={PTHREAD_MUTEX_INITIALIZER,0,0x5a5a};
static _Atomic int bad=0;
static pthread_barrier_t ready;
static void *writer(void *unused) {
    (void)unused;pthread_barrier_wait(&ready);
    for(int i=1;i<=350;++i)publish_stamp(&stamp,i);
    return NULL;
}
static void *reader(void *unused) {
    (void)unused;pthread_barrier_wait(&ready);
    for(int i=0;i<700;++i) {
        int generation,checksum;read_stamp(&stamp,&generation,&checksum);
        if(checksum!=(generation ^ 0x5a5a))atomic_fetch_add(&bad,1);
    }
    return NULL;
}
int main(int argc,char **argv) {
    pthread_t threads[3];pthread_barrier_init(&ready,NULL,3);
    pthread_create(&threads[0],NULL,writer,NULL);
    pthread_create(&threads[1],NULL,reader,NULL);
    pthread_create(&threads[2],NULL,reader,NULL);
    for(int i=0;i<3;++i)pthread_join(threads[i],NULL);
    publish_stamp(&stamp,12000);
    int generation,checksum;read_stamp(&stamp,&generation,&checksum);
    if(atomic_load(&bad) || generation!=12000 || checksum!=(12000 ^ 0x5a5a))return 1;
    puts(argc>1 && !strcmp(argv[1],"--check")?"SEMANTIC_PASS":"PASS");return 0;
}
