#include "state.h"
#include <stdio.h>
#include <string.h>
State s;
int main(void){memset(&s,0,sizeof s);int ok=1;pthread_mutex_init(&s.mutex,0);pthread_cond_init(&s.changed,0);sem_init(&s.waiting,0,0);atomic_init(&s.awakened,0);s.value=17;s.ready=1;ok &= await_value(&s)==17 && s.ready==0;complete(&s);ok &= s.value==42 && s.ready==1;ok &= await_value(&s)==42 && s.ready==0;if(!ok){puts("API_FAIL");return 1;}puts("SEMANTIC_PASS");return 0;}
