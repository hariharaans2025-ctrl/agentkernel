#include "state.h"
#include <stdio.h>
#include <string.h>
State s;
int main(void){memset(&s,0,sizeof s);int ok=1;pthread_mutex_init(&s.mutex,0);publish(&s,17);ok &= s.lo==17 && s.hi==24 && check_snapshot(&s);s.hi++;ok &= !check_snapshot(&s);s.hi--;publish(&s,23);ok &= s.lo==23 && s.hi==30 && check_snapshot(&s);if(!ok){puts("API_FAIL");return 1;}puts("SEMANTIC_PASS");return 0;}
