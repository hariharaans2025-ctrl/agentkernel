#include "state.h"
#include <stdio.h>
pthread_mutex_t queue_guard = PTHREAD_MUTEX_INITIALIZER;
int occupied, item;
static int first, second, value=-1, last;
static void *empty(void *p) {(void)p;first=take(&value);return 0;}
static void *fill(void *p) {(void)p;put(42);return 0;}
static void *consume(void *p) {(void)p;second=take(&value);last=take(&value);return 0;}
int main(void) {
    pthread_t t;
    if(pthread_create(&t,0,empty,0)||pthread_join(t,0)) return 2;
    if(pthread_create(&t,0,fill,0)||pthread_join(t,0)) return 2;
    if(pthread_create(&t,0,consume,0)||pthread_join(t,0)) return 2;
    if(first!=0 || second!=1 || value!=42 || last!=0 || occupied!=0) {puts("SEMANTIC_FAIL");return 1;}
    puts("SEMANTIC_PASS");puts("PASS");return 0;
}
