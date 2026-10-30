#include "state.h"
#include <stdio.h>
State s;void*a(void*x){publish(&s);return 0;}void*b(void*x){observe(&s);return 0;}int main(int argc,char**argv){pthread_mutex_init(&s.mutex,0);pthread_barrier_init(&s.gate,0,2);atomic_init(&s.arrivals,0);s.value=s.seen=s.visits=0;pthread_t x,y;pthread_create(&x,0,a,0);pthread_create(&y,0,b,0);pthread_join(x,0);pthread_join(y,0);int ok=atomic_load(&s.arrivals)==2 && (s.value==31 && s.visits==2 && (s.seen==0 || s.seen==31));if(!ok) { puts("FAIL"); return 1; } puts(argc>1?"SEMANTIC_PASS":"PASS"); return 0;}
