#include "state.h"
#include <stdio.h>
#include <string.h>
State s;
int main(void){memset(&s,0,sizeof s);int ok=1;pthread_mutex_init(&s.mutex,0);ok &= consistent(&s);record(&s,0);ok &= s.total==1 && s.accepted==0 && s.rejected==1 && consistent(&s);record(&s,1);ok &= s.total==2 && s.accepted==1 && s.rejected==1 && consistent(&s);s.total++;ok &= !consistent(&s);if(!ok){puts("API_FAIL");return 1;}puts("SEMANTIC_PASS");return 0;}
