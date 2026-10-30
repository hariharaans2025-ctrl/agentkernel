#include "state.h"
#include <stdio.h>
#include <string.h>
State s;
int main(void){memset(&s,0,sizeof s);int ok=1;pthread_mutex_init(&s.mutex,0);s.balance=6;ok &= inspect(&s)==0;ok &= acquire(&s,0)==0;ok &= acquire(&s,-1)==0;ok &= acquire(&s,7)==0;ok &= s.balance==6 && s.withdrawn==0;for(int i=0;i<3;i++){ok &= acquire(&s,2)==1;ok &= s.balance==4-i*2 && s.withdrawn==(i+1)*2;}ok &= inspect(&s)==6;ok &= acquire(&s,2)==0;ok &= inspect(&s)==6 && s.balance==0;if(!ok){puts("API_FAIL");return 1;}puts("SEMANTIC_PASS");return 0;}
