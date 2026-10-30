#include "state.h"
#include <stdio.h>
#include <string.h>
State s;
int main(void){memset(&s,0,sizeof s);int ok=1;pthread_mutex_init(&s.mutex,0);s.buckets[0]=2;s.buckets[1]=3;ok &= snapshot(&s)==5;update(&s,0);ok &= s.buckets[0]==3 && s.buckets[1]==3 && snapshot(&s)==6;update(&s,1);ok &= s.buckets[0]==3 && s.buckets[1]==4 && snapshot(&s)==7;if(!ok){puts("API_FAIL");return 1;}puts("SEMANTIC_PASS");return 0;}
