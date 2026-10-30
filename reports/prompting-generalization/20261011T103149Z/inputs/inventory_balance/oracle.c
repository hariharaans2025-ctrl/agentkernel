#include "state.h"
#include <stdio.h>
pthread_mutex_t stock_guard = PTHREAD_MUTEX_INITIALIZER, sales_guard = PTHREAD_MUTEX_INITIALIZER;
int stock=10000;
static pthread_barrier_t start;
static void *supply(void *p) {(void)p;pthread_barrier_wait(&start);for(int i=0;i<3000;i++) restock();return 0;}
static void *demand(void *p) {(void)p;pthread_barrier_wait(&start);for(int i=0;i<3000;i++) sell();return 0;}
int main(void) {
    pthread_t a,b;
    restock(); if(stock!=10001) return 1;
    sell(); if(stock!=10000) return 1;
    if(pthread_barrier_init(&start,0,2)) return 2;
    if(pthread_create(&a,0,supply,0)||pthread_create(&b,0,demand,0)) return 2;
    if(pthread_join(a,0)||pthread_join(b,0)) return 2;
    if(stock!=10000) {puts("SEMANTIC_FAIL");return 1;}
    puts("SEMANTIC_PASS");puts("PASS");return 0;
}
