#include "state.h"
#include <stdio.h>
#include <string.h>
State s;
int main(void){memset(&s,0,sizeof s);int ok=1;pthread_mutex_init(&s.mutex,0);s.available=3;ok &= inspect(&s)==0 && s.cancelled==1;for(int i=0;i<3;i++){ok &= acquire(&s)==1;ok &= s.available==2-i && s.reserved==i+1;}ok &= inspect(&s)==3 && s.cancelled==2;ok &= acquire(&s)==0;ok &= inspect(&s)==3 && s.cancelled==3 && s.available==0;if(!ok){puts("API_FAIL");return 1;}puts("SEMANTIC_PASS");return 0;}
