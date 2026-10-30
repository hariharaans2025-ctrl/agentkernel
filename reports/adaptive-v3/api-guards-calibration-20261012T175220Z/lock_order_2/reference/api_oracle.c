#include "state.h"
#include <stdio.h>
#include <string.h>
State s;
void* companion(void*x){ready(&s);return 0;}
void partner_call(int reverse_mode){pthread_t t;atomic_store(&s.arrivals,0);pthread_create(&t,0,companion,0);if(reverse_mode)reverse(&s);else forward(&s);pthread_join(t,0);}
int main(void){memset(&s,0,sizeof s);int ok=1;pthread_mutex_init(&s.left,0);pthread_mutex_init(&s.right,0);pthread_mutex_init(&s.third,0);pthread_barrier_init(&s.gate,0,2);atomic_init(&s.arrivals,0);s.a=s.b=20;partner_call(0);ok &= s.a==16 && s.b==24 && atomic_load(&s.arrivals)==2;partner_call(1);ok &= s.a==18 && s.b==22 && atomic_load(&s.arrivals)==2;if(!ok){puts("API_FAIL");return 1;}puts("SEMANTIC_PASS");return 0;}
