#include "state.h"
#include <stdio.h>
#include <string.h>
State s;
int main(void){memset(&s,0,sizeof s);int ok=1;pthread_mutex_init(&s.mutex,0);s.produced=9;s.consumed=2;ok &= snapshot(&s)==5;update(&s,0);ok &= s.produced==11 && s.consumed==3 && snapshot(&s)==5;update(&s,1);ok &= s.produced==13 && s.consumed==4 && snapshot(&s)==5;if(!ok){puts("API_FAIL");return 1;}puts("SEMANTIC_PASS");return 0;}
