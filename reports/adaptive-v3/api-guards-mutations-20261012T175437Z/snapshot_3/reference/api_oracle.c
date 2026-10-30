#include "state.h"
#include <stdio.h>
#include <string.h>
State s;
int main(void){memset(&s,0,sizeof s);int ok=1;pthread_mutex_init(&s.mutex,0);publish(&s,17);ok &= s.epoch==17 && s.payload==187 && s.valid==1 && check_snapshot(&s);s.payload++;ok &= !check_snapshot(&s);s.payload--;publish(&s,23);ok &= s.epoch==23 && s.payload==253 && s.valid==1 && check_snapshot(&s);if(!ok){puts("API_FAIL");return 1;}puts("SEMANTIC_PASS");return 0;}
