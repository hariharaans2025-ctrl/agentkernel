#include "state.h"
#include <stdio.h>
#include <string.h>
State s;
int main(void){memset(&s,0,sizeof s);int ok=1;pthread_mutex_init(&s.mutex,0);ok &= consistent(&s);record(&s,0);ok &= s.count==1 && s.sum==5 && consistent(&s);record(&s,1);ok &= s.count==2 && s.sum==10 && consistent(&s);s.sum++;ok &= !consistent(&s);if(!ok){puts("API_FAIL");return 1;}puts("SEMANTIC_PASS");return 0;}
