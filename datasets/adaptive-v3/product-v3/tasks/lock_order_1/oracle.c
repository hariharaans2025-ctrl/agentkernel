#include "state.h"
#include <stdio.h>
State s;void*a(void*x){forward(&s);return 0;}void*b(void*x){reverse(&s);return 0;}int main(int argc,char**argv){pthread_mutex_init(&s.left,0);pthread_mutex_init(&s.right,0);pthread_mutex_init(&s.third,0);pthread_barrier_init(&s.gate,0,2);atomic_init(&s.arrivals,0);s.a=s.b=s.c=0;pthread_t x,y;pthread_create(&x,0,a,0);pthread_create(&y,0,b,0);pthread_join(x,0);pthread_join(y,0);int ok=atomic_load(&s.arrivals)==2 && s.a==8 && s.b==18 && s.c==0;if(!ok) { puts("FAIL"); return 1; } puts(argc>1?"SEMANTIC_PASS":"PASS"); return 0;}
