#include "state.h"
#include <stdio.h>
pthread_mutex_t ledger = PTHREAD_MUTEX_INITIALIZER;
int accounts[2]={1000,1000};
static void *worker(void *p) {(void)p;for(int i=0;i<100;i++) transfer(0,1);return 0;}
int main(void) {
    pthread_t a,b;
    if(pthread_create(&a,0,worker,0)||pthread_create(&b,0,worker,0)) return 2;
    if(pthread_join(a,0)||pthread_join(b,0)) return 2;
    if(accounts[0]!=800 || accounts[1]!=1200) {puts("SEMANTIC_FAIL");return 1;}
    puts("SEMANTIC_PASS");puts("PASS");return 0;
}
