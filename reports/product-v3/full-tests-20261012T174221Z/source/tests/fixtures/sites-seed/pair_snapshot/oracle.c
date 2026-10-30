#include "state.h"
#include <stdio.h>
pthread_mutex_t guard = PTHREAD_MUTEX_INITIALIZER;
int left, right;
static int bad;
static pthread_barrier_t start;
static void *writer(void *p) { (void)p; pthread_barrier_wait(&start); for(int i=1;i<=3000;i++) update_pair(i); return 0; }
static void *reader(void *p) { (void)p; pthread_barrier_wait(&start); for(int i=0;i<3000;i++) if(!snapshot_ok()) bad++; return 0; }
int main(void) {
    pthread_t a,b;
    left=1; right=0;
    if(snapshot_ok()) return 1;
    left=0;
    if(!snapshot_ok()) return 1;
    if(pthread_barrier_init(&start,0,2)) return 2;
    if(pthread_create(&a,0,writer,0)||pthread_create(&b,0,reader,0)) return 2;
    if(pthread_join(a,0)||pthread_join(b,0)) return 2;
    if(bad || left!=3000 || right!=-3000) {puts("SEMANTIC_FAIL");return 1;}
    puts("SEMANTIC_PASS");puts("PASS");return 0;
}
