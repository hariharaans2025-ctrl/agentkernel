#define _POSIX_C_SOURCE 200809L
#include "pair.h"
#include <pthread.h>
#include <sched.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <limits.h>
_Atomic(uint64_t) pair_bits;
static pthread_barrier_t gate;
static int n, yields, bad;
static uint64_t writer_ns,reader_ns;
static uint64_t now_ns(void) {
    struct timespec t;
    if(clock_gettime(CLOCK_MONOTONIC,&t)) exit(2);
    return (uint64_t)t.tv_sec*1000000000ULL+(uint64_t)t.tv_nsec;
}
static void *writer(void *p) {
    (void)p;pthread_barrier_wait(&gate);uint64_t t=now_ns();
    for(int i=1;i<=n;i++){set_pair(i,-i);if(yields)sched_yield();}
    writer_ns=now_ns()-t;return 0;
}
static void *reader(void *p) {
    (void)p;pthread_barrier_wait(&gate);uint64_t t=now_ns();
    for(int i=0;i<n;i++){
        int32_t a,b;get_pair(&a,&b);
        if((int64_t)a+(int64_t)b!=0 || a<0 || a>n)bad++;
        if(yields)sched_yield();
    }
    reader_ns=now_ns()-t;return 0;
}
static int exact(int32_t a,int32_t b) {
    int32_t x,y;set_pair(a,b);get_pair(&x,&y);return x==a && y==b;
}
int main(int argc,char **argv) {
    int bench=argc>1 && strcmp(argv[1],"bench")==0;
    int lockfree=atomic_is_lock_free(&pair_bits);
    if(MODE!=0 && !lockfree){puts("NOT_LOCK_FREE");return 77;}
    if(!exact(7,-7)||!exact(-10,11)||!exact(INT32_MIN,INT32_MAX)||!exact(0,0))return 1;
    n=bench?500000:3000;yields=!bench;
    uint64_t single=0,checksum=0;
    if(bench){
        uint64_t t=now_ns();
        for(int i=1;i<=n;i++){
            int32_t a,b;set_pair(i,-i);get_pair(&a,&b);
            if(a!=i || b!=-i)return 1;
            checksum+=(uint32_t)a;
        }
        single=now_ns()-t;
        if(checksum!=(uint64_t)n*(n+1)/2)return 1;
    }
    set_pair(0,0);
    if(pthread_barrier_init(&gate,0,3))return 2;
    pthread_t w,r;
    if(pthread_create(&w,0,writer,0)||pthread_create(&r,0,reader,0))return 2;
    uint64_t t=now_ns();pthread_barrier_wait(&gate);
    if(pthread_join(w,0)||pthread_join(r,0))return 2;
    uint64_t elapsed=now_ns()-t;
    int32_t a,b;get_pair(&a,&b);
    if(bad || a!=n || b!=-n){puts("SEMANTIC_FAIL");return 1;}
    if(bench){
        struct timespec resolution;if(clock_getres(CLOCK_MONOTONIC,&resolution))return 2;
        printf("{\"mode\":%d,\"lock_free\":%d,\"iterations\":%d,\"single_ns_per_op\":%.4f,\"writer_ns_per_op\":%.4f,\"reader_ns_per_op\":%.4f,\"concurrent_wall_ns_per_op\":%.4f,\"clock_resolution_ns\":%llu}\n",
            MODE,lockfree,n,(double)single/(2*n),(double)writer_ns/n,(double)reader_ns/n,
            (double)elapsed/(2*n),(unsigned long long)((uint64_t)resolution.tv_sec*1000000000ULL+resolution.tv_nsec));
    } else {puts("SEMANTIC_PASS");puts("PASS");}
    return 0;
}
