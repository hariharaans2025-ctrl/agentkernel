#include "state.h"
#include <stdio.h>
#include <string.h>
State s;
int main(void){memset(&s,0,sizeof s);int ok=1;pthread_mutex_init(&s.mutex,0);atomic_init(&s.audits,7);ok &= count_audits(&s)==7;commit(&s);ok &= count_audits(&s)==8;ok &= s.committed==1 && s.bytes==13;commit(&s);ok &= s.committed==2 && s.bytes==26 && count_audits(&s)==9;if(!ok){puts("API_FAIL");return 1;}puts("SEMANTIC_PASS");return 0;}
