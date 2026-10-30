#include "state.h"
#include <stdio.h>
#include <string.h>
State s;
void* companion(void*x){rendezvous(&s);return 0;}
void partner_call(int publish_mode){pthread_t t;atomic_store(&s.arrivals,0);pthread_create(&t,0,companion,0);if(publish_mode)publish(&s);else observe(&s);pthread_join(t,0);}
int main(void){memset(&s,0,sizeof s);int ok=1;pthread_mutex_init(&s.mutex,0);pthread_barrier_init(&s.gate,0,2);atomic_init(&s.arrivals,0);s.value=19;partner_call(0);ok &= s.seen==19 && atomic_load(&s.arrivals)==2;s.value=7;partner_call(0);ok &= s.seen==7 && atomic_load(&s.arrivals)==2;s.value=0;partner_call(1);ok &= s.value==27 && atomic_load(&s.arrivals)==2;if(!ok){puts("API_FAIL");return 1;}puts("SEMANTIC_PASS");return 0;}
