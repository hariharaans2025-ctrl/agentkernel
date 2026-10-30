#include "state.h"
#include <stdio.h>
#include <string.h>
State s;
int main(void){memset(&s,0,sizeof s);int ok=1;pthread_mutex_init(&s.mutex,0);s.credits=19;ok &= snapshot(&s)==19;update(&s,0);ok &= s.credits==22 && snapshot(&s)==22;update(&s,1);ok &= s.credits==25 && snapshot(&s)==25;if(!ok){puts("API_FAIL");return 1;}puts("SEMANTIC_PASS");return 0;}
